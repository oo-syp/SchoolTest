# -*- coding: utf-8 -*-
"""Приложение SchoolTest: общий маршрутизатор и вспомогательные функции API."""
import base64
import os
import time

from .server import Router, ApiError, FileResponse  # noqa: F401  (реэкспорт для модулей API)

router = Router()
APP = {}
XLSX_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

ORG_TYPES = {
    "school": "Школа (гимназия, лицей)",
    "vuz": "ВУЗ, колледж",
    "enterprise": "Предприятие, организация",
}


class App(object):
    def __init__(self, db, data_dir, static_dir, verbose=False):
        self.db = db
        self.data_dir = data_dir
        self.static_dir = static_dir
        self.verbose = verbose
        self.backup_dir = os.path.join(data_dir, "backup")
        self.router = router
        if not os.path.isdir(self.backup_dir):
            os.makedirs(self.backup_dir)


def db():
    return APP["app"].db


def app():
    return APP["app"]


def need(cond, msg="Недостаточно прав", status=403):
    if not cond:
        raise ApiError(status, msg)


def need_admin(req):
    need(req.user and req.user["role"] == "admin")


def is_admin(req):
    return bool(req.user) and req.user["role"] == "admin"


def pick(d, keys):
    return dict((k, d[k]) for k in keys if k in d)


def org_type():
    return db().get_setting("org_type") or ""


def now():
    return time.time()


def b64data(d, field="data"):
    try:
        return base64.b64decode(d.get(field) or "")
    except Exception:
        raise ApiError(400, "Файл повреждён при загрузке")


def fio(s, full=True):
    parts = [s.get("last_name") or "", s.get("first_name") or ""]
    if full and s.get("middle_name"):
        parts.append(s["middle_name"])
    return " ".join(p for p in parts if p).strip()


def default_scale():
    return db().get_setting("default_scale") or None


def load_modules():
    # регистрация маршрутов
    from . import api_admin, api_classes, api_tests, api_runs, api_student, api_io, sgbridge  # noqa: F401
