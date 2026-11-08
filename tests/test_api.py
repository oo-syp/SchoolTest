# -*- coding: utf-8 -*-
"""Сквозная проверка API SchoolTest через настоящий HTTP-сервер."""
import base64
import http.cookiejar
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from schooltest import main as M  # noqa: E402
from schooltest.server import ServerThread  # noqa: E402
from schooltest import api_io, grading as G  # noqa: E402


class Client(object):
    def __init__(self, base):
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar),
                                              urllib.request.ProxyHandler({}))

    def call(self, method, path, data=None, raw=False, expect=200):
        body = json.dumps(data).encode("utf-8") if data is not None else None
        rq = urllib.request.Request(self.base + path, data=body, method=method)
        rq.add_header("X-SchoolTest", "1")
        rq.add_header("Content-Type", "application/json")
        try:
            r = self.op.open(rq, timeout=20)
            status, payload = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, payload = e.code, e.read()
        if status != expect:
            raise AssertionError("%s %s -> %s %s" % (method, path, status, payload[:300].decode("utf-8", "replace")))
        if raw:
            return payload
        return json.loads(payload.decode("utf-8")) if payload else None

    get = lambda self, p, **k: self.call("GET", p, **k)          # noqa: E731
    post = lambda self, p, d=None, **k: self.call("POST", p, d or {}, **k)   # noqa: E731
    put = lambda self, p, d=None, **k: self.call("PUT", p, d or {}, **k)     # noqa: E731


def b64(s):
    return base64.b64encode(s if isinstance(s, bytes) else s.encode("utf-8")).decode("ascii")


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.app = M.init_app(cls.tmp)
        cls.srv = ServerThread(cls.app, "127.0.0.1", 0)
        cls.srv.start()
        cls.base = "http://127.0.0.1:%d" % cls.srv.httpd.server_address[1]
        t = Client(cls.base)
        t.post("/api/login", {"login": "admin", "password": "admin"})
        t.post("/api/me/password", {"old": "admin", "new": "Secret123"})
        t.put("/api/settings", {"org_type": "school", "school_name": "ГУО «СШ № 1»"})
        cls.t = t

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()
        cls.app.db.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ---------------------------------------------------------------- помощники
    def make_class(self, name="7А", n=3):
        cid = self.t.post("/api/classes", {"name": name})["id"]
        text = "\n".join("Ученик%d Иван Петрович" % i for i in range(1, n + 1))
        self.t.post("/api/classes/%d/paste" % cid, {"text": text})
        return cid

    def make_test(self):
        tid = self.t.post("/api/tests", {"title": "Проверочная", "subject": "Математика"})["id"]
        q = lambda d: self.t.post("/api/tests/%d/questions" % tid, d)   # noqa: E731
        q({"type": "single", "points": 1, "body": {"text": "2+2?", "options": [{"id": "a", "text": "4"}, {"id": "b", "text": "5"}]},
           "answer": {"correct": ["a"]}})
        q({"type": "multi", "points": 2, "body": {"text": "Чётные", "options": [{"id": 1, "text": "2"}, {"id": 2, "text": "3"},
                                                                                {"id": 3, "text": "4"}]},
           "answer": {"correct": [1, 3]}})
        q({"type": "short", "points": 2, "body": {"text": "Прямоугольник 3×4", "fields": [{"id": "s", "label": "площадь"},
                                                                                        {"id": "p", "label": "периметр"}]},
           "answer": {"fields": {"s": ["12"], "p": ["14"]}}})
        q({"type": "match", "points": 2, "body": {"text": "Столицы", "left": [{"id": "l1", "text": "Беларусь"}, {"id": "l2", "text": "Литва"}],
                                                  "right": [{"id": "r1", "text": "Минск"}, {"id": "r2", "text": "Вильнюс"}]},
           "answer": {"pairs": {"l1": "r1", "l2": "r2"}}})
        q({"type": "chrono", "points": 2, "body": {"text": "Линия времени", "events": [
            {"id": "e1", "text": "Полоцк", "date": "862"}, {"id": "e2", "text": "Кревская уния", "date": "1385"},
            {"id": "e3", "text": "Люблинская уния", "date": "1569"}]}, "answer": {}})
        q({"type": "cloze", "points": 1, "body": {"text": "Столица — {{x}}.", "blanks": [{"id": "x", "kind": "input"}]},
           "answer": {"blanks": {"x": ["Минск"]}}})
        q({"type": "likert", "body": {"text": "Мнение", "statements": [{"id": 1, "text": "Интересно"}]}, "answer": {}})
        q({"type": "essay", "points": 3, "body": {"text": "Эссе \\(x^2\\)"}, "answer": {"sample": "..."}})
        return tid

    # ---------------------------------------------------------------- сценарии
    def test_full_cycle(self):
        cid = self.make_class("7Б", 3)
        tid = self.make_test()
        info = self.t.get("/api/tests/%d" % tid)
        self.assertEqual(info["questions"], 8)
        run = self.t.post("/api/runs", {"test_id": tid, "class_id": cid})
        code = run["code"]
        self.assertEqual(len(code), 6)

        s = Client(self.base)
        j = s.post("/api/s/join", {"code": code})
        self.assertEqual(len(j["students"]), 3)
        sid = j["students"][0]["id"]
        st = s.post("/api/s/start", {"code": code, "student_id": sid})
        aid = st["attempt_id"]
        state = s.get("/api/s/a/%d" % aid)
        self.assertEqual(state["total"], 8)
        dump = json.dumps(state, ensure_ascii=False)
        self.assertNotIn("correct", dump)      # правильные ответы не передаются
        self.assertNotIn("1385", dump)         # даты хронологии тоже
        self.assertNotIn("Минск\"]", dump)
        qs = dict((q["type"], q) for q in state["questions"])
        resp = {
            "single": {"choice": [o["id"] for o in qs["single"]["options"] if o["text"] == "4"][0]},
            "multi": {"choices": [o["id"] for o in qs["multi"]["options"] if o["text"] in ("2", "4")]},
            "short": {"fields": dict((f["id"], "12" if f["label"] == "площадь" else "15") for f in qs["short"]["fields"])},
            "match": {"pairs": dict((l["id"], [r["id"] for r in qs["match"]["right"]
                                               if (r["text"], l["text"]) in (("Минск", "Беларусь"), ("Вильнюс", "Литва"))][0])
                                    for l in qs["match"]["left"])},
            "chrono": {"order": [i["id"] for i in sorted(qs["chrono"]["items"],
                                                         key=lambda x: ["Полоцк", "Кревская уния", "Люблинская уния"].index(x["text"]))]},
            "cloze": {"blanks": {qs["cloze"]["blanks"][0]["id"]: " минск "}},
            "likert": {"values": {qs["likert"]["statements"][0]["id"]: 4}},
            "essay": {"text": "Мой ответ"},
        }
        for t, r in resp.items():
            s.put("/api/s/a/%d/answer" % aid, {"qid": qs[t]["id"], "response": r})
        s.post("/api/s/a/%d/focus" % aid, {"e": "blur"})
        mon = self.t.get("/api/runs/%d" % run["id"])
        row = [x for x in mon["students"] if x["student_id"] == sid][0]
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["focus_lost"], 1)
        # другое устройство — нужно разрешение учителя
        s2 = Client(self.base)
        w = s2.post("/api/s/start", {"code": code, "student_id": sid})
        self.assertTrue(w.get("waiting"))
        s2.get("/api/s/a/%d" % aid)
        s2.put("/api/s/a/%d/answer" % aid, {"qid": qs["single"]["id"], "response": {}}, expect=403)
        self.t.post("/api/runs/%d/allow" % run["id"], {"student_id": sid})
        s.get("/api/s/a/%d" % aid, expect=403)       # старое устройство отключено
        s = s2
        fin = s.post("/api/s/a/%d/finish" % aid)
        self.assertEqual(fin["status"], "finished")
        self.assertTrue(fin["result"]["pending"])    # эссе ждёт проверки
        # баллы: 1 + 2 + 1 (одно поле из двух) + 2 + 2 + 1 = 9 из 13 (эссе 3 — на проверке)
        det = self.t.get("/api/attempts/%d" % aid)
        self.assertEqual(det["score"], 9)
        self.assertEqual(det["max_score"], 13)
        essay = [i for i in det["items"] if i["question"]["type"] == "essay"][0]
        chk = self.t.get("/api/runs/%d/check" % run["id"])
        self.assertEqual(len(chk), 1)
        g = self.t.put("/api/attempts/%d/grade" % aid, {"qid": essay["question"]["id"], "points": 3, "comment": "Хорошо"})
        self.assertEqual(g["score"], 12)
        self.assertFalse(g["pending"])
        self.assertEqual(g["mark"], "9")             # 92 % → 9
        # повторно без разрешения нельзя
        s.post("/api/s/start", {"code": code, "student_id": sid}, expect=409)
        self.t.post("/api/runs/%d/retake" % run["id"], {"student_id": sid})
        st2 = s.post("/api/s/start", {"code": code, "student_id": sid})
        self.assertNotEqual(st2["attempt_id"], aid)
        mon = self.t.get("/api/runs/%d" % run["id"])
        self.assertEqual([x for x in mon["students"] if x["student_id"] == sid][0]["num"], 2)
        # отчёты
        res = self.t.get("/api/runs/%d/results" % run["id"])
        self.assertEqual(res["headers"][1], "Ученик")
        x = self.t.get("/api/runs/%d/results?format=xlsx" % run["id"], raw=True)
        self.assertEqual(x[:2], b"PK")
        an = self.t.get("/api/runs/%d/analysis" % run["id"])
        self.assertEqual(len(an["rows"]), 8)
        hist = self.t.get("/api/students/%d/history" % sid)
        self.assertEqual(len(hist["rows"]), 1)
        self.t.post("/api/runs/%d/close" % run["id"])
        s.post("/api/s/join", {"code": code}, expect=404)
        sg = self.t.get("/api/runs/%d/sg_file" % run["id"], raw=True)
        self.assertEqual(json.loads(sg.decode("utf-8"))["marks"][0]["mark"], 1)   # засчитывается последняя попытка (пустая повторная)

    def test_strict_nav_and_timer(self):
        cid = self.make_class("8А", 1)
        tid = self.make_test()
        self.t.put("/api/tests/%d" % tid, {"settings": {"free_nav": False, "time_limit": 1}})
        run = self.t.post("/api/runs", {"test_id": tid, "class_id": cid})
        s = Client(self.base)
        sid = s.post("/api/s/join", {"code": run["code"]})["students"][0]["id"]
        aid = s.post("/api/s/start", {"code": run["code"], "student_id": sid})["attempt_id"]
        st = s.get("/api/s/a/%d" % aid)
        self.assertEqual(len(st["questions"]), 1)      # только текущий вопрос
        self.assertLessEqual(st["time_left"], 60)
        s.post("/api/s/a/%d/nav" % aid, {"cur": 1}, expect=409)   # без ответа дальше нельзя
        # время вышло
        self.app.db.ex("UPDATE attempts SET deadline=deadline-200 WHERE id=?", (aid,))
        st = s.get("/api/s/a/%d" % aid)
        self.assertEqual(st["status"], "finished")

    def test_paper(self):
        cid = self.make_class("9А", 2)
        tid = self.make_test()
        self.t.put("/api/tests/%d" % tid, {"settings": {"variants": 2}})
        run = self.t.post("/api/runs", {"test_id": tid, "class_id": cid, "mode": "paper"})
        self.assertIsNone(run["code"])
        p = self.t.get("/api/runs/%d/paper?copies=2" % run["id"])
        self.assertEqual(len(p["copies"]), 2)
        studs = self.t.get("/api/classes/%d/students" % cid)
        self.t.put("/api/runs/%d/paper_marks" % run["id"], {"marks": {str(studs[0]["id"]): "7"}})
        res = self.t.get("/api/runs/%d/results" % run["id"])
        self.assertIn("7", [r[4] for r in res["rows"]])

    def test_norms_test_lang(self):
        tid = self.t.post("/api/tests", {"title": "Тест по языку"})["id"]
        for i in range(10):
            self.t.post("/api/tests/%d/questions" % tid, {"type": "single", "body": {"text": "В%d" % i, "options": [
                {"id": "a", "text": "да"}, {"id": "b", "text": "нет"}]}, "answer": {"correct": ["a"]}})
        self.t.put("/api/tests/%d" % tid, {"settings": {"scale": {"mode": "norms", "norm": "test_lang"}}})
        cid = self.make_class("10А", 1)
        run = self.t.post("/api/runs", {"test_id": tid, "class_id": cid})
        s = Client(self.base)
        sid = s.post("/api/s/join", {"code": run["code"]})["students"][0]["id"]
        aid = s.post("/api/s/start", {"code": run["code"], "student_id": sid})["attempt_id"]
        st = s.get("/api/s/a/%d" % aid)
        for k, q in enumerate(st["questions"]):
            ok = [o["id"] for o in q["options"] if o["text"] == ("да" if k < 8 else "нет")][0]
            s.put("/api/s/a/%d/answer" % aid, {"qid": q["id"], "response": {"choice": ok}})
        r = s.post("/api/s/a/%d/finish" % aid)["result"]
        self.assertEqual(r["score"], 16)
        self.assertEqual(r["max_score"], 20)
        self.assertEqual(r["mark"], "8")    # 80 % по таблице тестовой работы: 78–88 → 8

    def test_text_import(self):
        text = ("Какой месяц идет после марта?\n- январь\n+ апрель\n- июнь\n"
                "Укажите порядок следования всех вариантов ответа:\n1. январь\n3. март\n2. февраль\n"
                "Длина сторон прямоугольника равна 3 и 4 см.\nНайдите площадь и периметр прямоугольника.\n"
                "= {площадь:} 12\n= {периметр:} 14\n"
                "На портрете изображен Александр Сергеевич...\n[Pushkin.jpg]\n= Пушкин\n"
                "?\nВыберите чётные числа\n+ 2\n- 3\n+ 4\n"
                "+ потерянный ответ\n")
        qs, errors = api_io.parse_text(text)
        self.assertEqual([q["type"] for q in qs], ["single", "order", "short", "short", "multi"])
        self.assertEqual(qs[1]["items"], ["январь", "февраль", "март"])
        self.assertEqual(qs[3]["images"], ["Pushkin.jpg"])
        self.assertEqual(len(qs[2]["fields"]), 2)
        prev = self.t.post("/api/import/text", {"text": text, "files": [{"name": "Pushkin.jpg", "data": b64(b"\xff\xd8jpg")}]})
        self.assertEqual(len(prev["questions"]), 5)
        self.assertEqual(prev["questions"][3]["missing"], [])
        r = self.t.post("/api/import/text", {"text": text, "commit": True, "title": "Из текста",
                                             "files": [{"name": "Pushkin.jpg", "data": b64(b"\xff\xd8jpg")}]})
        self.assertEqual(r["added"], 5)
        t = self.t.get("/api/tests/%d" % r["test_id"])
        self.assertEqual(t["questions"], 5)
        txt = self.t.get("/api/tests/%d/export?format=txt" % r["test_id"], raw=True).decode("utf-8-sig")
        qs2, _e = api_io.parse_text(txt)
        self.assertEqual([q["type"] for q in qs2], ["single", "order", "short", "short", "multi"])

    def test_excel_and_file_roundtrip(self):
        tpl = self.t.get("/api/import/excel_template", raw=True)
        r = self.t.post("/api/import/excel", {"files": [{"name": "tpl.xlsx", "data": b64(tpl)}]})
        self.assertEqual(len(r["questions"]), 10, r["errors"])
        self.assertEqual(r["errors"], [])
        r = self.t.post("/api/import/excel", {"files": [{"name": "tpl.xlsx", "data": b64(tpl)}], "commit": True})
        self.assertEqual(r["added"], 10, r["errors"])
        t = self.t.get("/api/tests/%d" % r["test_id"])
        self.assertEqual(len(t["tasks"]), 5)
        # картинка + экспорт/импорт файла теста
        m = self.t.post("/api/tests/%d/media" % r["test_id"], {"name": "a.png", "data": b64(PNG)})
        q = [x for x in t["questions_list"] if x["type"] == "single"][0] if "questions_list" in t else None
        data = self.t.get("/api/tests/%d/export" % r["test_id"], raw=True)
        r2 = self.t.post("/api/import/test", {"files": [{"name": "x.stest", "data": b64(data)}]})
        self.assertEqual(r2["errors"], [])
        t2 = self.t.get("/api/tests/%d" % r2["test_id"])
        self.assertEqual(t2["questions"], 10)
        self.assertTrue(m["id"])
        _ = q

    def test_grading_units(self):
        self.assertEqual(G.round_half_up(2.5), 3)
        ev = G.evaluate([{"task_num": 1, "maxp": 1, "got": 0.95, "scored": True}], {"mode": "percent"})
        self.assertEqual(ev["mark"], "10")
        ev = G.evaluate([{"task_num": 1, "maxp": 100, "got": 14, "scored": True}], {"mode": "percent"})
        self.assertEqual(ev["mark"], "1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
