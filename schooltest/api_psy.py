# -*- coding: utf-8 -*-
"""Психологическая служба: каталог методик, проведение по коду, результаты.

Результаты видят только педагоги-психологи и администратор; учителя к ним доступа не имеют.
Проведение устроено так же, как тест: код для учащихся, выбор себя в списке, наблюдение."""
import json
import re
import time
from collections import Counter

from . import auth, psy as P, psy_more, psy_socio, psy_shtur, xlsx, i18n
from . import attempts as A
from .web import router, FileResponse, db, need, is_admin, fio, XLSX_CT


def grade_of(class_name):
    """Номер класса из названия: «9А» → 9, «10 Б» → 10."""
    m = re.match(r"\s*(\d{1,2})", class_name or "")
    return int(m.group(1)) if m else 0


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
        m["kind"] = P.kind(mid)
        if mid in psy_shtur.METHODS:
            m["forms"] = psy_shtur.D.FORMS
            m["sections"] = [{"title": s["title"], "count": s["count"], "minutes": s["minutes"]}
                             for s in psy_shtur.sections()]
        m["runs"] = db().val("SELECT COUNT(*) FROM runs WHERE kind='psy' AND snapshot LIKE ?", ('%"psy": "' + mid + '"%',)) or 0
        out.append(m)
    return out


@router.route("GET", "/api/psy/methods/:mid")
def api_psy_method(req, mid):
    """Описание, вопросы (для бланка) и ключ методики."""
    need_psy(req)
    m = dict(_method(mid))
    m["id"] = mid
    m["kind"] = P.kind(mid)
    m["questions"] = P.questions(mid, {"form": req.arg("form") or "А"})
    if mid in psy_more.METHODS:
        m["key"] = psy_more.key_rows(mid)
    elif mid in psy_socio.METHODS:
        m["key"] = psy_socio.key_rows(mid)
        m["criteria"] = [{"text": c[0], "sign": c[1], "note": c[2]} for c in psy_socio.PRESET]
        m["default_criteria"] = psy_socio.DEFAULT
    elif mid in psy_shtur.METHODS:
        m["key"] = psy_shtur.key_rows(mid)
        m["forms"] = psy_shtur.D.FORMS
        m["form"] = req.arg("form") or "А"
        m["sections"] = psy_shtur.sections()
    elif mid == "ddo":
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
    st = {"show_result": d.get("show_result") if d.get("show_result") in ("none", "profile") else None}
    if mid in psy_socio.METHODS:
        studs = db().q("SELECT * FROM students WHERE class_id=? AND active=1 ORDER BY last_name, first_name", (cls["id"],))
        need(len(studs) >= 3, "В классе слишком мало учащихся для социометрии", 400)
        st["roster"] = [{"id": s["id"], "name": fio(s)} for s in studs]
        st["picks"] = max(1, min(10, int(d.get("picks") or 3)))
        cr = d.get("criteria")
        if isinstance(cr, list) and cr:
            st["criteria"] = [{"text": str(c.get("text") or "")[:300], "sign": "neg" if c.get("sign") == "neg" else "pos"}
                              for c in cr if isinstance(c, dict) and str(c.get("text") or "").strip()]
        need(st.get("criteria") or True, "Укажите хотя бы один вопрос", 400)
    if mid in psy_shtur.METHODS:
        st["form"] = d.get("form") if d.get("form") in psy_shtur.D.FORMS else "А"
        st["grade"] = grade_of(cls["name"])
        st["timed"] = d.get("timed") is not False
    if mid == "tsr":
        about = str(d.get("about") or "").strip()[:200]
        need(about, "Укажите, о каком учителе заполняется анкета", 400)
        st["about"] = about
    snap = P.snapshot(mid, st)
    code = auth.new_code(db())
    title = snap["test"]["title"] + ((" — " + st["about"]) if st.get("about") else "")
    rid = db().insert("runs", {"test_id": None, "class_id": cls["id"], "teacher_id": req.user["id"], "kind": "psy",
                               "title": title, "mode": "online", "code": code, "status": "open",
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
    settings = snap["test"]["settings"]
    socio = None
    if mid in psy_socio.METHODS:
        people = [{"id": s["id"], "name": fio(s),
                   "res": _res(att.get(s["id"])) if att.get(s["id"]) and att[s["id"]]["status"] == "finished" else None}
                  for s in studs]
        socio = psy_socio.report(settings, people)
    rows, results, sids = [], [], []
    for i, s in enumerate(studs, 1):
        sids.append(s["id"])
        a = att.get(s["id"])
        res = _res(a) if a and a["status"] == "finished" else None
        if res and socio:
            res = dict(res, group=socio["people"][i - 1])
        if res:
            results.append(res)
            rows.append([i, fio(s), time.strftime("%d.%m.%Y", time.localtime(a["finished_at"] or r["created_at"])),
                         res.get("summary", "")] + P.table_values(res) + ["; ".join(res.get("warnings") or [])])
        else:
            st = "проходит" if a and a["status"] == "active" else "не проходил(а)"
            rows.append([i, fio(s), "", st] + [""] * len(heads) + [""])
    return {"name": "Результаты", "title": "%s — %s" % (P.METHODS[mid]["short"], cls), "socio": socio,
            "about": settings.get("about") or "", "form": settings.get("form") or "",
            "subtitle": "%s · %s · %s" % (P.METHODS[mid]["name"], cls, time.strftime("%d.%m.%Y", time.localtime(r["created_at"]))),
            "headers": ["№", "Учащийся", "Дата", "Итог"] + heads + ["Замечания"],
            "widths": [5, 30, 11, 50] + [10] * len(heads) + [30], "rows": rows, "results": results, "method": mid, "sids": sids}


def group_summary(mid, results):
    """Сводка по группе: распределение типов и средние значения шкал."""
    if not results:
        return []
    out = []
    n = len(results)
    if mid in psy_more.METHODS:
        return psy_more.summary(mid, results)
    if mid in psy_shtur.METHODS:
        return psy_shtur.summary(mid, results)
    if mid in psy_socio.METHODS:
        return []
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


def socio_sheets(socio, subtitle):
    """Социоматрица и индексы отдельными листами Excel."""
    people = socio["people"]
    nums = [str(p["num"]) for p in people]
    rows = []
    for i, p in enumerate(people):
        rows.append([p["num"], p["name"]] + socio["matrix"][i] +
                    [p["made_pos"], p["made_neg"], p["got_pos"], p["got_neg"], p["mutual_pos"], p["status_name"]])
    matrix = {"name": "Социоматрица", "title": "Социометрическая матрица", "subtitle": subtitle,
              "headers": ["№", "Кто выбирает"] + nums + ["Отдано +", "Отдано –", "Получено +", "Получено –",
                                                         "Взаимных +", "Статус"],
              "widths": [4, 28] + [4] * len(nums) + [10, 10, 11, 11, 11, 22], "rows": rows}
    idx = socio["indices"]
    g = [["Учащихся в классе", idx["N"]], ["Прошли опрос", idx["done"]],
         ["Положительных выборов", "%d (%s %%)" % (idx["pos"], idx["pct_pos"])],
         ["Отрицательных выборов", "%d (%s %%)" % (idx["neg"], idx["pct_neg"])],
         ["Безразличных", "%d (%s %%)" % (idx["zero"], idx["pct_zero"])],
         ["Взаимных пар «+»", idx["pairs_pos"]], ["Взаимных пар «–»", idx["pairs_neg"]],
         ["Индекс сплочённости группы (ИС)", "%s %%" % idx["cohesion"]],
         ["Индекс групповой взаимности (ИГВ)", idx["mutuality"]],
         ["Коэффициент удовлетворённости (имеют взаимный выбор)", "%s %%" % idx["satisfaction"]]]
    for s in socio["status_order"]:
        g.append([socio["status_names"][s], socio["counts"][s]])
    ind = {"name": "Индексы", "title": "Групповые индексы", "subtitle": subtitle,
           "headers": ["Показатель", "Значение"], "widths": [52, 18], "rows": g}
    pers = {"name": "Индексы учащихся", "title": "Персональные социометрические индексы", "subtitle": subtitle,
            "headers": ["№", "Учащийся", "Статус", "ИСС", "ИСС+", "ИСС–", "ИПЭ", "ИПЭ+", "ИПЭ–", "ИВ", "ИП"],
            "widths": [4, 28, 22] + [8] * 8,
            "rows": [[p["num"], p["name"], p["status_name"], p["iss"], p["iss_pos"], p["iss_neg"],
                      p["ipe"], p["ipe_pos"], p["ipe_neg"], p["iv"], p["ip"]] for p in people]}
    return [matrix, ind, pers]


@router.route("PUT", "/api/psy/attempts/:aid/gen")
def api_psy_gen(req, aid):
    """Ручная оценка ответов субтеста «Обобщения» ШТУР-2: {номер задания: 0|1|2|null}."""
    need_psy(req)
    a = db().one("SELECT * FROM attempts WHERE id=?", (int(aid),))
    need(a, "Не найдено", 404)
    snap = A.snapshot_for(a["run_id"])
    need(snap.get("psy") in psy_shtur.METHODS, "Ручная оценка доступна только для ШТУР-2", 400)
    d = req.json() or {}
    for qid, v in (d.get("scores") or {}).items():
        try:
            n = int(qid)
        except (TypeError, ValueError):
            continue
        if not 86 <= n <= 104:
            continue
        if v in (None, ""):
            db().ex("UPDATE answers SET manual=NULL WHERE attempt_id=? AND qid=?", (a["id"], str(n)))
        else:
            try:
                val = max(0, min(2, int(v)))
            except (TypeError, ValueError):
                continue
            db().ex("INSERT INTO answers(attempt_id,qid,manual,updated_at) VALUES(?,?,?,?) "
                    "ON CONFLICT(attempt_id,qid) DO UPDATE SET manual=excluded.manual", (a["id"], str(n), val, time.time()))
    A.regrade(a["id"])
    db().audit(req.user, req.ip, "psy_gen", {"attempt": a["id"]})
    return {"ok": True}


@router.route("GET", "/api/psy/runs/:rid/results")
def api_psy_results(req, rid):
    r = _run(req, rid)
    rep = results_report(r)
    summary = group_summary(rep["method"], rep.pop("results"))
    socio = rep.get("socio")
    if req.arg("format") == "xlsx":
        rep.pop("sids", None)
        rep.pop("socio", None)
        sheets = [i18n.report(rep, "ru")]
        if socio:
            sheets += socio_sheets(socio, rep["subtitle"])
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
            resp = json.loads(row["response"]) or {}
        except (ValueError, AttributeError):
            continue
        if not isinstance(resp, dict):
            continue
        answers[row["qid"]] = resp.get("choice") if resp.get("choice") is not None else (
            resp.get("text") if resp.get("text") is not None else resp.get("choices"))
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
