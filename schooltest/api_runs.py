# -*- coding: utf-8 -*-
"""Проведение тестов (для учителя): запуск, наблюдение, проверка, результаты,
анализ вопросов, история ученика, бумажный вариант."""
import json
import random
import time
from collections import Counter

from . import auth, engine as E, grading as G, xlsx, i18n
from . import attempts as A
from .api_tests import get_test
from .web import router, ApiError, FileResponse, db, need, is_admin, fio, default_scale, XLSX_CT

ONLINE_ACTIVE = 90   # секунд без связи — ученик «не на связи»


def get_run(rid, req):
    r = db().one("SELECT * FROM runs WHERE id=?", (int(rid),))
    need(r, "Не найдено", 404)
    need(r["teacher_id"] == req.user["id"] or is_admin(req))
    return r


@router.route("POST", "/api/runs")
def api_run_start(req):
    d = req.json()
    t = get_test(d.get("test_id"), req)
    cls = db().one("SELECT * FROM classes WHERE id=? AND archived=0", (int(d.get("class_id") or 0),))
    need(cls, "Выберите класс", 400)
    mode = "paper" if d.get("mode") == "paper" else "online"
    snap = E.build_snapshot(db(), t["id"], default_scale())
    need(snap["questions"], "В тесте нет вопросов", 400)
    code = auth.new_code(db()) if mode == "online" else None
    rid = db().insert("runs", {"test_id": t["id"], "class_id": cls["id"], "teacher_id": req.user["id"],
                               "title": t["title"], "mode": mode, "code": code, "status": "open",
                               "snapshot": json.dumps(snap, ensure_ascii=False), "created_at": time.time()})
    db().audit(req.user, req.ip, "run_start", {"test": t["title"], "class": cls["name"], "mode": mode})
    return {"id": rid, "code": code}


def _run_out(r):
    r = dict(r)
    r.pop("snapshot", None)
    r["class_name"] = db().val("SELECT name FROM classes WHERE id=?", (r["class_id"],)) or ""
    r["teacher"] = db().val("SELECT full_name FROM users WHERE id=?", (r["teacher_id"],)) or ""
    c = db().one("SELECT COUNT(*) n, SUM(status='finished') f, SUM(pending_manual) p FROM attempts WHERE run_id=?", (r["id"],))
    r["attempts"], r["finished"], r["pending"] = c["n"] or 0, c["f"] or 0, c["p"] or 0
    return r


@router.route("GET", "/api/runs")
def api_runs(req):
    sql, args = "SELECT * FROM runs WHERE 1=1", []
    if not is_admin(req) or req.arg("mine") == "1":
        sql += " AND teacher_id=?"
        args.append(req.user["id"])
    for k in ("test_id", "class_id"):
        if req.arg(k):
            sql += " AND %s=?" % k
            args.append(int(req.arg(k)))
    if req.arg("status"):
        sql += " AND status=?"
        args.append(req.arg("status"))
    sql += " ORDER BY created_at DESC LIMIT 300"
    return [_run_out(r) for r in db().q(sql, args)]


@router.route("GET", "/api/runs/:rid")
def api_run_monitor(req, rid):
    r = get_run(rid, req)
    snap = A.snapshot_for(r["id"])
    st = snap["test"]["settings"]
    studs = db().q("SELECT * FROM students WHERE class_id=? AND active=1 ORDER BY last_name, first_name", (r["class_id"],))
    att = {}
    for a in db().q("SELECT * FROM attempts WHERE run_id=? ORDER BY num", (r["id"],)):
        att[a["student_id"]] = a        # последняя попытка
    now = time.time()
    rows = []
    for s in studs:
        a = att.get(s["id"])
        row = {"student_id": s["id"], "name": fio(s), "status": "absent"}
        if a:
            plan = json.loads(a["plan"] or "[]")
            answered = db().val("SELECT COUNT(*) FROM answers WHERE attempt_id=? AND response IS NOT NULL AND response<>'null'",
                                (a["id"],))
            row.update({"attempt_id": a["id"], "status": a["status"], "num": a["num"], "answered": answered,
                        "total": len(plan), "cur": a["cur"] + 1, "focus_lost": a["focus_lost"],
                        "waiting": bool(a["pending_device"]) and a["status"] == "active",
                        "online": bool(a["last_seen"] and now - a["last_seen"] < ONLINE_ACTIVE),
                        "time_left": max(0, int(a["deadline"] - now)) if a["deadline"] and a["status"] == "active" else None,
                        "score": a["score"], "max_score": a["max_score"], "percent": a["percent"],
                        "mark": a["manual_mark"] or a["mark"], "pending": bool(a["pending_manual"]),
                        "paper": bool(a["paper"]), "variant": a["variant"]})
        rows.append(row)
    out = _run_out(r)
    out["students"] = rows
    out["settings"] = st
    out["questions"] = len(snap["questions"])
    return out


def _att(r, sid):
    a = db().one("SELECT * FROM attempts WHERE run_id=? AND student_id=? ORDER BY num DESC LIMIT 1", (r["id"], int(sid)))
    need(a, "Ученик ещё не начинал тест", 404)
    return a


@router.route("POST", "/api/runs/:rid/allow")
def api_run_allow(req, rid):
    """Разрешить продолжить тест на другом устройстве (после сбоя)."""
    r = get_run(rid, req)
    a = _att(r, req.json().get("student_id"))
    need(a["pending_device"], "Ученик не ожидает разрешения", 400)
    db().ex("UPDATE attempts SET device=pending_device, pending_device=NULL WHERE id=?", (a["id"],))
    db().audit(req.user, req.ip, "run_allow_resume", {"run": r["id"], "student": a["student_name"]})
    return {"ok": True}


@router.route("POST", "/api/runs/:rid/retake")
def api_run_retake(req, rid):
    r = get_run(rid, req)
    a = _att(r, req.json().get("student_id"))
    need(a["status"] == "finished", "Ученик ещё не завершил тест", 400)
    db().insert("attempts", {"run_id": r["id"], "student_id": a["student_id"], "student_name": a["student_name"],
                             "num": a["num"] + 1, "status": "allowed"})
    db().audit(req.user, req.ip, "run_retake", {"run": r["id"], "student": a["student_name"]})
    return {"ok": True}


@router.route("POST", "/api/runs/:rid/extend")
def api_run_extend(req, rid):
    r = get_run(rid, req)
    d = req.json()
    minutes = max(1, min(240, int(d.get("minutes") or 5)))
    if d.get("student_id"):
        a = _att(r, d["student_id"])
        ids = [a["id"]]
    else:
        ids = [x["id"] for x in db().q("SELECT id FROM attempts WHERE run_id=? AND status='active'", (r["id"],))]
    for aid in ids:
        a = db().one("SELECT * FROM attempts WHERE id=?", (aid,))
        base = max(a["deadline"] or time.time(), time.time()) if a["deadline"] else None
        if base:
            db().ex("UPDATE attempts SET deadline=? WHERE id=?", (base + minutes * 60, aid))
    return {"ok": True, "count": len(ids)}


@router.route("POST", "/api/runs/:rid/stop")
def api_run_stop_one(req, rid):
    r = get_run(rid, req)
    a = _att(r, req.json().get("student_id"))
    A.finish(a["id"], "teacher")
    return {"ok": True}


@router.route("POST", "/api/runs/:rid/close")
def api_run_close(req, rid):
    r = get_run(rid, req)
    for a in db().q("SELECT id FROM attempts WHERE run_id=? AND status='active'", (r["id"],)):
        A.finish(a["id"], "closed")
    db().ex("DELETE FROM attempts WHERE run_id=? AND status='allowed'", (r["id"],))
    db().ex("UPDATE runs SET status='closed', code=NULL, closed_at=? WHERE id=?", (time.time(), r["id"]))
    db().audit(req.user, req.ip, "run_close", r["id"])
    return {"ok": True}


@router.route("POST", "/api/runs/:rid/reopen")
def api_run_reopen(req, rid):
    r = get_run(rid, req)
    need(r["mode"] == "online", "Бумажный тест не открывается для прохождения", 400)
    code = auth.new_code(db())
    db().ex("UPDATE runs SET status='open', code=?, closed_at=NULL WHERE id=?", (code, r["id"]))
    return {"code": code}


@router.route("DELETE", "/api/runs/:rid")
def api_run_del(req, rid):
    r = get_run(rid, req)
    db().ex("DELETE FROM runs WHERE id=?", (r["id"],))
    A._SNAP_CACHE.pop(r["id"], None)
    db().audit(req.user, req.ip, "run_delete", r["id"])
    return {"ok": True}


# ------------------------------------------------------------------ подробности попытки и проверка
def _resp(row):
    try:
        return json.loads(row["response"]) if row and row.get("response") else None
    except ValueError:
        return None


@router.route("GET", "/api/attempts/:aid")
def api_attempt(req, aid):
    a = db().one("SELECT * FROM attempts WHERE id=?", (int(aid),))
    need(a, "Не найдено", 404)
    r = get_run(a["run_id"], req)
    snap = A.snapshot_for(r["id"])
    scale = snap["test"]["settings"]["scale"]
    qs = E.qmap(snap)
    ans = A.answers_map(a["id"])
    items = []
    for i, e in enumerate(json.loads(a["plan"] or "[]")):
        q = qs.get(e["q"])
        if not q:
            continue
        row = ans.get(e["q"])
        files = db().q("SELECT id, name, size FROM uploads WHERE attempt_id=? AND qid=? ORDER BY id DESC", (a["id"], e["q"]))
        items.append({"index": i, "question": q, "order": e.get("o", {}), "task_num": e["t"], "response": _resp(row),
                      "auto": row["auto"] if row else None, "manual": row["manual"] if row else None,
                      "comment": row["comment"] if row else "", "maxp": G.question_points(q, scale),
                      "manual_type": q["type"] in G.MANUAL_TYPES, "files": files})
    out = dict(a)
    out["plan"] = None
    out["focus_log"] = json.loads(a["focus_log"] or "[]")
    out["items"] = items
    out["run"] = _run_out(r)
    out["scale"] = scale
    return out


@router.route("PUT", "/api/attempts/:aid/grade")
def api_attempt_grade(req, aid):
    """Баллы за вопрос, выставленные учителем (развёрнутый ответ, файл или исправление автопроверки)."""
    a = db().one("SELECT * FROM attempts WHERE id=?", (int(aid),))
    need(a, "Не найдено", 404)
    r = get_run(a["run_id"], req)
    d = req.json()
    qid = str(d.get("qid"))
    snap = A.snapshot_for(r["id"])
    q = E.qmap(snap).get(qid)
    need(q, "Вопрос не найден", 404)
    maxp = G.question_points(q, snap["test"]["settings"]["scale"])
    pts = d.get("points")
    if pts in (None, ""):
        pts = None
    else:
        pts = float(str(pts).replace(",", "."))
        need(0 <= pts <= maxp, "Баллы — от 0 до %s" % G.round_half_up(maxp) if maxp == int(maxp) else maxp, 400)
    db().ex("INSERT INTO answers(attempt_id,qid,manual,comment,updated_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(attempt_id,qid) DO UPDATE SET manual=excluded.manual, comment=excluded.comment",
            (a["id"], qid, pts, (d.get("comment") or "")[:2000], time.time()))
    a = A.regrade(a["id"])
    return {"score": a["score"], "max_score": a["max_score"], "percent": a["percent"], "mark": a["mark"],
            "pending": bool(a["pending_manual"])}


@router.route("PUT", "/api/attempts/:aid/mark")
def api_attempt_mark(req, aid):
    """Отметка, выставленная учителем вручную (исправление итоговой отметки)."""
    a = db().one("SELECT * FROM attempts WHERE id=?", (int(aid),))
    need(a, "Не найдено", 404)
    get_run(a["run_id"], req)
    m = str(req.json().get("mark") or "").strip()
    db().ex("UPDATE attempts SET manual_mark=? WHERE id=?", (m or None, a["id"]))
    return {"ok": True}


@router.route("GET", "/api/uploads/:fid")
def api_upload_get(req, fid):
    f = db().one("SELECT u.*, a.run_id FROM uploads u JOIN attempts a ON a.id=u.attempt_id WHERE u.id=?", (int(fid),))
    need(f, "Не найдено", 404)
    get_run(f["run_id"], req)
    return FileResponse(f["data"], f["name"], "application/octet-stream")


@router.route("GET", "/api/runs/:rid/check")
def api_run_check(req, rid):
    """Ответы, ожидающие ручной проверки, по вопросам."""
    r = get_run(rid, req)
    snap = A.snapshot_for(r["id"])
    qs = E.qmap(snap)
    scale = snap["test"]["settings"]["scale"]
    out = []
    for a in db().q("SELECT * FROM attempts WHERE run_id=? AND status='finished' ORDER BY student_name", (r["id"],)):
        ans = A.answers_map(a["id"])
        for e in json.loads(a["plan"] or "[]"):
            q = qs.get(e["q"])
            if not q or q["type"] not in G.MANUAL_TYPES:
                continue
            row = ans.get(e["q"])
            resp = _resp(row)
            if not G.is_answered(q, resp):
                continue
            files = db().q("SELECT id, name, size FROM uploads WHERE attempt_id=? AND qid=? ORDER BY id DESC LIMIT 1",
                           (a["id"], e["q"]))
            out.append({"attempt_id": a["id"], "student": a["student_name"], "qid": e["q"], "question": q,
                        "response": resp, "manual": row["manual"] if row else None, "comment": row["comment"] if row else "",
                        "maxp": G.question_points(q, scale), "files": files})
    return out


# ------------------------------------------------------------------ результаты и отчёты
def _fmt_time(a):
    if not a.get("started_at") or not a.get("finished_at"):
        return ""
    s = int(a["finished_at"] - a["started_at"])
    return "%d:%02d" % (s // 60, s % 60)


def results_report(r):
    snap = A.snapshot_for(r["id"])
    st = snap["test"]["settings"]
    cls = db().val("SELECT name FROM classes WHERE id=?", (r["class_id"],)) or ""
    studs = db().q("SELECT * FROM students WHERE class_id=? AND active=1 ORDER BY last_name, first_name", (r["class_id"],))
    att = {}
    for a in db().q("SELECT * FROM attempts WHERE run_id=? AND status IN ('finished','active') ORDER BY num", (r["id"],)):
        att[a["student_id"]] = a
    rows, marks = [], []
    for i, s in enumerate(studs, 1):
        a = att.get(s["id"])
        if not a:
            rows.append([i, fio(s), "", "", "", "не проходил(а)", "", ""])
            continue
        mark = a["manual_mark"] or a["mark"]
        if a["pending_manual"] and not a["manual_mark"]:
            mark = "на проверке"
        if a["status"] == "active":
            mark = "проходит"
        if mark and str(mark).isdigit():
            marks.append(int(mark))
        score = "" if a["paper"] else ("%s из %s" % (_num(a["score"]), _num(a["max_score"])) if a["max_score"] is not None else "")
        rows.append([i, fio(s), score, "" if a["paper"] or a["percent"] is None else "%s %%" % _num(a["percent"]),
                     mark or "", _fmt_time(a) if not a["paper"] else "на бумаге",
                     a["focus_lost"] or "" if not a["paper"] else "", a["variant"] if (st.get("variants") or 1) > 1 else ""])
    if marks:
        rows.append(["", "Средняя отметка", "", "", _num(round(sum(marks) / float(len(marks)), 2)), "", "", ""])
    sc = st["scale"]
    scale_name = G.NORMS[sc["norm"]]["name"] if sc.get("mode") == "norms" and sc.get("norm") in G.NORMS else "по проценту выполнения"
    return {"name": "Результаты",
            "title": "Результаты теста «%s»" % snap["test"]["title"],
            "subtitle": "%s · %s · %s · шкала: %s" % (cls, time.strftime("%d.%m.%Y", time.localtime(r["created_at"])),
                                                      snap["test"].get("subject") or "", scale_name),
            "headers": ["№", "Ученик", "Баллы", "Процент", "Отметка", "Время", "Уходы со страницы", "Вариант"],
            "widths": [5, 32, 12, 10, 12, 10, 12, 9], "rows": rows}


def _num(v):
    if v is None:
        return ""
    v = round(float(v), 2)
    return str(int(v)) if v == int(v) else str(v).replace(".", ",")


@router.route("GET", "/api/runs/:rid/results")
def api_run_results(req, rid):
    r = get_run(rid, req)
    rep = i18n.report(results_report(r), req.lang if req.arg("lang") != "ru" else "ru")
    if req.arg("format") == "xlsx":
        return FileResponse(xlsx.build([rep]), "Результаты_%s.xlsx" % rep["title"][:40].replace(" ", "_"), XLSX_CT)
    return rep


def _short_resp(q, resp):
    """Текст ответа ученика для анализа частых ошибок."""
    if resp is None:
        return ""
    b = q["body"]
    t = q["type"]
    if t in ("single", "multi"):
        ids = [resp.get("choice")] if t == "single" else (resp.get("choices") or [])
        texts = dict((o["id"], o.get("text") or "[картинка]") for o in b.get("options", []))
        return "; ".join(texts.get(i, "?") for i in ids if i)
    if t == "short":
        return "; ".join(str(v) for v in (resp.get("fields") or {}).values() if str(v).strip())
    if t == "cloze":
        return "; ".join(str(v) for v in (resp.get("blanks") or {}).values() if str(v).strip())
    if t in ("order", "chrono"):
        key = "items" if t == "order" else "events"
        texts = dict((o["id"], o.get("text") or "?") for o in b.get(key, []))
        return " → ".join(texts.get(i, "?") for i in resp.get("order") or [])
    if t == "match":
        lt = dict((o["id"], o.get("text") or "?") for o in b.get("left", []))
        rt = dict((o["id"], o.get("text") or "?") for o in b.get("right", []))
        return "; ".join("%s — %s" % (lt.get(k, "?"), rt.get(v, "?")) for k, v in (resp.get("pairs") or {}).items() if v)
    return ""


def analysis_report(r):
    snap = A.snapshot_for(r["id"])
    scale = snap["test"]["settings"]["scale"]
    qs = snap["questions"]
    stats = dict((q["id"], {"n": 0, "full": 0, "pts": 0.0, "max": 0.0, "wrong": Counter(), "likert": {}}) for q in qs)
    attempts = db().q("SELECT * FROM attempts WHERE run_id=? AND status='finished' AND paper=0", (r["id"],))
    for a in attempts:
        ans = A.answers_map(a["id"])
        for e in json.loads(a["plan"] or "[]"):
            q = next((x for x in qs if x["id"] == e["q"]), None)
            if not q:
                continue
            s = stats[q["id"]]
            row = ans.get(q["id"])
            resp = _resp(row)
            s["n"] += 1
            if q["type"] == "likert":
                for k, v in ((resp or {}).get("values") or {}).items():
                    s["likert"].setdefault(k, Counter())[v] += 1
                continue
            maxp = G.question_points(q, scale)
            got = (row or {}).get("manual") if (row or {}).get("manual") is not None else (row or {}).get("auto")
            s["max"] += maxp
            s["pts"] += got or 0
            if maxp and (got or 0) >= maxp - 1e-9:
                s["full"] += 1
            elif q["type"] not in G.MANUAL_TYPES:
                txt = _short_resp(q, resp) or "нет ответа"
                s["wrong"][txt[:120]] += 1
    rows = []
    for i, q in enumerate(qs, 1):
        s = stats[q["id"]]
        text = _plain(q["body"].get("text") or "")[:300]
        if q["type"] == "likert":
            parts = []
            scale_names = q["body"].get("scale") or []
            for st in q["body"].get("statements", []):
                c = s["likert"].get(st["id"], Counter())
                parts.append("%s: %s" % (st["text"][:40], ", ".join("%s — %d" % (scale_names[int(k)] if str(k).isdigit() and int(k) < len(scale_names) else k, n)
                                                                    for k, n in sorted(c.items()))))
            rows.append([i, text, G.TYPE_NAMES[q["type"]], s["n"], "", "", "; ".join(parts)])
            continue
        share = 100.0 * s["full"] / s["n"] if s["n"] else 0
        avg = 100.0 * s["pts"] / s["max"] if s["max"] else 0
        common = "; ".join("«%s» — %d" % (k, n) for k, n in s["wrong"].most_common(3))
        rows.append([i, text, G.TYPE_NAMES[q["type"]], s["n"], "%s %%" % _num(round(share, 1)) if s["n"] else "",
                     "%s %%" % _num(round(avg, 1)) if s["n"] else "", common])
    return {"name": "Анализ вопросов", "title": "Анализ вопросов теста «%s»" % snap["test"]["title"],
            "subtitle": "%s · выполнили: %d" % (db().val("SELECT name FROM classes WHERE id=?", (r["class_id"],)) or "", len(attempts)),
            "headers": ["№", "Вопрос", "Тип", "Ответили", "Полностью верно", "Средний балл, % от максимума", "Самые частые ошибки"],
            "widths": [5, 50, 18, 10, 12, 14, 60], "rows": rows}


def _plain(text):
    import re
    t = re.sub(r"\{\{[^}]+\}\}", "___", text)
    return re.sub(r"\s+", " ", t).strip()


@router.route("GET", "/api/runs/:rid/analysis")
def api_run_analysis(req, rid):
    r = get_run(rid, req)
    rep = i18n.report(analysis_report(r), req.lang)
    if req.arg("format") == "xlsx":
        import re
        for row in rep["rows"]:
            row[1] = re.sub(r"\\[\(\)\[\]]", "", row[1])
        return FileResponse(xlsx.build([rep]), "Анализ_вопросов.xlsx", XLSX_CT)
    return rep


@router.route("GET", "/api/students/:sid/history")
def api_student_history(req, sid):
    s = db().one("SELECT * FROM students WHERE id=?", (int(sid),))
    need(s, "Не найдено", 404)
    sql = ("SELECT a.*, r.title, r.created_at AS run_at, r.teacher_id, r.mode FROM attempts a JOIN runs r ON r.id=a.run_id "
           "WHERE a.student_id=? AND a.status='finished'")
    args = [s["id"]]
    if not is_admin(req):
        sql += " AND r.teacher_id=?"
        args.append(req.user["id"])
    rows = []
    for i, a in enumerate(db().q(sql + " ORDER BY r.created_at", args), 1):
        mark = a["manual_mark"] or a["mark"] or ("на проверке" if a["pending_manual"] else "")
        rows.append([i, time.strftime("%d.%m.%Y", time.localtime(a["run_at"])), a["title"],
                     "" if a["paper"] else "%s %%" % _num(a["percent"]), mark, a["num"] if a["num"] > 1 else ""])
    rep = {"name": "История", "title": "История тестирования: %s" % fio(s),
           "subtitle": db().val("SELECT name FROM classes WHERE id=?", (s["class_id"],)) or "",
           "headers": ["№", "Дата", "Тест", "Процент", "Отметка", "Попытка"], "widths": [5, 12, 50, 10, 12, 9], "rows": rows}
    rep = i18n.report(rep, req.lang)
    if req.arg("format") == "xlsx":
        return FileResponse(xlsx.build([rep]), "История_%s.xlsx" % fio(s).replace(" ", "_"), XLSX_CT)
    return rep


# ------------------------------------------------------------------ бумажный тест
@router.route("GET", "/api/runs/:rid/paper")
def api_run_paper(req, rid):
    """Варианты для печати (с перемешиванием по настройкам теста) и ключ ответов."""
    r = get_run(rid, req)
    snap = A.snapshot_for(r["id"])
    st = snap["test"]["settings"]
    nvar = max(1, int(st.get("variants") or 1))
    copies = max(1, min(60, req.arg("copies", cast=int) or nvar))
    seed = req.arg("seed", cast=int) or r["id"]
    rng = random.Random(seed)
    qs = E.qmap(snap)
    excluded = []
    out = []
    for k in range(copies):
        plan, variant = E.make_plan(snap, (k % nvar) + 1, rng)
        items = []
        for e in plan:
            q = qs[e["q"]]
            if q["type"] in G.PAPER_UNSUPPORTED or (q["body"].get("audio") or {}).get("media"):
                if q["id"] not in [x["id"] for x in excluded]:
                    excluded.append({"id": q["id"], "text": _plain(q["body"].get("text", ""))[:100], "type": G.TYPE_NAMES[q["type"]]})
                continue
            pq = E.public_question(q, e, scale=st["scale"])
            items.append({"q": pq, "key": E.correct_view(q), "answer": q["answer"], "task_num": e["t"]})
        out.append({"copy": k + 1, "variant": variant, "items": items})
    return {"title": snap["test"]["title"], "subject": snap["test"].get("subject") or "",
            "class": db().val("SELECT name FROM classes WHERE id=?", (r["class_id"],)) or "",
            "copies": out, "excluded": excluded, "scale": st["scale"], "variants": nvar}


@router.route("PUT", "/api/runs/:rid/paper_marks")
def api_run_paper_marks(req, rid):
    """Отметки за бумажный тест, выставленные учителем."""
    r = get_run(rid, req)
    marks = req.json().get("marks") or {}
    n = 0
    with db().tx():
        for sid, m in marks.items():
            m = str(m or "").strip()
            stu = db().one("SELECT * FROM students WHERE id=? AND class_id=?", (int(sid), r["class_id"]))
            if not stu:
                continue
            a = db().one("SELECT * FROM attempts WHERE run_id=? AND student_id=? ORDER BY num DESC LIMIT 1", (r["id"], stu["id"]))
            if not m:
                if a and a["paper"]:
                    db().ex("DELETE FROM attempts WHERE id=?", (a["id"],))
                continue
            if a and not a["paper"]:
                db().ex("UPDATE attempts SET manual_mark=? WHERE id=?", (m, a["id"]))
            elif a:
                db().ex("UPDATE attempts SET manual_mark=?, mark=? WHERE id=?", (m, m, a["id"]))
            else:
                db().insert("attempts", {"run_id": r["id"], "student_id": stu["id"], "student_name": fio(stu), "num": 1,
                                         "status": "finished", "paper": 1, "mark": m, "manual_mark": m, "plan": "[]",
                                         "finished_at": time.time()})
            n += 1
    return {"saved": n}
