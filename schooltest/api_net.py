# -*- coding: utf-8 -*-
"""Адрес по имени компьютера и собственный HTTPS-сертификат школы (1.4).
HTTP и HTTPS работают на одном порту (по умолчанию 8081). Модуль cert.py общий с SchoolGrade:
один и тот же комплект сертификата (ZIP) можно импортировать в обе программы."""
import base64
import os
import re
import time

from . import cert
from .server import ApiError, FileResponse, local_addresses
from .web import router, db, app, need_admin, need


def cert_store():
    return cert.CertStore(os.path.join(app().data_dir, "certs"))


def https_enabled():
    return bool(db().get_setting("https_enabled", False))


def org_name():
    return (db().get_setting("school_name") or "SchoolTest")[:50]


def apply_tls():
    """Применить настройки HTTPS к работающему серверу (при старте и после изменений)."""
    srv = getattr(app(), "server", None)
    if srv is None:
        return
    ctx = None
    try:
        ctx = cert_store().ssl_context() if https_enabled() else None
    except Exception:  # noqa — повреждённый сертификат не должен ронять сервер
        ctx = None
    srv.set_tls(ctx, https_enabled())


def addresses(port=None, https=None):
    port = port or getattr(app(), "port", 8081)
    https = https_enabled() if https is None else https
    names = cert.host_names() or ["localhost"]
    out = []
    for n in names:
        h = n.upper() if "." not in n else n
        out.append("http://%s:%d" % (h, port))
        if https:
            out.append("https://%s:%d" % (h, port))
    out += ["http://%s:%d" % (ip, port) for ip in local_addresses()]
    return out


def public_get(h, path, query):
    if path.startswith("/blitz/"):
        from . import blitz
        return blitz.public_get(h, path, query)
    """Публичная страница: /ca.cer (DER) и /ca.crt (PEM) — корневой сертификат школы."""
    store = cert_store()
    data = store.ca_der() if path.endswith("cer") else (store.ca_pem() or "").encode()
    if not data:
        return h._send(404, "Сертификат ещё не создан", "text/plain; charset=utf-8")
    return h._send(200, data, "application/x-x509-ca-cert", [("Content-Disposition", 'attachment; filename="schoolca%s"' % path[-4:])])


@router.route("GET", "/api/server_info")
def api_server_info(req):
    return {"host": (cert.host_names() or [""])[0], "port": getattr(app(), "port", 8081), "urls": addresses(), "https": https_enabled()}


@router.route("GET", "/api/https")
def api_https(req):
    need_admin(req)
    st = cert_store().status()
    st.update({"enabled": https_enabled(), "urls": addresses(), "port": getattr(app(), "port", 8081), "ca_url": "/ca.cer"})
    return st


@router.route("POST", "/api/https/generate")
def api_https_generate(req):
    need_admin(req)
    d = req.json()
    try:
        years = max(0, min(50, int(d.get("years") or 0)))
    except (TypeError, ValueError):
        raise ApiError(400, "Срок — число лет (0 — бессрочный)")
    names = [x for x in re.split(r"[\s,;]+", d.get("names") or "") if x] if isinstance(d.get("names"), str) else (d.get("names") or [])
    try:
        cert_store().generate(years, names, org_name(), bool(d.get("new_ca")))
    except cert.CertError as e:
        raise ApiError(400, str(e))
    db().audit(req.user, req.ip, "https_generated", "years=%s" % years)
    apply_tls()
    return api_https(req)


@router.route("POST", "/api/https/enable")
def api_https_enable(req):
    need_admin(req)
    on = bool(req.json().get("enabled"))
    if on:
        need(cert_store().has_server(), "Сначала создайте или импортируйте сертификат", 400)
        try:
            cert_store().ssl_context()
        except Exception as e:  # noqa
            raise ApiError(400, "Сертификат не удалось загрузить: %s" % e)
    db().set_setting("https_enabled", on)
    apply_tls()
    return api_https(req)


@router.route("GET", "/api/https/export")
def api_https_export(req):
    need_admin(req)
    try:
        data = cert_store().export_zip(req.arg("keys") != "0")
    except cert.CertError as e:
        raise ApiError(400, str(e))
    db().audit(req.user, req.ip, "https_exported", "keys=%s" % (req.arg("keys") != "0"))
    return FileResponse(data, "SchoolCert_%s.zip" % time.strftime("%Y%m%d"), "application/zip")


@router.route("POST", "/api/https/import")
def api_https_import(req):
    need_admin(req)
    d = req.json()
    files = []
    for f in (d.get("files") or [])[:10]:
        try:
            files.append((os.path.basename(f.get("name") or "file"), base64.b64decode(f.get("data") or "")))
        except ValueError:
            raise ApiError(400, "Файл не прочитан")
    need(files, "Выберите файлы сертификата", 400)
    try:
        warns = cert_store().import_files(files, d.get("reissue", True) is not False, org_name())
    except cert.CertError as e:
        raise ApiError(400, str(e))
    db().audit(req.user, req.ip, "https_imported", "")
    apply_tls()
    st = api_https(req)
    st["warnings"] = warns
    return st


@router.route("DELETE", "/api/https")
def api_https_del(req):
    need_admin(req)
    cert_store().remove()
    db().set_setting("https_enabled", False)
    apply_tls()
    return {"ok": True}


def install(application):
    application.public_get = public_get
