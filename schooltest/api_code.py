# -*- coding: utf-8 -*-
"""Задачи с кодом: посылки учеников, очередь проверки, настройки компиляторов,
загрузка тестов из архива, проверка эталонного решения учителем."""
import io
import json
import os
import re
import time
import zipfile

from . import judge as J, engine as E
from . import attempts as A
from .web import router, ApiError, db, need, need_admin, is_admin, app, b64data

MAX_CODE = 64 * 1024
MIN_INTERVAL = 3          # секунд между посылками одного ученика
_QUEUE = {"q": None}


# ------------------------------------------------------------------ настройки и очередь
def cfg():
    return J.Config(db().get_setting("compilers") or {})


def workroot():
    p = os.path.join(app().data_dir, "judge")
    if not os.path.isdir(p):
        os.makedirs(p)
    return p


def queue():
    if _QUEUE["q"] is None:
        n = int(db().get_setting("judge_workers") or max(1, min(4, (os.cpu_count() or 2) // 2)))
        q = J.Queue(n)
        q.start(_process)
        _QUEUE["q"] = q
        # посылки, не проверенные до перезапуска программы
        for r in db().q("SELECT id FROM submissions WHERE status IN ('queued','running') ORDER BY id"):
            q.put(r["id"])
    return _QUEUE["q"]


def spec_of(q):
    """Условие и тесты задачи из вопроса (body — видит ученик, answer — тесты и настройки проверки)."""
    b, a = q["body"], q.get("answer") or {}
    return {"time_limit": b.get("time_limit") or 1, "memory": b.get("memory") or 256, "checker": a.get("checker") or "tokens",
            "eps": a.get("eps") or 1e-6, "scoring": a.get("scoring") or "subtasks", "examples": b.get("examples") or [],
            "subtasks": a.get("subtasks") or [], "check_examples": a.get("check_examples", True)}


def _process(sid):
    s = db().one("SELECT * FROM submissions WHERE id=?", (sid,))
    if not s or s["status"] not in ("queued", "running"):
        return
    db().ex("UPDATE submissions SET status='running' WHERE id=?", (sid,))
    a = db().one("SELECT * FROM attempts WHERE id=?", (s["attempt_id"],))
    snap = A.snapshot_for(a["run_id"]) if a else None
    q = E.qmap(snap).get(s["qid"]) if snap else None
    if not q:
        db().ex("UPDATE submissions SET status='done', verdict='SE', frac=0, judged_at=? WHERE id=?", (time.time(), sid))
        return
    res = J.judge(spec_of(q), s["lang"], s["code"], workroot(), cfg())
    db().ex("UPDATE submissions SET status='done', verdict=?, frac=?, details=?, judged_at=? WHERE id=?",
            (res["verdict"], res["frac"], json.dumps(res, ensure_ascii=False), time.time(), sid))
    update_answer(a["id"], s["qid"])


def update_answer(attempt_id, qid):
    """Ответ на вопрос «Код» — лучшая посылка; пересчёт результата попытки."""
    rows = db().q("SELECT id, frac, status FROM submissions WHERE attempt_id=? AND qid=? ORDER BY id", (attempt_id, qid))
    done = [r for r in rows if r["status"] == "done"]
    best = max([r["frac"] or 0 for r in done] or [0])
    resp = {"subs": len(rows), "judged": best, "last": rows[-1]["id"] if rows else None, "pending": len(rows) - len(done)}
    db().ex("INSERT INTO answers(attempt_id,qid,response,updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(attempt_id,qid) DO UPDATE SET response=excluded.response, updated_at=excluded.updated_at",
            (attempt_id, qid, json.dumps(resp), time.time()))
    a = db().one("SELECT status FROM attempts WHERE id=?", (attempt_id,))
    if a and a["status"] == "finished":
        A.regrade(attempt_id)


def _public_details(res, feedback):
    """Что ученик видит о посылке: full — подзадачи и номер теста, verdict — только итог, none — «отправлено»."""
    if feedback == "none":
        return {}
    out = {"compile": res.get("compile") or "", "time": res.get("time"), "memory": res.get("memory")}
    if res.get("fail"):
        out["fail"] = res["fail"]
    if feedback == "full":
        gs = []
        for g in res.get("groups") or []:
            gg = {"name": g["name"], "points": g["points"], "got": g["got"], "status": g["status"], "sample": g.get("sample")}
            if g.get("sample"):
                gg["tests"] = g["tests"]
            else:
                gg["tests"] = [{"n": x["n"], "status": x["status"], "time": x["time"], "memory": x["memory"]} for x in g["tests"]]
            gs.append(gg)
        out["groups"] = gs
    return out


def sub_out(s, q, full=False):
    fb = (q["body"].get("feedback") or "full") if q else "full"
    d = {"id": s["id"], "lang": s["lang"], "lang_name": J.LANG_NAMES.get(s["lang"], s["lang"]), "status": s["status"],
         "verdict": s["verdict"], "verdict_name": J.VERDICTS.get(s["verdict"] or "", ""), "created_at": s["created_at"]}
    res = json.loads(s["details"] or "{}")
    if full:
        d["code"] = s["code"]
        d["details"] = res
        d["frac"] = s["frac"]
    else:
        if fb == "none" and s["status"] == "done":
            d["verdict"], d["verdict_name"] = "SENT", "Решение принято на проверку"
        d["details"] = _public_details(res, fb)
        if fb != "none":
            d["frac"] = s["frac"]
    if q and s["frac"] is not None:
        d["points_total"] = sum(float(x.get("points") or 0) for x in (q.get("answer") or {}).get("subtasks") or [])
    return d


# ------------------------------------------------------------------ ученик
def _student_attempt(req, aid):
    from .api_student import _attempt
    a, _w = _attempt(req, aid)
    return a


@router.route("POST", "/api/s/a/:aid/submit", public=True)
def s_submit(req, aid):
    from .api_student import _active
    a = _active(req, aid)
    d = req.json()
    qid = str(d.get("qid"))
    snap = A.snapshot_for(a["run_id"])
    q = E.qmap(snap).get(qid)
    plan = json.loads(a["plan"] or "[]")
    need(q and q["type"] == "code" and any(e["q"] == qid for e in plan), "Задача не найдена", 404)
    lang = str(d.get("lang") or "")
    langs = q["body"].get("languages") or J.LANG_IDS
    need(lang in langs, "Этот язык программирования в задаче не разрешён", 400)
    code = str(d.get("code") or "")
    need(code.strip(), "Пустое решение", 400)
    need(len(code.encode("utf-8")) <= MAX_CODE, "Слишком длинный код (больше 64 КБ)", 413)
    rows = db().q("SELECT created_at FROM submissions WHERE attempt_id=? AND qid=? ORDER BY id DESC", (a["id"], qid))
    limit = int(q["body"].get("max_submissions") or 0)
    need(not limit or len(rows) < limit, "Исчерпано число посылок по задаче (%d)" % limit, 409)
    need(not rows or time.time() - rows[0]["created_at"] >= MIN_INTERVAL, "Подождите несколько секунд перед новой посылкой", 429)
    sid = db().insert("submissions", {"attempt_id": a["id"], "qid": qid, "lang": lang, "code": code, "status": "queued",
                                      "created_at": time.time()})
    update_answer(a["id"], qid)
    queue().put(sid)
    return {"id": sid}


@router.route("GET", "/api/s/a/:aid/subs", public=True)
def s_subs(req, aid):
    a = _student_attempt(req, aid)
    qid = str(req.arg("qid") or "")
    q = E.qmap(A.snapshot_for(a["run_id"])).get(qid)
    need(q and q["type"] == "code", "Задача не найдена", 404)
    rows = db().q("SELECT * FROM submissions WHERE attempt_id=? AND qid=? ORDER BY id DESC", (a["id"], qid))
    out = [sub_out(s, q) for s in rows]
    if req.arg("code"):
        for o, s in zip(out, rows):
            if str(s["id"]) == req.arg("code"):
                o["code"] = s["code"]
    return {"items": out, "left": (max(0, int(q["body"]["max_submissions"]) - len(rows)) if q["body"].get("max_submissions") else None)}


# ------------------------------------------------------------------ учитель
def _teacher_attempt(req, aid):
    from .api_runs import get_run
    a = db().one("SELECT * FROM attempts WHERE id=?", (int(aid),))
    need(a, "Не найдено", 404)
    r = get_run(a["run_id"], req)
    return a, r


@router.route("GET", "/api/attempts/:aid/subs")
def api_attempt_subs(req, aid):
    a, r = _teacher_attempt(req, aid)
    snap = A.snapshot_for(r["id"])
    qid = str(req.arg("qid") or "")
    q = E.qmap(snap).get(qid)
    rows = db().q("SELECT * FROM submissions WHERE attempt_id=? AND qid=? ORDER BY id DESC", (a["id"], qid))
    return [sub_out(s, q, full=True) for s in rows]


@router.route("POST", "/api/runs/:rid/rejudge")
def api_rejudge(req, rid):
    """Перепроверить посылки (после исправления тестов в задаче нужен новый запуск теста — снимок неизменен)."""
    from .api_runs import get_run
    r = get_run(rid, req)
    d = req.json()
    sql = "SELECT s.id FROM submissions s JOIN attempts a ON a.id=s.attempt_id WHERE a.run_id=?"
    args = [r["id"]]
    if d.get("qid"):
        sql += " AND s.qid=?"
        args.append(str(d["qid"]))
    if d.get("attempt_id"):
        sql += " AND s.attempt_id=?"
        args.append(int(d["attempt_id"]))
    ids = [x["id"] for x in db().q(sql + " ORDER BY s.id", args)]
    for sid in ids:
        db().ex("UPDATE submissions SET status='queued' WHERE id=?", (sid,))
        queue().put(sid)
    return {"queued": len(ids)}


def _need_editor(req):
    need(req.user and req.user["role"] in ("admin", "teacher", "psychologist"))


@router.route("POST", "/api/judge/check")
def api_judge_check(req):
    """Проверка решения учителем в редакторе задачи: те же тесты и ограничения, без сохранения."""
    _need_editor(req)
    d = req.json()
    lang = d.get("lang")
    need(lang in J.LANG_IDS, "Выберите язык", 400)
    spec = d.get("spec") or {}
    need(sum(len(s.get("tests") or []) for s in spec.get("subtasks") or []) + len(spec.get("examples") or []) <= 500,
         "Слишком много тестов", 400)
    return J.judge(spec, lang, d.get("code") or "", workroot(), cfg())


@router.route("POST", "/api/judge/answers")
def api_judge_answers(req):
    """Получить ответы к тестам эталонным решением: на входе — список входных данных."""
    _need_editor(req)
    d = req.json()
    lang = d.get("lang")
    need(lang in J.LANG_IDS, "Выберите язык", 400)
    inputs = [str(x or "") for x in d.get("inputs") or []][:500]
    return J.run_custom(lang, d.get("code") or "", inputs, workroot(), cfg(), float(d.get("time_limit") or 2),
                        int(d.get("memory") or 256))


_TEST_NAME = [
    (re.compile(r"^(?:.*/)?(\d+)$"), re.compile(r"^(?:.*/)?(\d+)\.a$")),                      # 01, 01.a (Polygon)
    (re.compile(r"^(?:.*/)?(\d+)\.in$"), re.compile(r"^(?:.*/)?(\d+)\.out$")),                # 1.in, 1.out
    (re.compile(r"^(?:.*/)?input(\d+)\.txt$", re.I), re.compile(r"^(?:.*/)?output(\d+)\.txt$", re.I)),
    (re.compile(r"^(?:.*/)?(\d+)\.dat$"), re.compile(r"^(?:.*/)?(\d+)\.ans$")),
    (re.compile(r"^(?:.*/)?(\d+)\.in\.txt$"), re.compile(r"^(?:.*/)?(\d+)\.out\.txt$")),
    (re.compile(r"^(?:.*/)?(\d+)\.txt$"), re.compile(r"^(?:.*/)?(\d+)\.(?:a|ans|out)\.txt$")),
]


def parse_tests_zip(data):
    """Тесты из ZIP-архива: пары файлов 01 / 01.a, 1.in / 1.out, input1.txt / output1.txt и т. п.
    Папки внутри архива становятся подзадачами (по алфавиту), иначе — одна группа."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ApiError(400, "Файл не является ZIP-архивом")
    names = [n for n in z.namelist() if not n.endswith("/") and "__MACOSX" not in n]
    total = sum(z.getinfo(n).file_size for n in names)
    need(total <= 40 * 1024 * 1024, "Тесты в архиве больше 40 МБ", 413)
    best = None
    for rin, rout in _TEST_NAME:
        ins = dict()
        outs = dict()
        for n in names:
            m = rin.match(n)
            if m:
                ins[(os.path.dirname(n), int(m.group(1)))] = n
            m = rout.match(n)
            if m:
                outs[(os.path.dirname(n), int(m.group(1)))] = n
        pairs = [(k, ins[k], outs[k]) for k in sorted(ins) if k in outs]
        if pairs and (best is None or len(pairs) > len(best)):
            best = pairs
    need(best, "В архиве не найдены пары файлов с тестами (01 и 01.a, 1.in и 1.out, input1.txt и output1.txt)", 400)

    def rd(n):
        b = z.read(n)
        for enc in ("utf-8-sig", "cp1251"):
            try:
                return b.decode(enc).replace("\r\n", "\n")
            except UnicodeDecodeError:
                pass
        return b.decode("utf-8", "replace")

    groups = {}
    for (folder, num), fin, fout in best:
        groups.setdefault(folder, []).append({"in": rd(fin), "out": rd(fout), "num": num})
    out = []
    for folder in sorted(groups):
        out.append({"name": os.path.basename(folder) or "", "tests": [{"in": t["in"], "out": t["out"]} for t in
                                                                       sorted(groups[folder], key=lambda x: x["num"])]})
    return out


@router.route("POST", "/api/judge/tests_zip")
def api_tests_zip(req):
    _need_editor(req)
    return {"groups": parse_tests_zip(b64data(req.json()))}


@router.route("GET", "/api/compilers")
def api_compilers(req):
    """Компиляторы: найденные пути, выбранный путь, ключи, версия."""
    need(req.user is not None)
    c = cfg()
    st = db().get_setting("compilers") or {}
    out = []
    for L in J.LANGS:
        p = c.path(L["id"])
        item = {"id": L["id"], "name": L["name"], "path": p, "custom": (st.get("paths") or {}).get(L["id"]) or "",
                "flags": c.flags.get(L["id"], ""), "default_flags": J.DEFAULT_FLAGS.get(L["id"], ""),
                "candidates": J.candidates(L["id"]), "enabled": L["id"] not in c.disabled and bool(p)}
        if req.arg("versions") == "1" and p:
            item["version"] = J.tool_version(L["id"], p)
        out.append(item)
    return {"langs": out, "workers": int(db().get_setting("judge_workers") or max(1, min(4, (os.cpu_count() or 2) // 2)))}


@router.route("PUT", "/api/compilers")
def api_compilers_put(req):
    need_admin(req)
    d = req.json()
    st = db().get_setting("compilers") or {}
    paths, flags = dict(st.get("paths") or {}), dict(st.get("flags") or {})
    for L in J.LANG_IDS:
        x = (d.get("langs") or {}).get(L) or {}
        if "path" in x:
            p = (x.get("path") or "").strip().strip('"')
            need(not p or p == "builtin" or os.path.isfile(p), "Файл не найден: %s" % p, 400)
            if p:
                paths[L] = p
            else:
                paths.pop(L, None)
        if "flags" in x:
            flags[L] = str(x.get("flags") or "")[:300]
    disabled = [L for L in J.LANG_IDS if ((d.get("langs") or {}).get(L) or {}).get("enabled") is False]
    db().set_setting("compilers", {"paths": paths, "flags": flags, "disabled": disabled})
    if d.get("workers"):
        db().set_setting("judge_workers", max(1, min(8, int(d["workers"]))))
    db().audit(req.user, req.ip, "compilers", {"paths": paths})
    return {"ok": True}


@router.route("POST", "/api/compilers/test")
def api_compilers_test(req):
    """Пробная компиляция «Hello» на выбранном языке."""
    need(req.user is not None)
    lang = req.json().get("lang")
    need(lang in J.LANG_IDS, "Неизвестный язык", 400)
    sample = {"fpc": "var a, b: longint;\nbegin\n  readln(a, b);\n  writeln(a + b);\nend.\n",
              "pabc": "begin\n  var (a, b) := ReadInteger2;\n  Println(a + b);\nend.\n",
              "py": "a, b = map(int, input().split())\nprint(a + b)\n",
              "cpp": "#include <iostream>\nint main(){ long long a, b; std::cin >> a >> b; std::cout << a + b << std::endl; }\n"}[lang]
    t0 = time.time()
    res = J.judge({"time_limit": 5, "memory": 256, "examples": [{"in": "2 3", "out": "5"}], "subtasks": []},
                  lang, sample, workroot(), cfg())
    return {"verdict": res["verdict"], "name": J.VERDICTS.get(res["verdict"], res["verdict"]), "compile": res.get("compile"),
            "seconds": round(time.time() - t0, 2), "details": res}
