# -*- coding: utf-8 -*-
"""Классы (группы, подразделения) и ученики."""
import csv
import io
import json
import re

from . import xls as XLS, xlsx as XLSX
from .web import router, ApiError, db, need, need_admin, pick, b64data, fio


def _class_out(c):
    c = dict(c)
    c["students"] = db().val("SELECT COUNT(*) FROM students WHERE class_id=? AND active=1", (c["id"],))
    return c


def year_arg(req, d=None):
    """Учебный год запроса: явно указанный или текущий."""
    v = (d or {}).get("year_id") if d else None
    v = v or req.arg("year_id")
    try:
        v = int(v)
    except (TypeError, ValueError):
        v = None
    if v and db().val("SELECT 1 FROM years WHERE id=?", (v,)):
        return v
    return db().current_year()


@router.route("GET", "/api/classes")
def api_classes(req):
    arch = req.arg("archived") == "1"
    if req.arg("year_id") == "all":
        rows = db().q("SELECT c.*, y.name year_name FROM classes c LEFT JOIN years y ON y.id=c.year_id WHERE c.archived=? "
                      "ORDER BY y.start_date DESC, c.grade, c.name", (1 if arch else 0,))
    else:
        rows = db().q("SELECT * FROM classes WHERE archived=? AND year_id=? ORDER BY grade, name", (1 if arch else 0, year_arg(req)))
    return [_class_out(c) for c in rows]


def _grade_of(name):
    m = re.match(r"\s*(\d{1,2})", name or "")
    return int(m.group(1)) if m else None


@router.route("POST", "/api/classes")
def api_class_add(req):
    need_admin(req)
    d = req.json()
    name = (d.get("name") or "").strip()
    need(name, "Укажите название", 400)
    cid = db().insert("classes", {"name": name, "grade": d.get("grade") or _grade_of(name), "year_id": year_arg(req, d)})
    return {"id": cid}


@router.route("PUT", "/api/classes/:cid")
def api_class_put(req, cid):
    need_admin(req)
    d = pick(req.json(), ["name", "grade", "archived"])
    if "name" in d:
        d["name"] = d["name"].strip()
        need(d["name"], "Укажите название", 400)
    db().update("classes", int(cid), d)
    return {"ok": True}


@router.route("DELETE", "/api/classes/:cid")
def api_class_del(req, cid):
    need_admin(req)
    used = db().val("SELECT COUNT(*) FROM attempts a JOIN students s ON s.id=a.student_id WHERE s.class_id=?", (int(cid),))
    if used:   # есть результаты — только в архив, чтобы не потерять историю
        db().ex("UPDATE classes SET archived=1 WHERE id=?", (int(cid),))
        return {"archived": True}
    db().ex("DELETE FROM classes WHERE id=?", (int(cid),))
    return {"deleted": True}


@router.route("GET", "/api/classes/:cid/students")
def api_students(req, cid):
    rows = db().q("SELECT * FROM students WHERE class_id=? AND (active=1 OR ?=1) ORDER BY last_name, first_name, middle_name",
                  (int(cid), 1 if req.arg("all") == "1" else 0))
    for r in rows:
        r["name"] = fio(r)
    return rows


def split_fio(s):
    s = re.sub(r"([а-яёіў])([А-ЯЁІЎ])", r"\1 \2", str(s or "").strip())
    s = re.sub(r"^\d+[.)]?\s+", "", s)          # «1. Иванов Иван»
    p = s.split()
    return (p[0] if p else ""), (p[1] if len(p) > 1 else ""), " ".join(p[2:])


def _norm(s):
    return re.sub(r"\s+", " ", str(s or "").replace("ё", "е").replace("Ё", "Е")).strip().lower()


def upsert_student(cid, last, first, middle="", sg_id=None):
    """Добавить ученика, если такого (по ФИО или по номеру в SchoolGrade) ещё нет. Возвращает (id, created).
    Поиск — только среди классов того же учебного года: в прошлых годах остаются копии с историей."""
    year = db().val("SELECT year_id FROM classes WHERE id=?", (cid,))
    person = None
    if sg_id:
        r = db().one("SELECT s.id FROM students s JOIN classes c ON c.id=s.class_id WHERE s.sg_id=? AND c.year_id IS ?",
                     (sg_id, year))
        person = db().val("SELECT person_id FROM students WHERE sg_id=? ORDER BY id DESC LIMIT 1", (sg_id,))
        if r:
            db().ex("UPDATE students SET class_id=?, last_name=?, first_name=?, middle_name=?, active=1 WHERE id=?",
                    (cid, last, first, middle, r["id"]))
            return r["id"], False
    key = _norm(" ".join([last, first]))
    for r in db().q("SELECT id, last_name, first_name, middle_name, sg_id FROM students WHERE class_id=?", (cid,)):
        if _norm(r["last_name"] + " " + r["first_name"]) == key and \
                (not middle or not r["middle_name"] or _norm(r["middle_name"]) == _norm(middle)):
            upd = {"active": 1}
            if middle and not r["middle_name"]:
                upd["middle_name"] = middle
            if sg_id and not r["sg_id"]:
                upd["sg_id"] = sg_id
            db().update("students", r["id"], upd)
            return r["id"], False
    sid = db().insert("students", {"class_id": cid, "last_name": last, "first_name": first, "middle_name": middle or "",
                                   "sg_id": sg_id})
    db().ex("UPDATE students SET person_id=? WHERE id=?", (person or sid, sid))
    return sid, True


@router.route("POST", "/api/classes/:cid/students")
def api_student_add(req, cid):
    need_admin(req)
    d = req.json()
    need((d.get("last_name") or "").strip(), "Укажите фамилию", 400)
    sid, created = upsert_student(int(cid), d["last_name"].strip(), (d.get("first_name") or "").strip(),
                                  (d.get("middle_name") or "").strip())
    need(created, "Такой ученик уже есть в списке", 400)
    return {"id": sid}


@router.route("PUT", "/api/students/:sid")
def api_student_put(req, sid):
    need_admin(req)
    d = pick(req.json(), ["last_name", "first_name", "middle_name", "class_id", "active"])
    db().update("students", int(sid), d)
    return {"ok": True}


@router.route("DELETE", "/api/students/:sid")
def api_student_del(req, sid):
    need_admin(req)
    if db().val("SELECT COUNT(*) FROM attempts WHERE student_id=?", (int(sid),)):
        db().ex("UPDATE students SET active=0 WHERE id=?", (int(sid),))
        return {"archived": True}
    db().ex("DELETE FROM students WHERE id=?", (int(sid),))
    return {"deleted": True}


@router.route("POST", "/api/classes/:cid/paste")
def api_students_paste(req, cid):
    """Список ФИО, по одному на строку."""
    need_admin(req)
    added = skipped = 0
    with db().tx():
        for line in (req.json().get("text") or "").splitlines():
            line = line.strip().strip(";,\t")
            if not line or not re.search(r"[A-Za-zА-Яа-яЁёІіЎў]", line):
                continue
            last, first, middle = split_fio(line.split("\t")[0])
            _sid, created = upsert_student(int(cid), last, first, middle)
            added += created
            skipped += not created
    return {"added": added, "skipped": skipped}


# ------------------------------------------------------------------ импорт из таблицы
_HDR = {
    "class": re.compile(r"^(класс|группа|подразделение|клас|група|падраздзяленне)", re.I),
    "fio": re.compile(r"^(фио|ф\.и\.о|прозвишча.*імя|фамилия.*имя|ученик|учащ|студент|работник|сотрудник)", re.I),
    "last": re.compile(r"^(фамилия|прозвішча)$", re.I),
    "first": re.compile(r"^(имя|імя)$", re.I),
    "middle": re.compile(r"^(отчество|імя па бацьку)$", re.I),
}


def _table_rows(filename, data):
    name = (filename or "").lower()
    if name.endswith(".xlsx"):
        rows = XLSX.read_first_sheet(data)
        return [[("" if v is None else (str(int(v)) if isinstance(v, float) and v.is_integer() else str(v))).strip()
                 for v in r] for r in rows]
    if name.endswith(".xls"):
        b = XLS.open_workbook(data)
        sh = b.sheet(b.sheet_names()[0])
        return [[sh.text(r, c) for c in range(sh.ncols)] for r in range(sh.nrows)]
    if name.endswith((".csv", ".txt")):
        for enc in ("utf-8-sig", "cp1251"):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ApiError(400, "Не удалось прочитать файл")
        sample = text[:2000]
        delim = ";" if sample.count(";") >= sample.count(",") else ","
        if "\t" in sample:
            delim = "\t"
        return [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), delimiter=delim)]
    raise ApiError(400, "Поддерживаются файлы .xlsx, .xls и .csv")


def parse_student_table(rows, default_class=None):
    """Строки таблицы -> [{class, last, first, middle, error}]."""
    rows = [r for r in rows if any(c for c in r)]
    if not rows:
        raise ApiError(400, "Таблица пуста")
    cols, hdr = {}, -1
    for i, r in enumerate(rows[:5]):
        found = {}
        for c, v in enumerate(r):
            for k, rx in _HDR.items():
                if k not in found and rx.search((v or "").strip()):
                    found[k] = c
                    break
        if "fio" in found or "last" in found:
            cols, hdr = found, i
            break
    if not cols:                      # без заголовка: [класс,] ФИО
        n = max(len(r) for r in rows)
        cols = {"fio": n - 1, "class": 0} if n >= 2 else {"fio": 0}
    out = []
    for r in rows[hdr + 1:]:
        get = lambda k: (r[cols[k]].strip() if k in cols and cols[k] < len(r) else "")  # noqa: E731
        if "last" in cols:
            last, first, middle = get("last"), get("first"), get("middle")
        else:
            last, first, middle = split_fio(get("fio"))
        cls = get("class") or (default_class or "")
        item = {"class": cls, "last": last, "first": first, "middle": middle, "error": ""}
        if not last:
            item["error"] = "нет фамилии"
        elif not first:
            item["error"] = "нет имени"
        elif not cls:
            item["error"] = "не указан класс"
        out.append(item)
    return out


@router.route("POST", "/api/import/students/preview")
def api_import_students_preview(req):
    need_admin(req)
    d = req.json()
    if d.get("text") is not None:
        rows = [re.split(r"\t|;", l) for l in d["text"].splitlines()]
    else:
        rows = _table_rows(d.get("filename"), b64data(d))
    items = parse_student_table(rows, d.get("default_class"))
    classes = dict((_norm(c["name"]), c["id"]) for c in db().q("SELECT id, name FROM classes WHERE archived=0 AND year_id=?",
                                                                 (year_arg(req, d),)))
    for it in items:
        it["class_exists"] = _norm(it["class"]) in classes
        it["exists"] = False
        if it["class_exists"] and not it["error"]:
            cid = classes[_norm(it["class"])]
            it["exists"] = bool(db().val("SELECT 1 FROM students WHERE class_id=? AND lower(last_name||' '||first_name)=?",
                                         (cid, _norm(it["last"] + " " + it["first"]))))
    return {"rows": items, "new_classes": sorted(set(it["class"] for it in items if it["class"] and not it["class_exists"]))}


@router.route("POST", "/api/import/students/commit")
def api_import_students_commit(req):
    need_admin(req)
    rows = req.json().get("rows") or []
    added = updated = classes_new = 0
    year = year_arg(req, req.json())
    cache = dict((_norm(c["name"]), c["id"]) for c in db().q("SELECT id, name FROM classes WHERE archived=0 AND year_id=?", (year,)))
    with db().tx():
        for it in rows:
            if it.get("error") or not it.get("last"):
                continue
            key = _norm(it["class"])
            if key not in cache:
                cache[key] = db().insert("classes", {"name": it["class"].strip(), "grade": _grade_of(it["class"]), "year_id": year})
                classes_new += 1
            _sid, created = upsert_student(cache[key], it["last"], it.get("first", ""), it.get("middle", ""))
            added += created
            updated += not created
    db().audit(req.user, req.ip, "students_import", {"added": added, "updated": updated})
    return {"added": added, "updated": updated, "classes_new": classes_new}


# ------------------------------------------------------------------ файл экспорта SchoolGrade
def apply_schoolgrade_classes(payload, deactivate_missing=True):
    """payload — {"classes": [{"id", "name", "grade", "students": [{"id", "last_name", ...}]}]}."""
    st = {"classes_new": 0, "classes_updated": 0, "added": 0, "updated": 0, "deactivated": 0}
    year = db().current_year()
    with db().tx():
        for c in payload.get("classes") or []:
            row = db().one("SELECT * FROM classes WHERE sg_id=? AND year_id=?", (c["id"], year)) or \
                db().one("SELECT * FROM classes WHERE sg_id IS NULL AND lower(name)=? AND archived=0 AND year_id=?",
                         (_norm(c["name"]), year))
            if row:
                db().update("classes", row["id"], {"name": c["name"], "grade": c.get("grade"), "sg_id": c["id"], "archived": 0})
                cid = row["id"]
                st["classes_updated"] += 1
            else:
                cid = db().insert("classes", {"name": c["name"], "grade": c.get("grade"), "sg_id": c["id"], "year_id": year})
                st["classes_new"] += 1
            seen = set()
            for s in c.get("students") or []:
                sid, created = upsert_student(cid, s.get("last_name", ""), s.get("first_name", ""), s.get("middle_name", ""),
                                              sg_id=s.get("id"))
                seen.add(sid)
                st["added" if created else "updated"] += 1
            if deactivate_missing:
                for r in db().q("SELECT id FROM students WHERE class_id=? AND active=1 AND sg_id IS NOT NULL", (cid,)):
                    if r["id"] not in seen:
                        db().ex("UPDATE students SET active=0 WHERE id=?", (r["id"],))
                        st["deactivated"] += 1
    return st


@router.route("POST", "/api/import/schoolgrade_file")
def api_import_sg_file(req):
    need_admin(req)
    try:
        payload = json.loads(b64data(req.json()).decode("utf-8"))
    except ValueError:
        raise ApiError(400, "Файл не является выгрузкой SchoolGrade")
    need(payload.get("format") == "schoolgrade-classes", "Файл не является выгрузкой классов SchoolGrade", 400)
    st = apply_schoolgrade_classes(payload)
    db().audit(req.user, req.ip, "sg_file_import", st)
    return st
