# -*- coding: utf-8 -*-
"""Банк вопросов (1.3): общее на школу хранилище для сборки тестов.

Вопрос можно отправить в банк прямо из теста (кнопка «В банк» у вопроса) и вставить из банка
в любой тест. Банк общий для всех педагогов, как и папки — это рабочий инструмент, а не личный архив.
"""
import json

from . import engine as E
from .web import router, ApiError, db, need, pick
from .api_tests import normalize_question, touch


def _staff(req):
    need(req.user and req.user["role"] in ("teacher", "psychologist", "admin"), "Недостаточно прав")


def _out(r):
    r = dict(r)
    try:
        r["body"] = json.loads(r["body"])
    except ValueError:
        r["body"] = {}
    try:
        r["answer"] = json.loads(r["answer"])
    except ValueError:
        r["answer"] = {}
    return r


@router.route("GET", "/api/bank")
def api_bank_list(req):
    _staff(req)
    subject = req.arg("subject")
    tag = req.arg("tag")
    q = req.arg("q")
    sql = "SELECT * FROM bank_questions WHERE 1=1"
    args = []
    if subject:
        sql += " AND subject=?"
        args.append(subject)
    if tag:
        sql += " AND (',' || tags || ',') LIKE ?"
        args.append("%,%s,%%" % tag)
    if q:
        sql += " AND body LIKE ?"
        args.append("%" + q + "%")
    sql += " ORDER BY id DESC"
    rows = db().q(sql, tuple(args))
    subjects = [r["subject"] for r in db().q("SELECT DISTINCT subject FROM bank_questions WHERE subject<>'' ORDER BY subject")]
    return {"items": [_out(r) for r in rows], "subjects": subjects}


@router.route("POST", "/api/bank")
def api_bank_add(req):
    _staff(req)
    d = req.json()
    qtype = d.get("type")
    body, answer, _w = normalize_question(qtype, d.get("body") or {}, d.get("answer") or {})
    bid = db().insert("bank_questions", {
        "owner_id": req.user["id"], "subject": (d.get("subject") or "").strip(), "tags": (d.get("tags") or "").strip(),
        "type": qtype, "body": json.dumps(body, ensure_ascii=False), "answer": json.dumps(answer, ensure_ascii=False),
        "points": float(d.get("points") or 1),
    })
    return {"id": bid}


@router.route("PUT", "/api/bank/:bid")
def api_bank_put(req, bid):
    _staff(req)
    r = db().one("SELECT * FROM bank_questions WHERE id=?", (int(bid),))
    need(r, "Вопрос не найден в банке", 404)
    d = req.json()
    row = pick(d, ["subject", "tags"])
    if "type" in d or "body" in d or "answer" in d:
        qtype = d.get("type") or r["type"]
        body, answer, _w = normalize_question(qtype, d.get("body") or json.loads(r["body"]), d.get("answer") or json.loads(r["answer"]))
        row.update({"type": qtype, "body": json.dumps(body, ensure_ascii=False), "answer": json.dumps(answer, ensure_ascii=False)})
    if "points" in d:
        row["points"] = float(d["points"])
    db().update("bank_questions", r["id"], row)
    return {"ok": True}


@router.route("DELETE", "/api/bank/:bid")
def api_bank_delete(req, bid):
    _staff(req)
    db().ex("DELETE FROM bank_questions WHERE id=?", (int(bid),))
    return {"ok": True}


@router.route("POST", "/api/questions/:qid/to_bank")
def api_question_to_bank(req, qid):
    """Отправить вопрос теста в банк."""
    _staff(req)
    q = db().one("SELECT * FROM questions WHERE id=?", (int(qid),))
    need(q, "Вопрос не найден", 404)
    d = req.json() or {}
    bid = db().insert("bank_questions", {
        "owner_id": req.user["id"], "subject": (d.get("subject") or "").strip(), "tags": (d.get("tags") or "").strip(),
        "type": q["type"], "body": q["body"], "answer": q["answer"], "points": q["points"], "source_test_id": q["test_id"],
    })
    return {"id": bid}


@router.route("POST", "/api/bank/:bid/insert")
def api_bank_insert(req, bid):
    """Вставить вопрос из банка в тест (в указанное задание или в последнее)."""
    from .api_tests import get_test
    r = db().one("SELECT * FROM bank_questions WHERE id=?", (int(bid),))
    need(r, "Вопрос не найден в банке", 404)
    d = req.json()
    tid = int(d.get("test_id") or 0)
    need(tid, "Не указан тест", 400)
    t = get_test(tid, req, write=True)
    task_id = d.get("task_id")
    if task_id:
        need(db().val("SELECT 1 FROM tasks WHERE id=? AND test_id=?", (int(task_id), t["id"])), "Неверное задание", 400)
    else:
        task_id = db().val("SELECT id FROM tasks WHERE test_id=? ORDER BY num DESC LIMIT 1", (t["id"],))
    sort = (db().val("SELECT MAX(sort) FROM questions WHERE test_id=?", (t["id"],)) or 0) + 1
    qid = db().insert("questions", {"test_id": t["id"], "task_id": task_id, "type": r["type"], "body": r["body"],
                                    "answer": r["answer"], "points": r["points"], "sort": sort})
    touch(t["id"])
    return E.load_question(db().one("SELECT * FROM questions WHERE id=?", (qid,)))
