# -*- coding: utf-8 -*-
"""Тесты версии 1.3: новые методики, папки, избранное, банк вопросов, анкеты, проверка на списывание."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from schooltest import main as M  # noqa: E402
from schooltest.server import ServerThread  # noqa: E402
from test_api import Client  # noqa: E402


class V13Test(unittest.TestCase):
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
        t.put("/api/settings", {"org_type": "school"})
        t.post("/api/users", {"login": "psy", "password": "Psy12345", "full_name": "Психолог", "role": "psychologist"})
        p = Client(cls.base)
        p.post("/api/login", {"login": "psy", "password": "Psy12345"})
        p.post("/api/me/password", {"old": "Psy12345", "new": "Psy123456"})
        cls.t, cls.p = t, p

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()
        cls.app.db.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def make_class(self, name, n=3):
        cid = self.t.post("/api/classes", {"name": name})["id"]
        self.t.post("/api/classes/%d/paste" % cid,
                    {"text": "\n".join("Фамилия%d Имя%d Отчество" % (i, i) for i in range(1, n + 1))})
        return cid

    def student(self, code, idx=0):
        s = Client(self.base)
        j = s.post("/api/s/join", {"code": code})
        st = s.post("/api/s/start", {"code": code, "student_id": j["students"][idx]["id"]})
        return s, st["attempt_id"]

    # ------------------------------------------------------------ новые методики
    def test_1_new_methods_catalog(self):
        ms = self.p.get("/api/psy/methods")
        ids = [m["id"] for m in ms]
        for mid, count in (("phillips", 58), ("lusk", 10), ("stai", 40)):
            self.assertIn(mid, ids)
            self.assertEqual(dict((m["id"], m) for m in ms)[mid]["count"], count)

    def test_2_phillips_zero_anxiety(self):
        cid = self.make_class("5А", 1)
        r = self.p.post("/api/psy/runs", {"method": "phillips", "class_id": cid})
        s, aid = self.student(r["code"])
        state = s.get("/api/s/a/%d" % aid)
        plus = {11, 20, 22, 24, 25, 30, 35, 36, 38, 39, 41, 43, 44}
        for i, q in enumerate(state["questions"], start=1):
            choice = "y" if i in plus else "n"
            s.put("/api/s/a/%d/answer" % aid, {"qid": q["id"], "response": {"choice": choice}})
        s.post("/api/s/a/%d/finish" % aid)
        res = self.p.get("/api/psy/attempts/%d" % aid)["result"]
        self.assertEqual(res["total_percent"], 0)
        self.assertEqual(res["total_level"], "норма")

    def test_3_lusk_and_stai(self):
        cid = self.make_class("3Б", 1)
        r = self.p.post("/api/psy/runs", {"method": "lusk", "class_id": cid})
        s, aid = self.student(r["code"])
        state = s.get("/api/s/a/%d" % aid)
        for q in state["questions"]:
            s.put("/api/s/a/%d/answer" % aid, {"qid": q["id"], "response": {"choice": "1"}})
        s.post("/api/s/a/%d/finish" % aid)
        res = self.p.get("/api/psy/attempts/%d" % aid)["result"]
        self.assertIn("total", res)

        cid2 = self.make_class("10А", 1)
        r2 = self.p.post("/api/psy/runs", {"method": "stai", "class_id": cid2})
        s2, aid2 = self.student(r2["code"])
        state2 = s2.get("/api/s/a/%d" % aid2)
        for q in state2["questions"]:
            s2.put("/api/s/a/%d/answer" % aid2, {"qid": q["id"], "response": {"choice": "2"}})
        s2.post("/api/s/a/%d/finish" % aid2)
        res2 = self.p.get("/api/psy/attempts/%d" % aid2)["result"]
        scales = res2["scales"]
        self.assertEqual(len(scales), 2)
        self.assertEqual(scales[0]["answered"], 20)

    # ------------------------------------------------------------ избранное
    def test_4_favorites(self):
        r = self.t.post("/api/favorites/toggle", {"kind": "psy", "ref": "phillips"})
        self.assertTrue(r["favorite"])
        items = self.t.get("/api/favorites")["items"]
        self.assertTrue(any(x["ref"] == "phillips" for x in items))
        r2 = self.t.post("/api/favorites/toggle", {"kind": "psy", "ref": "phillips"})
        self.assertFalse(r2["favorite"])

    # ------------------------------------------------------------ папки
    def test_5_folders(self):
        fid = self.t.post("/api/folders", {"name": "Математика"})["id"]
        sub = self.t.post("/api/folders", {"name": "5 класс", "parent_id": fid})["id"]
        tree = self.t.get("/api/folders", {}) if False else self.t.get("/api/folders")
        names = [n["name"] for n in tree["tree"]]
        self.assertIn("Математика", names)
        tid = self.t.post("/api/tests", {"title": "Контрольная №1"})["id"]
        self.t.post("/api/tests/%d/move" % tid, {"folder_id": sub})
        tt = self.t.get("/api/tests/%d" % tid)
        self.assertEqual(tt["folder_id"], sub)
        self.t.call("DELETE", "/api/folders/%d" % fid)

    # ------------------------------------------------------------ банк вопросов
    def test_6_bank(self):
        tid = self.t.post("/api/tests", {"title": "Тест для банка"})["id"]
        q = self.t.post("/api/tests/%d/questions" % tid,
                         {"type": "single", "body": {"text": "2+2=?", "options": [{"id": "1", "text": "3"}, {"id": "2", "text": "4"}]},
                          "answer": {"correct": "2"}, "points": 1})
        bq = self.t.post("/api/questions/%d/to_bank" % q["id"], {"subject": "Математика", "tags": "арифметика"})
        self.assertTrue(bq["id"])
        items = self.t.get("/api/bank")["items"]
        self.assertTrue(any(x["id"] == bq["id"] for x in items))
        tid2 = self.t.post("/api/tests", {"title": "Второй тест"})["id"]
        ins = self.t.post("/api/bank/%d/insert" % bq["id"], {"test_id": tid2})
        self.assertEqual(ins["body"]["text"], "2+2=?")
        self.t.call("DELETE", "/api/bank/%d" % bq["id"])

    # ------------------------------------------------------------ конструктор анкет
    def test_7_survey(self):
        sid = self.t.post("/api/surveys", {"title": "Обратная связь", "audience": "anon"})["id"]
        q1 = self.t.post("/api/surveys/%d/questions" % sid,
                          {"type": "single", "text": "Нравится ли вам урок?", "options": ["Да", "Нет"]})
        q2 = self.t.post("/api/surveys/%d/questions" % sid, {"type": "open", "text": "Что улучшить?"})
        run = self.t.post("/api/surveys/%d/runs" % sid, {})
        anon = Client(self.base)
        joined = anon.post("/api/sv/join", {"code": run["code"]})
        self.assertEqual(len(joined["items"]), 2)
        anon.post("/api/sv/%d/submit" % run["id"], {"answers": {str(q1["id"]): "1", str(q2["id"]): "Больше практики"}})
        anon2 = Client(self.base)
        anon2.post("/api/sv/join", {"code": run["code"]})
        anon2.post("/api/sv/%d/submit" % run["id"], {"answers": {str(q1["id"]): "2", str(q2["id"]): ""}})
        rep = self.t.get("/api/survey_runs/%d" % run["id"])
        self.assertEqual(rep["total"], 2)
        counts = dict((c["option"], c["n"]) for c in rep["report"][0]["counts"])
        self.assertEqual(counts["Да"], 1)
        self.assertEqual(counts["Нет"], 1)
        self.assertIn("Больше практики", rep["report"][1]["texts"])

    # ------------------------------------------------------------ проверка на списывание
    def test_8_anticheat_pair_match(self):
        cid = self.make_class("7В", 2)
        tid = self.t.post("/api/tests", {"title": "Контрольная со списыванием"})["id"]
        qs = []
        for i in range(6):
            qs.append(self.t.post("/api/tests/%d/questions" % tid,
                                   {"type": "single", "body": {"text": "Вопрос %d" % i,
                                    "options": [{"id": "1", "text": "А"}, {"id": "2", "text": "Б"}]},
                                    "answer": {"correct": "1"}, "points": 1}))
        self.t.put("/api/tests/%d" % tid, {"settings": {"anticheat": {"enabled": True, "block": True, "pair_percent": 80,
                                                                       "focus_limit": 99, "fast_seconds": 0}}})
        r = self.t.post("/api/runs", {"test_id": tid, "class_id": cid})
        s1, a1 = self.student(r["code"], 0)
        s2, a2 = self.student(r["code"], 1)
        resp = None
        for q in qs[:5]:          # с 5-го общего ответа пара уже сравнивается (нужно >=5 общих вопросов)
            s1.put("/api/s/a/%d/answer" % a1, {"qid": q["id"], "response": {"choice": "1"}})
            resp = s2.put("/api/s/a/%d/answer" % a2, {"qid": q["id"], "response": {"choice": "1"}})
        self.assertEqual(resp["cheat_status"], "blocked")
        with self.assertRaises(AssertionError):
            s2.put("/api/s/a/%d/answer" % a2, {"qid": qs[5]["id"], "response": {"choice": "1"}})
        rep = self.t.get("/api/runs/%d/anticheat" % r["id"])
        self.assertTrue(rep["pairs"])
        self.t.post("/api/attempts/%d/unblock" % a2, {})
        s2.put("/api/s/a/%d/answer" % a2, {"qid": qs[0]["id"], "response": {"choice": "2"}})

    # ------------------------------------------------------------ профориентационный профиль и сравнение
    def test_9_profile_and_compare(self):
        cid = self.make_class("9А", 1)
        sid = self.p.get("/api/classes/%d/students" % cid)[0]["id"]
        r1 = self.p.post("/api/psy/runs", {"method": "ddo", "class_id": cid})
        s, aid1 = self.student(r1["code"])
        qs = s.get("/api/s/a/%d" % aid1)["questions"]
        for q in qs:
            s.put("/api/s/a/%d/answer" % aid1, {"qid": q["id"], "response": {"choice": "a"}})
        s.post("/api/s/a/%d/finish" % aid1)

        profile = self.p.get("/api/psy/students/%d/profile" % sid)
        ddo_part = next(p for p in profile["parts"] if p["method"] == "ddo")
        self.assertTrue(ddo_part["has_data"])
        ki_part = next(p for p in profile["parts"] if p["method"] == "ki144")
        self.assertFalse(ki_part["has_data"])

        r2 = self.p.post("/api/psy/runs", {"method": "ddo", "class_id": cid})
        s2, aid2 = self.student(r2["code"])
        qs2 = s2.get("/api/s/a/%d" % aid2)["questions"]
        for q in qs2:
            s2.put("/api/s/a/%d/answer" % aid2, {"qid": q["id"], "response": {"choice": "b"}})
        s2.post("/api/s/a/%d/finish" % aid2)

        cmp = self.p.get("/api/psy/compare?a1=%d&a2=%d" % (aid1, aid2))
        self.assertEqual(cmp["method"], "ddo")
        self.assertTrue(cmp["rows"])


if __name__ == "__main__":
    unittest.main()
