# -*- coding: utf-8 -*-
"""Вход, настройки, пользователи, резервные копии."""
import os

from . import APP_NAME, APP_VERSION, APP_ORG, APP_AUTHOR, APP_CITY_YEAR
from . import auth, grading as G
from .web import (router, ApiError, FileResponse, db, app, need, need_admin, pick, org_type, ORG_TYPES,
                  b64data)

SETTING_KEYS = ["org_type", "school_name", "lang", "default_scale", "sg", "upload_max_mb", "student_lang_switch"]


def _cookie(token, max_age=None):
    c = "st_session=%s; Path=/; HttpOnly; SameSite=Strict" % token
    if max_age is not None:
        c += "; Max-Age=%d" % max_age
    return c


@router.route("POST", "/api/login", public=True)
def api_login(req):
    d = req.json()
    token = auth.login(db(), d.get("login"), d.get("password"), req.ip)
    if not token:
        db().audit(None, req.ip, "login_failed", d.get("login") or "")
        raise ApiError(401, "Неверный логин или пароль")
    db().audit({"login": d.get("login")}, req.ip, "login")
    return {"ok": True}, [("Set-Cookie", _cookie(token))]


@router.route("POST", "/api/logout", public=True)
def api_logout(req):
    if req.token:
        auth.logout(db(), req.token)
    return {"ok": True}, [("Set-Cookie", _cookie("", 0))]


def public_settings():
    sg = db().get_setting("sg") or {}
    return {
        "org_type": org_type(), "org_types": ORG_TYPES,
        "school_name": db().get_setting("school_name") or "",
        "lang": db().get_setting("lang") or "ru",
        "student_lang_switch": db().get_setting("student_lang_switch", True),
        "default_scale": db().get_setting("default_scale") or G.PERCENT_DEFAULT,
        "sg": {"enabled": bool(sg.get("url") and sg.get("key")), "import_classes": bool(sg.get("import_classes")),
               "export_marks": bool(sg.get("export_marks"))},
        "upload_max_mb": db().get_setting("upload_max_mb") or 10,
        "version": APP_VERSION,
    }


@router.route("GET", "/api/public", public=True)
def api_public(req):
    s = public_settings()
    return {"school_name": s["school_name"], "org_type": s["org_type"], "lang": s["lang"],
            "student_lang_switch": s["student_lang_switch"], "version": APP_VERSION}


@router.route("GET", "/api/me")
def api_me(req):
    u = dict(req.user)
    from .server import local_addresses
    host = req.headers.get("Host") or ""
    port = host.rsplit(":", 1)[1] if ":" in host else "80"
    urls = ["http://%s:%s" % (ip, port) for ip in local_addresses()]
    return {"user": u, "urls": urls, "settings": public_settings(), "norms": norms_catalog(), "types": G.TYPE_NAMES,
            "result_kinds": G.RESULT_KINDS,
            "about": {"name": APP_NAME, "version": APP_VERSION, "org": APP_ORG, "author": APP_AUTHOR, "city": APP_CITY_YEAR}}


def norms_catalog():
    return [{"id": k, "name": v["name"], "kind": v["kind"], "note": v.get("note", ""),
             "task_points": v.get("task_points"), "levels": v.get("levels"), "table": v["table"]}
            for k, v in G.NORMS.items()]


@router.route("POST", "/api/me/password")
def api_me_password(req):
    d = req.json()
    u = db().one("SELECT * FROM users WHERE id=?", (req.user["id"],))
    need(auth.check_password(d.get("old") or "", u["pw_hash"], u["pw_salt"]), "Неверный текущий пароль", 400)
    p = auth.password_problem(d.get("new"))
    need(not p, p or "", 400)
    h, s = auth.hash_password(d["new"])
    db().ex("UPDATE users SET pw_hash=?, pw_salt=?, must_change=0 WHERE id=?", (h, s, u["id"]))
    db().ex("DELETE FROM sessions WHERE user_id=? AND token<>?", (u["id"], req.token))
    db().audit(req.user, req.ip, "password_changed")
    return {"ok": True}


@router.route("GET", "/api/settings")
def api_settings_get(req):
    need_admin(req)
    out = public_settings()
    out["sg_full"] = db().get_setting("sg") or {}
    return out


@router.route("PUT", "/api/settings")
def api_settings_put(req):
    need_admin(req)
    d = req.json()
    for k in SETTING_KEYS:
        if k not in d:
            continue
        v = d[k]
        if k == "org_type":
            need(v in ORG_TYPES, "Неизвестный тип организации", 400)
        if k == "lang":
            need(v in ("ru", "be"), "Неизвестный язык", 400)
        if k == "default_scale":
            v = _check_table(v)
        if k == "upload_max_mb":
            v = max(1, min(50, int(v or 10)))
        if k == "sg":
            old = db().get_setting("sg") or {}
            v = dict(old, **pick(v or {}, ["url", "key", "import_classes", "export_marks"]))
            v["url"] = (v.get("url") or "").strip().rstrip("/")
        db().set_setting(k, v)
    db().audit(req.user, req.ip, "settings", list(d))
    return api_settings_get(req)


def _check_table(v):
    try:
        t = sorted([[float(p), int(m)] for p, m in v], key=lambda x: -x[0])
    except (TypeError, ValueError):
        raise ApiError(400, "Неверная шкала")
    need(t and t[-1][0] == 0, "Нижний порог шкалы должен быть 0 %", 400)
    need(all(1 <= m <= 10 for _p, m in t), "Отметки шкалы — от 1 до 10", 400)
    return t


# ------------------------------------------------------------------ пользователи
@router.route("GET", "/api/users")
def api_users(req):
    need_admin(req)
    return db().q("SELECT id, login, full_name, role, active, must_change, last_login, "
                  "(SELECT COUNT(*) FROM tests t WHERE t.owner_id=users.id) AS tests FROM users ORDER BY role, full_name")


@router.route("POST", "/api/users")
def api_user_add(req):
    need_admin(req)
    d = req.json()
    login = (d.get("login") or "").strip()
    need(login, "Укажите логин", 400)
    need(not db().val("SELECT 1 FROM users WHERE login=?", (login,)), "Такой логин уже есть", 400)
    pw = d.get("password") or auth.random_password()
    p = auth.password_problem(pw)
    need(not p, p or "", 400)
    h, s = auth.hash_password(pw)
    uid = db().ex("INSERT INTO users(login,pw_hash,pw_salt,full_name,role,must_change) VALUES(?,?,?,?,?,1)",
                  (login, h, s, (d.get("full_name") or "").strip(), d.get("role") if d.get("role") in auth.ROLES else "teacher"))
    db().audit(req.user, req.ip, "user_add", login)
    return {"id": uid, "password": pw}


@router.route("PUT", "/api/users/:uid")
def api_user_put(req, uid):
    need_admin(req)
    d = pick(req.json(), ["full_name", "role", "active"])
    if "role" in d:
        need(d["role"] in auth.ROLES, "Неизвестная роль", 400)
    if int(uid) == req.user["id"]:
        d.pop("role", None)
        d.pop("active", None)
    if d.get("active") in (0, False) or d.get("role") == "teacher":
        others = db().val("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1 AND id<>?", (int(uid),))
        is_adm = db().val("SELECT role FROM users WHERE id=?", (int(uid),)) == "admin"
        need(not is_adm or others > 0, "Должен остаться хотя бы один администратор", 400)
    db().update("users", int(uid), d)
    if d.get("active") in (0, False):
        db().ex("DELETE FROM sessions WHERE user_id=?", (int(uid),))
    return {"ok": True}


@router.route("POST", "/api/users/:uid/reset")
def api_user_reset(req, uid):
    need_admin(req)
    pw = auth.random_password()
    h, s = auth.hash_password(pw)
    db().ex("UPDATE users SET pw_hash=?, pw_salt=?, must_change=1 WHERE id=?", (h, s, int(uid)))
    db().ex("DELETE FROM sessions WHERE user_id=?", (int(uid),))
    db().audit(req.user, req.ip, "user_reset", uid)
    return {"password": pw}


@router.route("DELETE", "/api/users/:uid")
def api_user_del(req, uid):
    need_admin(req)
    need(int(uid) != req.user["id"], "Нельзя удалить себя", 400)
    need(db().val("SELECT role FROM users WHERE id=?", (int(uid),)) != "admin"
         or db().val("SELECT COUNT(*) FROM users WHERE role='admin'") > 1, "Должен остаться хотя бы один администратор", 400)
    db().ex("DELETE FROM users WHERE id=?", (int(uid),))
    db().audit(req.user, req.ip, "user_delete", uid)
    return {"ok": True}


# ------------------------------------------------------------------ резервные копии
@router.route("GET", "/api/backups")
def api_backups(req):
    need_admin(req)
    d = app().backup_dir
    files = sorted((f for f in os.listdir(d) if f.endswith(".db")), reverse=True)
    return [{"name": f, "size": os.path.getsize(os.path.join(d, f))} for f in files]


@router.route("POST", "/api/backups")
def api_backup_make(req):
    need(req.user["role"] in ("admin", "teacher"))
    p = db().backup(app().backup_dir, "manual")
    db().prune_backups(app().backup_dir, 60)
    db().audit(req.user, req.ip, "backup", os.path.basename(p))
    return {"name": os.path.basename(p)}


@router.route("GET", "/api/backups/:name")
def api_backup_get(req, name):
    need_admin(req)
    name = os.path.basename(name)
    p = os.path.join(app().backup_dir, name)
    need(os.path.isfile(p) and name.endswith(".db"), "Не найдено", 404)
    with open(p, "rb") as f:
        return FileResponse(f.read(), name, "application/octet-stream")


@router.route("POST", "/api/backups/restore")
def api_backup_restore(req):
    need_admin(req)
    d = req.json()
    if d.get("name"):
        src = os.path.join(app().backup_dir, os.path.basename(d["name"]))
        need(os.path.isfile(src), "Не найдено", 404)
    else:
        src = os.path.join(app().backup_dir, "_upload.tmp")
        with open(src, "wb") as f:
            f.write(b64data(d))
    db().backup(app().backup_dir, "before_restore")
    try:
        db().restore(src)
    except Exception as e:
        raise ApiError(400, "Не удалось восстановить: %s" % e)
    finally:
        if src.endswith("_upload.tmp") and os.path.exists(src):
            os.remove(src)
    from . import attempts
    attempts._SNAP_CACHE.clear()            # снимки тестов из прежней базы больше не действительны
    db().audit(req.user, req.ip, "restore", d.get("name") or "file")
    return {"ok": True}


@router.route("GET", "/api/audit")
def api_audit(req):
    need_admin(req)
    return db().q("SELECT * FROM audit ORDER BY id DESC LIMIT 500")
