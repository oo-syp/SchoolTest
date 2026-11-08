# -*- coding: utf-8 -*-
"""HTTP-сервер SchoolTest на стандартной библиотеке Python (без зависимостей).

/            — страница ученика (ввод кода теста)
/teacher     — интерфейс учителя и администратора
/api/...     — API
"""
import json
import mimetypes
import os
import re
import socket
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs, quote

from . import auth, i18n

MAX_BODY = 60 * 1024 * 1024


class ApiError(Exception):
    def __init__(self, status, message, code=None):
        Exception.__init__(self, message)
        self.status, self.message, self.code = status, message, code


class FileResponse(object):
    def __init__(self, data, filename, ctype, inline=False, cache=False):
        self.data, self.filename, self.ctype, self.inline, self.cache = data, filename, ctype, inline, cache


class Request(object):
    def __init__(self, method, path, query, body, user, token, ip, headers, cookies):
        self.method, self.path, self.query, self.body = method, path, query, body
        self.user, self.token, self.ip, self.headers, self.cookies = user, token, ip, headers, cookies
        self.lang = (headers.get("X-Lang") or "ru")[:2]

    def arg(self, name, default=None, cast=None):
        v = self.query.get(name, [default])[0]
        if v in (None, "") and default is None:
            return None
        if cast and v not in (None, ""):
            try:
                return cast(v)
            except ValueError:
                raise ApiError(400, "Неверный параметр %s" % name)
        return v

    def json(self):
        if not self.body:
            return {}
        if not hasattr(self, "_json"):
            try:
                self._json = json.loads(self.body.decode("utf-8"))
            except ValueError:
                raise ApiError(400, "Неверный формат данных")
        return self._json

    def cookie(self, name):
        return self.cookies.get(name)


class Router(object):
    def __init__(self):
        self.routes = []

    def route(self, method, pattern, public=False):
        def deco(f):
            rx = re.compile("^" + re.sub(r":(\w+)", r"(?P<\1>[^/]+)", pattern) + "$")
            self.routes.append((method, rx, f, public))
            return f
        return deco

    def match(self, method, path):
        allowed = False
        for m, rx, f, public in self.routes:
            mt = rx.match(path)
            if mt:
                if m == method:
                    return f, mt.groupdict(), public
                allowed = True
        if allowed:
            raise ApiError(405, "Метод не поддерживается")
        return None, None, None


class ThreadingServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 128


def make_handler(app):
    static_dir = app.static_dir

    class Handler(BaseHTTPRequestHandler):
        server_version = "SchoolTest"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            if app.verbose:
                sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

        def _cookies(self):
            out = {}
            for part in self.headers.get("Cookie", "").split(";"):
                if "=" in part:
                    k, v = part.strip().split("=", 1)
                    out[k] = v
            return out

        def _send(self, status, body, ctype="application/json; charset=utf-8", extra=None):
            if isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "SAMEORIGIN")
            self.send_header("Referrer-Policy", "same-origin")
            for k, v in (extra or []):
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_PUT(self):
            self._dispatch("PUT")

        def do_DELETE(self):
            self._dispatch("DELETE")

        def _static(self, path):
            if path == "/i18n_be.js":
                return self._send(200, i18n.js(), "application/javascript; charset=utf-8", [("Cache-Control", "no-cache")])
            if path in ("/", ""):
                path = "/student.html"
            elif path == "/teacher" or path.startswith("/teacher/"):
                path = "/index.html"
            rel = os.path.normpath(path.lstrip("/")).replace("\\", "/")
            if rel.startswith("..") or rel.startswith("/"):
                return self._send(404, "Not found", "text/plain")
            full = os.path.join(static_dir, rel)
            if not os.path.isfile(full):
                return self._send(404, "Not found", "text/plain; charset=utf-8")
            ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
            if full.endswith(".js"):
                ctype = "application/javascript"
            if full.endswith(".woff2"):
                ctype = "font/woff2"
            if ctype.startswith("text/") or ctype == "application/javascript":
                ctype += "; charset=utf-8"
            with open(full, "rb") as f:
                data = f.read()
            cache = "public, max-age=86400" if "/katex/" in full.replace("\\", "/") else "no-cache"
            self._send(200, data, ctype, [("Cache-Control", cache)])

        def _dispatch(self, method):
            url = urlparse(self.path)
            path = url.path
            if not path.startswith("/api/"):
                if method != "GET":
                    return self._send(405, "Method not allowed", "text/plain")
                return self._static(path)
            lang = (self.headers.get("X-Lang") or "ru")[:2]
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    raise ApiError(413, "Слишком большой запрос")
                body = self.rfile.read(length) if length else b""
                func, params, public = app.router.match(method, path)
                if not func:
                    raise ApiError(404, "Не найдено")
                # защита от CSRF: изменяющие запросы только из интерфейса программы
                if method != "GET" and self.headers.get("X-SchoolTest") != "1":
                    raise ApiError(403, "Запрос отклонён")
                cookies = self._cookies()
                token = cookies.get("st_session")
                user = auth.session_user(app.db, token)
                if not public and not user:
                    raise ApiError(401, "Требуется вход в систему")
                if user and user.get("must_change") and not public and path not in ("/api/me", "/api/me/password", "/api/logout"):
                    raise ApiError(403, "Необходимо сменить пароль")
                req = Request(method, path, parse_qs(url.query), body, user, token, self.client_address[0], self.headers, cookies)
                res = func(req, **params)
                if isinstance(res, FileResponse):
                    disp = ("inline" if res.inline else "attachment") + "; filename*=UTF-8''" + quote(res.filename)
                    hdr = [("Content-Disposition", disp),
                           ("Cache-Control", "private, max-age=3600" if res.cache else "no-store"),
                           # загруженные файлы (в том числе SVG) не могут выполнять скрипты
                           ("Content-Security-Policy", "default-src 'none'; img-src 'self' data:; media-src 'self'; style-src 'unsafe-inline'; sandbox")]
                    return self._send(200, res.data, res.ctype, hdr)
                extra = None
                if isinstance(res, tuple):
                    res, extra = res
                self._send(200, json.dumps(res if res is not None else {"ok": True}, ensure_ascii=False),
                           extra=(extra or []) + [("Cache-Control", "no-store")])
            except ApiError as e:
                body = {"error": i18n.msg(e.message, lang)}
                if e.code:
                    body["code"] = e.code
                self._send(e.status, json.dumps(body, ensure_ascii=False))
            except ValueError as e:
                self._send(400, json.dumps({"error": i18n.msg(str(e), lang)}, ensure_ascii=False))
            except Exception as e:  # noqa
                traceback.print_exc()
                self._send(500, json.dumps({"error": i18n.msg("Внутренняя ошибка: %s" % e, lang)}, ensure_ascii=False))

    return Handler


def local_addresses():
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except socket.error:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0])
        s.close()
    except socket.error:
        pass
    ips.discard("127.0.0.1")
    return sorted(ips)


class ServerThread(threading.Thread):
    def __init__(self, app, host, port):
        threading.Thread.__init__(self)
        self.daemon = True
        self.httpd = ThreadingServer((host, port), make_handler(app))

    def run(self):
        self.httpd.serve_forever(poll_interval=0.5)

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
