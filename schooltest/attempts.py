# -*- coding: utf-8 -*-
"""Попытки прохождения: завершение, подсчёт, контроль времени."""
import json
import threading
import time

from . import engine as E
from .web import db

GRACE = 5   # секунд на задержку сети после окончания времени


def run_snapshot(run):
    snap = run["snapshot"]
    return json.loads(snap) if isinstance(snap, str) else snap


_SNAP_CACHE = {}


def snapshot_for(run_id):
    """Снимок теста кэшируется в памяти: при 60 учениках его не нужно разбирать на каждый запрос."""
    c = _SNAP_CACHE.get(run_id)
    if c:
        return c
    run = db().one("SELECT snapshot FROM runs WHERE id=?", (run_id,))
    if not run:
        return None
    snap = json.loads(run["snapshot"])
    if len(_SNAP_CACHE) > 200:
        _SNAP_CACHE.clear()
    _SNAP_CACHE[run_id] = snap
    return snap


def answers_map(attempt_id):
    return dict((r["qid"], r) for r in db().q("SELECT * FROM answers WHERE attempt_id=?", (attempt_id,)))


def regrade(attempt_id):
    """Пересчитать баллы и отметку попытки (после завершения или ручной проверки)."""
    a = db().one("SELECT * FROM attempts WHERE id=?", (attempt_id,))
    if not a or a["paper"]:
        return a
    snap = snapshot_for(a["run_id"])
    plan = json.loads(a["plan"] or "[]")
    ans = answers_map(attempt_id)
    if snap.get("psy"):            # психодиагностика: шкалы и интерпретация вместо отметки
        from . import psy as P
        resp = {}
        for qid, row in ans.items():
            try:
                resp[qid] = json.loads(row["response"]) if row.get("response") else None
            except ValueError:
                resp[qid] = None
        try:
            extra = json.loads(a.get("extra") or "{}")
        except ValueError:
            extra = {}
        res = P.score(snap["psy"], resp, extra)
        db().ex("UPDATE attempts SET psy=?, score=NULL, max_score=NULL, percent=NULL, mark=NULL, pending_manual=0 WHERE id=?",
                (json.dumps(res, ensure_ascii=False), attempt_id))
        return db().one("SELECT * FROM attempts WHERE id=?", (attempt_id,))
    ev, autos, _items = E.score_attempt(snap, plan, ans)
    for qid, pts in autos.items():
        if qid in ans:
            db().ex("UPDATE answers SET auto=? WHERE attempt_id=? AND qid=?", (pts, attempt_id, qid))
    db().ex("UPDATE attempts SET score=?, max_score=?, percent=?, mark=?, pending_manual=? WHERE id=?",
            (ev["score"], ev["max_score"], ev["percent"], ev["mark"], 1 if ev["pending"] else 0, attempt_id))
    return db().one("SELECT * FROM attempts WHERE id=?", (attempt_id,))


def finish(attempt_id, reason="student"):
    with db().tx():
        a = db().one("SELECT * FROM attempts WHERE id=?", (attempt_id,))
        if not a or a["status"] != "active":
            return a
        db().ex("UPDATE attempts SET status='finished', finished_at=? WHERE id=?", (time.time(), attempt_id))
        log = json.loads(a["focus_log"] or "[]")
        log.append({"t": time.time(), "e": "finish:" + reason})
        db().ex("UPDATE attempts SET focus_log=? WHERE id=?", (json.dumps(log[-300:]), attempt_id))
    return regrade(attempt_id)


def expired(a, now=None):
    return a["status"] == "active" and a["deadline"] and (now or time.time()) > a["deadline"] + GRACE


def sweep():
    """Завершить попытки с истёкшим временем (в фоне, раз в 10 секунд)."""
    now = time.time()
    for a in db().q("SELECT id, deadline, status FROM attempts WHERE status='active' AND deadline IS NOT NULL AND deadline<?",
                    (now - GRACE,)):
        finish(a["id"], "timeout")


def start_sweeper():
    def loop():
        while True:
            try:
                sweep()
            except Exception:  # noqa
                pass
            time.sleep(10)
    th = threading.Thread(target=loop, daemon=True)
    th.start()
    return th
