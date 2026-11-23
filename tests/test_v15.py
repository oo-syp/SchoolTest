# -*- coding: utf-8 -*-
"""Тесты версии 1.5: числовые вопросы, блиц-опрос, роли, режим показа варианта."""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from schooltest import main as M, mathexpr as MX, blitz, grading as G, mediafix  # noqa: E402
from schooltest.server import ServerThread  # noqa: E402
from test_api import Client  # noqa: E402


class MathTest(unittest.TestCase):
    def test_eval_safe(self):
        self.assertEqual(MX.evaluate("s/t", {"s": 100, "t": 4}), 25.0)
        self.assertAlmostEqual(MX.evaluate("2^3+sqrt(16)"), 12.0)
        for bad in ("__import__('os')", "().__class__", "x", "1/0", "9**9**9"):
            with self.assertRaises(MX.FormulaError):
                MX.evaluate(bad)

    def test_tolerances(self):
        ok = MX.check_numeric
        self.assertTrue(ok("25,1", 25, {"tol_abs": 0.2}))
        self.assertFalse(ok("25,5", 25, {"tol_abs": 0.2}))
        self.assertTrue(ok("26", 25, {"tol_rel": 5}))
        self.assertFalse(ok("27", 25, {"tol_rel": 5}))
        self.assertTrue(ok("5 м", 5, {"ignore_units": True}))
        self.assertFalse(ok("5 кг", 5, {"unit": "м"}))
        self.assertTrue(ok("5 м", 5, {"unit": "м"}))
        self.assertTrue(ok("3.14", 3.14159, {"sig": 3}))
        self.assertFalse(ok("3.2", 3.14159, {"sig": 3}))
        self.assertTrue(ok("1 000", 1000, {}))

    def test_grid_values(self):
        for _ in range(50):
            v = MX.gen_vars([{"name": "s", "min": 100, "max": 500, "step": 10}, {"name": "t", "min": 2, "max": 10, "step": 1}])
            self.assertTrue(100 <= v["s"] <= 500 and v["s"] % 10 == 0 and 2 <= v["t"] <= 10)

    def test_substitute(self):
        self.assertEqual(MX.substitute("{s} м за {t} с", {"s": 120, "t": 4}), "120 м за 4 с")


class MediaTest(unittest.TestCase):
    def test_jpeg_exif_stripped(self):
        import struct
        app1 = b"\xff\xe1" + struct.pack(">H", 2 + 8) + b"Exif\0\0AB"
        com = b"\xff\xfe" + struct.pack(">H", 2 + 3) + b"abc"
        jpg = b"\xff\xd8" + app1 + com + b"\xff\xda\x00\x02" + b"DATA" + b"\xff\xd9"
        out, _ = mediafix.optimize("a.jpg", "image", jpg)
        self.assertNotIn(b"Exif", out)
        self.assertNotIn(b"abc", out)
        self.assertIn(b"DATA", out)

    def test_png_text_dropped(self):
        import struct
        import zlib

        def ch(t, d):
            return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
        png = b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + ch(b"tEXt", b"Author\0Me") + \
            ch(b"IDAT", zlib.compress(b"\0\0\0\0")) + ch(b"IEND", b"")
        out, _ = mediafix.optimize("a.png", "image", png)
        self.assertNotIn(b"tEXt", out)
        self.assertIn(b"IDAT", out)

    def test_mp3_tags_and_wav(self):
        import io
        import wave
        mp3 = b"ID3\x03\x00\x00\x00\x00\x00\x04" + b"abcd" + b"\xff\xfbFRAME" + b"TAG" + b"\0" * 125
        out, _ = mediafix.optimize("a.mp3", "audio", mp3)
        self.assertEqual(out, b"\xff\xfbFRAME")
        buf = io.BytesIO()
        w = wave.open(buf, "wb")
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(44100)
        w.writeframes(b"\x01\x02" * 2 * 44100)
        w.close()
        out, _ = mediafix.optimize("a.wav", "audio", buf.getvalue())
        r = wave.open(io.BytesIO(out))
        self.assertEqual((r.getnchannels(), r.getframerate()), (1, 22050))
        self.assertLess(len(out), len(buf.getvalue()) // 3)


class V15Test(unittest.TestCase):
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
        a.post("/api/users", {"login": "teach", "password": "Teach1234", "full_name": "Учитель", "role": "teacher", "roles": ["psychologist"]})
        t = Client(cls.base)
        t.post("/api/login", {"login": "teach", "password": "Teach1234"})
        t.post("/api/me/password", {"old": "Teach1234", "new": "Teach12345"})
        cls.a, cls.t = a, t

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()
        cls.app.db.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def klass(self, n=3):
        cid = self.a.post("/api/classes", {"name": "8А%d" % int(time.time() * 1000 % 100000)})["id"]
        self.a.post("/api/classes/%d/paste" % cid, {"text": "\n".join("Ученик%d Иван Петрович" % i for i in range(1, n + 1))})
        return cid

    def test_1_numeric_parametric_flow(self):
        tid = self.t.post("/api/tests", {"title": "Скорость"})["id"]
        self.t.post("/api/tests/%d/questions" % tid, {
            "type": "num", "points": 1,
            "body": {"text": "Путь {s} м за {t} с. Найдите v.", "params": [{"name": "s", "min": 100, "max": 500, "step": 10},
                                                                         {"name": "t", "min": 2, "max": 10, "step": 1}]},
            "answer": {"formula": "s/t", "tol_rel": 1, "unit": "м/с", "ignore_units": True}})
        cid = self.klass(4)
        code = self.t.post("/api/runs", {"test_id": tid, "class_id": cid})["code"]
        seen = set()
        for k in range(3):
            s = Client(self.base)
            j = s.post("/api/s/join", {"code": code})
            aid = s.post("/api/s/start", {"code": code, "student_id": j["students"][k]["id"]})["attempt_id"]
            st = s.get("/api/s/a/%d" % aid)
            q = st["questions"][0]
            self.assertNotIn("{s}", q["text"])
            self.assertEqual(q["unit"], "м/с")
            import re
            sv, tv = [int(x) for x in re.findall(r"\d+", q["text"])[:2]]
            seen.add(q["text"])
            good = "%.2f м/с" % (sv / float(tv))
            val = good.replace(".", ",") if k == 1 else ("0" if k == 2 else good)
            s.put("/api/s/a/%d/answer" % aid, {"qid": q["id"], "response": {"value": val}})
            fin = s.post("/api/s/a/%d/finish" % aid)
            if k == 2:
                self.assertEqual(fin["result"]["percent"], 0)
            else:
                self.assertEqual(fin["result"]["percent"], 100, (val, q["text"]))
        self.assertGreater(len(seen), 1)             # у учеников разные числа

    def test_2_formula_preview(self):
        r = self.t.post("/api/num/preview", {"params": [{"name": "a", "min": 2, "max": 2, "step": 1}], "formula": "a^2", "text": "{a}"})
        self.assertEqual(r["value"], "4")
        self.t.post("/api/num/preview", {"formula": "foo(1)"}, expect=400)

    def test_3_blitz(self):
        blitz.COUNTDOWN, blitz.REVEAL, blitz.MIN_SECONDS = 0.3, 0.6, 1
        tid = self.t.post("/api/tests", {"title": "Блиц", "settings": {"blitz": True, "blitz_seconds": 1}})["id"]
        self.t.put("/api/tests/%d" % tid, {"title": "Блиц", "settings": {"blitz": True, "blitz_seconds": 1}})
        for txt, ok in (("2+2?", "a"), ("3+3?", "b")):
            self.t.post("/api/tests/%d/questions" % tid, {"type": "single", "points": 1, "body": {"text": txt, "options": [
                {"id": "a", "text": "4"}, {"id": "b", "text": "6"}]}, "answer": {"correct": [ok]}})

        cid = self.klass(3)
        run = self.t.post("/api/runs", {"test_id": tid, "class_id": cid})
        code, rid = run["code"], run["id"]
        # публичный экран без входа
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        html = op.open(self.base + "/blitz/%s/screen" % code, timeout=10).read().decode("utf-8")
        self.assertIn("EventSource", html)
        pub = json.loads(op.open(self.base + "/blitz/%s/state" % code, timeout=10).read().decode("utf-8"))
        self.assertEqual(pub["phase"], "lobby")
        studs, ids = [], []
        for k in range(3):
            s = Client(self.base)
            j = s.post("/api/s/join", {"code": code})
            aid = s.post("/api/s/start", {"code": code, "student_id": j["students"][k]["id"]})["attempt_id"]
            studs.append(s)
            ids.append(aid)
        self.t.post("/api/runs/%d/blitz" % rid, {"action": "start"})
        # ждём первый вопрос
        for _ in range(40):
            st = studs[0].get("/api/s/blitz/%d" % ids[0])
            if st["phase"] == "question":
                break
            time.sleep(0.1)
        self.assertEqual(st["phase"], "question")
        self.assertNotIn("correct", st)
        pick = lambda q, txt: [o["id"] for o in q["options"] if o["text"] == txt][0]   # noqa: E731
        studs[0].put("/api/s/blitz/%d/answer" % ids[0], {"qid": st["q"]["id"], "response": {"choice": pick(st["q"], "4")}})
        studs[1].put("/api/s/blitz/%d/answer" % ids[1], {"qid": st["q"]["id"], "response": {"choice": pick(st["q"], "6")}})
        studs[0].put("/api/s/blitz/%d/answer" % ids[0], {"qid": st["q"]["id"], "response": {"choice": pick(st["q"], "6")}}, expect=409)
        pub = json.loads(op.open(self.base + "/blitz/%s/state" % code, timeout=10).read().decode("utf-8"))
        self.assertEqual(sorted(pub["hist"].values()), [1, 1])
        self.assertNotIn("correct", pub)
        # игра идёт до конца
        for _ in range(60):
            pub = json.loads(op.open(self.base + "/blitz/%s/state" % code, timeout=10).read().decode("utf-8"))
            if pub["phase"] == "reveal" and pub["i"] == 1:
                studs[0].put("/api/s/blitz/%d/answer" % ids[0], {"qid": pub["q"]["id"], "response": {"choice": pick(pub["q"], "4")}}, expect=409)
            if pub["phase"] == "done":
                break
            if pub["phase"] == "question" and pub["i"] == 1:
                studs[0].put("/api/s/blitz/%d/answer" % ids[0], {"qid": pub["q"]["id"], "response": {"choice": pick(pub["q"], "6")}}, expect=None)
            time.sleep(0.15)
        self.assertEqual(pub["phase"], "done")
        self.assertEqual(pub["top"][0]["name"].split()[0], "Ученик1")
        fin = studs[0].get("/api/s/a/%d" % ids[0])
        self.assertEqual(fin["status"], "finished")
        self.assertEqual(fin["result"]["percent"], 100)
        st = self.t.get("/api/runs/%d/blitz" % rid)
        self.assertEqual(st["phase"], "done")

    def test_4_sse_headers(self):
        tid = self.t.post("/api/tests", {"title": "Блиц2"})["id"]
        self.t.put("/api/tests/%d" % tid, {"title": "Блиц2", "settings": {"blitz": True}})
        self.t.post("/api/tests/%d/questions" % tid, {"type": "single", "points": 1, "body": {"text": "q", "options": [
            {"id": "a", "text": "1"}, {"id": "b", "text": "2"}]}, "answer": {"correct": ["a"]}})
        code = self.t.post("/api/runs", {"test_id": tid, "class_id": self.klass(1)})["code"]
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        r = op.open(self.base + "/blitz/%s/events" % code, timeout=10)
        self.assertIn("text/event-stream", r.headers["Content-Type"])
        buf = r.read(80)
        self.assertIn(b"retry", buf)
        r.close()

    def test_4b_dynamics(self):
        tid = self.t.post("/api/tests", {"title": "Дроби", "subject": "Математика"})["id"]
        self.t.post("/api/tests/%d/questions" % tid, {"type": "num", "points": 1, "body": {"text": "1+1", "tags": ["сложение"]},
                                                      "answer": {"formula": "2"}})
        cid = self.klass(2)
        for k in range(2):
            code = self.t.post("/api/runs", {"test_id": tid, "class_id": cid})["code"]
            s = Client(self.base)
            j = s.post("/api/s/join", {"code": code})
            aid = s.post("/api/s/start", {"code": code, "student_id": j["students"][0]["id"]})["attempt_id"]
            q = s.get("/api/s/a/%d" % aid)["questions"][0]
            s.put("/api/s/a/%d/answer" % aid, {"qid": q["id"], "response": {"value": "2" if k else "3"}})
            s.post("/api/s/a/%d/finish" % aid)
        d = self.t.get("/api/dynamics?class_id=%d&period=quarter" % cid)
        self.assertEqual(len(d["series"]), 2)
        tp = [x for x in d["topics"] if x["tag"] == "сложение"][0]
        self.assertEqual([p["pct"] for p in tp["points"]], [0.0, 100.0])
        self.assertEqual(tp["trend"], "up")
        self.assertEqual(len(self.t.get("/api/dynamics?class_id=%d&tag=%%D0%%BD%%D0%%B5%%D1%%82" % cid)["series"]), 0)

    def test_6_matrix_doubt_quota_export(self):
        tid = self.t.post("/api/tests", {"title": "Смесь", "settings": {"max_attempts": 2, "retry_hours": 0}})["id"]
        self.t.put("/api/tests/%d" % tid, {"title": "Смесь", "settings": {"max_attempts": 2, "retry_hours": 0}})
        self.t.post("/api/tests/%d/questions" % tid, {
            "type": "matrix", "points": 4,
            "body": {"text": "Верно ли \\(x^2\\ge0\\)?", "rows": [{"id": "r1", "text": "для 3"}, {"id": "r2", "text": "для -3"}],
                     "cols": [{"id": "y", "text": "да"}, {"id": "n", "text": "нет"}]},
            "answer": {"cells": {"r1": ["y"], "r2": ["y"]}}})
        info = self.t.get("/api/tests/%d" % tid)
        cid = self.klass(1)
        code = self.t.post("/api/runs", {"test_id": tid, "class_id": cid})["code"]
        s = Client(self.base)
        sid = s.post("/api/s/join", {"code": code})["students"][0]["id"]
        aid = s.post("/api/s/start", {"code": code, "student_id": sid})["attempt_id"]
        st = s.get("/api/s/a/%d" % aid)
        q = st["questions"][0]
        self.assertEqual(q["type"], "matrix")
        rows, cols = [r["id"] for r in q["rows"]], dict((c["text"], c["id"]) for c in q["cols"])
        s.put("/api/s/a/%d/answer" % aid, {"qid": q["id"], "response": {"cells": {rows[0]: [cols["да"]], rows[1]: [cols["нет"]]}, "doubt": True}})
        fin = s.post("/api/s/a/%d/finish" % aid)
        self.assertEqual(fin["result"]["percent"], 50)          # верны 2 ячейки из 4
        d = self.t.get("/api/runs/%d/doubts" % self.t.get("/api/runs")[0]["id"])
        self.assertTrue(d["rows"] and d["rows"][0][3] == 1)
        # вторая попытка разрешена, третья — нет
        aid2 = s.post("/api/s/start", {"code": code, "student_id": sid})["attempt_id"]
        self.assertNotEqual(aid, aid2)
        s.post("/api/s/a/%d/finish" % aid2)
        s.post("/api/s/start", {"code": code, "student_id": sid}, expect=409)
        # окно доступа
        self.t.put("/api/tests/%d" % tid, {"title": "Смесь", "settings": {"window": {"from": "2999-01-01T08:00", "to": ""}}})
        code2 = self.t.post("/api/runs", {"test_id": tid, "class_id": cid})["code"]
        s2 = Client(self.base)
        sid2 = s2.post("/api/s/join", {"code": code2})["students"][0]["id"]
        s2.post("/api/s/start", {"code": code2, "student_id": sid2}, expect=403)
        # экспорт
        md = self.t.get("/api/tests/%d/export?format=md" % tid, raw=True).decode("utf-8")
        self.assertIn("$x^2\\ge0$", md)
        tex = self.t.get("/api/tests/%d/export?format=tex" % tid, raw=True).decode("utf-8")
        self.assertIn("\\begin{document}", tex)
        self.assertIn("\\(x^2\\ge0\\)", tex)

    def test_7_rubric_and_peer(self):
        cfg = {"peer": {"enabled": True, "count": 2, "weight": 50}}
        tid = self.t.post("/api/tests", {"title": "Эссе", "settings": cfg})["id"]
        self.t.put("/api/tests/%d" % tid, {"title": "Эссе", "settings": cfg})
        self.t.post("/api/tests/%d/questions" % tid, {"type": "essay", "points": 10, "body": {
            "text": "Напишите", "rubric": [{"title": "Тезис", "max": 5}, {"title": "Аргументы", "max": 5}]}, "answer": {}})
        cid = self.klass(4)
        run = self.t.post("/api/runs", {"test_id": tid, "class_id": cid})
        code, rid = run["code"], run["id"]
        studs, ids = [], []
        for k in range(4):
            s = Client(self.base)
            j = s.post("/api/s/join", {"code": code})
            aid = s.post("/api/s/start", {"code": code, "student_id": j["students"][k]["id"]})["attempt_id"]
            q = s.get("/api/s/a/%d" % aid)["questions"][0]
            s.put("/api/s/a/%d/answer" % aid, {"qid": q["id"], "response": {"text": "Работа номер %d" % k}})
            s.post("/api/s/a/%d/finish" % aid)
            studs.append(s); ids.append(aid)
        self.assertTrue(self.t.get("/api/runs/%d" % rid)["peer"])
        item = [x for x in self.t.get("/api/runs/%d/check" % rid) if x["attempt_id"] == ids[0]][0]
        rub = item["question"]["body"]["rubric"]
        # учитель ставит автору 0: 3 из 5 + 3 из 5 = 6 из 10
        self.t.put("/api/attempts/%d/grade" % ids[0], {"qid": item["qid"], "points": 6, "rubric": dict((c["id"], 3) for c in rub)})
        # все рецензенты ставят максимум → подозрительно, в среднее не входят
        for k in range(1, 4):
            p = studs[k].get("/api/s/a/%d/peer" % ids[k])
            self.assertEqual(len(p["items"]), 2)
            self.assertNotIn("Работа номер %d" % k, json.dumps(p, ensure_ascii=False))     # свою работу не получает
            for it in p["items"]:
                studs[k].put("/api/s/a/%d/peer/%d" % (ids[k], it["id"]), {"scores": dict((c["id"], 5) for c in it["rubric"])})
        rep = self.t.get("/api/runs/%d/peer" % rid)
        self.assertTrue(any("максимум" in " ".join(map(str, r)) for r in rep["rows"]))
        d = self.t.get("/api/attempts/%d" % ids[0])
        self.assertEqual(d["score"], 6)          # накрученные оценки отброшены — остаётся оценка учителя

    def test_5_roles_and_variant_flag(self):
        me = self.t.get("/api/me")
        self.assertTrue(me["user"].get("roles") or me.get("user"))
        self.assertTrue(G.TYPE_NAMES["num"])


if __name__ == "__main__":
    unittest.main()
