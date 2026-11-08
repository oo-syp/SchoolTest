# -*- coding: utf-8 -*-
"""Связь с SchoolGrade: по локальной сети (адрес программы и ключ) или файлами.

Протокол (SchoolGrade 1.3 и новее), заголовок X-SchoolGrade-Key:
  GET  /api/ext/ping                     — проверка связи
  GET  /api/ext/classes                  — классы и ученики (format "schoolgrade-classes")
  GET  /api/ext/assignments?class_id=N   — предметы класса (нагрузка)
  POST /api/ext/marks                    — отметки за тест в журнал
Файл отметок для ручного переноса — format "schooltest-marks".
"""
import json
import re
import time
import urllib.error
import urllib.request

from . import APP_VERSION
from . import attempts as A
from .api_classes import apply_schoolgrade_classes
from .api_runs import get_run
from .web import router, ApiError, FileResponse, db, need, need_admin, fio

TIMEOUT = 15


def _cfg():
    sg = db().get_setting("sg") or {}
    need(sg.get("url") and sg.get("key"), "Связь с SchoolGrade не настроена (Администрирование → SchoolGrade)", 400)
    url = sg["url"].strip().rstrip("/")
    if not re.match(r"^https?://", url):
        url = "http://" + url
    return url, sg["key"].strip(), sg


def call(method, path, payload=None, cfg=None):
    url, key, _sg = cfg or _cfg()
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    rq = urllib.request.Request(url + path, data=data, method=method)
    rq.add_header("X-SchoolGrade-Key", key)
    rq.add_header("X-SchoolGrade", "1")       # защита SchoolGrade от подделки запросов
    rq.add_header("User-Agent", "SchoolTest/" + APP_VERSION)
    if data is not None:
        rq.add_header("Content-Type", "application/json; charset=utf-8")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # только локальная сеть, без прокси
    try:
        with opener.open(rq, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8")).get("error")
        except Exception:
            msg = None
        if e.code in (401, 403):
            raise ApiError(400, "SchoolGrade отклонил ключ доступа. Проверьте ключ в настройках")
        if e.code == 404:
            raise ApiError(400, "SchoolGrade не поддерживает связь с SchoolTest — обновите SchoolGrade до версии 1.3")
        raise ApiError(400, "Ошибка SchoolGrade: %s" % (msg or e.code))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ApiError(400, "Не удалось связаться с SchoolGrade по адресу %s. Проверьте, что программа запущена и адрес указан верно" % url)


@router.route("POST", "/api/sg/ping")
def api_sg_ping(req):
    need_admin(req)
    d = req.json()
    cfg = None
    if d.get("url") and d.get("key"):
        url = d["url"].strip().rstrip("/")
        cfg = (url if re.match(r"^https?://", url) else "http://" + url, d["key"].strip(), {})
    r = call("GET", "/api/ext/ping", cfg=cfg)
    return {"ok": True, "school": r.get("school"), "version": r.get("version")}


@router.route("POST", "/api/sg/sync_classes")
def api_sg_sync(req):
    need_admin(req)
    payload = call("GET", "/api/ext/classes")
    need(payload.get("format") == "schoolgrade-classes", "SchoolGrade вернул неожиданный ответ", 400)
    st = apply_schoolgrade_classes(payload)
    db().set_setting("sg_last_sync", time.time())
    db().audit(req.user, req.ip, "sg_sync", st)
    return st


def _class_sg(r):
    c = db().one("SELECT * FROM classes WHERE id=?", (r["class_id"],))
    return c


def run_marks(r):
    """Итоговые отметки по попыткам (последняя завершённая), только целые 1–10."""
    rows, skipped = [], []
    att = {}
    for a in db().q("SELECT * FROM attempts WHERE run_id=? AND status='finished' ORDER BY num", (r["id"],)):
        att[a["student_id"]] = a
    for s in db().q("SELECT * FROM students WHERE class_id=? ORDER BY last_name, first_name", (r["class_id"],)):
        a = att.get(s["id"])
        if not a:
            continue
        m = str(a["manual_mark"] or a["mark"] or "").strip()
        if a["pending_manual"] and not a["manual_mark"]:
            skipped.append({"name": fio(s), "reason": "ответ ещё не проверен"})
            continue
        if not re.match(r"^(10|[1-9])$", m):
            skipped.append({"name": fio(s), "reason": "нет отметки 1–10" if not m else "«%s» — не отметка 1–10" % m})
            continue
        rows.append({"student_id": s["sg_id"], "name": fio(s), "last_name": s["last_name"], "first_name": s["first_name"],
                     "middle_name": s["middle_name"], "mark": int(m)})
    return rows, skipped


@router.route("GET", "/api/runs/:rid/sg")
def api_run_sg_info(req, rid):
    """Что будет отправлено в SchoolGrade и список предметов класса."""
    r = get_run(rid, req)
    c = _class_sg(r)
    marks, skipped = run_marks(r)
    out = {"class": c["name"], "class_sg_id": c["sg_id"], "marks": marks, "skipped": skipped,
           "date": time.strftime("%Y-%m-%d", time.localtime(r["created_at"])), "title": r["title"],
           "sent": r["sg_sent"], "assignments": [], "network": False}
    sg = db().get_setting("sg") or {}
    if sg.get("url") and sg.get("key") and sg.get("export_marks", True):
        out["network"] = True
        if c["sg_id"]:
            try:
                out["assignments"] = call("GET", "/api/ext/assignments?class_id=%d" % int(c["sg_id"]))
            except ApiError as e:
                out["network_error"] = e.message
        else:
            out["network_error"] = "Класс не связан с SchoolGrade — выполните синхронизацию классов"
    return out


@router.route("POST", "/api/runs/:rid/sg_send")
def api_run_sg_send(req, rid):
    r = get_run(rid, req)
    d = req.json()
    c = _class_sg(r)
    need(c["sg_id"], "Класс не связан с SchoolGrade — выполните синхронизацию классов", 400)
    need(d.get("assignment_id"), "Выберите предмет", 400)
    date = str(d.get("date") or "")
    need(re.match(r"^\d{4}-\d{2}-\d{2}$", date), "Укажите дату", 400)
    marks, skipped = run_marks(r)
    need(marks, "Нет отметок для отправки", 400)
    res = call("POST", "/api/ext/marks", {"assignment_id": int(d["assignment_id"]), "class_id": c["sg_id"], "date": date,
                                          "title": (d.get("title") or r["title"])[:200], "source": "SchoolTest",
                                          "run": r["id"], "marks": marks,
                                          "overwrite": bool(d.get("overwrite"))})
    db().ex("UPDATE runs SET sg_sent=? WHERE id=?", (time.time(), r["id"]))
    db().audit(req.user, req.ip, "sg_marks_sent", {"run": r["id"], "saved": res.get("saved")})
    return {"saved": res.get("saved", 0), "problems": res.get("problems", []), "skipped": skipped}


@router.route("GET", "/api/runs/:rid/sg_file")
def api_run_sg_file(req, rid):
    """Файл отметок для загрузки в SchoolGrade вручную."""
    r = get_run(rid, req)
    c = _class_sg(r)
    marks, _sk = run_marks(r)
    snap = A.snapshot_for(r["id"])
    doc = {"format": "schooltest-marks", "version": 1, "app": "SchoolTest " + APP_VERSION,
           "class": {"id": c["sg_id"], "name": c["name"]}, "subject": snap["test"].get("subject") or "",
           "date": time.strftime("%Y-%m-%d", time.localtime(r["created_at"])), "title": r["title"], "marks": marks}
    name = "Отметки_%s_%s.sgmarks.json" % (re.sub(r"[^\w\-]+", "_", c["name"]), time.strftime("%d.%m.%Y", time.localtime(r["created_at"])))
    return FileResponse(json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8"), name, "application/json")
