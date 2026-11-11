# -*- coding: utf-8 -*-
"""Психологическая служба: каталог методик, проведение по коду, результаты.

Результаты видят только педагоги-психологи и администратор; учителя к ним доступа не имеют.
Проведение устроено так же, как тест: код для учащихся, выбор себя в списке, наблюдение."""
import json
import time
from collections import Counter

from . import auth, psy as P, xlsx, i18n
from . import attempts as A
from .web import router, FileResponse, db, need, is_admin, fio, XLSX_CT


def need_psy(req):
    need(req.user and (req.user["role"] in ("psychologist", "admin")),
         "Раздел доступен педагогу-психологу и администратору")


def _method(mid):
    need(mid in P.METHODS, "Методика не найдена", 404)
    return P.METHODS[mid]


@router.route("GET", "/api/psy/methods")
def api_psy_methods(req):
    need_psy(req)
    out = []
    for mid in P.METHOD_ORDER:
        m = dict(P.METHODS[mid])
        m["id"] = mid
        m["runs"] = db().val("SELECT COUNT(*) FROM runs WHERE kind='psy' AND snapshot LIKE ?", ('%"psy": "' + mid + '"%',)) or 0
        out.append(m)
    return out


@router.route("GET", "/api/psy/methods/:mid")
def api_psy_method(req, mid):
    """Описание, вопросы (для бланка) и ключ методики."""
    need_psy(req)
    m = dict(_method(mid))
    m["id"] = mid
    m["questions"] = P.questions(mid)
    if mid == "ddo":
        m["key"] = [{"name": v[0], "items": v[1].replace("a", "а").replace("b", "б")} for k, v in
                    ((k, P.DDO_KEY[k]) for k in P.DDO_ORDER)]
    elif mid == "kos":
        m["key"] = [{"name": v[0], "items": "«да»: %s; «нет»: %s" % (", ".join(map(str, v[1])), ", ".join(map(str, v[2])))}
                    for v in P.KOS_KEY.values()]
    elif mid == "epi":
        m["key"] = [{"name": v[0], "items": "«да»: %s%s" % (", ".join(map(str, v[1])), ("; «нет»: " + ", ".join(map(str, v[2])))
                                                           if v[2] else "")} for v in P.EPI_KEY.values()]
    elif mid == "ki144":
        m["key"] = [{"name": "%d. %s" % (i, n), "items": ", ".join(str(i + 24 * j) for j in range(6))}
                    for i, n in enumerate(P.KI_SPHERES, 1)]
    return m


@router.route("POST", "/api/psy/runs")
def api_psy_start(req):
    need_psy(req)
    d = req.json()
    mid = d.get("method")
    _method(mid)
    cls = db().one("SELECT * FROM classes WHERE id=? AND archived=0", (int(d.get("class_id") or 0),))
    need(cls, "Выберите класс", 400)
    snap = P.snapshot(mid, {"show_result": d.get("show_result") if d.get("show_result") in ("none", "profile") else None})
    code = auth.new_code(db())
    rid = db().insert("runs", {"test_id": None, "class_id": cls["id"], "teacher_id": req.user["id"], "kind": "psy",
                               "title": P.METHODS[mid]["name"], "mode": "online", "code": code, "status": "open",
                               "snapshot": json.dumps(snap, ensure_ascii=False), "created_at": time.time()})
    db().audit(req.user, req.ip, "psy_start", {"method": mid, "class": cls["name"]})
    return {"id": rid, "code": code}


def _run(req, rid):
    need_psy(req)
    r = db().one("SELECT * FROM runs WHERE id=? AND kind='psy'", (int(rid),))
    need(r, "Не найдено", 404)
    return r


def _res(a):
    try:
        return json.loads(a["psy"]) if a.get("psy") else None
    except ValueError:
        return None


def results_report(r):
    snap = A.snapshot_for(r["id"])
    mid = snap["psy"]
    cls = db().val("SELECT name FROM classes WHERE id=?", (r["class_id"],)) or ""
    studs = db().q("SELECT * FROM students WHERE class_id=? AND active=1 ORDER BY last_name, first_name", (r["class_id"],))
    att = {}
    for a in db().q("SELECT * FROM attempts WHERE run_id=? ORDER BY num", (r["id"],)):
        att[a["student_id"]] = a
    heads = P.table_headers(mid)
    rows, results, sids = [], [], []
    for i, s in enumerate(studs, 1):
        sids.append(s["id"])
        a = att.get(s["id"])
        res = _res(a) if a and a["status"] == "finished" else None
        if res:
            results.append(res)
            rows.append([i, fio(s), time.strftime("%d.%m.%Y", time.localtime(a["finished_at"] or r["created_at"])),
                         res.get("summary", "")] + P.table_values(res) + ["; ".join(res.get("warnings") or [])])
        else:
            st = "проходит" if a and a["status"] == "active" else "не проходил(а)"
            rows.append([i, fio(s), "", st] + [""] * len(heads) + [""])
    return {"name": "Результаты", "title": "%s — %s" % (P.METHODS[mid]["short"], cls),
            "subtitle": "%s · %s · %s" % (P.METHODS[mid]["name"], cls, time.strftime("%d.%m.%Y", time.localtime(r["created_at"]))),
            "headers": ["№", "Учащийся", "Дата", "Итог"] + heads + ["Замечания"],
            "widths": [5, 30, 11, 50] + [10] * len(heads) + [30], "rows": rows, "results": results, "method": mid, "sids": sids}


def group_summary(mid, results):
    """Сводка по группе: распределение типов и средние значения шкал."""
    if not results:
        return []
    out = []
    n = len(results)
    if mid == "ddo":
        c = Counter(t for r in results for t in r.get("top") or [])
        for k in P.DDO_ORDER:
            avg = sum(s["value"] for r in results for s in r["scales"] if s["id"] == k) / float(n)
            out.append({"name": P.DDO_KEY[k][0], "count": c.get(k, 0), "avg": round(avg, 1), "max": 8})
    elif mid == "kos":
        for k in ("comm", "org"):
            lv = Counter(s["mark"] for r in results for s in r["scales"] if s["id"] == k)
            avg = sum(s["coef"] for r in results for s in r["scales"] if s["id"] == k) / float(n)
            out.append({"name": P.KOS_KEY[k][0], "avg": round(avg, 2), "max": 1,
                        "levels": [{"name": P.KOS_LEVELS[m], "count": lv.get(m, 0)} for m in range(1, 6)]})
    elif mid == "epi":
        c = Counter(r.get("temperament") for r in results)
        for k in ("sanguine", "choleric", "phlegmatic", "melancholic"):
            out.append({"name": P.EPI_TEMPER[k][0], "count": c.get(k, 0)})
        bad = sum(1 for r in results for s in r["scales"] if s["id"] == "L" and s["value"] > 5)
        out.append({"name": "Недостоверные результаты (шкала лжи > 5)", "count": bad})
    elif mid == "ki144":
        for i, name in enumerate(P.KI_SPHERES, 1):
            vals = [s["value"] for r in results for s in r["scales"] if s["id"] == "s%d" % i]
            out.append({"name": name, "avg": round(sum(vals) / float(n), 1), "count": sum(1 for v in vals if v >= 5), "max": 12, "min": -12})
    return out


@router.route("GET", "/api/psy/runs/:rid/results")
def api_psy_results(req, rid):
    r = _run(req, rid)
    rep = results_report(r)
    summary = group_summary(rep["method"], rep.pop("results"))
    if req.arg("format") == "xlsx":
        rep.pop("sids", None)
        sheets = [i18n.report(rep, "ru")]
        if summary:
            sheets.append({"name": "Сводка", "title": "Сводка по группе", "subtitle": rep["subtitle"],
                           "headers": ["Показатель", "Учащихся", "Среднее"], "widths": [50, 12, 12],
                           "rows": [[x["name"], x.get("count", ""), x.get("avg", "")] for x in summary]})
        return FileResponse(xlsx.build(sheets), "Психодиагностика_%s.xlsx" % rep["title"][:40].replace(" ", "_"), XLSX_CT)
    rep["summary"] = summary
    rep["attempts"] = dict((str(a["student_id"]), a["id"]) for a in
                           db().q("SELECT id, student_id FROM attempts WHERE run_id=? AND status='finished'", (r["id"],)))
    return rep


@router.route("GET", "/api/psy/attempts/:aid")
def api_psy_attempt(req, aid):
    need_psy(req)
    a = db().one("SELECT * FROM attempts WHERE id=?", (int(aid),))
    need(a, "Не найдено", 404)
    r = _run(req, a["run_id"])
    snap = A.snapshot_for(r["id"])
    res = _res(a) or {}
    stu = db().one("SELECT * FROM students WHERE id=?", (a["student_id"],)) if a["student_id"] else None
    answers = {}
    for row in db().q("SELECT qid, response FROM answers WHERE attempt_id=?", (a["id"],)):
        try:
            answers[row["qid"]] = (json.loads(row["response"]) or {}).get("choice")
        except (ValueError, AttributeError):
            pass
    return {"attempt_id": a["id"], "student": a["student_name"], "student_id": a["student_id"],
            "class": db().val("SELECT name FROM classes WHERE id=?", (r["class_id"],)) or "",
            "date": a["finished_at"] or a["started_at"], "method": snap["psy"], "method_name": P.METHODS[snap["psy"]]["name"],
            "result": res, "extra": json.loads(a.get("extra") or "{}"), "status": a["status"], "answers": answers,
            "person_id": stu["person_id"] if stu else None}


@router.route("GET", "/api/psy/students/:sid")
def api_psy_student(req, sid):
    """Все обследования учащегося за все учебные годы."""
    need_psy(req)
    s = db().one("SELECT * FROM students WHERE id=?", (int(sid),))
    need(s, "Не найдено", 404)
    sql = ("SELECT a.id, a.finished_at, a.psy, r.title, r.snapshot, c.name AS class_name, y.name AS year_name, r.teacher_id "
           "FROM attempts a JOIN runs r ON r.id=a.run_id JOIN students st ON st.id=a.student_id "
           "LEFT JOIN classes c ON c.id=st.class_id LEFT JOIN years y ON y.id=c.year_id "
           "WHERE st.person_id=? AND r.kind='psy' AND a.status='finished'")
    args = [s["person_id"] or s["id"]]
    out = []
    for a in db().q(sql + " ORDER BY a.finished_at", args):
        res = _res(a) or {}
        out.append({"attempt_id": a["id"], "date": a["finished_at"], "method": res.get("method"), "title": a["title"],
                    "class": a["class_name"], "year": a["year_name"], "summary": res.get("summary", "")})
    return {"student": fio(s), "items": out}
