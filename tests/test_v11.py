# -*- coding: utf-8 -*-
"""Тесты версии 1.1: учебные годы и перевод, задачи с кодом, психодиагностика, проверка обновлений."""
import base64
import io
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from schooltest import main as M, judge as J, psy as P, db as DB  # noqa: E402
from schooltest.server import ServerThread  # noqa: E402
from test_api import Client  # noqa: E402


class V11Test(unittest.TestCase):
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
        cls.t = t

    @classmethod
    def tearDownClass(cls):
        cls.srv.stop()
        cls.app.db.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def make_class(self, name, n=2, year=None):
        cid = self.t.post("/api/classes", {"name": name, "year_id": year})["id"]
        self.t.post("/api/classes/%d/paste" % cid, {"text": "\n".join("%s Ученик%d Иван" % (name, i) for i in range(1, n + 1))})
        return cid

    def student(self, code, idx=0, extra=None):
        s = Client(self.base)
        j = s.post("/api/s/join", {"code": code})
        st = s.post("/api/s/start", {"code": code, "student_id": j["students"][idx]["id"], "extra": extra})
        return s, st["attempt_id"], j

    # ---------------------------------------------------------------- учебные годы
    def test_1_years_promote(self):
        me = self.t.get("/api/me")
        y0 = me["current_year"]
        c5 = self.make_class("5А", 3)
        c11 = self.make_class("11Б", 2)
        tid = self.t.post("/api/tests", {"title": "Т1"})["id"]
        self.t.post("/api/tests/%d/questions" % tid, {"type": "single", "points": 1, "body": {"text": "?", "options": [
            {"id": "a", "text": "1"}, {"id": "b", "text": "2"}]}, "answer": {"correct": ["a"]}})
        run = self.t.post("/api/runs", {"test_id": tid, "class_id": c5})
        s, aid, j = self.student(run["code"])
        qid = s.get("/api/s/a/%d" % aid)["questions"][0]["id"]
        s.put("/api/s/a/%d/answer" % aid, {"qid": qid, "response": {"choice": None}})
        s.post("/api/s/a/%d/finish" % aid)
        old_sid = j["students"][0]["id"]
        P_ = self.t.get("/api/years/%d/promote" % y0)
        acts = dict((c["name"], c["action"]) for c in P_["classes"])
        self.assertEqual(acts["5А"], "promote")
        self.assertEqual(acts["11Б"], "graduate")
        self.assertEqual([c["new_name"] for c in P_["classes"] if c["name"] == "5А"], ["6А"])
        excl = [j["students"][2]["id"]]
        r = self.t.post("/api/years/%d/promote" % y0, {"to": {"name": P_["to"]["name"]}, "make_current": True, "classes": [
            {"class_id": c5, "action": "promote", "new_name": "6А", "exclude": excl}, {"class_id": c11, "action": "graduate"}]})
        self.assertEqual((r["classes"], r["students"], r["graduated"], r["excluded"]), (1, 2, 2, 1))
        me = self.t.get("/api/me")
        self.assertNotEqual(me["current_year"], y0)
        cur = self.t.get("/api/classes")
        self.assertEqual([c["name"] for c in cur], ["6А"])
        old = self.t.get("/api/classes?year_id=%d" % y0)
        self.assertEqual(sorted(c["name"] for c in old), ["11Б", "5А"])
        new_sid = self.t.get("/api/classes/%d/students" % cur[0]["id"])[0]["id"]
        self.assertNotEqual(new_sid, old_sid)
        hist = self.t.get("/api/students/%d/history" % new_sid)    # история нового года включает прошлый
        self.assertEqual(len(hist["rows"]), 1)
        self.assertIn("5А", hist["rows"][0][2])
        self.assertIn("6А", hist["subtitle"])
        # повторный перевод не дублирует учеников
        r2 = self.t.post("/api/years/%d/promote" % y0, {"to": {"id": me["current_year"]}, "make_current": False, "classes": [
            {"class_id": c5, "action": "promote", "new_name": "6А"}]})
        self.assertEqual(r2["students"], 1)            # только тот, кого раньше исключили
        self.assertEqual(len(self.t.get("/api/runs?year_id=%d" % y0)), 1)
        self.assertEqual(len(self.t.get("/api/runs?year_id=%d" % me["current_year"])), 0)
        self.t.put("/api/years/%d" % y0, {"current": True})    # вернуть год для следующих тестов

    # ---------------------------------------------------------------- задача с кодом
    def code_question(self, tid, **kw):
        body = {"text": "Сумма двух чисел", "input_format": "Два числа", "output_format": "Сумма",
                "examples": [{"in": "2 3", "out": "5"}], "time_limit": 1, "memory": 128, "languages": ["py", "cpp"],
                "feedback": "full"}
        body.update(kw.pop("body", {}))
        ans = {"subtasks": [{"name": "малые", "points": 40, "tests": [{"in": "1 1", "out": "2"}, {"in": "4 5", "out": "9"}]},
                            {"name": "большие", "points": 60, "deps": [1], "tests": [{"in": "1000000000000 1", "out": "1000000000001"}]}]}
        ans.update(kw.pop("answer", {}))
        return self.t.post("/api/tests/%d/questions" % tid, {"type": "code", "points": 10, "body": body, "answer": ans})

    def wait_subs(self, s, aid, qid, n):
        for _ in range(200):
            items = s.get("/api/s/a/%d/subs?qid=%s" % (aid, qid))["items"]
            if len(items) >= n and all(x["status"] == "done" for x in items):
                return items
            time.sleep(0.1)
        self.fail("посылки не проверены")

    def test_2_code(self):
        cid = self.make_class("8А", 2)
        tid = self.t.post("/api/tests", {"title": "Программирование"})["id"]
        self.code_question(tid)
        T = self.t.get("/api/tests/%d" % tid)
        self.assertEqual(T["question_list"][0]["answer"]["subtasks"][1]["deps"], [1])
        run = self.t.post("/api/runs", {"test_id": tid, "class_id": cid})
        s, aid, _j = self.student(run["code"])
        st = s.get("/api/s/a/%d" % aid)
        q = st["questions"][0]
        self.assertNotIn("tests", str(q["subtasks"][0]["tests"]))         # ученику — только число тестов
        self.assertEqual(q["subtasks"][0]["tests"], 2)
        self.assertNotIn("1000000000001", str(st))
        # ответ на задачу с кодом нельзя записать в обход проверки
        s.put("/api/s/a/%d/answer" % aid, {"qid": q["id"], "response": {"judged": 1, "subs": 1}}, expect=400)
        s.post("/api/s/a/%d/submit" % aid, {"qid": q["id"], "lang": "fpc", "code": "begin end."}, expect=400)  # язык не разрешён
        # 1) int переполняется на «больших» — частичное решение 40 из 100
        s.post("/api/s/a/%d/submit" % aid, {"qid": q["id"], "lang": "cpp",
                                            "code": "#include <cstdio>\nint main(){int a,b;scanf(\"%d %d\",&a,&b);printf(\"%d\",a+b);}"})
        items = self.wait_subs(s, aid, q["id"], 1)
        self.assertEqual(items[0]["verdict"], "PT")
        self.assertAlmostEqual(items[0]["frac"], 0.4)
        self.assertEqual([g["status"] for g in items[0]["details"]["groups"]], ["OK", "OK", "WA"])
        s.post("/api/s/a/%d/submit" % aid, {"qid": q["id"], "lang": "py", "code": "print(sum(map(int, input().split())))"}, expect=429)
        time.sleep(3.1)
        s.post("/api/s/a/%d/submit" % aid, {"qid": q["id"], "lang": "py", "code": "print(sum(map(int, input().split())))"})
        items = self.wait_subs(s, aid, q["id"], 2)
        self.assertEqual(items[0]["verdict"], "OK")
        s.post("/api/s/a/%d/finish" % aid)
        res = self.t.get("/api/runs/%d" % run["id"])["students"][0]
        self.assertEqual(res["score"], 10)
        self.assertEqual(res["mark"], "10")
        # учитель видит код посылок; перепроверка
        subs = self.t.get("/api/attempts/%d/subs?qid=%s" % (aid, q["id"]))
        self.assertIn("scanf", subs[1]["code"])
        self.assertEqual(self.t.post("/api/runs/%d/rejudge" % run["id"], {"qid": q["id"]})["queued"], 2)
        # ошибка компиляции и ограничение времени
        s2, aid2, _ = self.student(run["code"], 1)
        s2.post("/api/s/a/%d/submit" % aid2, {"qid": q["id"], "lang": "cpp", "code": "int main( {"})
        it = self.wait_subs(s2, aid2, q["id"], 1)[0]
        self.assertEqual(it["verdict"], "CE")
        self.assertTrue(it["details"]["compile"])
        time.sleep(3.1)
        s2.post("/api/s/a/%d/submit" % aid2, {"qid": q["id"], "lang": "py", "code": "while True: pass"})
        it = self.wait_subs(s2, aid2, q["id"], 2)[0]
        self.assertEqual(it["verdict"], "TL")
        self.assertEqual(it["details"]["fail"]["test"], 1)

    def test_3_code_manual_and_feedback(self):
        cid = self.make_class("9А", 1)
        tid = self.t.post("/api/tests", {"title": "Ручная"})["id"]
        self.code_question(tid, body={"feedback": "none"}, answer={"manual": True})
        run = self.t.post("/api/runs", {"test_id": tid, "class_id": cid})
        s, aid, _ = self.student(run["code"])
        q = s.get("/api/s/a/%d" % aid)["questions"][0]
        s.post("/api/s/a/%d/submit" % aid, {"qid": q["id"], "lang": "py", "code": "print(sum(map(int, input().split())))"})
        it = self.wait_subs(s, aid, q["id"], 1)[0]
        self.assertEqual(it["verdict"], "SENT")               # ученик не видит результат
        self.assertNotIn("frac", it)
        s.post("/api/s/a/%d/finish" % aid)
        a = self.t.get("/api/attempts/%d" % aid)
        self.assertTrue(a["pending_manual"])
        chk = self.t.get("/api/runs/%d/check" % run["id"])
        self.assertEqual(len(chk), 1)
        self.t.put("/api/attempts/%d/grade" % aid, {"qid": q["id"], "points": 8})
        self.assertEqual(self.t.get("/api/attempts/%d" % aid)["mark"], "8")     # 80 % → 8

    def test_4_tests_zip_and_answers(self):
        bio = io.BytesIO()
        z = zipfile.ZipFile(bio, "w")
        for i in (1, 2, 10):
            z.writestr("tests/1/%02d" % i, "%d %d\n" % (i, i))
            z.writestr("tests/1/%02d.a" % i, "%d\n" % (2 * i))
        z.writestr("tests/2/01", "5 5\n")
        z.writestr("tests/2/01.a", "10\n")
        z.close()
        g = self.t.post("/api/judge/tests_zip", {"data": base64.b64encode(bio.getvalue()).decode()})["groups"]
        self.assertEqual([len(x["tests"]) for x in g], [3, 1])
        self.assertEqual(g[0]["tests"][2]["out"], "20\n")      # 10 после 2 (сортировка по числу)
        r = self.t.post("/api/judge/answers", {"lang": "py", "code": "a,b=map(int,input().split())\nprint(a*b)", "inputs": ["3 4", "5 6"]})
        self.assertEqual([o["output"].strip() for o in r["outputs"]], ["12", "30"])
        c = self.t.post("/api/compilers/test", {"lang": "py"})
        self.assertEqual(c["verdict"], "OK")
        lst = self.t.get("/api/compilers")
        self.assertEqual([x["id"] for x in lst["langs"]], ["fpc", "pabc", "py", "cpp"])

    def test_5_checker_units(self):
        self.assertTrue(J.check_output("1 2\n3\n", "1 2 3"))
        self.assertFalse(J.check_output("1 2 3", "1 2  4"))
        self.assertTrue(J.check_output("0.3333333", "0.33333333", "float", 1e-6))
        self.assertFalse(J.check_output("a b", "a  b", "lines"))
        self.assertTrue(J.check_output("a b  \n\n", "a b", "lines"))

    # ---------------------------------------------------------------- психодиагностика
    def test_6_psy_keys(self):
        # ДДО: 40 пунктов ключа, каждый ровно один раз
        items = sorted(x for k in P.DDO_ORDER for x in P.DDO_KEY[k][1].split())
        self.assertEqual(items, sorted("%d%s" % (i, s) for i in range(1, 21) for s in "ab"))
        kos = sorted(q for v in P.KOS_KEY.values() for q in v[1] + v[2])
        self.assertEqual(kos, list(range(1, 41)))
        self.assertEqual(len(P.KI_Q), 144)
        self.assertEqual(len(P.EPI_Q), 57)
        self.assertEqual(len(P.DDO_PAIRS), 20)
        self.assertEqual(len(P.KOS_Q), 40)
        # Карта интересов: сфера 1 — вопросы 1, 25, 49, 73, 97, 121
        ans = dict((str(i), {"choice": "2" if i in (1, 25, 49, 73, 97, 121) else "0"}) for i in range(1, 145))
        r = P.score("ki144", ans)
        self.assertEqual(r["scales"][0]["value"], 12)
        self.assertEqual(r["top"], ["s1"])
        # КОС: все «да» → коммуникативные: 10 из 20 (К = 0,5) → оценка 2
        r = P.score("kos", dict((str(i), {"choice": "y"}) for i in range(1, 41)))
        self.assertEqual([s["value"] for s in r["scales"]], [10, 10])
        self.assertEqual(r["scales"][0]["mark"], 2)
        # EPI: экстраверт и нестабильный → холерик
        ep = {}
        for i in range(1, 58):
            ep[str(i)] = {"choice": "y" if (i in P.EPI_KEY["E"][1] or i in P.EPI_KEY["N"][1]) else "n"}
        r = P.score("epi", ep, {"age": 14, "gender": "f"})
        self.assertEqual(r["temperament"], "choleric")
        self.assertIn("norm", r)

    def test_7_psy_run(self):
        cid = self.make_class("7В", 2)
        self.t.post("/api/users", {"login": "psy", "password": "Psy12345", "full_name": "Психолог", "role": "psychologist"})
        self.t.post("/api/users", {"login": "teach", "password": "Teach123", "full_name": "Учитель", "role": "teacher"})
        p = Client(self.base)
        p.post("/api/login", {"login": "psy", "password": "Psy12345"})
        p.post("/api/me/password", {"old": "Psy12345", "new": "Psy123456"})
        tch = Client(self.base)
        tch.post("/api/login", {"login": "teach", "password": "Teach123"})
        tch.post("/api/me/password", {"old": "Teach123", "new": "Teach1234"})
        tch.get("/api/psy/methods", expect=403)
        ms = p.get("/api/psy/methods")
        self.assertEqual([m["id"] for m in ms][:4], ["ddo", "kos", "epi", "ki144"])
        run = p.post("/api/psy/runs", {"method": "epi", "class_id": cid, "show_result": "profile"})
        s, aid, j = self.student(run["code"], 0, {"gender": "m", "age": "13"})
        self.assertEqual(j["run"]["ask"], ["gender", "age"])
        st = s.get("/api/s/a/%d" % aid)
        self.assertEqual(len(st["questions"]), 57)
        self.assertIn("instruction", st["psy"])
        for q in st["questions"]:
            s.put("/api/s/a/%d/answer" % aid, {"qid": q["id"], "response": {"choice": "y"}})
        fin = s.post("/api/s/a/%d/finish" % aid)
        self.assertIn("summary", fin["result"]["psy"])
        rep = p.get("/api/psy/runs/%d/results" % run["id"])
        self.assertEqual(rep["headers"][4:8], ["Э", "Н", "Л", "Темперамент"])
        self.assertTrue(rep["summary"])
        res = p.get("/api/psy/attempts/%d" % aid)
        self.assertEqual(res["extra"], {"gender": "m", "age": 13})
        self.assertEqual(res["result"]["norm"]["age"], 13)
        x = p.call("GET", "/api/psy/runs/%d/results?format=xlsx" % run["id"], raw=True)
        self.assertEqual(x[:2], b"PK")
        # конфиденциальность: учитель не видит, в списке тестов администратора обследования нет
        tch.get("/api/runs/%d" % run["id"], expect=403)
        self.assertNotIn(run["id"], [r["id"] for r in self.t.get("/api/runs")])
        self.assertIn(run["id"], [r["id"] for r in p.get("/api/runs?kind=psy")])
        hist = p.get("/api/psy/students/%d" % j["students"][0]["id"])
        self.assertEqual(len(hist["items"]), 1)

    def test_8_update_check(self):
        self.t.put("/api/update_check", {"enabled": False})
        r = self.t.get("/api/update_check")
        self.assertFalse(r["enabled"])
        self.assertIn("github.com/oo-syp/SchoolTest/releases/latest", r["url"])
        me = self.t.get("/api/me")
        self.assertIn("SchoolGrade", me["about"]["releases"])


class MigrationTest(unittest.TestCase):
    def test_old_db(self):
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "old.db")
            d = DB.Database(path)
            d.ex("INSERT INTO classes(name, grade) VALUES('5А', 5)")
            d.close()
            con = sqlite3.connect(path)
            con.execute("DROP TABLE years")
            con.execute("DROP INDEX ix_classes_year")
            con.execute("DROP INDEX ix_students_person")
            for t_, c in (("classes", "year_id"), ("students", "person_id"), ("runs", "kind"), ("attempts", "psy"), ("attempts", "extra")):
                con.execute("ALTER TABLE %s DROP COLUMN %s" % (t_, c))
            con.execute("UPDATE meta SET value='1' WHERE key='schema'")
            con.commit()
            con.close()
            d = DB.Database(path)
            self.assertEqual(d.val("SELECT value FROM meta WHERE key='schema'"), "2")
            self.assertEqual(d.val("SELECT year_id FROM classes"), d.current_year())
            self.assertIn("kind", [r["name"] for r in d.q("PRAGMA table_info(runs)")])
            d.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
