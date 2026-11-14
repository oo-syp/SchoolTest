# -*- coding: utf-8 -*-
"""Проверка на списывание (1.3).

Признаки: совпадение ответов у пары учащихся (вопросы без развёрнутого ответа и без файла),
подозрительно быстрые и равномерные ответы, частый уход со страницы (focus_lost уже
учитывается при проведении теста). Учитель включает проверку и порог в настройках теста
(settings.anticheat) и решает, только показывать отчёт или ещё и останавливать подозрительную
попытку до его решения (cheat_status='blocked').
"""
import json

from .web import db


def _comparable_answers(attempt_id):
    """{qid: нормализованный ответ} — только вопросы, где ответ можно сравнить буквально."""
    out = {}
    for r in db().q("SELECT qid, response FROM answers WHERE attempt_id=? AND response IS NOT NULL", (attempt_id,)):
        try:
            v = json.loads(r["response"])
        except (ValueError, TypeError):
            continue
        if isinstance(v, dict):
            v = v.get("choice") if "choice" in v else (tuple(sorted(v.get("choices") or [])) if "choices" in v else None)
        if v in (None, ""):
            continue
        out[r["qid"]] = v
    return out


def pair_similarity(a1, a2):
    """Доля совпадающих ответов среди вопросов, на которые ответили оба."""
    common = set(a1) & set(a2)
    if len(common) < 5:
        return 0.0, len(common)
    same = sum(1 for q in common if a1[q] == a2[q])
    return 100.0 * same / len(common), len(common)


def timing_flag(attempt_id, fast_seconds):
    """Подозрительно быстрые, равномерные ответы: медианный интервал между ответами меньше порога."""
    rows = db().q("SELECT updated_at FROM answers WHERE attempt_id=? AND updated_at IS NOT NULL ORDER BY updated_at", (attempt_id,))
    ts = [r["updated_at"] for r in rows]
    if len(ts) < 6:
        return None
    gaps = sorted(ts[i + 1] - ts[i] for i in range(len(ts) - 1))
    median = gaps[len(gaps) // 2]
    if median < fast_seconds:
        return "Подозрительно быстрые ответы (медианный интервал %.1f с на вопрос)" % median
    return None


def run_report(run_id):
    """Отчёт по проведению: попытки с флагами + пары с высоким совпадением ответов."""
    run = db().one("SELECT * FROM runs WHERE id=?", (run_id,))
    if not run:
        return {"attempts": [], "pairs": []}
    snap = json.loads(run["snapshot"] or "{}")
    settings = (snap.get("test") or {}).get("settings") or {}
    ac = settings.get("anticheat") or {}
    threshold = float(ac.get("pair_percent") or 85)
    fast = float(ac.get("fast_seconds") or 4)
    focus_limit = int(ac.get("focus_limit") or 3)
    attempts = db().q("SELECT id, student_name, focus_lost, cheat_status, cheat_flags FROM attempts WHERE run_id=?", (run_id,))
    answers = dict((a["id"], _comparable_answers(a["id"])) for a in attempts)
    out_attempts = []
    for a in attempts:
        flags = []
        if a["focus_lost"] and a["focus_lost"] >= focus_limit:
            flags.append("Уход со страницы: %d раз" % a["focus_lost"])
        tf = timing_flag(a["id"], fast)
        if tf:
            flags.append(tf)
        out_attempts.append({"id": a["id"], "student_name": a["student_name"], "focus_lost": a["focus_lost"],
                             "status": a["cheat_status"], "flags": flags})
    pairs = []
    ids = list(answers)
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            pct, common = pair_similarity(answers[ids[i]], answers[ids[j]])
            if pct >= threshold:
                n1 = next(a["student_name"] for a in attempts if a["id"] == ids[i])
                n2 = next(a["student_name"] for a in attempts if a["id"] == ids[j])
                pairs.append({"a": ids[i], "b": ids[j], "name_a": n1, "name_b": n2,
                             "percent": round(pct, 1), "common": common})
    pairs.sort(key=lambda p: -p["percent"])
    return {"attempts": out_attempts, "pairs": pairs, "settings": ac}


def check_after_answer(attempt_id):
    """Пересчитать флаги попытки сразу после сохранения ответа (для блокировки «на лету»)."""
    a = db().one("SELECT * FROM attempts WHERE id=?", (attempt_id,))
    if not a or a["status"] != "active":
        return
    run = db().one("SELECT * FROM runs WHERE id=?", (a["run_id"],))
    if not run:
        return
    snap = json.loads(run["snapshot"] or "{}")
    settings = (snap.get("test") or {}).get("settings") or {}
    ac = settings.get("anticheat") or {}
    if not ac.get("enabled") or snap.get("psy"):
        return
    flags = []
    focus_limit = int(ac.get("focus_limit") or 3)
    if a["focus_lost"] and a["focus_lost"] >= focus_limit:
        flags.append("Частый уход со страницы")
    tf = timing_flag(attempt_id, float(ac.get("fast_seconds") or 4))
    if tf:
        flags.append(tf)
    my_answers = _comparable_answers(attempt_id)
    threshold = float(ac.get("pair_percent") or 85)
    for other in db().q("SELECT id FROM attempts WHERE run_id=? AND id<>? AND status IN ('active','finished')",
                        (a["run_id"], attempt_id)):
        pct, common = pair_similarity(my_answers, _comparable_answers(other["id"]))
        if pct >= threshold:
            flags.append("Совпадение ответов с другим участником: %.0f%%" % pct)
            break
    status = "ok"
    if flags:
        status = "blocked" if ac.get("block") else "suspect"
    if status != a["cheat_status"] or flags:
        db().ex("UPDATE attempts SET cheat_flags=?, cheat_status=? WHERE id=?",
                (json.dumps(flags, ensure_ascii=False), status, attempt_id))


def unblock(attempt_id):
    db().ex("UPDATE attempts SET cheat_status='ok' WHERE id=?", (attempt_id,))
