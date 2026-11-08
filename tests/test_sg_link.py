# -*- coding: utf-8 -*-
"""Связка SchoolTest ↔ SchoolGrade: оба сервера запускаются по-настоящему.
Нужен исходный код SchoolGrade 1.3 рядом (../SchoolGrade) или в переменной SCHOOLGRADE_SRC."""
import base64
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SG_SRC = os.environ.get("SCHOOLGRADE_SRC") or os.path.join(os.path.dirname(ROOT), "SchoolGrade")
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
sys.path.insert(1, SG_SRC)

from test_api import Client  # noqa: E402

HAVE_SG = os.path.isdir(os.path.join(SG_SRC, "schoolgrade"))


@unittest.skipUnless(HAVE_SG, "нет исходников SchoolGrade")
class LinkTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from schoolgrade import main as SGM, server as SGS
        from schooltest import main as STM
        from schooltest.server import ServerThread
        cls.tmp = tempfile.mkdtemp()
        # --- SchoolGrade
        os.makedirs(os.path.join(cls.tmp, "sg"))
        cls.sg_app = SGM.init_app(os.path.join(cls.tmp, "sg"))
        cls.sg_srv = SGS.ServerThread(cls.sg_app, "127.0.0.1", 0)
        cls.sg_srv.start()
        sg_port = cls.sg_srv.httpd.server_address[1]
        g = Client("http://127.0.0.1:%d" % sg_port)
        g.hdr = "X-SchoolGrade"
        cls.g = g
        sgcall(g, "POST", "/api/login", {"login": "admin", "password": "admin"})
        sgcall(g, "POST", "/api/me/password", {"old": "admin", "new": "Secret123"})
        sgcall(g, "PUT", "/api/org_type", {"org_type": "secondary"})
        sgcall(g, "POST", "/api/years", {"start_year": 2026})
        cls.cid = sgcall(g, "POST", "/api/classes", {"grade": 7, "letter": "А"})["id"]
        for fio in [("Иванов", "Иван", "Иванович"), ("Петрова", "Анна", "Сергеевна"), ("Сидоров", "Пётр", "")]:
            sgcall(g, "POST", "/api/students", {"class_id": cls.cid, "last_name": fio[0], "first_name": fio[1], "middle_name": fio[2]})
        subj = [s for s in sgcall(g, "GET", "/api/subjects") if s["name"] == "Математика"][0]
        sgcall(g, "POST", "/api/assignments", {"class_id": cls.cid, "subject_id": subj["id"]})
        st = sgcall(g, "PUT", "/api/schooltest/settings", {"enabled": True})
        cls.key = st["key"]
        cls.sg_url = "127.0.0.1:%d" % sg_port
        # --- SchoolTest
        os.makedirs(os.path.join(cls.tmp, "st"))
        cls.st_app = STM.init_app(os.path.join(cls.tmp, "st"))
        cls.st_srv = ServerThread(cls.st_app, "127.0.0.1", 0)
        cls.st_srv.start()
        t = Client("http://127.0.0.1:%d" % cls.st_srv.httpd.server_address[1])
        t.post("/api/login", {"login": "admin", "password": "admin"})
        t.post("/api/me/password", {"old": "admin", "new": "Secret123"})
        t.put("/api/settings", {"org_type": "school", "sg": {"url": cls.sg_url, "key": cls.key, "import_classes": True, "export_marks": True}})
        cls.t = t

    @classmethod
    def tearDownClass(cls):
        cls.st_srv.stop()
        cls.sg_srv.stop()
        cls.st_app.db.close()
        cls.sg_app.db.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_link(self):
        t = self.t
        self.assertTrue(t.post("/api/sg/ping", {"url": self.sg_url, "key": self.key})["ok"])
        t.post("/api/sg/ping", {"url": self.sg_url, "key": "wrong"}, expect=400)
        st = t.post("/api/sg/sync_classes")
        self.assertEqual(st["classes_new"], 1)
        self.assertEqual(st["added"], 3)
        st = t.post("/api/sg/sync_classes")             # повторно — без дублей
        self.assertEqual((st["classes_new"], st["added"], st["updated"]), (0, 0, 3))
        cls = t.get("/api/classes")[0]
        self.assertEqual(cls["name"], "7 «А»")
        tid = t.post("/api/tests", {"title": "Дроби", "subject": "Математика"})["id"]
        t.post("/api/tests/%d/questions" % tid, {"type": "single", "body": {"text": "1/2 = ?", "options": [
            {"id": "a", "text": "0,5"}, {"id": "b", "text": "2"}]}, "answer": {"correct": ["a"]}})
        run = t.post("/api/runs", {"test_id": tid, "class_id": cls["id"]})
        for k, stud in enumerate(t.get("/api/classes/%d/students" % cls["id"])[:2]):
            s = Client(t.base)
            aid = s.post("/api/s/start", {"code": run["code"], "student_id": stud["id"]})["attempt_id"]
            q = s.get("/api/s/a/%d" % aid)["questions"][0]
            pick = [o["id"] for o in q["options"] if o["text"] == ("0,5" if k == 0 else "2")][0]
            s.put("/api/s/a/%d/answer" % aid, {"qid": q["id"], "response": {"choice": pick}})
            s.post("/api/s/a/%d/finish" % aid)
        info = t.get("/api/runs/%d/sg" % run["id"])
        self.assertTrue(info["network"], info)
        self.assertEqual(len(info["assignments"]), 1, info)
        self.assertEqual(len(info["marks"]), 2)
        r = t.post("/api/runs/%d/sg_send" % run["id"], {"assignment_id": info["assignments"][0]["id"], "date": "2026-11-05",
                                                         "title": "Тест «Дроби»"})
        self.assertEqual(r["saved"], 2, r)
        db = self.sg_app.db
        rows = db.q("SELECT l.work_type, l.topic, l.date, m.value FROM marks m JOIN lessons l ON l.id=m.lesson_id ORDER BY m.value")
        self.assertEqual([x["value"] for x in rows], ["1", "10"])
        self.assertEqual(rows[0]["work_type"], "тест")
        self.assertEqual(rows[0]["date"], "2026-11-05")
        # повторная отправка — тот же урок, без дублей
        r = t.post("/api/runs/%d/sg_send" % run["id"], {"assignment_id": info["assignments"][0]["id"], "date": "2026-11-05",
                                                         "title": "Тест «Дроби»"})
        self.assertEqual(db.val("SELECT COUNT(*) FROM lessons"), 1)
        # файлами: выгрузка классов SchoolGrade → SchoolTest, отметки SchoolTest → SchoolGrade
        f = sgcall(self.g, "GET", "/api/schooltest/classes_file", raw=True)
        st = t.post("/api/import/schoolgrade_file", {"data": base64.b64encode(f).decode()})
        self.assertEqual(st["added"], 0)
        mf = t.get("/api/runs/%d/sg_file" % run["id"], raw=True)
        data = base64.b64encode(mf).decode()
        p = sgcall(self.g, "POST", "/api/schooltest/marks_preview", {"data": data})
        self.assertTrue(p["class_found"])
        r = sgcall(self.g, "POST", "/api/schooltest/marks_import", {"data": data, "assignment_id": p["assignments"][0]["id"],
                                                                     "date": "2026-11-06", "title": "Тест из файла"})
        self.assertEqual(r["saved"], 2)
        self.assertEqual(db.val("SELECT COUNT(*) FROM lessons"), 2)


def sgcall(c, method, path, data=None, raw=False, expect=200):
    import urllib.request
    import urllib.error
    body = json.dumps(data).encode("utf-8") if data is not None else None
    rq = urllib.request.Request(c.base + path, data=body, method=method)
    rq.add_header("X-SchoolGrade", "1")
    rq.add_header("Content-Type", "application/json")
    try:
        r = c.op.open(rq, timeout=20)
        status, payload = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, payload = e.code, e.read()
    if status != expect:
        raise AssertionError("%s %s -> %s %s" % (method, path, status, payload[:300].decode("utf-8", "replace")))
    return payload if raw else json.loads(payload.decode("utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
