# -*- coding: utf-8 -*-
"""Движок проведения: снимок теста, план попытки, представление вопроса для
ученика (без правильных ответов) и подсчёт результата."""
import json
import random

from . import grading as G

DEFAULT_SETTINGS = {
    "shuffle_questions": False,
    "shuffle_options": True,
    "time_limit": 0,            # минут, 0 — без ограничения
    "free_nav": True,           # можно пропускать вопросы и возвращаться
    "show_result": "mark",      # none | mark | review
    "no_copy": False,
    "track_focus": True,
    "variants": 1,
    "scale": {"mode": "percent"},
    "result_kind": "mark",      # mark | passfail | percent | credit (для предприятий)
    "pass_percent": 60,
}


def test_settings(raw):
    s = dict(DEFAULT_SETTINGS)
    try:
        s.update(json.loads(raw) if isinstance(raw, str) else (raw or {}))
    except ValueError:
        pass
    if not isinstance(s.get("scale"), dict):
        s["scale"] = {"mode": "percent"}
    return s


def load_question(row):
    q = dict(row)
    q["body"] = json.loads(q["body"] or "{}") if isinstance(q.get("body"), str) else (q.get("body") or {})
    q["answer"] = json.loads(q["answer"] or "{}") if isinstance(q.get("answer"), str) else (q.get("answer") or {})
    return q


def build_snapshot(db, test_id, default_scale=None):
    t = db.one("SELECT * FROM tests WHERE id=?", (test_id,))
    if not t:
        raise ValueError("Тест не найден")
    st = test_settings(t["settings"])
    if st["scale"].get("mode") == "percent" and not st["scale"].get("thresholds") and default_scale:
        st["scale"]["thresholds"] = default_scale
    tasks = db.q("SELECT * FROM tasks WHERE test_id=? ORDER BY num, id", (test_id,))
    tnum = dict((x["id"], i + 1) for i, x in enumerate(tasks))
    qs = []
    for r in db.q("SELECT q.* FROM questions q JOIN tasks k ON k.id=q.task_id WHERE q.test_id=? ORDER BY k.num, k.id, q.sort, q.id",
                  (test_id,)):
        q = load_question(r)
        qs.append({"id": str(q["id"]), "task_id": q["task_id"], "task_num": tnum.get(q["task_id"], 1),
                   "variant": q["variant"], "type": q["type"], "body": q["body"], "answer": q["answer"],
                   "points": q["points"]})
    return {"test": {"id": t["id"], "title": t["title"], "subject": t["subject"], "grade": t["grade"], "settings": st},
            "tasks": [{"id": x["id"], "num": tnum[x["id"]], "title": x["title"], "level": x["level"], "pick": x["pick"]}
                      for x in tasks],
            "questions": qs}


def _perm(ids, rng, avoid_identity=False):
    ids = list(ids)
    if len(ids) < 2:
        return ids
    for _ in range(10):
        p = ids[:]
        rng.shuffle(p)
        if not avoid_identity or p != ids:
            return p
    return ids[::-1]


def make_plan(snap, variant, rng=None):
    """Список вопросов попытки: [{q, t, o: {порядок элементов}}]."""
    rng = rng or random.SystemRandom()
    st = snap["test"]["settings"]
    nvar = max(1, int(st.get("variants") or 1))
    variant = ((variant - 1) % nvar) + 1
    groups = []
    for task in snap["tasks"]:
        qs = [q for q in snap["questions"] if q["task_id"] == task["id"] and q["variant"] in (0, variant)]
        if task.get("pick") and 0 < task["pick"] < len(qs):
            chosen = set(id(x) for x in rng.sample(qs, task["pick"]))
            qs = [q for q in qs if id(q) in chosen]
        groups.append(qs)
    if st.get("shuffle_questions"):
        if G.norm_tasks_info(st["scale"]):
            for g in groups:          # задания по уровням идут по порядку, вопросы внутри — вперемешку
                rng.shuffle(g)
            flat = [q for g in groups for q in g]
        else:
            flat = [q for g in groups for q in g]
            rng.shuffle(flat)
    else:
        flat = [q for g in groups for q in g]
    plan = []
    for q in flat:
        b = q["body"]
        o = {}
        if q["type"] in ("single", "multi") and st.get("shuffle_options", True) and not b.get("keep_order"):
            o["options"] = _perm([x["id"] for x in b.get("options", [])], rng)
        if q["type"] == "match":
            o["right"] = _perm([x["id"] for x in b.get("right", [])], rng, avoid_identity=True)
        if q["type"] in ("order", "chrono"):
            key = "items" if q["type"] == "order" else "events"
            o["items"] = _perm([x["id"] for x in b.get(key, [])], rng, avoid_identity=True)
        if q["type"] == "cloze":
            o["choices"] = dict((str(bl["id"]), _perm(bl.get("choices") or [], rng))
                                for bl in b.get("blanks", []) if bl.get("kind") == "select")
        plan.append({"q": q["id"], "t": q["task_num"], "o": o})
    return plan, variant


def qmap(snap):
    return dict((q["id"], q) for q in snap["questions"])


def _ordered(items, order):
    by = dict((str(x["id"]), x) for x in items)
    out = [by[str(i)] for i in order if str(i) in by]
    out += [x for x in items if str(x["id"]) not in set(str(i) for i in order)]
    return out


def public_question(q, entry, plays_used=0, scale=None):
    """Вопрос для ученика: только то, что нужно для ответа. Правильных ответов здесь нет."""
    b = q["body"]
    o = entry.get("o", {})
    out = {"id": q["id"], "type": q["type"], "text": b.get("text", ""), "images": b.get("images") or []}
    if scale is not None:
        out["points"] = G.question_points(q, scale)
    audio = b.get("audio")
    if audio and audio.get("media"):
        lim = int(audio.get("plays") or 0)
        out["audio"] = {"media": audio["media"], "limit": lim, "left": (max(0, lim - plays_used) if lim else None)}
    t = q["type"]
    if t in ("single", "multi"):
        opts = b.get("options", [])
        if o.get("options"):
            opts = _ordered(opts, o["options"])
        out["options"] = [{"id": x["id"], "text": x.get("text", ""), "image": x.get("image")} for x in opts]
    elif t == "short":
        out["fields"] = [{"id": f["id"], "label": f.get("label", "")} for f in (b.get("fields") or [{"id": "1", "label": ""}])]
    elif t == "match":
        out["left"] = [{"id": x["id"], "text": x.get("text", ""), "image": x.get("image")} for x in b.get("left", [])]
        right = _ordered(b.get("right", []), o.get("right") or [])
        out["right"] = [{"id": x["id"], "text": x.get("text", ""), "image": x.get("image")} for x in right]
    elif t in ("order", "chrono"):
        key = "items" if t == "order" else "events"
        items = _ordered(b.get(key, []), o.get("items") or [])
        out["items"] = [{"id": x["id"], "text": x.get("text", ""), "image": x.get("image")} for x in items]
        if t == "chrono":
            out["labels"] = {"start": b.get("start_label", ""), "end": b.get("end_label", "")}
    elif t == "cloze":
        out["blanks"] = []
        for bl in b.get("blanks", []):
            d = {"id": bl["id"], "kind": bl.get("kind", "input")}
            if d["kind"] == "select":
                d["choices"] = (o.get("choices") or {}).get(str(bl["id"])) or bl.get("choices") or []
            out["blanks"].append(d)
    elif t == "likert":
        out["statements"] = [{"id": x["id"], "text": x.get("text", "")} for x in b.get("statements", [])]
        out["scale"] = b.get("scale") or []
    elif t == "essay":
        out["min_words"] = b.get("min_words") or 0
    elif t == "file":
        out["task_files"] = b.get("task_files") or []
        out["accept"] = b.get("accept") or ""
        out["max_mb"] = b.get("max_mb") or 10
    elif t == "code":
        for k in ("input_format", "output_format", "notes", "examples", "time_limit", "memory", "languages",
                  "feedback", "max_submissions"):
            out[k] = b.get(k)
        a = q.get("answer") or {}
        out["subtasks"] = [{"name": s.get("name") or "", "points": s.get("points"), "deps": s.get("deps") or [],
                            "limits": s.get("limits") or "", "tests": len(s.get("tests") or [])} for s in a.get("subtasks") or []]
        out["manual"] = bool(a.get("manual"))
    elif t == "psy":
        out["options"] = [{"id": x["id"], "text": x.get("text", "")} for x in b.get("options", [])]
    return out


def score_attempt(snap, plan, answers):
    """answers: {qid: строка answers}. Возвращает (итог, {qid: auto-баллы}, items)."""
    st = snap["test"]["settings"]
    scale = st["scale"]
    qs = qmap(snap)
    items, autos = [], {}
    for e in plan:
        q = qs.get(e["q"])
        if not q:
            continue
        maxp = G.question_points(q, scale)
        row = answers.get(e["q"]) or {}
        resp = row.get("response")
        if isinstance(resp, str):
            try:
                resp = json.loads(resp)
            except ValueError:
                resp = None
        scored = q["type"] not in G.UNSCORED_TYPES
        if G.is_manual(q):
            got = row.get("manual")
            if got is None and not G.is_answered(q, resp):
                got = 0.0                    # нет ответа — нечего проверять
            autos[e["q"]] = None
        elif scored:
            res = G.check(q, resp)
            got = G.award(q, res, maxp, scale)
            if row.get("manual") is not None:  # учитель может исправить балл
                got = row["manual"]
            autos[e["q"]] = got
        else:
            got = None
            autos[e["q"]] = None
        items.append({"qid": e["q"], "task_num": e["t"], "maxp": maxp, "got": got, "scored": scored, "type": q["type"]})
    ev = G.evaluate(items, scale, st.get("result_kind", "mark"), st.get("pass_percent", 60))
    return ev, autos, items


def review_question(q, entry, row, scale):
    """Разбор для ученика после теста (если разрешено): ответ ученика и правильный ответ."""
    pq = public_question(q, entry, scale=scale)
    resp = (row or {}).get("response")
    if isinstance(resp, str):
        try:
            resp = json.loads(resp)
        except ValueError:
            resp = None
    pq["response"] = resp
    pq["correct"] = correct_view(q)
    res = G.check(q, resp)
    pq["frac"] = None if res is None else res["frac"]
    pq["got"] = (row or {}).get("manual") if G.is_manual(q) else None
    pq["comment"] = (row or {}).get("comment") or ""
    return pq


def correct_view(q):
    a = q["answer"]
    t = q["type"]
    if t in ("single", "multi"):
        return {"options": a.get("correct", [])}
    if t == "short":
        return {"fields": dict((k, (v or [""])[0]) for k, v in (a.get("fields") or {}).items())}
    if t == "match":
        return {"pairs": a.get("pairs", {})}
    if t in ("order", "chrono"):
        return {"order": a.get("order", []), "dates": a.get("dates", {})}
    if t == "cloze":
        return {"blanks": dict((k, (v or [""])[0]) for k, v in (a.get("blanks") or {}).items())}
    if t in ("essay", "file"):
        return {"sample": a.get("sample", "")}
    return {}
