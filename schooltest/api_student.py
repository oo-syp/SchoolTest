# -*- coding: utf-8 -*-
"""API ученика: вход по коду, прохождение, сохранение ответов, результат.

Учётных записей у учеников нет. Браузер получает cookie устройства (st_dev);
попытка привязывается к нему. На другом устройстве продолжить можно только
после разрешения учителя. Правильные ответы ученику до завершения не передаются."""
import json
import secrets
import time

from . import engine as E, grading as G
from . import attempts as A
from .web import router, ApiError, FileResponse, db, need, b64data, fio

_JOIN_LOG = {}
MAX_RESPONSE = 200 * 1024
DEFAULT_ACCEPT = ("pdf,doc,docx,odt,rtf,txt,xls,xlsx,ods,csv,ppt,pptx,odp,jpg,jpeg,png,gif,bmp,svg,zip,rar,7z,"
                  "py,pas,cpp,c,h,java,cs,js,html,css,sb3,dwg,psd,mp3,wav,mp4")
BLOCKED_EXT = {"exe", "com", "bat", "cmd", "msi", "scr", "vbs", "ps1", "jar", "dll", "lnk", "reg", "hta"}


def _rate_ok(ip):
    """Подбор кода: не больше 20 неверных кодов в минуту с одного адреса.
    Верные входы не ограничиваются — несколько планшетов могут выходить в сеть через один адрес."""
    now = time.time()
    hits = [t for t in _JOIN_LOG.get(ip, []) if now - t < 60]
    _JOIN_LOG[ip] = hits
    return len(hits) < 20


def _failed(ip):
    _JOIN_LOG.setdefault(ip, []).append(time.time())
    if len(_JOIN_LOG) > 5000:
        _JOIN_LOG.clear()


def _dev_cookie(token):
    return ("Set-Cookie", "st_dev=%s; Path=/; HttpOnly; SameSite=Strict; Max-Age=%d" % (token, 60 * 86400))


def _open_run(code, ip=None):
    code = "".join(ch for ch in str(code or "") if ch.isdigit())
    run = db().one("SELECT * FROM runs WHERE code=? AND status='open' AND mode='online'", (code,)) if code else None
    if not run:
        if ip:
            _failed(ip)
        raise ApiError(404, "Тест с таким кодом не найден или уже завершён")
    return run


@router.route("POST", "/api/s/join", public=True)
def s_join(req):
    need(_rate_ok(req.ip), "Слишком много попыток. Подождите минуту", 429)
    run = _open_run(req.json().get("code"), req.ip)
    snap = A.snapshot_for(run["id"])
    st = snap["test"]["settings"]
    studs = db().q("SELECT id, last_name, first_name, middle_name FROM students WHERE class_id=? AND active=1 "
                   "ORDER BY last_name, first_name", (run["class_id"],))
    cls = db().val("SELECT name FROM classes WHERE id=?", (run["class_id"],)) or ""
    out = {"run": {"title": snap["test"]["title"], "class": cls, "time_limit": st.get("time_limit") or 0,
                   "questions": len(snap["questions"]), "psy": bool(snap.get("psy")), "ask": st.get("ask") or []},
           "students": [{"id": s["id"], "name": fio(s, False)} for s in studs]}
    extra = [] if req.cookie("st_dev") else [_dev_cookie(secrets.token_urlsafe(24))]
    return out, extra


def _new_plan(run, attempt_id):
    snap = A.snapshot_for(run["id"])
    st = snap["test"]["settings"]
    nvar = max(1, int(st.get("variants") or 1))
    order = db().val("SELECT COUNT(*) FROM attempts WHERE run_id=? AND id<=?", (run["id"], attempt_id)) or 1
    plan, variant = E.make_plan(snap, ((order - 1) % nvar) + 1)
    now = time.time()
    deadline = now + int(st.get("time_limit") or 0) * 60 if st.get("time_limit") else None
    return {"plan": json.dumps(plan), "variant": variant, "started_at": now, "deadline": deadline, "last_seen": now,
            "status": "active", "cur": 0}


@router.route("POST", "/api/s/start", public=True)
def s_start(req):
    need(_rate_ok(req.ip), "Слишком много попыток. Подождите минуту", 429)
    d = req.json()
    run = _open_run(d.get("code"), req.ip)
    dev = req.cookie("st_dev")
    extra = []
    if not dev:
        dev = secrets.token_urlsafe(24)
        extra.append(_dev_cookie(dev))
    sid = d.get("student_id")
    stu = db().one("SELECT * FROM students WHERE id=? AND class_id=? AND active=1", (int(sid or 0), run["class_id"])) if sid else None
    need(stu, "Выберите себя в списке", 400)
    with db().tx():
        a = db().one("SELECT * FROM attempts WHERE run_id=? AND student_id=? ORDER BY num DESC LIMIT 1", (run["id"], stu["id"]))
        if a and a["status"] == "finished":
            raise ApiError(409, "Вы уже прошли этот тест. Повторно пройти его можно только с разрешения учителя", )
        if a and a["status"] == "active":
            if a["device"] == dev:
                aid = a["id"]
            else:
                db().ex("UPDATE attempts SET pending_device=? WHERE id=?", (dev, a["id"]))
                return {"attempt_id": a["id"], "waiting": True}, extra
        elif a and a["status"] == "allowed":       # повторное прохождение, разрешённое учителем
            db().update("attempts", a["id"], dict(_new_plan(run, a["id"]), device=dev))
            aid = a["id"]
        else:
            aid = db().insert("attempts", {"run_id": run["id"], "student_id": stu["id"], "student_name": fio(stu),
                                           "num": 1, "status": "active", "device": dev})
            db().update("attempts", aid, _new_plan(run, aid))
        ex = d.get("extra") or {}
        if isinstance(ex, dict) and ex:
            clean = {}
            if ex.get("gender") in ("m", "f"):
                clean["gender"] = ex["gender"]
            try:
                age = int(ex.get("age") or 0)
                if 5 <= age <= 99:
                    clean["age"] = age
            except (TypeError, ValueError):
                pass
            db().ex("UPDATE attempts SET extra=? WHERE id=?", (json.dumps(clean), aid))
    return {"attempt_id": aid}, extra


def _attempt(req, aid, allow_waiting=False):
    a = db().one("SELECT * FROM attempts WHERE id=?", (int(aid),))
    need(a, "Тест не начат", 404)
    dev = req.cookie("st_dev")
    if a["device"] != dev or not dev:
        if allow_waiting and dev and a["pending_device"] == dev:
            return a, True
        raise ApiError(403, "Тест уже начат на другом устройстве. Попросите учителя разрешить продолжить", "other_device")
    if A.expired(a):
        a = A.finish(a["id"], "timeout")
    return a, False


def _state(a):
    run = db().one("SELECT * FROM runs WHERE id=?", (a["run_id"],))
    snap = A.snapshot_for(a["run_id"])
    st = snap["test"]["settings"]
    plan = json.loads(a["plan"] or "[]")
    out = {"attempt_id": a["id"], "status": a["status"], "title": snap["test"]["title"], "student": a["student_name"],
           "total": len(plan), "cur": a["cur"], "free_nav": bool(st.get("free_nav", True)),
           "no_copy": bool(st.get("no_copy")), "track_focus": bool(st.get("track_focus", True)),
           "time_left": max(0, int(a["deadline"] - time.time())) if a["deadline"] and a["status"] == "active" else None}
    if snap.get("psy"):
        from . import psy as P
        m = P.METHODS[snap["psy"]]
        out["psy"] = {"method": snap["psy"], "name": m["name"], "instruction": m["instruction"]}
    if a["status"] == "active":
        qs = E.qmap(snap)
        ans = A.answers_map(a["id"])
        idx = range(len(plan)) if out["free_nav"] else [min(a["cur"], len(plan) - 1)]
        out["questions"] = []
        for i in idx:
            e = plan[i]
            q = qs.get(e["q"])
            if not q:
                continue
            pq = E.public_question(q, e, (ans.get(e["q"]) or {}).get("plays", 0))
            pq["index"] = i
            out["questions"].append(pq)
        out["responses"] = {}
        out["answered"] = []
        for qid, r in ans.items():
            try:
                resp = json.loads(r["response"]) if r["response"] else None
            except ValueError:
                resp = None
            if any(q["id"] == qid for q in out["questions"]):
                if qid in qs and qs[qid]["type"] == "code" and isinstance(resp, dict):
                    resp = {"subs": resp.get("subs") or 0}       # баллы — только в списке посылок
                out["responses"][qid] = resp
            if resp is not None and qid in qs and G.is_answered(qs[qid], resp):
                out["answered"].append(qid)
    else:
        out["result"] = _result(a, snap, run)
    return out


def _result(a, snap, run):
    st = snap["test"]["settings"]
    show = st.get("show_result", "mark")
    res = {"show": show}
    if show == "none":
        return res
    if snap.get("psy"):
        try:
            res["psy"] = json.loads(a["psy"]) if a.get("psy") else None
        except ValueError:
            res["psy"] = None
        return res
    mark = a["manual_mark"] or a["mark"]
    res.update({"mark": mark, "pending": bool(a["pending_manual"]) and not a["manual_mark"],
                "percent": a["percent"], "score": a["score"], "max_score": a["max_score"],
                "result_kind": st.get("result_kind", "mark")})
    if show == "review":
        qs = E.qmap(snap)
        ans = A.answers_map(a["id"])
        res["review"] = []
        for e in json.loads(a["plan"] or "[]"):
            q = qs.get(e["q"])
            if q:
                res["review"].append(E.review_question(q, e, ans.get(e["q"]), st["scale"]))
    return res


@router.route("GET", "/api/s/a/:aid", public=True)
def s_state(req, aid):
    a, waiting = _attempt(req, aid, allow_waiting=True)
    if waiting:
        return {"attempt_id": a["id"], "status": "waiting", "student": a["student_name"]}
    db().ex("UPDATE attempts SET last_seen=? WHERE id=?", (time.time(), a["id"]))
    return _state(a)


def _active(req, aid):
    a, _w = _attempt(req, aid)
    if a["status"] != "active":
        raise ApiError(409, "Время вышло" if a["deadline"] and time.time() > a["deadline"] else "Тест завершён", "finished")
    run = db().one("SELECT status FROM runs WHERE id=?", (a["run_id"],))
    if run["status"] != "open":
        A.finish(a["id"], "closed")
        raise ApiError(409, "Тест завершён", "finished")
    return a


@router.route("PUT", "/api/s/a/:aid/answer", public=True)
def s_answer(req, aid):
    a = _active(req, aid)
    d = req.json()
    qid = str(d.get("qid"))
    plan = json.loads(a["plan"] or "[]")
    idx = [i for i, e in enumerate(plan) if e["q"] == qid]
    need(idx, "Вопрос не найден", 404)
    snap = A.snapshot_for(a["run_id"])
    if not snap["test"]["settings"].get("free_nav", True):
        need(idx[0] == a["cur"], "Вопросы проходятся по порядку: вернуться нельзя", 409)
    qq = E.qmap(snap).get(qid)
    need(not qq or qq["type"] != "code", "Решение задачи отправляется кнопкой «Отправить»", 400)
    raw = json.dumps(d.get("response"), ensure_ascii=False)
    need(len(raw) <= MAX_RESPONSE, "Слишком большой запрос", 413)
    now = time.time()
    db().ex("INSERT INTO answers(attempt_id,qid,response,updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(attempt_id,qid) DO UPDATE SET response=excluded.response, updated_at=excluded.updated_at",
            (a["id"], qid, raw, now))
    db().ex("UPDATE attempts SET last_seen=? WHERE id=?", (now, a["id"]))
    return {"ok": True, "saved": now}


@router.route("POST", "/api/s/a/:aid/nav", public=True)
def s_nav(req, aid):
    a = _active(req, aid)
    cur = int(req.json().get("cur") or 0)
    plan = json.loads(a["plan"] or "[]")
    cur = max(0, min(cur, len(plan) - 1))
    snap = A.snapshot_for(a["run_id"])
    if not snap["test"]["settings"].get("free_nav", True):
        need(cur >= a["cur"], "Вопросы проходятся по порядку: вернуться нельзя", 409)
        if cur > a["cur"]:
            need(cur == a["cur"] + 1, "Вопросы проходятся по порядку: вернуться нельзя", 409)
            q = E.qmap(snap).get(plan[a["cur"]]["q"])
            row = db().one("SELECT response FROM answers WHERE attempt_id=? AND qid=?", (a["id"], plan[a["cur"]]["q"]))
            resp = json.loads(row["response"]) if row and row["response"] else None
            need(q and G.is_answered(q, resp), "Ответьте на вопрос, чтобы перейти к следующему", 409)
    db().ex("UPDATE attempts SET cur=?, last_seen=? WHERE id=?", (cur, time.time(), a["id"]))
    return _state(db().one("SELECT * FROM attempts WHERE id=?", (a["id"],)))


@router.route("POST", "/api/s/a/:aid/ping", public=True)
def s_ping(req, aid):
    """Сигнал «на связи» раз в 20 секунд: время, состояние (учитель мог продлить время или завершить тест)."""
    a, waiting = _attempt(req, aid, allow_waiting=True)
    if waiting:
        return {"status": "waiting"}
    if a["status"] == "active":
        run = db().one("SELECT status FROM runs WHERE id=?", (a["run_id"],))
        if run["status"] != "open":
            a = A.finish(a["id"], "closed")
        else:
            db().ex("UPDATE attempts SET last_seen=? WHERE id=?", (time.time(), a["id"]))
    return {"status": a["status"],
            "time_left": max(0, int(a["deadline"] - time.time())) if a["deadline"] and a["status"] == "active" else None}


@router.route("POST", "/api/s/a/:aid/focus", public=True)
def s_focus(req, aid):
    a, _w = _attempt(req, aid)
    if a["status"] != "active":
        return {"ok": True}
    ev = str(req.json().get("e") or "")[:20]
    log = json.loads(a["focus_log"] or "[]")
    log.append({"t": time.time(), "e": ev})
    lost = a["focus_lost"] + (1 if ev in ("blur", "hidden") else 0)
    db().ex("UPDATE attempts SET focus_lost=?, focus_log=? WHERE id=?", (lost, json.dumps(log[-300:]), a["id"]))
    return {"ok": True}


@router.route("POST", "/api/s/a/:aid/play", public=True)
def s_play(req, aid):
    a = _active(req, aid)
    qid = str(req.json().get("qid"))
    q = E.qmap(A.snapshot_for(a["run_id"])).get(qid)
    need(q and q["body"].get("audio"), "Вопрос не найден", 404)
    limit = int(q["body"]["audio"].get("plays") or 0)
    row = db().one("SELECT plays FROM answers WHERE attempt_id=? AND qid=?", (a["id"], qid))
    used = row["plays"] if row else 0
    need(not limit or used < limit, "Лимит прослушиваний исчерпан", 409)
    db().ex("INSERT INTO answers(attempt_id,qid,plays,updated_at) VALUES(?,?,1,?) "
            "ON CONFLICT(attempt_id,qid) DO UPDATE SET plays=plays+1", (a["id"], qid, time.time()))
    return {"left": (limit - used - 1) if limit else None}


@router.route("POST", "/api/s/a/:aid/upload", public=True)
def s_upload(req, aid):
    a = _active(req, aid)
    d = req.json()
    qid = str(d.get("qid"))
    q = E.qmap(A.snapshot_for(a["run_id"])).get(qid)
    need(q and q["type"] == "file", "Вопрос не найден", 404)
    name = (d.get("name") or "file").replace("\\", "/").split("/")[-1][:200]
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    allowed = [x.strip().lower().lstrip(".") for x in (q["body"].get("accept") or DEFAULT_ACCEPT).split(",") if x.strip()]
    need(ext and ext in allowed and ext not in BLOCKED_EXT, "Недопустимый тип файла", 400)
    data = b64data(d)
    limit = int(q["body"].get("max_mb") or 10)
    need(len(data) <= limit * 1024 * 1024, "Файл слишком большой", 413)
    import mimetypes
    fid = db().insert("uploads", {"attempt_id": a["id"], "qid": qid, "name": name,
                                  "mime": mimetypes.guess_type(name)[0] or "application/octet-stream",
                                  "size": len(data), "data": data, "created_at": time.time()})
    return {"file_id": fid, "name": name, "size": len(data)}


@router.route("POST", "/api/s/a/:aid/finish", public=True)
def s_finish(req, aid):
    a, _w = _attempt(req, aid)
    if a["status"] == "active":
        a = A.finish(a["id"], "student")
    return _state(a)


def _media_ids(q):
    b = q["body"]
    ids = set(b.get("images") or []) | set(b.get("task_files") or [])
    if b.get("audio"):
        ids.add(b["audio"].get("media"))
    for key in ("options", "left", "right", "items", "events"):
        for x in b.get(key) or []:
            if x.get("image"):
                ids.add(x["image"])
    return set(int(x) for x in ids if x)


@router.route("GET", "/api/s/media/:mid", public=True)
def s_media(req, mid):
    a, _w = _attempt(req, req.arg("a", cast=int) or 0)
    snap = A.snapshot_for(a["run_id"])
    qs = E.qmap(snap)
    allowed = set()
    for e in json.loads(a["plan"] or "[]"):
        if e["q"] in qs:
            allowed |= _media_ids(qs[e["q"]])
    need(int(mid) in allowed, "Не найдено", 404)
    m = db().one("SELECT * FROM media WHERE id=?", (int(mid),))
    need(m, "Не найдено", 404)
    return FileResponse(m["data"], m["name"], m["mime"] if m["kind"] != "file" else "application/octet-stream",
                        inline=m["kind"] != "file", cache=True)
