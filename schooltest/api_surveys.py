# -*- coding: utf-8 -*-
"""Конструктор анкет (1.3): упрощённые типы вопросов (один/несколько вариантов, шкала, открытый
ответ), без оценивания. Анкету проводят по коду — так же, как тест, но без баллов и правильных
ответов. Аудитория: учащиеся по списку класса, анонимно по коду, или педагоги из списка
пользователей — это только описывает, кому раздаётся код; сама подача ответа всегда идёт по коду.
"""
import json
import secrets
import string
import time

from .web import router, ApiError, db, need, is_admin, fio

TYPES = ("single", "multi", "likert", "open")
LIKERT_DEFAULT = ["Совершенно не согласен", "Не согласен", "Нейтрально", "Согласен", "Совершенно согласен"]


def _new_code():
    while True:
        code = "".join(secrets.choice(string.digits) for _ in range(6))
        if code[0] != "0" and not db().val("SELECT 1 FROM runs WHERE code=? AND status='open'", (code,)) \
                and not db().val("SELECT 1 FROM survey_runs WHERE code=? AND status='open'", (code,)):
            return code


def _survey(sid, req, write=False):
    s = db().one("SELECT * FROM surveys WHERE id=?", (int(sid),))
    need(s, "Анкета не найдена", 404)
    if write:
        need(s["owner_id"] == req.user["id"] or is_admin(req), "Недостаточно прав")
    return s


def _q_out(q):
    q = dict(q)
    q["options"] = json.loads(q["options"] or "[]")
    return q


@router.route("GET", "/api/surveys")
def api_surveys_list(req):
    need(req.user and req.user["role"] in ("teacher", "psychologist", "admin"), "Недостаточно прав")
    sql = "SELECT * FROM surveys WHERE archived=0"
    args = []
    if not is_admin(req) and req.arg("all") != "1":
        sql += " AND owner_id=?"
        args.append(req.user["id"])
    rows = db().q(sql + " ORDER BY updated_at DESC", tuple(args))
    out = []
    for s in rows:
        s = dict(s)
        s["questions"] = db().val("SELECT COUNT(*) FROM survey_questions WHERE survey_id=?", (s["id"],))
        s["owner"] = db().val("SELECT full_name FROM users WHERE id=?", (s["owner_id"],)) or ""
        out.append(s)
    return {"items": out}


@router.route("POST", "/api/surveys")
def api_survey_add(req):
    need(req.user and req.user["role"] in ("teacher", "psychologist", "admin"), "Недостаточно прав")
    d = req.json()
    title = (d.get("title") or "").strip()
    need(title, "Укажите название анкеты", 400)
    sid = db().insert("surveys", {"owner_id": req.user["id"], "title": title, "description": d.get("description") or "",
                                  "audience": d.get("audience") or "anon", "folder_id": d.get("folder_id") or None})
    return {"id": sid}


@router.route("GET", "/api/surveys/:sid")
def api_survey_get(req, sid):
    s = _survey(sid, req)
    s = dict(s)
    s["items"] = [_q_out(q) for q in db().q("SELECT * FROM survey_questions WHERE survey_id=? ORDER BY sort, id", (s["id"],))]
    return s


@router.route("PUT", "/api/surveys/:sid")
def api_survey_put(req, sid):
    s = _survey(sid, req, write=True)
    d = req.json()
    row = {}
    for k in ("title", "description", "audience"):
        if k in d:
            row[k] = d[k]
    if "folder_id" in d:
        row["folder_id"] = d["folder_id"] or None
    if "archived" in d:
        row["archived"] = 1 if d["archived"] else 0
    if row:
        db().update("surveys", s["id"], row)
    db().ex("UPDATE surveys SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (s["id"],))
    return {"ok": True}


@router.route("DELETE", "/api/surveys/:sid")
def api_survey_delete(req, sid):
    s = _survey(sid, req, write=True)
    db().ex("DELETE FROM surveys WHERE id=?", (s["id"],))
    return {"ok": True}


def _question_in(d):
    qtype = d.get("type")
    need(qtype in TYPES, "Неверный тип вопроса", 400)
    text = (d.get("text") or "").strip()
    need(text, "Укажите текст вопроса", 400)
    options = d.get("options") or []
    if qtype in ("single", "multi"):
        options = [{"id": str(i + 1), "text": str(o).strip() if not isinstance(o, dict) else o.get("text", "")}
                   for i, o in enumerate(options) if (o if isinstance(o, str) else o.get("text"))]
        need(len(options) >= 2, "Нужно минимум два варианта ответа", 400)
    elif qtype == "likert":
        options = [{"id": str(i + 1), "text": t} for i, t in enumerate(options or LIKERT_DEFAULT)]
    else:
        options = []
    return {"type": qtype, "text": text, "options": json.dumps(options, ensure_ascii=False),
            "required": 1 if d.get("required", True) else 0}


@router.route("POST", "/api/surveys/:sid/questions")
def api_survey_q_add(req, sid):
    s = _survey(sid, req, write=True)
    row = _question_in(req.json())
    row["survey_id"] = s["id"]
    row["sort"] = (db().val("SELECT MAX(sort) FROM survey_questions WHERE survey_id=?", (s["id"],)) or 0) + 1
    qid = db().insert("survey_questions", row)
    return _q_out(db().one("SELECT * FROM survey_questions WHERE id=?", (qid,)))


@router.route("PUT", "/api/survey_questions/:qid")
def api_survey_q_put(req, qid):
    q = db().one("SELECT * FROM survey_questions WHERE id=?", (int(qid),))
    need(q, "Вопрос не найден", 404)
    _survey(q["survey_id"], req, write=True)
    d = req.json()
    d.setdefault("type", q["type"])
    d.setdefault("text", q["text"])
    if "options" not in d:
        d["options"] = json.loads(q["options"] or "[]")
    db().update("survey_questions", q["id"], _question_in(d))
    return _q_out(db().one("SELECT * FROM survey_questions WHERE id=?", (q["id"],)))


@router.route("DELETE", "/api/survey_questions/:qid")
def api_survey_q_del(req, qid):
    q = db().one("SELECT * FROM survey_questions WHERE id=?", (int(qid),))
    need(q, "Вопрос не найден", 404)
    _survey(q["survey_id"], req, write=True)
    db().ex("DELETE FROM survey_questions WHERE id=?", (q["id"],))
    return {"ok": True}


@router.route("POST", "/api/surveys/:sid/runs")
def api_survey_run_start(req, sid):
    s = _survey(sid, req, write=True)
    items = db().q("SELECT * FROM survey_questions WHERE survey_id=? ORDER BY sort, id", (s["id"],))
    need(items, "В анкете нет вопросов", 400)
    d = req.json() or {}
    class_id = d.get("class_id") or None
    snap = {"title": s["title"], "description": s["description"], "audience": s["audience"],
            "items": [_q_out(q) for q in items]}
    code = _new_code()
    rid = db().insert("survey_runs", {"survey_id": s["id"], "class_id": class_id, "owner_id": req.user["id"],
                                      "code": code, "status": "open", "snapshot": json.dumps(snap, ensure_ascii=False),
                                      "created_at": time.time()})
    return {"id": rid, "code": code}


@router.route("GET", "/api/surveys/:sid/runs")
def api_survey_runs_list(req, sid):
    s = _survey(sid, req, write=True)
    rows = db().q("SELECT * FROM survey_runs WHERE survey_id=? ORDER BY id DESC", (s["id"],))
    out = []
    for r in rows:
        r = dict(r)
        r["responses"] = db().val("SELECT COUNT(*) FROM survey_responses WHERE run_id=?", (r["id"],))
        r.pop("snapshot", None)
        out.append(r)
    return {"items": out}


def _run_or_404(rid):
    r = db().one("SELECT * FROM survey_runs WHERE id=?", (int(rid),))
    need(r, "Не найдено", 404)
    return r


@router.route("POST", "/api/survey_runs/:rid/close")
def api_survey_run_close(req, rid):
    r = _run_or_404(rid)
    need(r["owner_id"] == req.user["id"] or is_admin(req), "Недостаточно прав")
    db().ex("UPDATE survey_runs SET status='closed', closed_at=? WHERE id=?", (time.time(), r["id"]))
    return {"ok": True}


@router.route("GET", "/api/survey_runs/:rid")
def api_survey_run_get(req, rid):
    """Результаты: по закрытым вопросам — частоты ответов, по открытым — список текстов."""
    r = _run_or_404(rid)
    need(r["owner_id"] == req.user["id"] or is_admin(req), "Недостаточно прав")
    snap = json.loads(r["snapshot"] or "{}")
    responses = db().q("SELECT * FROM survey_responses WHERE run_id=? ORDER BY id", (r["id"],))
    parsed = [json.loads(x["answers"] or "{}") for x in responses]
    report = []
    for item in snap.get("items") or []:
        qid = str(item["id"])
        if item["type"] == "open":
            texts = [p[qid] for p in parsed if p.get(qid)]
            report.append({"question": item, "texts": texts})
        else:
            counts = {}
            for opt in item["options"]:
                counts[opt["id"]] = 0
            for p in parsed:
                v = p.get(qid)
                vals = v if isinstance(v, list) else ([v] if v else [])
                for x in vals:
                    if str(x) in counts:
                        counts[str(x)] += 1
            report.append({"question": item, "counts": [{"option": o["text"], "n": counts[o["id"]]} for o in item["options"]]})
    out = dict(r)
    out.pop("snapshot", None)
    out["title"] = snap.get("title")
    out["total"] = len(responses)
    out["report"] = report
    out["respondents"] = [x["respondent"] for x in responses] if snap.get("audience") != "anon" else []
    return out


# -------------------------------------------------------------- публичная подача ответа по коду

@router.route("POST", "/api/sv/join", public=True)
def sv_join(req):
    d = req.json()
    code = str(d.get("code") or "").strip()
    r = db().one("SELECT * FROM survey_runs WHERE code=? AND status='open'", (code,))
    need(r, "Анкета с таким кодом не найдена или закрыта", 404)
    snap = json.loads(r["snapshot"] or "{}")
    return {"run_id": r["id"], "title": snap.get("title"), "description": snap.get("description"),
            "audience": snap.get("audience"), "items": snap.get("items")}


@router.route("POST", "/api/sv/:rid/submit", public=True)
def sv_submit(req, rid):
    r = _run_or_404(rid)
    need(r["status"] == "open", "Анкета уже закрыта", 409)
    d = req.json()
    snap = json.loads(r["snapshot"] or "{}")
    answers = d.get("answers") or {}
    for item in snap.get("items") or []:
        if item.get("required") and item["type"] != "open" and not answers.get(str(item["id"])):
            raise ApiError(400, "Ответьте на все обязательные вопросы")
    n = db().val("SELECT COUNT(*) FROM survey_responses WHERE run_id=?", (r["id"],)) or 0
    respondent = (d.get("respondent") or "").strip() or ("Аноним #%d" % (n + 1))
    db().ex("INSERT INTO survey_responses(run_id, respondent, answers, created_at) VALUES(?,?,?,?)",
            (r["id"], respondent, json.dumps(answers, ensure_ascii=False), time.time()))
    return {"ok": True}
