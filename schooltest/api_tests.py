# -*- coding: utf-8 -*-
"""Тесты, задания, вопросы, медиафайлы."""
import hashlib
import json
import secrets

from . import engine as E, grading as G
from .web import router, ApiError, FileResponse, db, need, is_admin, pick, b64data

MEDIA_LIMITS = {"image": 5, "audio": 30, "file": 20}       # МБ
IMAGE_EXT = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp",
             "svg": "image/svg+xml", "bmp": "image/bmp"}
AUDIO_EXT = {"mp3": "audio/mpeg", "wav": "audio/wav", "ogg": "audio/ogg", "m4a": "audio/mp4", "aac": "audio/aac",
             "oga": "audio/ogg", "webm": "audio/webm"}


# ------------------------------------------------------------------ доступ
def get_test(tid, req, write=False):
    t = db().one("SELECT * FROM tests WHERE id=?", (int(tid),))
    need(t, "Тест не найден", 404)
    mine = t["owner_id"] == req.user["id"]
    if write:
        need(mine or is_admin(req), "Тест принадлежит другому учителю — сделайте копию, чтобы изменить его")
    else:
        need(mine or is_admin(req) or t["shared"])
    return t


def touch(tid):
    db().ex("UPDATE tests SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (tid,))


def _test_out(t, full=False):
    t = dict(t)
    t["settings"] = E.test_settings(t["settings"])
    t["questions"] = db().val("SELECT COUNT(*) FROM questions WHERE test_id=?", (t["id"],))
    t["runs"] = db().val("SELECT COUNT(*) FROM runs WHERE test_id=?", (t["id"],))
    t["owner"] = db().val("SELECT full_name FROM users WHERE id=?", (t["owner_id"],)) or ""
    if full:
        t["tasks"] = db().q("SELECT * FROM tasks WHERE test_id=? ORDER BY num, id", (t["id"],))
        qs = [E.load_question(r) for r in db().q("SELECT * FROM questions WHERE test_id=? ORDER BY sort, id", (t["id"],))]
        t["question_list"] = qs
        t["media"] = db().q("SELECT id, kind, name, mime, size FROM media WHERE test_id=?", (t["id"],))
        t["warnings"] = test_warnings(t, qs)
    return t


@router.route("GET", "/api/tests")
def api_tests(req):
    arch = 1 if req.arg("archived") == "1" else 0
    if is_admin(req):
        rows = db().q("SELECT * FROM tests WHERE archived=? ORDER BY updated_at DESC", (arch,))
    else:
        rows = db().q("SELECT * FROM tests WHERE archived=? AND (owner_id=? OR shared=1) ORDER BY updated_at DESC",
                      (arch, req.user["id"]))
    out = [_test_out(t) for t in rows]
    for t in out:
        t["mine"] = t["owner_id"] == req.user["id"]
    return out


@router.route("POST", "/api/tests")
def api_test_add(req):
    d = req.json()
    title = (d.get("title") or "").strip() or "Новый тест"
    st = dict(E.DEFAULT_SETTINGS)
    with db().tx():
        tid = db().insert("tests", {"owner_id": req.user["id"], "title": title, "subject": (d.get("subject") or "").strip(),
                                    "grade": d.get("grade"), "settings": json.dumps(st, ensure_ascii=False)})
        db().insert("tasks", {"test_id": tid, "num": 1, "title": ""})
    db().audit(req.user, req.ip, "test_add", title)
    return {"id": tid}


@router.route("GET", "/api/tests/:tid")
def api_test_get(req, tid):
    t = get_test(tid, req)
    out = _test_out(t, full=True)
    from . import i18n
    out["warnings"] = [i18n.msg(w, req.lang) for w in out["warnings"]]
    out["can_edit"] = t["owner_id"] == req.user["id"] or is_admin(req)
    return out


@router.route("PUT", "/api/tests/:tid")
def api_test_put(req, tid):
    t = get_test(tid, req, write=True)
    d = req.json()
    row = pick(d, ["title", "subject", "grade", "description", "shared", "archived"])
    if "settings" in d:
        st = E.test_settings(t["settings"])
        st.update(pick(d["settings"], list(E.DEFAULT_SETTINGS)))
        sc = st.get("scale") or {}
        need(sc.get("mode") in ("percent", "norms"), "Неизвестная шкала", 400)
        if sc.get("mode") == "norms":
            need(sc.get("norm") in G.NORMS, "Выберите шкалу по нормам", 400)
        if sc.get("thresholds"):
            from .api_admin import _check_table
            sc["thresholds"] = _check_table(sc["thresholds"])
        st["time_limit"] = max(0, min(600, int(st.get("time_limit") or 0)))
        st["variants"] = max(1, min(10, int(st.get("variants") or 1)))
        st["pass_percent"] = max(1, min(100, int(st.get("pass_percent") or 60)))
        need(st["show_result"] in ("none", "mark", "review"), "Неверная настройка", 400)
        need(st["result_kind"] in G.RESULT_KINDS, "Неверная настройка", 400)
        row["settings"] = json.dumps(st, ensure_ascii=False)
        # уровни заданий по выбранной шкале
        tn = G.norm_tasks_info(sc)
        if tn and tn.get("levels"):
            tasks = db().q("SELECT id FROM tasks WHERE test_id=? ORDER BY num, id", (t["id"],))
            for i, k in enumerate(tasks[:len(tn["levels"])]):
                db().ex("UPDATE tasks SET level=? WHERE id=?", (tn["levels"][i], k["id"]))
    if "title" in row:
        row["title"] = row["title"].strip() or "Без названия"
    db().update("tests", t["id"], row)
    touch(t["id"])
    return api_test_get(req, tid)


@router.route("DELETE", "/api/tests/:tid")
def api_test_del(req, tid):
    t = get_test(tid, req, write=True)
    if db().val("SELECT COUNT(*) FROM runs WHERE test_id=?", (t["id"],)):
        db().ex("UPDATE tests SET archived=1 WHERE id=?", (t["id"],))
        return {"archived": True}
    db().ex("DELETE FROM tests WHERE id=?", (t["id"],))
    db().audit(req.user, req.ip, "test_delete", t["title"])
    return {"deleted": True}


def copy_test(src_id, owner_id, title=None):
    t = db().one("SELECT * FROM tests WHERE id=?", (src_id,))
    with db().tx():
        nid = db().insert("tests", {"owner_id": owner_id, "title": title or (t["title"] + " (копия)"), "subject": t["subject"],
                                    "grade": t["grade"], "description": t["description"], "settings": t["settings"]})
        mmap = {}
        for m in db().q("SELECT * FROM media WHERE test_id=?", (src_id,)):
            mmap[m["id"]] = db().insert("media", {"test_id": nid, "kind": m["kind"], "name": m["name"], "mime": m["mime"],
                                                  "size": m["size"], "sha1": m["sha1"], "data": m["data"]})
        for k in db().q("SELECT * FROM tasks WHERE test_id=? ORDER BY num, id", (src_id,)):
            kid = db().insert("tasks", {"test_id": nid, "num": k["num"], "title": k["title"], "level": k["level"], "pick": k["pick"]})
            for q in db().q("SELECT * FROM questions WHERE task_id=? ORDER BY sort, id", (k["id"],)):
                body = remap_media(json.loads(q["body"]), mmap)
                db().insert("questions", {"test_id": nid, "task_id": kid, "variant": q["variant"], "type": q["type"],
                                          "body": json.dumps(body, ensure_ascii=False), "answer": q["answer"],
                                          "points": q["points"], "sort": q["sort"]})
    return nid


def remap_media(body, mmap):
    """Заменить номера медиафайлов в теле вопроса (при копировании и импорте)."""
    def m(v):
        return mmap.get(v, mmap.get(str(v), v)) if v is not None else v
    body = dict(body)
    body["images"] = [m(x) for x in body.get("images") or []]
    if body.get("audio"):
        body["audio"] = dict(body["audio"], media=m(body["audio"].get("media")))
    body["task_files"] = [m(x) for x in body.get("task_files") or []]
    for key in ("options", "left", "right", "items", "events"):
        if body.get(key):
            body[key] = [dict(x, image=m(x.get("image"))) if x.get("image") else x for x in body[key]]
    return body


@router.route("POST", "/api/tests/:tid/copy")
def api_test_copy(req, tid):
    get_test(tid, req)
    nid = copy_test(int(tid), req.user["id"])
    db().audit(req.user, req.ip, "test_copy", tid)
    return {"id": nid}


# ------------------------------------------------------------------ задания
@router.route("POST", "/api/tests/:tid/tasks")
def api_task_add(req, tid):
    t = get_test(tid, req, write=True)
    d = req.json()
    num = (db().val("SELECT MAX(num) FROM tasks WHERE test_id=?", (t["id"],)) or 0) + 1
    kid = db().insert("tasks", {"test_id": t["id"], "num": num, "title": (d.get("title") or "").strip(),
                                "level": d.get("level"), "pick": int(d.get("pick") or 0)})
    touch(t["id"])
    return {"id": kid}


@router.route("PUT", "/api/tasks/:kid")
def api_task_put(req, kid):
    k = db().one("SELECT * FROM tasks WHERE id=?", (int(kid),))
    need(k, "Не найдено", 404)
    get_test(k["test_id"], req, write=True)
    d = pick(req.json(), ["title", "level", "pick", "num"])
    if "pick" in d:
        d["pick"] = max(0, int(d["pick"] or 0))
    if "level" in d and d["level"] not in (None, ""):
        need(1 <= int(d["level"]) <= 5, "Уровень — от I до V", 400)
    db().update("tasks", k["id"], d)
    touch(k["test_id"])
    return {"ok": True}


@router.route("DELETE", "/api/tasks/:kid")
def api_task_del(req, kid):
    k = db().one("SELECT * FROM tasks WHERE id=?", (int(kid),))
    need(k, "Не найдено", 404)
    get_test(k["test_id"], req, write=True)
    need(db().val("SELECT COUNT(*) FROM tasks WHERE test_id=?", (k["test_id"],)) > 1, "В тесте должно остаться хотя бы одно задание", 400)
    first = db().val("SELECT id FROM tasks WHERE test_id=? AND id<>? ORDER BY num LIMIT 1", (k["test_id"], k["id"]))
    with db().tx():
        db().ex("UPDATE questions SET task_id=? WHERE task_id=?", (first, k["id"]))   # вопросы не теряются
        db().ex("DELETE FROM tasks WHERE id=?", (k["id"],))
        for i, r in enumerate(db().q("SELECT id FROM tasks WHERE test_id=? ORDER BY num, id", (k["test_id"],))):
            db().ex("UPDATE tasks SET num=? WHERE id=?", (i + 1, r["id"]))
    touch(k["test_id"])
    return {"ok": True}


# ------------------------------------------------------------------ вопросы
def _rid():
    return secrets.token_hex(4)


def _txt(v, limit=5000):
    return str(v or "").strip()[:limit]


def normalize_question(qtype, body, answer):
    """Проверка и приведение вопроса. Идентификаторы элементов заменяются случайными,
    чтобы по ним нельзя было угадать правильный ответ. Возвращает (body, answer, предупреждения)."""
    need(qtype in G.TYPES, "Неизвестный тип вопроса", 400)
    b = {"text": _txt(body.get("text"), 20000), "images": [int(x) for x in body.get("images") or [] if str(x).isdigit()]}
    au = body.get("audio") or {}
    if au.get("media"):
        b["audio"] = {"media": int(au["media"]), "plays": max(0, int(au.get("plays") or 0))}
    a = {}
    warn = []

    def items(src, key="text"):
        out, idmap = [], {}
        for x in src or []:
            if not (_txt(x.get(key)) or x.get("image")):
                continue
            nid = _rid()
            idmap[str(x.get("id"))] = nid
            it = {"id": nid, "text": _txt(x.get(key))}
            if x.get("image"):
                it["image"] = int(x["image"])
            out.append(it)
        return out, idmap

    if qtype in ("single", "multi"):
        b["options"], idmap = items(body.get("options"))
        b["keep_order"] = bool(body.get("keep_order"))
        a["correct"] = [idmap[str(c)] for c in answer.get("correct") or [] if str(c) in idmap]
        if qtype == "single":
            a["correct"] = a["correct"][:1]
        a["partial"] = answer.get("partial", "norms") if answer.get("partial") in ("norms", "proportional", "none") else "norms"
        need(len(b["options"]) >= 2, "Добавьте хотя бы два варианта ответа", 400)
        need(a["correct"], "Отметьте верный ответ", 400)
    elif qtype == "short":
        fields = body.get("fields") or [{"id": "1", "label": ""}]
        b["fields"], acc = [], {}
        for f in fields:
            nid = _rid()
            b["fields"].append({"id": nid, "label": _txt(f.get("label"), 200)})
            vals = [v.strip() for v in (answer.get("fields") or {}).get(str(f.get("id")), []) if str(v).strip()]
            need(vals, "Укажите правильный ответ для каждого поля", 400)
            acc[nid] = vals
        a["fields"] = acc
        a["tol"] = float(answer.get("tol") or 0)
    elif qtype == "match":
        b["left"], lmap = items(body.get("left"))
        b["right"], rmap = items(body.get("right"))
        pairs = {}
        for k, v in (answer.get("pairs") or {}).items():
            if str(k) in lmap and str(v) in rmap:
                pairs[lmap[str(k)]] = rmap[str(v)]
        need(len(b["left"]) >= 2 and len(pairs) == len(b["left"]), "Для каждого элемента слева выберите пару справа", 400)
        a["pairs"] = pairs
        a["partial"] = answer.get("partial", True) is not False
    elif qtype in ("order", "chrono"):
        key = "items" if qtype == "order" else "events"
        src = body.get(key) or []
        b[key], idmap = items(src)
        need(len(b[key]) >= 2, "Добавьте хотя бы два элемента", 400)
        # правильный порядок — порядок, в котором учитель ввёл элементы
        a["order"] = [x["id"] for x in b[key]]
        if qtype == "chrono":
            a["dates"] = dict((idmap[str(x.get("id"))], _txt(x.get("date"), 40)) for x in src
                              if str(x.get("id")) in idmap and _txt(x.get("date")))
            b["start_label"] = _txt(body.get("start_label"), 60)
            b["end_label"] = _txt(body.get("end_label"), 60)
        a["partial"] = answer.get("partial", "none") if answer.get("partial") in ("none", "positions", "pairs") else "none"
    elif qtype == "cloze":
        text = b["text"]
        blanks, acc = [], {}
        for bl in body.get("blanks") or []:
            old = str(bl.get("id"))
            marker = "{{%s}}" % old
            if marker not in text:
                continue
            nid = _rid()
            text = text.replace(marker, "{{%s}}" % nid)
            kind = "select" if bl.get("kind") == "select" else "input"
            right = [v.strip() for v in (answer.get("blanks") or {}).get(old, []) if str(v).strip()]
            need(right, "Укажите правильное слово для каждого пропуска", 400)
            item = {"id": nid, "kind": kind}
            if kind == "select":
                ch = [c.strip() for c in bl.get("choices") or [] if str(c).strip()]
                if right[0] not in ch:
                    ch.insert(0, right[0])
                need(len(ch) >= 2, "Для пропуска с выбором нужны хотя бы два слова", 400)
                item["choices"] = ch
                right = right[:1]
            blanks.append(item)
            acc[nid] = right
        b["text"] = text
        b["blanks"] = blanks
        a["blanks"] = acc
        need(blanks, "Отметьте пропуски в тексте", 400)
    elif qtype == "likert":
        b["statements"], _ = items(body.get("statements"))
        b["scale"] = [_txt(x, 80) for x in body.get("scale") or [] if _txt(x)] or \
            ["Полностью не согласен", "Скорее не согласен", "Затрудняюсь ответить", "Скорее согласен", "Полностью согласен"]
        need(b["statements"], "Добавьте хотя бы одно утверждение", 400)
    elif qtype == "essay":
        b["min_words"] = max(0, int(body.get("min_words") or 0))
        a["sample"] = _txt(answer.get("sample"), 20000)
    elif qtype == "file":
        b["task_files"] = [int(x) for x in body.get("task_files") or [] if str(x).isdigit()]
        b["accept"] = _txt(body.get("accept"), 200)
        b["max_mb"] = max(1, min(20, int(body.get("max_mb") or 10)))
        a["sample"] = _txt(answer.get("sample"), 20000)
    elif qtype == "code":
        b, a = normalize_code(body, answer, b)
    elif qtype == "psy":
        b["options"], _ = items(body.get("options"))
    if not b["text"] and qtype not in ("likert",):
        warn.append("Нет текста вопроса")
    return b, a, warn


def _tests(src, limit):
    out = []
    for t in src or []:
        if not isinstance(t, dict):
            continue
        i, o = str(t.get("in") or ""), str(t.get("out") or "")
        if not i.strip() and not o.strip():
            continue
        out.append({"in": i.replace("\r\n", "\n"), "out": o.replace("\r\n", "\n")})
    return out[:limit]


def normalize_code(body, answer, b):
    """Задача с кодом: условие и примеры видит ученик, тесты и эталонное решение — только учитель."""
    from . import judge as J
    for k, lim in (("input_format", 20000), ("output_format", 20000), ("notes", 20000)):
        b[k] = _txt(body.get(k), lim)
    b["examples"] = _tests(body.get("examples"), 20)
    try:
        b["time_limit"] = max(0.1, min(20.0, float(str(body.get("time_limit") or 1).replace(",", "."))))
        b["memory"] = max(16, min(1024, int(body.get("memory") or 256)))
    except ValueError:
        raise ApiError(400, "Неверные ограничения времени или памяти")
    langs = [x for x in body.get("languages") or [] if x in J.LANG_IDS]
    need(langs, "Разрешите хотя бы один язык программирования", 400)
    b["languages"] = langs
    b["feedback"] = body.get("feedback") if body.get("feedback") in ("full", "verdict", "none") else "full"
    b["max_submissions"] = max(0, min(500, int(body.get("max_submissions") or 0)))
    a = {"scoring": answer.get("scoring") if answer.get("scoring") in ("subtasks", "tests") else "subtasks",
         "checker": answer.get("checker") if answer.get("checker") in ("tokens", "lines", "float") else "tokens",
         "eps": float(answer.get("eps") or 1e-6), "manual": bool(answer.get("manual")),
         "check_examples": answer.get("check_examples", True) is not False}
    subs = []
    for i, st in enumerate(answer.get("subtasks") or [], 1):
        tests = _tests(st.get("tests"), 300)
        if not tests:
            continue
        try:
            pts = max(0.0, float(str(st.get("points") or 0).replace(",", ".")))
        except ValueError:
            pts = 0.0
        deps = [int(x) for x in st.get("deps") or [] if str(x).isdigit() and 0 < int(x) < i]
        subs.append({"name": _txt(st.get("name"), 200), "points": pts, "deps": deps, "tests": tests,
                     "limits": _txt(st.get("limits"), 500)})
    a["subtasks"] = subs
    size = sum(len(t["in"]) + len(t["out"]) for st in subs for t in st["tests"])
    need(size <= 30 * 1024 * 1024, "Тесты задачи больше 30 МБ — уменьшите их", 413)
    need(subs or a["manual"] or b["examples"], "Добавьте тесты (или включите ручную проверку)", 400)
    if subs and not sum(st["points"] for st in subs):
        for st in subs:
            st["points"] = round(100.0 / len(subs), 2)
    sol = answer.get("solution") or {}
    if sol.get("code") and sol.get("lang") in J.LANG_IDS:
        a["solution"] = {"lang": sol["lang"], "code": str(sol["code"])[:65536]}
    return b, a


def _question_in(tid, d, qid=None):
    qtype = d.get("type")
    body, answer, _w = normalize_question(qtype, d.get("body") or {}, d.get("answer") or {})
    row = {"type": qtype, "body": json.dumps(body, ensure_ascii=False), "answer": json.dumps(answer, ensure_ascii=False)}
    if "points" in d:
        try:
            row["points"] = max(0.0, min(100.0, float(str(d["points"]).replace(",", "."))))
        except ValueError:
            raise ApiError(400, "Неверное количество баллов")
    if qtype == "likert":
        row["points"] = 0
    if "variant" in d:
        row["variant"] = max(0, min(10, int(d.get("variant") or 0)))
    if "task_id" in d:
        need(db().val("SELECT 1 FROM tasks WHERE id=? AND test_id=?", (int(d["task_id"]), tid)), "Неверное задание", 400)
        row["task_id"] = int(d["task_id"])
    return row


@router.route("POST", "/api/tests/:tid/questions")
def api_q_add(req, tid):
    t = get_test(tid, req, write=True)
    d = req.json()
    row = _question_in(t["id"], d)
    if "task_id" not in row:
        row["task_id"] = db().val("SELECT id FROM tasks WHERE test_id=? ORDER BY num DESC LIMIT 1", (t["id"],))
    row["test_id"] = t["id"]
    row["sort"] = (db().val("SELECT MAX(sort) FROM questions WHERE test_id=?", (t["id"],)) or 0) + 1
    row.setdefault("points", 1)
    qid = db().insert("questions", row)
    touch(t["id"])
    return E.load_question(db().one("SELECT * FROM questions WHERE id=?", (qid,)))


@router.route("PUT", "/api/questions/:qid")
def api_q_put(req, qid):
    q = db().one("SELECT * FROM questions WHERE id=?", (int(qid),))
    need(q, "Вопрос не найден", 404)
    get_test(q["test_id"], req, write=True)
    d = req.json()
    d.setdefault("type", q["type"])
    db().update("questions", q["id"], _question_in(q["test_id"], d))
    touch(q["test_id"])
    return E.load_question(db().one("SELECT * FROM questions WHERE id=?", (q["id"],)))


@router.route("DELETE", "/api/questions/:qid")
def api_q_del(req, qid):
    q = db().one("SELECT * FROM questions WHERE id=?", (int(qid),))
    need(q, "Вопрос не найден", 404)
    get_test(q["test_id"], req, write=True)
    db().ex("DELETE FROM questions WHERE id=?", (q["id"],))
    touch(q["test_id"])
    return {"ok": True}


@router.route("POST", "/api/questions/:qid/copy")
def api_q_copy(req, qid):
    q = db().one("SELECT * FROM questions WHERE id=?", (int(qid),))
    need(q, "Вопрос не найден", 404)
    get_test(q["test_id"], req, write=True)
    row = dict(q)
    row.pop("id")
    row["sort"] = q["sort"] + 0.5
    nid = db().insert("questions", row)
    _resort(q["test_id"])
    touch(q["test_id"])
    return {"id": nid}


def _resort(tid):
    for i, r in enumerate(db().q("SELECT id FROM questions WHERE test_id=? ORDER BY sort, id", (tid,))):
        db().ex("UPDATE questions SET sort=? WHERE id=?", (i + 1, r["id"]))


@router.route("PUT", "/api/tests/:tid/order")
def api_q_order(req, tid):
    t = get_test(tid, req, write=True)
    d = req.json()
    with db().tx():
        for i, it in enumerate(d.get("items") or []):
            db().ex("UPDATE questions SET sort=?, task_id=COALESCE(?, task_id) WHERE id=? AND test_id=?",
                    (i + 1, it.get("task_id"), int(it["id"]), t["id"]))
    touch(t["id"])
    return {"ok": True}


def test_warnings(t, qs):
    warn = []
    tasks = db().q("SELECT * FROM tasks WHERE test_id=? ORDER BY num, id", (t["id"],))
    st = t["settings"] if isinstance(t["settings"], dict) else E.test_settings(t["settings"])
    warn += G.validate_scale(st["scale"], [k["num"] for k in tasks])
    if not qs:
        warn.append("В тесте нет вопросов.")
    nvar = int(st.get("variants") or 1)
    if nvar > 1:
        for v in range(1, nvar + 1):
            if not [q for q in qs if q["variant"] in (0, v)]:
                warn.append("В варианте %d нет вопросов." % v)
    for k in tasks:
        n = len([q for q in qs if q["task_id"] == k["id"]])
        if k["pick"] and k["pick"] > n:
            warn.append("В задании %d выбирается %d вопросов, а в банке только %d." % (k["num"], k["pick"], n))
        if G.norm_tasks_info(st["scale"]) and n == 0:
            warn.append("Задание %d пустое." % k["num"])
    if st["scale"].get("mode") == "percent" and qs and all(q["type"] in G.UNSCORED_TYPES for q in qs):
        warn.append("В тесте только вопросы-опросы: отметка выставляться не будет.")
    return warn


# ------------------------------------------------------------------ медиафайлы
def store_media(tid, name, data, kind=None):
    ext = (name.rsplit(".", 1)[-1] if "." in name else "").lower()
    if kind is None:
        kind = "image" if ext in IMAGE_EXT else ("audio" if ext in AUDIO_EXT else "file")
    if kind == "image":
        need(ext in IMAGE_EXT, "Картинка должна быть в формате PNG, JPG, GIF, WEBP, SVG или BMP", 400)
        mime = IMAGE_EXT[ext]
    elif kind == "audio":
        need(ext in AUDIO_EXT, "Звук должен быть в формате MP3, WAV, OGG или M4A", 400)
        mime = AUDIO_EXT[ext]
    else:
        import mimetypes
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    need(len(data) <= MEDIA_LIMITS[kind] * 1024 * 1024, "Файл слишком большой (не более %d МБ)" % MEDIA_LIMITS[kind], 400)
    sha = hashlib.sha1(data).hexdigest()
    same = db().val("SELECT id FROM media WHERE test_id=? AND sha1=? AND kind=?", (tid, sha, kind))
    if same:
        return same
    return db().insert("media", {"test_id": tid, "kind": kind, "name": name[:200], "mime": mime, "size": len(data),
                                 "sha1": sha, "data": data})


@router.route("POST", "/api/tests/:tid/media")
def api_media_add(req, tid):
    t = get_test(tid, req, write=True)
    d = req.json()
    kind = d.get("kind") if d.get("kind") in MEDIA_LIMITS else None
    mid = store_media(t["id"], (d.get("name") or "file").strip(), b64data(d), kind)
    m = db().one("SELECT id, kind, name, mime, size FROM media WHERE id=?", (mid,))
    return m


@router.route("GET", "/api/media/:mid")
def api_media_get(req, mid):
    m = db().one("SELECT * FROM media WHERE id=?", (int(mid),))
    need(m, "Не найдено", 404)
    if m["test_id"]:
        get_test(m["test_id"], req)
    return FileResponse(m["data"], m["name"], m["mime"] if m["kind"] != "file" else "application/octet-stream",
                        inline=m["kind"] != "file", cache=True)


@router.route("GET", "/api/norms")
def api_norms(req):
    from .api_admin import norms_catalog
    return norms_catalog()
