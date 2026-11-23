# -*- coding: utf-8 -*-
"""Взаимопроверка (1.5). После сдачи ученик анонимно оценивает 2–3 работы одноклассников по рубрике
учителя. Итог за вопрос = среднее оценки учителя и проверенной оценки учеников (вес задаёт учитель).
Защита от накруток: рецензент, который всем ставит максимум (или одно и то же), и оценки, сильно
расходящиеся с оценкой учителя, в среднее не входят и показываются учителю."""
import json
import random
import time

from . import attempts as A
from . import engine as E
from .web import router, ApiError, db, need
from . import api_student as S

DEVIATION = 0.4          # расхождение с учителем (доля максимума), после которого оценка не учитывается


def peer_cfg(snap):
    c = dict({"enabled": False, "count": 2, "weight": 50}, **(snap["test"]["settings"].get("peer") or {}))
    c["count"] = max(1, min(5, int(c.get("count") or 2)))
    c["weight"] = max(0, min(100, float(c.get("weight") or 0)))
    return c


def peer_questions(snap):
    return [q for q in snap["questions"] if q["type"] == "essay" and q["body"].get("rubric")]


def _frac(scores, rubric):
    mx = sum(c["max"] for c in rubric) or 1
    return sum(max(0.0, min(float(scores.get(c["id"]) or 0), c["max"])) for c in rubric) / mx


def validity(run_id, qid, rubric, teacher):
    """{review_id: (valid, причина)} для оценённых работ. teacher: {author_attempt: доля или None}."""
    rows = db().q("SELECT * FROM peer_reviews WHERE run_id=? AND qid=? AND done_at IS NOT NULL", (run_id, qid))
    by_rev = {}
    for r in rows:
        by_rev.setdefault(r["reviewer_id"], []).append(r)
    bad = {}
    for rev, lst in by_rev.items():
        if len(lst) >= 2:
            fr = [x["frac"] for x in lst]
            if all(f >= 0.999 for f in fr):
                for x in lst:
                    bad[x["id"]] = "все работы получили максимум"
            elif max(fr) - min(fr) < 0.001:
                for x in lst:
                    bad[x["id"]] = "всем поставлена одинаковая оценка"
    out = {}
    for r in rows:
        t = teacher.get(r["author_id"])
        if r["id"] in bad:
            out[r["id"]] = (False, bad[r["id"]])
        elif t is not None and abs(r["frac"] - t) > DEVIATION:
            out[r["id"]] = (False, "сильно расходится с оценкой учителя")
        else:
            out[r["id"]] = (True, "")
    return out


def _teacher_fracs(qid, maxp, run_id):
    return dict((r["attempt_id"], (r["manual"] / maxp if maxp else None)) for r in
                db().q("SELECT a.attempt_id, a.manual FROM answers a JOIN attempts t ON t.id=a.attempt_id "
                       "WHERE t.run_id=? AND a.qid=? AND a.manual IS NOT NULL", (run_id, qid)))


def blend_manual(snap, attempt_id, ans):
    """Подмешивает оценку учеников в manual (копия: сохранённая оценка учителя не меняется)."""
    cfg = peer_cfg(snap)
    if not cfg["enabled"]:
        return ans
    a = db().one("SELECT run_id FROM attempts WHERE id=?", (attempt_id,))
    out = dict(ans)
    scale = snap["test"]["settings"]["scale"]
    from . import grading as G
    for q in peer_questions(snap):
        row = ans.get(q["id"])
        if not row or row.get("manual") is None:
            continue
        maxp = G.question_points(q, scale)
        teacher = _teacher_fracs(q["id"], maxp, a["run_id"])
        val = validity(a["run_id"], q["id"], q["body"]["rubric"], teacher)
        good = [r["frac"] for r in db().q("SELECT id, frac FROM peer_reviews WHERE author_id=? AND qid=? AND done_at IS NOT NULL",
                                          (attempt_id, q["id"])) if val.get(r["id"], (False,))[0]]
        if not good:
            continue
        peer = sum(good) / len(good)
        w = cfg["weight"] / 100.0
        row = dict(row)
        row["manual"] = round(maxp * ((1 - w) * (row["manual"] / maxp if maxp else 0) + w * peer), 2)
        out[q["id"]] = row
    return out


def _cfg_for(a):
    snap = A.snapshot_for(a["run_id"])
    cfg = peer_cfg(snap)
    need(cfg["enabled"] and peer_questions(snap), "Взаимопроверка для этого теста не включена", 404)
    return snap, cfg


def _assign(a, snap, cfg):
    """Назначает работы одноклассников (если ещё не назначены и есть из кого выбрать)."""
    for q in peer_questions(snap):
        have = db().val("SELECT COUNT(*) FROM peer_reviews WHERE reviewer_id=? AND qid=?", (a["id"], q["id"])) or 0
        if have >= cfg["count"]:
            continue
        cand = []
        for o in db().q("SELECT id FROM attempts WHERE run_id=? AND status='finished' AND id<>? AND paper=0", (a["run_id"], a["id"])):
            row = db().one("SELECT response FROM answers WHERE attempt_id=? AND qid=?", (o["id"], q["id"]))
            try:
                text = (json.loads(row["response"]) or {}).get("text") if row else ""
            except ValueError:
                text = ""
            if not (text or "").strip():
                continue
            if db().val("SELECT 1 FROM peer_reviews WHERE reviewer_id=? AND author_id=? AND qid=?", (a["id"], o["id"], q["id"])):
                continue
            n = db().val("SELECT COUNT(*) FROM peer_reviews WHERE author_id=? AND qid=?", (o["id"], q["id"])) or 0
            cand.append((n, random.random(), o["id"]))
        cand.sort()
        for _n, _r, oid in cand[:cfg["count"] - have]:
            db().ex("INSERT OR IGNORE INTO peer_reviews(run_id,qid,author_id,reviewer_id,created_at) VALUES(?,?,?,?,?)",
                    (a["run_id"], q["id"], oid, a["id"], time.time()))


@router.route("GET", "/api/s/a/:aid/peer", public=True)
def s_peer(req, aid):
    a, _w = S._attempt(req, aid)
    need(a["status"] == "finished", "Сначала завершите тест", 409)
    snap, cfg = _cfg_for(a)
    _assign(a, snap, cfg)
    qs = E.qmap(snap)
    items = []
    for r in db().q("SELECT * FROM peer_reviews WHERE reviewer_id=? ORDER BY id", (a["id"],)):
        q = qs[r["qid"]]
        row = db().one("SELECT response FROM answers WHERE attempt_id=? AND qid=?", (r["author_id"], r["qid"]))
        try:
            text = (json.loads(row["response"]) or {}).get("text", "")
        except (ValueError, TypeError):
            text = ""
        items.append({"id": r["id"], "task": q["body"].get("text", ""), "work": text, "rubric": q["body"]["rubric"],
                      "done": r["done_at"] is not None, "scores": json.loads(r["scores"]) if r["scores"] else None})
    return {"count": cfg["count"], "items": items}


@router.route("PUT", "/api/s/a/:aid/peer/:rid", public=True)
def s_peer_save(req, aid, rid):
    a, _w = S._attempt(req, aid)
    snap, cfg = _cfg_for(a)
    r = db().one("SELECT * FROM peer_reviews WHERE id=? AND reviewer_id=?", (int(rid), a["id"]))
    need(r, "Работа не найдена", 404)
    need(r["done_at"] is None, "Эта работа уже оценена", 409)
    q = E.qmap(snap)[r["qid"]]
    sc = (req.json() or {}).get("scores") or {}
    clean = {}
    for c in q["body"]["rubric"]:
        try:
            v = float(sc.get(c["id"]))
        except (TypeError, ValueError):
            raise ApiError(400, "Поставьте оценку по критерию «%s»" % c["title"])
        need(0 <= v <= c["max"], "Оценка по критерию «%s» — от 0 до %s" % (c["title"], c["max"]), 400)
        clean[c["id"]] = v
    fr = _frac(clean, q["body"]["rubric"])
    db().ex("UPDATE peer_reviews SET scores=?, frac=?, done_at=? WHERE id=?", (json.dumps(clean), fr, time.time(), r["id"]))
    # оценки рецензента проверяются по всем его работам, поэтому пересчитываем всех затронутых авторов
    for x in db().q("SELECT DISTINCT author_id FROM peer_reviews WHERE reviewer_id=? AND done_at IS NOT NULL", (a["id"],)):
        A.regrade(x["author_id"])
    return {"ok": True}


@router.route("GET", "/api/runs/:rid/peer")
def api_run_peer(req, rid):
    """Отчёт учителю: оценка учителя, оценка одноклассников, итог, подозрительные рецензенты."""
    from .api_runs import get_run
    from . import grading as G
    r = get_run(rid, req)
    snap = A.snapshot_for(r["id"])
    cfg = peer_cfg(snap)
    scale = snap["test"]["settings"]["scale"]
    rows, flags = [], []
    for q in peer_questions(snap):
        maxp = G.question_points(q, scale)
        teacher = _teacher_fracs(q["id"], maxp, r["id"])
        val = validity(r["id"], q["id"], q["body"]["rubric"], teacher)
        names = dict((x["id"], x["student_name"]) for x in db().q("SELECT id, student_name FROM attempts WHERE run_id=?", (r["id"],)))
        by_author = {}
        for x in db().q("SELECT * FROM peer_reviews WHERE run_id=? AND qid=? AND done_at IS NOT NULL", (r["id"], q["id"])):
            by_author.setdefault(x["author_id"], []).append(x)
            ok, why = val[x["id"]]
            if not ok:
                flags.append([names.get(x["reviewer_id"], "?"), names.get(x["author_id"], "?"), "%d %%" % round(100 * x["frac"]), why])
        for aid_, lst in sorted(by_author.items(), key=lambda kv: names.get(kv[0], "")):
            good = [x["frac"] for x in lst if val[x["id"]][0]]
            t = teacher.get(aid_)
            pm = sum(good) / len(good) if good else None
            fin = None
            if t is not None:
                w = cfg["weight"] / 100.0
                fin = t if pm is None else (1 - w) * t + w * pm
            rows.append([names.get(aid_, "?"), len(lst), "" if t is None else "%d %%" % round(100 * t),
                         "" if pm is None else "%d %%" % round(100 * pm), "" if fin is None else "%d %%" % round(100 * fin),
                         len(lst) - len(good) or ""])
    return {"name": "Взаимопроверка", "title": "Взаимопроверка — «%s»" % snap["test"]["title"],
            "subtitle": "Итог = (1 − w)·оценка учителя + w·оценка учеников, w = %d %%. Оценки «всем максимум», одинаковые и резко расходящиеся с учителем не учитываются." % cfg["weight"],
            "headers": ["Автор работы", "Оценок получено", "Учитель", "Одноклассники (проверенные)", "Итог", "Отброшено"],
            "widths": [30, 14, 12, 22, 10, 12], "rows": rows + ([["", "", "", "", "", ""], ["Подозрительные оценки:", "", "", "", "", ""]] +
                                                                [[f[0] + " → " + f[1], "", "", f[2], "", f[3]] for f in flags] if flags else [])}
