# -*- coding: utf-8 -*-
"""Тесты версии 1.2: новые психодиагностические методики, социометрия, ШТУР-2."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from schooltest import main as M, psy as P, psy_socio as SO, shtur_data as SD  # noqa: E402
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

    def make_class(self, name, n=2):
        cid = self.t.post("/api/classes", {"name": name})["id"]
        self.t.post("/api/classes/%d/paste" % cid,
                    {"text": "\n".join("Фамилия%d Имя%d Отчество" % (i, i) for i in range(1, n + 1))})
        return cid

    def student(self, code, idx=0, extra=None):
        s = Client(self.base)
        j = s.post("/api/s/join", {"code": code})
        st = s.post("/api/s/start", {"code": code, "student_id": j["students"][idx]["id"], "extra": extra})
        return s, st["attempt_id"], j

    # ------------------------------------------------------------ каталог
    def test_1_catalog(self):
        ms = self.p.get("/api/psy/methods")
        ids = [m["id"] for m in ms]
        for mid in ("bd", "bai", "mot", "tsr", "socio", "shtur"):
            self.assertIn(mid, ids)
        by = dict((m["id"], m) for m in ms)
        self.assertEqual(by["bd"]["count"], 75)
        self.assertEqual(by["bai"]["count"], 21)
        self.assertEqual(by["mot"]["count"], 40)
        self.assertEqual(by["tsr"]["count"], 24)
        self.assertEqual(by["shtur"]["count"], 129)
        self.assertEqual(by["socio"]["kind"], "group")
        for mid in ids:
            m = self.p.get("/api/psy/methods/" + mid)
            self.assertTrue(m["key"], mid)
            self.assertTrue(m["questions"], mid)

    # ------------------------------------------------------------ опросники
    def _run_simple(self, mid, resp_of, extra=None, start=None):
        cid = self.make_class("8А", 2)
        body = {"method": mid, "class_id": cid, "show_result": "none"}
        body.update(start or {})
        run = self.p.post("/api/psy/runs", body)
        s, aid, j = self.student(run["code"], 0, extra)
        st = s.get("/api/s/a/%d" % aid)
        for q in st["questions"]:
            s.put("/api/s/a/%d/answer" % aid, {"qid": q["id"], "response": resp_of(q)})
        s.post("/api/s/a/%d/finish" % aid)
        rep = self.p.get("/api/psy/runs/%d/results" % run["id"])
        att = self.p.get("/api/psy/attempts/%d" % aid)
        return run, rep, att

    def test_2_buss_durkee(self):
        run, rep, att = self._run_simple("bd", lambda q: {"choice": "y"})
        res = att["result"]
        self.assertEqual(len(res["scales"]), 8)
        self.assertEqual(len(res["indices"]), 2)
        fiz = [s for s in res["scales"] if s["id"] == "fiz"][0]
        self.assertEqual(fiz["value"], 7)          # 7 прямых утверждений при ответе «да»
        self.assertEqual(fiz["std"], 70)
        self.assertEqual(rep["headers"][4:12], ["ФА", "КА", "Р", "Н", "О", "П", "ВА", "ЧВ"])
        self.assertTrue(rep["summary"])

    def test_3_beck(self):
        run, rep, att = self._run_simple("bai", lambda q: {"choice": "3"})
        res = att["result"]
        self.assertEqual(res["scales"][0]["value"], 63)
        self.assertIn("очень высокая", res["summary"].lower())
        self.assertTrue(res["warnings"])
        run2, rep2, att2 = self._run_simple("bai", lambda q: {"choice": "0"})
        self.assertEqual(att2["result"]["scales"][0]["value"], 0)

    def test_4_motivation(self):
        run, rep, att = self._run_simple("mot", lambda q: {"choice": "4"}, {"gender": "f", "age": "15"})
        res = att["result"]
        vals = dict((s["id"], s["value"]) for s in res["scales"])
        # «обратные» пункты: ПА 14,30,38; Т 1,9,25,33; МД 4,20,32
        self.assertEqual(vals["П"], 10 * 4 - 3 * 3)
        self.assertEqual(vals["Т"], 10 * 4 - 4 * 3)
        self.assertEqual(vals["Г"], 40)
        self.assertEqual(res["total"], vals["П"] + vals["М"] - vals["Т"] - vals["Г"])
        self.assertIn("уровень", res["summary"])

    def test_5_teacher_student(self):
        cid = self.make_class("9Б", 2)
        self.p.post("/api/psy/runs", {"method": "tsr", "class_id": cid}, expect=400)   # без учителя нельзя
        run, rep, att = self._run_simple("tsr", lambda q: {"choice": "y"}, start={"about": "Иванова И. И., математика"})
        res = att["result"]
        self.assertEqual([s["value"] for s in res["scales"]], [6, 4, 4])
        self.assertIn("Иванова", res["summary"])
        self.assertEqual(rep["about"], "Иванова И. И., математика")

    # ------------------------------------------------------------ социометрия
    def test_6_socio(self):
        cid = self.make_class("6А", 4)
        run = self.p.post("/api/psy/runs", {"method": "socio", "class_id": cid, "picks": 2,
                                            "criteria": [{"text": "Кого позовёшь на день рождения?", "sign": "pos"},
                                                         {"text": "С кем не хотел бы сидеть?", "sign": "neg"}]})
        ids = None
        for i in range(4):
            s, aid, j = self.student(run["code"], i)
            ids = [x["id"] for x in j["students"]]
            st = s.get("/api/s/a/%d" % aid)
            self.assertEqual(len(st["questions"]), 2)
            self.assertTrue(st["questions"][0]["multi"])
            self.assertEqual(st["questions"][0]["max"], 2)
            self.assertEqual(st["psy"]["self"], ids[i])
            pos = [str(ids[(i + 1) % 4])]           # каждый выбирает следующего
            neg = [str(ids[(i + 2) % 4])]
            s.put("/api/s/a/%d/answer" % aid, {"qid": st["questions"][0]["id"], "response": {"choices": pos}})
            s.put("/api/s/a/%d/answer" % aid, {"qid": st["questions"][1]["id"], "response": {"choices": neg}})
            s.post("/api/s/a/%d/finish" % aid)
        rep = self.p.get("/api/psy/runs/%d/results" % run["id"])
        so = rep["socio"]
        self.assertEqual(len(so["people"]), 4)
        self.assertEqual(so["indices"]["N"], 4)
        self.assertEqual(so["indices"]["done"], 4)
        self.assertEqual(so["indices"]["pos"], 4)
        self.assertEqual(so["indices"]["neg"], 4)
        for p in so["people"]:
            self.assertEqual(p["got_pos"], 1)
            self.assertEqual(p["made_pos"], 1)
        # при цикле «каждый выбирает следующего» взаимных выборов нет
        self.assertEqual(so["indices"]["pairs_pos"], 0)
        x = self.p.call("GET", "/api/psy/runs/%d/results?format=xlsx" % run["id"], raw=True)
        self.assertEqual(x[:2], b"PK")

    def test_7_socio_mutual(self):
        cid = self.make_class("6Б", 4)
        run = self.p.post("/api/psy/runs", {"method": "socio", "class_id": cid, "picks": 3})
        pairs = {0: 1, 1: 0, 2: 3, 3: 2}            # две взаимные пары
        for i in range(4):
            s, aid, j = self.student(run["code"], i)
            ids = [x["id"] for x in j["students"]]
            st = s.get("/api/s/a/%d" % aid)
            for q in st["questions"]:
                s.put("/api/s/a/%d/answer" % aid, {"qid": q["id"], "response": {"choices": [str(ids[pairs[i]])]}})
            s.post("/api/s/a/%d/finish" % aid)
        so = self.p.get("/api/psy/runs/%d/results" % run["id"])["socio"]
        self.assertEqual(so["indices"]["pairs_pos"], 2)
        self.assertEqual(len(so["groups"]), 2)
        for p in so["people"]:
            self.assertEqual(p["mutual_pos"], 1)
            self.assertEqual(p["status_name"], "«Звёзды»")
        self.assertAlmostEqual(so["indices"]["mutuality"], round(4 / 12.0, 3))

    # ------------------------------------------------------------ ШТУР-2
    def test_8_shtur_full(self):
        cid = self.make_class("9А", 2)
        run = self.p.post("/api/psy/runs", {"method": "shtur", "class_id": cid, "form": "Б", "timed": False})
        s, aid, j = self.student(run["code"], 0)
        st = s.get("/api/s/a/%d" % aid)
        self.assertEqual(st["psy"]["sec"], 0)
        self.assertEqual(len(st["questions"]), 0)        # до начала субтеста заданий нет
        self.assertEqual(len(st["psy"]["sections"]), 8)
        for sec in range(1, 9):
            st = s.post("/api/s/a/%d/section" % aid, {"sec": sec})
            a, b = st["psy"]["sections"][sec - 1]["from"], st["psy"]["sections"][sec - 1]["to"]
            self.assertEqual(len(st["questions"]), b - a + 1)
            for q in st["questions"]:
                n = int(q["id"])
                if sec == 5:
                    r = {"text": SD.GENERALIZE["Б"][n]["2"][0]}
                elif sec == 6:
                    r = {"text": str(SD.KEY["Б"][n])}
                else:
                    r = {"choice": SD.KEY["Б"][n]}
                s.put("/api/s/a/%d/answer" % aid, {"qid": q["id"], "response": r})
        st = s.post("/api/s/a/%d/section" % aid, {"sec": 9})
        self.assertEqual(st["status"], "finished")
        att = self.p.get("/api/psy/attempts/%d" % aid)
        res = att["result"]
        self.assertEqual(res["raw"], 148)
        self.assertEqual(res["percent"], 100.0)
        self.assertEqual(res["form"], "Б")
        self.assertEqual(res["grade"], 9)
        self.assertEqual(res["level"], "относительно высокое")
        rep = self.p.get("/api/psy/runs/%d/results" % run["id"])
        self.assertEqual(rep["form"], "Б")
        self.assertTrue(rep["summary"])

    def test_9_shtur_sections_closed(self):
        cid = self.make_class("8Б", 2)
        run = self.p.post("/api/psy/runs", {"method": "shtur", "class_id": cid, "form": "А", "timed": False})
        s, aid, j = self.student(run["code"], 0)
        st = s.post("/api/s/a/%d/section" % aid, {"sec": 1})
        first = st["questions"][0]["id"]
        s.put("/api/s/a/%d/answer" % aid, {"qid": first, "response": {"choice": "а"}})
        s.post("/api/s/a/%d/section" % aid, {"sec": 2})
        # вернуться в закрытый субтест нельзя
        s.put("/api/s/a/%d/answer" % aid, {"qid": first, "response": {"choice": "б"}}, expect=409)
        st = s.get("/api/s/a/%d" % aid)
        self.assertEqual(st["psy"]["sec"], 2)
        self.assertEqual(st["questions"][0]["id"], "21")

    def test_10_shtur_manual(self):
        cid = self.make_class("7А", 2)
        run = self.p.post("/api/psy/runs", {"method": "shtur", "class_id": cid, "form": "А", "timed": False})
        s, aid, j = self.student(run["code"], 0)
        for sec in range(1, 6):
            st = s.post("/api/s/a/%d/section" % aid, {"sec": sec})
            if sec == 5:
                for q in st["questions"]:
                    s.put("/api/s/a/%d/answer" % aid, {"qid": q["id"], "response": {"text": "непонятный ответ"}})
        s.post("/api/s/a/%d/finish" % aid)
        res = self.p.get("/api/psy/attempts/%d" % aid)["result"]
        self.assertEqual(res["per_sub"]["5"] if "5" in res["per_sub"] else res["per_sub"][5], 0)
        self.assertEqual(len(res["pending5"]), 19)
        self.p.put("/api/psy/attempts/%d/gen" % aid, {"scores": {"86": 2, "87": 1}})
        res = self.p.get("/api/psy/attempts/%d" % aid)["result"]
        got = res["per_sub"].get("5", res["per_sub"].get(5))
        self.assertEqual(got, 3)
        d = dict((x["num"], x) for x in res["details5"])
        self.assertEqual(d[86]["manual"], 2)
        self.assertEqual(d[86]["value"], 2)

    # ------------------------------------------------------------ данные ШТУР
    def test_11_shtur_data(self):
        for form in SD.FORMS:
            self.assertEqual(len(SD.TASKS[form]), 129)
            for n in range(1, 130):
                task = SD.TASKS[form][n]
                if 86 <= n <= 104 or 105 <= n <= 119:
                    self.assertFalse(task.get("options"), (form, n))
                else:
                    self.assertTrue(task.get("options"), (form, n))
                if 120 <= n <= 129:
                    self.assertTrue(task.get("image"), (form, n))
            for n in list(range(1, 86)) + list(range(105, 130)):
                self.assertIn(n, SD.KEY[form], (form, n))
            # ключ указывает на существующий вариант
            for n in list(range(1, 86)) + list(range(120, 130)):
                letters = ["а", "б", "в", "г", "д"][:len(SD.TASKS[form][n]["options"])]
                self.assertIn(SD.KEY[form][n], letters, (form, n))

    def test_12_shtur_images_exist(self):
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schooltest", "static")
        for form in SD.FORMS:
            for n in range(120, 130):
                p = os.path.join(base, "psy", "shtur", SD.TASKS[form][n]["image"] + ".png")
                self.assertTrue(os.path.isfile(p), p)
        for nm in ("ex7_1", "ex7_2", "ex8_1", "ex8_2"):
            self.assertTrue(os.path.isfile(os.path.join(base, "psy", "shtur", nm + ".png")), nm)

    def test_13_socio_indices(self):
        """Пример из руководства: Проскурина ИВ = +0,75, Войтов +0,5, Сидоров −0,37."""
        names = ["Иванов", "Петров", "Сидоров", "Юрьева", "Проскурина", "Дедков", "Войтов", "Кальянова", "Гурьев"]
        m = ["x0-++-+0-", "0x00+0++-", "+0x0+-+0-", "0+-x00+-+", "0+00x0++0",
             "---0+x0+0", "++00+0x0-", "++00+00x0", "+-0+00-0x"]
        settings = {"criteria": [{"text": "+", "sign": "pos"}, {"text": "-", "sign": "neg"}],
                    "roster": [{"id": i + 1, "name": n} for i, n in enumerate(names)], "picks": 8}
        people = []
        for i, n in enumerate(names):
            pos = [str(j + 1) for j in range(9) if m[i][j] == "+"]
            neg = [str(j + 1) for j in range(9) if m[i][j] == "-"]
            people.append({"id": i + 1, "name": n, "res": {"picks": {"1": pos, "2": neg}}})
        rep = SO.report(settings, people)
        by = dict((p["name"], p) for p in rep["people"])
        self.assertEqual(by["Проскурина"]["iv"], 0.75)
        self.assertEqual(by["Войтов"]["iv"], 0.5)
        self.assertEqual(by["Сидоров"]["iv"], -0.38)
        self.assertEqual(by["Кальянова"]["ip"], 0.38)
        self.assertEqual(by["Дедков"]["ip"], -0.12)
        self.assertEqual(by["Сидоров"]["status"], "rej")
        self.assertEqual(rep["indices"]["pos"], 25)
        self.assertEqual(rep["indices"]["neg"], 14)
        self.assertEqual(rep["indices"]["zero"], 33)
        self.assertEqual(rep["indices"]["total_choices"], 72)
        self.assertEqual(rep["indices"]["pos"] + rep["indices"]["neg"] + rep["indices"]["zero"], 72)


if __name__ == "__main__":
    unittest.main()
