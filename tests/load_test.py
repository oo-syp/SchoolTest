# -*- coding: utf-8 -*-
"""Нагрузочная проверка: 60 учеников одновременно проходят тест из 20 вопросов.

python tests/load_test.py  — поднимает сервер на свободном порту во временной папке."""
import http.client
import json
import os
import random
import shutil
import statistics
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from schooltest import main as M  # noqa: E402
from schooltest.server import ServerThread  # noqa: E402
from schooltest import attempts  # noqa: E402

N_STUDENTS = 60
N_Q = 20
LAT = []
ERR = []
lock = threading.Lock()


class C(object):
    def __init__(self, port):
        self.port = port
        self.cookies = {}

    def req(self, method, path, data=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        body = json.dumps(data).encode("utf-8") if data is not None else None
        hdr = {"X-SchoolTest": "1", "Content-Type": "application/json"}
        if self.cookies:
            hdr["Cookie"] = "; ".join("%s=%s" % kv for kv in self.cookies.items())
        t0 = time.time()
        conn.request(method, path, body=body, headers=hdr)
        r = conn.getresponse()
        payload = r.read()
        dt = time.time() - t0
        for k, v in r.getheaders():
            if k.lower() == "set-cookie":
                nv = v.split(";")[0]
                n, val = nv.split("=", 1)
                self.cookies[n] = val
        conn.close()
        with lock:
            LAT.append(dt)
        if r.status != 200:
            raise RuntimeError("%s %s -> %s %s" % (method, path, r.status, payload[:200]))
        return json.loads(payload.decode("utf-8")) if payload else None


def student(port, code, sid, results):
    try:
        c = C(port)
        time.sleep(random.random() * 2)
        c.req("POST", "/api/s/join", {"code": code})
        aid = c.req("POST", "/api/s/start", {"code": code, "student_id": sid})["attempt_id"]
        st = c.req("GET", "/api/s/a/%d" % aid)
        n_ok = 0
        for q in st["questions"]:
            time.sleep(random.uniform(0.05, 0.4))
            right = [o["id"] for o in q["options"] if o["text"] == "верно"][0]
            wrong = [o["id"] for o in q["options"] if o["text"] != "верно"][0]
            pick = right if random.random() < 0.7 else wrong
            n_ok += pick == right
            c.req("PUT", "/api/s/a/%d/answer" % aid, {"qid": q["id"], "response": {"choice": pick}})
            if random.random() < 0.2:
                c.req("POST", "/api/s/a/%d/ping" % aid, {})
        res = c.req("POST", "/api/s/a/%d/finish" % aid, {})
        results[sid] = (n_ok, res["result"]["score"])
    except Exception as e:  # noqa
        with lock:
            ERR.append(str(e))


def main():
    tmp = tempfile.mkdtemp()
    app = M.init_app(tmp)
    srv = ServerThread(app, "127.0.0.1", 0)
    srv.start()
    attempts.start_sweeper()
    port = srv.httpd.server_address[1]
    t = C(port)
    t.req("POST", "/api/login", {"login": "admin", "password": "admin"})
    t.req("POST", "/api/me/password", {"old": "admin", "new": "Secret123"})
    t.req("PUT", "/api/settings", {"org_type": "school"})
    cid = t.req("POST", "/api/classes", {"name": "11А"})["id"]
    t.req("POST", "/api/classes/%d/paste" % cid, {"text": "\n".join("Ученик%02d Имя" % i for i in range(N_STUDENTS))})
    tid = t.req("POST", "/api/tests", {"title": "Нагрузка"})["id"]
    for i in range(N_Q):
        t.req("POST", "/api/tests/%d/questions" % tid, {"type": "single", "body": {"text": "Вопрос %d" % i, "options": [
            {"id": "a", "text": "верно"}, {"id": "b", "text": "неверно"}, {"id": "c", "text": "нет"}]}, "answer": {"correct": ["a"]}})
    t.req("PUT", "/api/tests/%d" % tid, {"settings": {"shuffle_questions": True}})
    run = t.req("POST", "/api/runs", {"test_id": tid, "class_id": cid})
    studs = t.req("GET", "/api/classes/%d/students" % cid)
    results = {}
    stop = threading.Event()

    def teacher_monitor():          # учитель обновляет наблюдение каждые 4 секунды
        while not stop.is_set():
            t.req("GET", "/api/runs/%d" % run["id"])
            time.sleep(4)
    mt = threading.Thread(target=teacher_monitor)
    mt.start()
    t0 = time.time()
    ths = [threading.Thread(target=student, args=(port, run["code"], s["id"], results)) for s in studs]
    for th in ths:
        th.start()
    for th in ths:
        th.join()
    stop.set()
    mt.join()
    total = time.time() - t0
    mon = t.req("GET", "/api/runs/%d" % run["id"])
    finished = sum(1 for s in mon["students"] if s["status"] == "finished")
    lost = [sid for sid, (ok, score) in results.items() if ok != score]
    lat = sorted(LAT)
    print("учеников: %d, завершили: %d, ошибок: %d, расхождений баллов: %d" % (len(studs), finished, len(ERR), len(lost)))
    print("запросов: %d за %.1f с; задержка: медиана %.0f мс, 95%% %.0f мс, максимум %.0f мс" % (
        len(lat), total, statistics.median(lat) * 1000, lat[int(len(lat) * 0.95)] * 1000, lat[-1] * 1000))
    for e in ERR[:5]:
        print("  ", e)
    srv.stop()
    app.db.close()
    shutil.rmtree(tmp, ignore_errors=True)
    ok = not ERR and not lost and finished == N_STUDENTS
    print("OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
