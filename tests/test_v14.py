# -*- coding: utf-8 -*-
"""Тесты версии 1.4: адрес по имени ПК, собственный HTTPS-сертификат на том же порту, экспорт/импорт, служба Windows."""
import base64
import http.client
import io
import os
import shutil
import ssl
import sys
import tempfile
import time
import unittest
import urllib.request
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from schooltest import main as M, cert, winservice  # noqa: E402
from schooltest.server import ServerThread  # noqa: E402
from test_api import Client  # noqa: E402


def b64(b):
    return base64.b64encode(b).decode("ascii")


class V14Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.app = M.init_app(cls.tmp)
        cls.srv = ServerThread(cls.app, "127.0.0.1", 0)
        cls.port = cls.srv.httpd.server_address[1]
        cls.app.port = cls.port
        cls.srv.start()
        cls.base = "http://127.0.0.1:%d" % cls.port
        a = Client(cls.base)
        a.post("/api/login", {"login": "admin", "password": "admin"})
        a.post("/api/me/password", {"old": "admin", "new": "Secret123"})
        a.put("/api/settings", {"org_type": "school"})
        a.post("/api/users", {"login": "teach", "password": "Teach1234", "full_name": "Учитель", "role": "teacher"})
        t = Client(cls.base)
        t.post("/api/login", {"login": "teach", "password": "Teach1234"})
        t.post("/api/me/password", {"old": "Teach1234", "new": "Teach12345"})
        cls.a, cls.t = a, t

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()
        cls.app.db.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def get(self, path):
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return op.open(self.base + path, timeout=10)

    def test_1_cert_unit(self):
        d = os.path.join(self.tmp, "cu")
        st = cert.CertStore(d).generate(0, ["test.local"])
        self.assertEqual(st["server"]["not_after"], "unlimited")
        self.assertTrue(st["server"]["covers_host"])
        st2 = cert.CertStore(d + "2").generate(5)
        self.assertEqual(int(st2["server"]["not_after"][:4]) - time.gmtime().tm_year, 5)

    def test_2_server_info_and_rights(self):
        info = self.a.get("/api/server_info")
        self.assertTrue(info["urls"])
        self.assertEqual(info["port"], self.port)
        self.t.get("/api/https", expect=403)
        self.t.post("/api/https/generate", {"years": 0}, expect=403)

    def test_3_https_same_port(self):
        st = self.a.post("/api/https/generate", {"years": 0, "names": "test.local"})
        self.assertTrue(st["has_ca"] and st["has_server"])
        self.a.post("/api/https/enable", {"enabled": True})
        ca = self.get("/ca.cer").read()                                           # корневой сертификат — без входа
        self.assertEqual(ca[:1], b"\x30")
        ctx = ssl.create_default_context(cadata=ca)
        con = http.client.HTTPSConnection("localhost", self.port, context=ctx, timeout=10)
        con.request("GET", "/")
        self.assertEqual(con.getresponse().status, 200)                          # HTTPS на том же порту
        self.assertEqual(self.get("/").status, 200)                              # HTTP продолжает работать
        with self.assertRaises(ssl.SSLError):                                     # без доверия к корневому — отказ
            http.client.HTTPSConnection("localhost", self.port, context=ssl.create_default_context(), timeout=10).request("GET", "/")
        self.a.post("/api/https/enable", {"enabled": False})
        with self.assertRaises((ssl.SSLError, ConnectionError, OSError)):
            c2 = http.client.HTTPSConnection("localhost", self.port, context=ctx, timeout=5)
            c2.request("GET", "/")
            c2.getresponse()
        self.a.post("/api/https/enable", {"enabled": True})

    def test_4_export_import(self):
        data = self.a.op.open(urllib.request.Request(self.base + "/api/https/export"), timeout=10).read()
        names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        for n in ("schoolca.crt", "schoolca.cer", "schoolca.key", "server.crt", "server.key", "install_ca.bat"):
            self.assertIn(n, names)
        fp = self.a.get("/api/https")["ca"]["sha256"]
        self.a.call("DELETE", "/api/https")
        self.assertFalse(self.a.get("/api/https")["has_server"])
        r = self.a.post("/api/https/import", {"files": [{"name": "SchoolCert.zip", "data": b64(data)}]})
        self.assertEqual(r["ca"]["sha256"], fp)                                   # тот же корневой сертификат
        self.assertTrue(r["has_server"])
        pub = cert.CertStore(os.path.join(self.app.data_dir, "certs")).export_zip(False)
        self.a.post("/api/https/import", {"files": [{"name": "p.zip", "data": b64(pub)}]}, expect=400)   # без ключа — ошибка

    def test_5_service_module(self):
        self.assertEqual(winservice.SERVICE_NAME, "SchoolTest")
        if not winservice.IS_WIN:
            self.assertEqual(winservice.status(), "none")
            ok, _ = winservice.install(self.tmp, 8081)
            self.assertFalse(ok)
        cmd = winservice._command("D:\\data", 8081)
        self.assertIn("--service", cmd)
        self.assertIn("8081", cmd)
        # разбор аргументов командной строки
        import argparse  # noqa: F401
        self.assertEqual(M.urls(8081, "127.0.0.1"), ["http://127.0.0.1:8081"])
        self.assertTrue(any(u.endswith(":8081") for u in M.urls(8081, "0.0.0.0")))


if __name__ == "__main__":
    unittest.main()
