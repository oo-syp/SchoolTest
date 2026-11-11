# -*- coding: utf-8 -*-
"""Учебные годы и перевод учащихся на следующий год.

Класс принадлежит учебному году. При переводе в новом году создаются новые классы
и копии учеников с тем же person_id; классы и ученики прошлого года остаются вместе
с результатами тестов, поэтому история («в каком классе был, какие тесты решал,
какие отметки получил») сохраняется."""
import re

from .web import router, db, need, need_admin, org_type


def _year_out(y):
    y = dict(y)
    y["classes"] = db().val("SELECT COUNT(*) FROM classes WHERE year_id=? AND archived=0", (y["id"],)) or 0
    y["students"] = db().val("SELECT COUNT(*) FROM students s JOIN classes c ON c.id=s.class_id "
                             "WHERE c.year_id=? AND s.active=1 AND c.archived=0", (y["id"],)) or 0
    y["runs"] = db().val("SELECT COUNT(*) FROM runs r JOIN classes c ON c.id=r.class_id WHERE c.year_id=?", (y["id"],)) or 0
    return y


def years_list():
    return [_year_out(y) for y in db().q("SELECT * FROM years ORDER BY start_date, id")]


def _next_name(name):
    m = re.match(r"^\s*(\d{4})\s*[/\-–]\s*(\d{2,4})\s*$", name or "")
    if m:
        a = int(m.group(1)) + 1
        return "%d/%d" % (a, a + 1), "%d-09-01" % a, "%d-08-31" % (a + 1)
    return (name or "") + " (новый)", None, None


@router.route("GET", "/api/years")
def api_years(req):
    return years_list()


@router.route("POST", "/api/years")
def api_year_add(req):
    need_admin(req)
    d = req.json()
    name = (d.get("name") or "").strip()
    need(name, "Укажите название учебного года, например 2027/2028", 400)
    need(not db().val("SELECT 1 FROM years WHERE name=?", (name,)), "Такой учебный год уже есть", 400)
    m = re.match(r"^(\d{4})", name)
    start = d.get("start_date") or ("%s-09-01" % m.group(1) if m else None)
    end = d.get("end_date") or ("%d-08-31" % (int(m.group(1)) + 1) if m else None)
    yid = db().insert("years", {"name": name, "start_date": start, "end_date": end, "current": 0})
    if d.get("current"):
        _set_current(yid)
    db().audit(req.user, req.ip, "year_add", name)
    return {"id": yid}


def _set_current(yid):
    with db().tx():
        db().ex("UPDATE years SET current=0")
        db().ex("UPDATE years SET current=1 WHERE id=?", (yid,))


@router.route("PUT", "/api/years/:yid")
def api_year_put(req, yid):
    need_admin(req)
    d = req.json()
    y = db().one("SELECT * FROM years WHERE id=?", (int(yid),))
    need(y, "Не найдено", 404)
    upd = {}
    for k in ("name", "start_date", "end_date"):
        if k in d:
            upd[k] = (d[k] or "").strip() or None
    if upd.get("name") is None and "name" in upd:
        upd.pop("name")
    db().update("years", y["id"], upd)
    if d.get("current"):
        _set_current(y["id"])
        db().audit(req.user, req.ip, "year_current", y["name"])
    return {"ok": True}


@router.route("DELETE", "/api/years/:yid")
def api_year_del(req, yid):
    need_admin(req)
    y = db().one("SELECT * FROM years WHERE id=?", (int(yid),))
    need(y, "Не найдено", 404)
    need(not y["current"], "Текущий учебный год удалить нельзя", 400)
    need(not db().val("SELECT 1 FROM classes WHERE year_id=?", (y["id"],)),
         "В учебном году есть классы — удалить можно только пустой год", 400)
    db().ex("DELETE FROM years WHERE id=?", (y["id"],))
    return {"ok": True}


# ------------------------------------------------------------------ перевод
def promote_name(name, grade):
    """5А → 6А, 5 «А» → 6 «А», 10-Б → 11-Б. Без номера в начале — название не меняется."""
    m = re.match(r"^(\s*)(\d{1,2})(.*)$", name or "")
    if not m:
        return name, grade
    g = int(m.group(2)) + 1
    return "%s%d%s" % (m.group(1), g, m.group(3)), g


def _default_action(c):
    if org_type() not in ("", "school"):
        return "keep"
    g = c["grade"]
    if g is None:
        m = re.match(r"\s*(\d{1,2})", c["name"] or "")
        g = int(m.group(1)) if m else None
    if g is not None and g >= 11:
        return "graduate"
    return "promote" if g is not None else "keep"


@router.route("GET", "/api/years/:yid/promote")
def api_promote_preview(req, yid):
    """Предложение перевода: для каждого класса — действие и новое название."""
    need_admin(req)
    y = db().one("SELECT * FROM years WHERE id=?", (int(yid),))
    need(y, "Не найдено", 404)
    nxt = db().one("SELECT * FROM years WHERE start_date>? ORDER BY start_date LIMIT 1", (y["start_date"] or "",)) if y["start_date"] else None
    name, start, end = _next_name(y["name"])
    target = dict(nxt) if nxt else {"id": None, "name": name, "start_date": start, "end_date": end}
    target_classes = []
    if nxt:
        target_classes = [c["name"] for c in db().q("SELECT name FROM classes WHERE year_id=? AND archived=0", (nxt["id"],))]
    out = []
    for c in db().q("SELECT * FROM classes WHERE year_id=? AND archived=0 ORDER BY grade, name", (y["id"],)):
        act = _default_action(c)
        new = promote_name(c["name"], c["grade"])[0] if act == "promote" else c["name"]
        studs = db().q("SELECT id, last_name, first_name, middle_name FROM students WHERE class_id=? AND active=1 "
                       "ORDER BY last_name, first_name", (c["id"],))
        out.append({"class_id": c["id"], "name": c["name"], "grade": c["grade"], "action": act, "new_name": new,
                    "exists": new in target_classes,
                    "students": [{"id": s["id"], "name": " ".join(x for x in (s["last_name"], s["first_name"], s["middle_name"]) if x)}
                                 for s in studs]})
    return {"from": dict(y), "to": target, "classes": out}


@router.route("POST", "/api/years/:yid/promote")
def api_promote(req, yid):
    """Перевод на следующий учебный год.

    {to: {id} или {name, start_date, end_date}, make_current: bool,
     classes: [{class_id, action: promote|keep|graduate, new_name, exclude: [student_id]}]}"""
    need_admin(req)
    d = req.json()
    y = db().one("SELECT * FROM years WHERE id=?", (int(yid),))
    need(y, "Не найдено", 404)
    to = d.get("to") or {}
    stats = {"classes": 0, "students": 0, "graduated": 0, "excluded": 0}
    with db().tx():
        if to.get("id"):
            target = db().one("SELECT * FROM years WHERE id=?", (int(to["id"]),))
            need(target and target["id"] != y["id"], "Выберите другой учебный год", 400)
            tid = target["id"]
        else:
            name = (to.get("name") or "").strip()
            need(name, "Укажите название нового учебного года", 400)
            ex = db().one("SELECT id FROM years WHERE name=?", (name,))
            tid = ex["id"] if ex else db().insert("years", {"name": name, "start_date": to.get("start_date"),
                                                            "end_date": to.get("end_date"), "current": 0})
        existing = dict((c["name"].strip().lower(), c["id"]) for c in
                        db().q("SELECT id, name FROM classes WHERE year_id=? AND archived=0", (tid,)))
        for it in d.get("classes") or []:
            c = db().one("SELECT * FROM classes WHERE id=? AND year_id=?", (int(it.get("class_id") or 0), y["id"]))
            if not c:
                continue
            act = it.get("action") or "promote"
            studs = db().q("SELECT * FROM students WHERE class_id=? AND active=1", (c["id"],))
            if act == "graduate":
                stats["graduated"] += len(studs)
                continue
            new_name = (it.get("new_name") or "").strip() or (promote_name(c["name"], c["grade"])[0] if act == "promote" else c["name"])
            grade = c["grade"]
            if act == "promote":
                grade = promote_name(c["name"], c["grade"])[1]
                if grade is not None and re.match(r"\s*(\d{1,2})", new_name):
                    grade = int(re.match(r"\s*(\d{1,2})", new_name).group(1))
            key = new_name.lower()
            if key in existing:
                ncid = existing[key]
            else:
                ncid = db().insert("classes", {"name": new_name, "grade": grade, "year_id": tid, "sg_id": None})
                existing[key] = ncid
                stats["classes"] += 1
            excl = set(int(x) for x in it.get("exclude") or [])
            have = set(r["person_id"] for r in db().q("SELECT person_id FROM students WHERE class_id=?", (ncid,)))
            for s in studs:
                if s["id"] in excl:
                    stats["excluded"] += 1
                    continue
                person = s["person_id"] or s["id"]
                if person in have:
                    continue
                db().insert("students", {"class_id": ncid, "last_name": s["last_name"], "first_name": s["first_name"],
                                         "middle_name": s["middle_name"], "sg_id": s["sg_id"], "person_id": person, "active": 1})
                stats["students"] += 1
        if d.get("make_current", True):
            db().ex("UPDATE years SET current=0")
            db().ex("UPDATE years SET current=1 WHERE id=?", (tid,))
    db().audit(req.user, req.ip, "promote", dict(stats, frm=y["name"]))
    stats["year_id"] = tid
    return stats
