# -*- coding: utf-8 -*-
"""Импорт и экспорт тестов: файл теста SchoolTest, текстовый формат (.txt / текст из Word),
таблица Excel по шаблону."""
import base64
import gzip
import io
import json
import os
import re
import time
import zipfile

from . import APP_VERSION, engine as E, grading as G, xlsx, xls, i18n
from .api_tests import get_test, normalize_question, store_media, remap_media, touch, IMAGE_EXT
from .web import router, ApiError, FileResponse, db, need, b64data, XLSX_CT

FILE_FORMAT = "schooltest-test"
FILE_EXT = ".stest"


# ================================================================== файл теста SchoolTest
def export_test(tid):
    t = db().one("SELECT * FROM tests WHERE id=?", (tid,))
    media = []
    for m in db().q("SELECT * FROM media WHERE test_id=?", (tid,)):
        media.append({"id": m["id"], "kind": m["kind"], "name": m["name"], "mime": m["mime"],
                      "data": base64.b64encode(m["data"]).decode("ascii")})
    tasks = []
    for k in db().q("SELECT * FROM tasks WHERE test_id=? ORDER BY num, id", (tid,)):
        qs = []
        for q in db().q("SELECT * FROM questions WHERE task_id=? ORDER BY sort, id", (k["id"],)):
            qs.append({"type": q["type"], "variant": q["variant"], "points": q["points"],
                       "body": json.loads(q["body"]), "answer": json.loads(q["answer"])})
        tasks.append({"num": k["num"], "title": k["title"], "level": k["level"], "pick": k["pick"], "questions": qs})
    doc = {"format": FILE_FORMAT, "version": 1, "app": "SchoolTest " + APP_VERSION,
           "exported": time.strftime("%Y-%m-%d %H:%M"),
           "test": {"title": t["title"], "subject": t["subject"], "grade": t["grade"], "description": t["description"],
                    "settings": E.test_settings(t["settings"])},
           "tasks": tasks, "media": media}
    return gzip.compress(json.dumps(doc, ensure_ascii=False).encode("utf-8"))


def _safe_name(s):
    s = re.sub(r'[\\/:*?"<>|]+', "", s or "test").strip()
    return s[:60] or "test"


@router.route("GET", "/api/tests/:tid/export")
def api_test_export(req, tid):
    t = get_test(tid, req)
    fmt = req.arg("format") or "stest"
    if fmt == "txt":
        return FileResponse(export_text(t["id"]).encode("utf-8-sig"), _safe_name(t["title"]) + ".txt",
                            "text/plain; charset=utf-8")
    return FileResponse(export_test(t["id"]), _safe_name(t["title"]) + FILE_EXT, "application/octet-stream")


def read_test_file(data):
    try:
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        doc = json.loads(data.decode("utf-8-sig"))
    except Exception:
        raise ApiError(400, "Файл не является файлом теста SchoolTest")
    need(isinstance(doc, dict) and doc.get("format") == FILE_FORMAT, "Файл не является файлом теста SchoolTest", 400)
    return doc


def import_test_doc(doc, owner_id):
    """Создать тест из файла SchoolTest. Каждый вопрос проходит ту же проверку, что и при ручном вводе."""
    t = doc.get("test") or {}
    st = E.test_settings(json.dumps(t.get("settings") or {}))
    errors = []
    with db().tx():
        tid = db().insert("tests", {"owner_id": owner_id, "title": (t.get("title") or "Импортированный тест")[:300],
                                    "subject": (t.get("subject") or "")[:100], "grade": t.get("grade"),
                                    "description": (t.get("description") or "")[:5000],
                                    "settings": json.dumps(st, ensure_ascii=False)})
        mmap = {}
        for m in doc.get("media") or []:
            try:
                data = base64.b64decode(m.get("data") or "")
                mmap[m.get("id")] = store_media(tid, m.get("name") or "file", data, m.get("kind"))
            except ApiError as e:
                errors.append("%s: %s" % (m.get("name"), e.message))
        tasks = doc.get("tasks") or [{"num": 1, "questions": []}]
        sort = 0
        for i, k in enumerate(tasks):
            lvl = k.get("level")
            kid = db().insert("tasks", {"test_id": tid, "num": i + 1, "title": (k.get("title") or "")[:300],
                                        "level": int(lvl) if str(lvl or "").isdigit() and 1 <= int(lvl) <= 5 else None,
                                        "pick": max(0, int(k.get("pick") or 0))})
            for q in k.get("questions") or []:
                body = remap_media(q.get("body") or {}, mmap)
                try:
                    b, a, _w = _normalize_existing(q.get("type"), body, q.get("answer") or {})
                except ApiError as e:
                    errors.append("Задание %d, вопрос «%s»: %s" % (i + 1, (body.get("text") or "")[:40], e.message))
                    continue
                sort += 1
                db().insert("questions", {"test_id": tid, "task_id": kid, "variant": max(0, min(10, int(q.get("variant") or 0))),
                                          "type": q["type"], "body": json.dumps(b, ensure_ascii=False),
                                          "answer": json.dumps(a, ensure_ascii=False),
                                          "points": 0 if q["type"] == "likert" else max(0.0, min(100.0, float(q.get("points") or 1))),
                                          "sort": sort})
    return tid, errors


def _normalize_existing(qtype, body, answer):
    """Вопрос из файла уже хранит правильный ответ по идентификаторам — приводим к виду редактора."""
    body = dict(body)
    answer = dict(answer)
    if qtype in ("order", "chrono"):
        key = "items" if qtype == "order" else "events"
        order = answer.get("order") or []
        byid = dict((x.get("id"), x) for x in body.get(key) or [])
        items = [byid[i] for i in order if i in byid] + [x for x in body.get(key) or [] if x.get("id") not in order]
        if qtype == "chrono":
            dates = answer.get("dates") or {}
            items = [dict(x, date=dates.get(x.get("id"), "")) for x in items]
        body[key] = items
    if qtype == "short":
        answer["fields"] = answer.get("fields") or {}
    return normalize_question(qtype, body, answer)


def _decode_upload(d):
    files = d.get("files") or []
    if not files and d.get("data"):
        files = [{"name": d.get("name") or "file", "data": d.get("data")}]
    out = []
    for f in files:
        try:
            out.append((os.path.basename((f.get("name") or "file").replace("\\", "/")), base64.b64decode(f.get("data") or "")))
        except Exception:
            raise ApiError(400, "Файл повреждён при загрузке")
    return out


# ================================================================== текстовый формат
ANS_RE = re.compile(r"^\s*([+\-])\s?(.*)$")
ORD_RE = re.compile(r"^\s*(\d{1,2})[.)]\s+(.+)$")
SHORT_RE = re.compile(r"^\s*=\s?(.*)$")
FIELD_RE = re.compile(r"^\{([^}]*)\}\s*(.*)$")
IMG_RE = re.compile(r"^\s*\[([^\[\]]+\.(?:%s))\]\s*$" % "|".join(IMAGE_EXT), re.I)


def _clean_lines(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ").replace("﻿", "")
    # маркеры списков Word при вставке
    out = []
    for ln in text.split("\n"):
        ln = re.sub(r"^\s*[•·▪◦]\s*", "", ln.rstrip())
        ln = ln.replace("– ", "- ", 1) if ln.lstrip().startswith("– ") else ln   # «– ответ» из Word
        ln = ln.replace("— ", "- ", 1) if ln.lstrip().startswith("— ") else ln
        out.append(ln)
    return out


def parse_text(text):
    """Разбор текстового формата. Возвращает (вопросы, ошибки).
    Вопрос: {"type", "text", "images": [имена], "options"/"items"/"fields", "line"}."""
    lines = _clean_lines(text)
    blocks, cur = [], None
    errors = []

    def new(lineno):
        b = {"text": [], "images": [], "answers": [], "line": lineno}
        blocks.append(b)
        return b

    expect_text = False
    for i, raw in enumerate(lines, 1):
        ln = raw.strip()
        if not ln:
            continue
        if ln == "?":
            cur = new(i + 1)
            expect_text = True
            continue
        m_img = IMG_RE.match(ln)
        m_ans = ANS_RE.match(ln) if not expect_text else None
        m_ord = ORD_RE.match(ln) if not expect_text else None
        if m_ord and cur is not None:
            # нумерованная строка — элемент порядка, только если в вопросе нет других видов ответов
            # и номер ещё не встречался (иначе это начало следующего пронумерованного вопроса)
            kinds = set(a["kind"] for a in cur["answers"])
            used_pos = set(a.get("pos") for a in cur["answers"])
            if kinds - {"ord"} or int(m_ord.group(1)) in used_pos:
                m_ord = None
        m_sh = SHORT_RE.match(ln) if not expect_text else None
        if m_img and (cur is None or not cur["answers"]):
            if cur is None:
                cur = new(i)
            cur["images"].append(m_img.group(1).strip())
            continue
        if m_ans or (m_ord and cur and cur["text"]) or m_sh:
            if cur is None or not cur["text"] and not cur["images"]:
                errors.append({"line": i, "text": raw, "msg": "Вариант ответа без текста вопроса"})
                continue
            if m_ans:
                val = m_ans.group(2).strip()
                mi = re.match(r"^\[([^\[\]]+)\]$", val)
                cur["answers"].append({"kind": "opt", "correct": m_ans.group(1) == "+",
                                       "text": "" if mi else val, "image": mi.group(1) if mi else None, "line": i})
            elif m_sh:
                val = m_sh.group(1).strip()
                mf = FIELD_RE.match(val)
                label, val = (mf.group(1).strip().rstrip(":").strip(), mf.group(2).strip()) if mf else ("", val)
                cur["answers"].append({"kind": "short", "label": label, "text": val, "line": i})
            else:
                cur["answers"].append({"kind": "ord", "pos": int(m_ord.group(1)), "text": m_ord.group(2).strip(), "line": i})
            expect_text = False
            continue
        # строка текста вопроса
        if cur is None or cur["answers"]:
            cur = new(i)
        cur["text"].append(raw.rstrip())
        expect_text = False

    out = []
    for b in blocks:
        q = _block_to_question(b, errors)
        if q:
            out.append(q)
    return out, errors


def _block_to_question(b, errors):
    text = "\n".join(b["text"]).strip()
    ans = b["answers"]
    base = {"text": text, "images": b["images"], "line": b["line"]}
    if not ans:
        errors.append({"line": b["line"], "text": text[:80], "msg": "У вопроса нет вариантов ответа"})
        return None
    kinds = set(a["kind"] for a in ans)
    if len(kinds) > 1:
        errors.append({"line": b["line"], "text": text[:80], "msg": "В одном вопросе смешаны разные виды ответов"})
        return None
    kind = kinds.pop()
    if kind == "opt":
        right = [a for a in ans if a["correct"]]
        if not right:
            errors.append({"line": b["line"], "text": text[:80], "msg": "Не отмечен верный ответ (+)"})
            return None
        if len(ans) < 2:
            errors.append({"line": b["line"], "text": text[:80], "msg": "Нужно хотя бы два варианта ответа"})
            return None
        base["type"] = "single" if len(right) == 1 else "multi"
        base["options"] = [{"text": a["text"], "image": a["image"], "correct": a["correct"]} for a in ans]
    elif kind == "ord":
        pos = [a["pos"] for a in ans]
        if sorted(pos) != list(range(1, len(ans) + 1)):
            errors.append({"line": b["line"], "text": text[:80], "msg": "Номера мест должны идти от 1 до %d без пропусков" % len(ans)})
            return None
        base["type"] = "order"
        base["items"] = [a["text"] for a in sorted(ans, key=lambda a: a["pos"])]
    else:
        base["type"] = "short"
        fields, order = {}, []
        for a in ans:
            vals = [v.strip() for v in re.split(r"\s*;\s*", a["text"]) if v.strip()]
            if not vals:
                errors.append({"line": a["line"], "text": a["text"], "msg": "Пустой правильный ответ"})
                return None
            if a["label"] not in fields:
                fields[a["label"]] = []
                order.append(a["label"])
            fields[a["label"]] += vals       # повтор строки без подписи — ещё один допустимый ответ
        base["fields"] = [{"label": lb, "answers": fields[lb]} for lb in order]
    return base


def text_question_to_api(q, images):
    """Перевести разобранный вопрос в формат редактора (body, answer). images: имя файла -> id медиа."""
    def img(name):
        if not name:
            return None
        return images.get(name.lower())
    body = {"text": q["text"], "images": [img(n) for n in q["images"] if img(n)]}
    answer = {}
    if q["type"] in ("single", "multi"):
        body["options"] = []
        answer["correct"] = []
        for i, o in enumerate(q["options"]):
            it = {"id": str(i), "text": o["text"]}
            if o.get("image") and img(o["image"]):
                it["image"] = img(o["image"])
            elif o.get("image"):
                it["text"] = "[%s]" % o["image"]
            body["options"].append(it)
            if o["correct"]:
                answer["correct"].append(str(i))
    elif q["type"] == "order":
        body["items"] = [{"id": str(i), "text": t} for i, t in enumerate(q["items"])]
    elif q["type"] == "short":
        body["fields"] = [{"id": str(i), "label": f["label"]} for i, f in enumerate(q["fields"])]
        answer["fields"] = dict((str(i), f["answers"]) for i, f in enumerate(q["fields"]))
    return body, answer


def _media_from_files(files):
    """Картинки и текст из загруженных файлов (в том числе из ZIP-архива)."""
    texts, images = [], {}
    for name, data in files:
        low = name.lower()
        if low.endswith(".zip"):
            try:
                z = zipfile.ZipFile(io.BytesIO(data))
            except zipfile.BadZipFile:
                raise ApiError(400, "Архив повреждён")
            total = 0
            for zi in z.infolist():
                if zi.is_dir():
                    continue
                total += zi.file_size
                need(total < 200 * 1024 * 1024, "Архив слишком большой", 400)
                inner = os.path.basename(zi.filename)
                if inner.lower().endswith(".txt"):
                    texts.append((inner, z.read(zi)))
                elif inner.rsplit(".", 1)[-1].lower() in IMAGE_EXT:
                    images[inner.lower()] = (inner, z.read(zi))
        elif low.endswith(".txt"):
            texts.append((name, data))
        elif low.rsplit(".", 1)[-1] in IMAGE_EXT:
            images[low] = (name, data)
    return texts, images


def decode_text(data):
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def _preview_item(q, image_names):
    missing = [n for n in q["images"] + [o.get("image") for o in q.get("options", []) if o.get("image")]
               if n and n.lower() not in image_names]
    return {"type": q["type"], "type_name": G.TYPE_NAMES[q["type"]], "text": q["text"], "images": q["images"],
            "options": q.get("options"), "items": q.get("items"), "fields": q.get("fields"), "line": q["line"],
            "missing": missing}


@router.route("POST", "/api/import/text")
def api_import_text(req):
    """Разбор текста (вставка из Word или файлы .txt с картинками). commit=true — сохранить в тест."""
    d = req.json()
    texts, images = _media_from_files(_decode_upload(d))
    src = d.get("text") or ""
    if not src.strip() and texts:
        src = "\n".join(decode_text(data) for _n, data in texts)
    need(src.strip(), "Нет текста для разбора", 400)
    qs, errors = parse_text(src)
    _tr(errors, req.lang)
    if not d.get("commit"):
        return {"questions": [_preview_item(q, images) for q in qs], "errors": errors}
    need(qs, "Не удалось распознать ни одного вопроса", 400)
    if d.get("test_id"):
        t = get_test(d["test_id"], req, write=True)
        tid = t["id"]
    else:
        title = (d.get("title") or "").strip() or (os.path.splitext(texts[0][0])[0] if texts else "Тест из текста")
        tid = db().insert("tests", {"owner_id": req.user["id"], "title": title[:300], "subject": (d.get("subject") or "").strip(),
                                    "settings": json.dumps(E.DEFAULT_SETTINGS, ensure_ascii=False)})
        db().insert("tasks", {"test_id": tid, "num": 1, "title": ""})
    added, problems = _save_parsed(tid, qs, images, d.get("task_id"), d.get("points"))
    touch(tid)
    db().audit(req.user, req.ip, "test_import_text", {"test": tid, "questions": added})
    return {"test_id": tid, "added": added, "errors": _tr(errors + problems, req.lang)}


def _tr(errors, lang):
    for e in errors:
        if isinstance(e, dict):
            e["msg"] = i18n.msg(e.get("msg"), lang)
    return errors


def _save_parsed(tid, qs, images, task_id=None, points=None):
    """qs — вопросы в форме parse_text; images — имя (нижний регистр) -> (имя, данные)."""
    if task_id:
        need(db().val("SELECT 1 FROM tasks WHERE id=? AND test_id=?", (int(task_id), tid)), "Неверное задание", 400)
        kid = int(task_id)
    else:
        kid = db().val("SELECT id FROM tasks WHERE test_id=? ORDER BY num DESC LIMIT 1", (tid,))
    used = set()
    for q in qs:
        used.update(n.lower() for n in q["images"])
        used.update((o.get("image") or "").lower() for o in q.get("options") or [] if o.get("image"))
    ids = {}
    problems = []
    for low in used:
        if low in images:
            try:
                ids[low] = store_media(tid, images[low][0], images[low][1], "image")
            except ApiError as e:
                problems.append({"line": 0, "text": images[low][0], "msg": e.message})
    sort = db().val("SELECT MAX(sort) FROM questions WHERE test_id=?", (tid,)) or 0
    added = 0
    with db().tx():
        for q in qs:
            try:
                if "body" in q:       # из Excel: уже в формате редактора
                    body, answer = q["body"], q["answer"]
                    body["images"] = [ids[n.lower()] for n in q["images"] if n.lower() in ids]
                else:
                    body, answer = text_question_to_api(q, ids)
                b, a, _w = normalize_question(q["type"], body, answer)
            except ApiError as e:
                problems.append({"line": q.get("line", 0), "text": q.get("text", "")[:80], "msg": e.message})
                continue
            sort += 1
            pts = q.get("points") if q.get("points") is not None else points
            db().insert("questions", {"test_id": tid, "task_id": q.get("_task") or kid, "variant": int(q.get("variant") or 0),
                                      "type": q["type"], "body": json.dumps(b, ensure_ascii=False),
                                      "answer": json.dumps(a, ensure_ascii=False),
                                      "points": 0 if q["type"] == "likert" else max(0.0, min(100.0, float(pts or 1))),
                                      "sort": sort})
            added += 1
    return added, problems


def export_text(tid):
    """Выгрузка теста в текстовый формат (только типы, которые этот формат поддерживает)."""
    out = []
    media = dict((m["id"], m["name"]) for m in db().q("SELECT id, name FROM media WHERE test_id=?", (tid,)))
    for q in db().q("SELECT * FROM questions WHERE test_id=? ORDER BY sort, id", (tid,)):
        q = E.load_question(q)
        b, a = q["body"], q["answer"]
        if q["type"] not in ("single", "multi", "order", "short"):
            continue
        out.append(b.get("text") or "")
        for m in b.get("images") or []:
            if m in media:
                out.append("[%s]" % media[m])
        if q["type"] in ("single", "multi"):
            for o in b["options"]:
                sign = "+" if o["id"] in a.get("correct", []) else "-"
                out.append("%s %s" % (sign, ("[%s]" % media[o["image"]]) if o.get("image") in media and not o.get("text") else o["text"]))
        elif q["type"] == "order":
            pos = dict((i, n + 1) for n, i in enumerate(a["order"]))
            for it in b["items"]:
                out.append("%d. %s" % (pos[it["id"]], it["text"]))
        else:
            multi = len(b["fields"]) > 1 or b["fields"][0].get("label")
            for f in b["fields"]:
                vals = "; ".join(a["fields"].get(f["id"], []))
                out.append("= {%s:} %s" % (f["label"], vals) if multi else "= %s" % vals)
        out.append("")
    return "\n".join(out)


# ================================================================== таблица Excel
TEMPLATE_HEADERS = ["Задание", "Вариант", "Тип", "Баллы", "Вопрос", "Картинка", "Ответ 1", "Ответ 2", "Ответ 3",
                    "Ответ 4", "Ответ 5", "Ответ 6", "Ответ 7", "Ответ 8"]
TYPE_ALIASES = {
    "один": "single", "один ответ": "single", "single": "single",
    "несколько": "multi", "несколько ответов": "multi", "multi": "multi",
    "краткий": "short", "короткий": "short", "краткий ответ": "short", "short": "short",
    "соответствие": "match", "match": "match",
    "порядок": "order", "последовательность": "order", "order": "order",
    "хронология": "chrono", "хронологическая рулетка": "chrono", "chrono": "chrono",
    "пропуски": "cloze", "текст с пропусками": "cloze", "cloze": "cloze",
    "опрос": "likert", "шкала": "likert", "лайкерт": "likert", "likert": "likert",
    "развёрнутый": "essay", "развернутый": "essay", "развёрнутый ответ": "essay", "essay": "essay",
    "файл": "file", "file": "file",
}
TEMPLATE_HELP = [
    ["Один", "+ перед верным вариантом: «+Минск», «Брест»"],
    ["Несколько", "+ перед каждым верным вариантом"],
    ["Краткий", "Ответ 1 — правильный ответ (несколько допустимых — через «;»). Несколько полей: «площадь: 12», «периметр: 14»"],
    ["Порядок", "Элементы в правильном порядке — ученик увидит их вперемешку"],
    ["Хронология", "События от самого раннего к позднему; дату можно указать через «|»: «988 | Крещение Руси»"],
    ["Соответствие", "Пары через «=»: «Минск = Беларусь»"],
    ["Пропуски", "В тексте вопроса пропуск — в квадратных скобках: «Столица Беларуси — [Минск]». Варианты для выбора: [Минск|Брест|Гродно], первый — верный"],
    ["Опрос", "Ответы — утверждения для оценки по шкале согласия (не оценивается)"],
    ["Развёрнутый", "Ответ 1 — образец ответа для учителя (проверяется вручную)"],
    ["Файл", "Ответ 1 — допустимые типы файлов, например «.docx, .pdf» (проверяется вручную)"],
]


@router.route("GET", "/api/import/excel_template")
def api_excel_template(req):
    sample = [
        [1, "", "Один", 1, "Столица Беларуси?", "", "+Минск", "Брест", "Гродно", "Гомель"],
        [1, "", "Несколько", 2, "Какие числа чётные?", "", "+2", "3", "+4", "5"],
        [2, "", "Краткий", 1, "Сколько будет \\(2^{10}\\)?", "", "1024"],
        [2, "", "Краткий", 2, "Стороны прямоугольника 3 и 4 см. Найдите площадь и периметр.", "", "площадь: 12", "периметр: 14"],
        [3, "", "Порядок", 2, "Расположите числа по возрастанию", "", "0,1", "0,25", "0,5", "1"],
        [3, "", "Хронология", 2, "Расположите события на линии времени", "", "862 | Первое упоминание Полоцка",
         "1385 | Кревская уния", "1569 | Люблинская уния"],
        [4, "", "Соответствие", 2, "Соотнесите столицу и страну", "", "Минск = Беларусь", "Вильнюс = Литва", "Рига = Латвия"],
        [4, "", "Пропуски", 2, "Столица Беларуси — [Минск], крупнейшая река — [Днепр|Неман|Припять].", ""],
        [5, "", "Опрос", 0, "Оцените утверждения", "", "Мне было интересно", "Задания были понятны"],
        [5, "", "Развёрнутый", 3, "Опишите значение Кревской унии", "", "Образец ответа для учителя"],
    ]
    rows = [r + [""] * (len(TEMPLATE_HEADERS) - len(r)) for r in sample]
    sheet = {"name": "Вопросы", "title": "Шаблон импорта вопросов SchoolTest",
             "subtitle": "Заполните строки ниже заголовка. «Вариант» пусто — вопрос для всех вариантов. Картинка — имя файла, загрузите его вместе с таблицей.",
             "headers": TEMPLATE_HEADERS, "widths": [9, 9, 14, 7, 50, 14] + [22] * 8, "rows": rows}
    hlp = {"name": "Подсказка", "title": "Как заполнять столбцы ответов", "headers": ["Тип", "Что писать в столбцах «Ответ»"],
           "widths": [16, 110], "rows": TEMPLATE_HELP}
    return FileResponse(xlsx.build([sheet, hlp]), "Шаблон_вопросов_SchoolTest.xlsx", XLSX_CT)


def _read_table(name, data):
    low = name.lower()
    if low.endswith(".xlsx"):
        try:
            return xlsx.read_first_sheet(data)
        except Exception:
            raise ApiError(400, "Не удалось прочитать файл Excel")
    if low.endswith(".xls"):
        try:
            sh = xls.open_workbook(data).sheet(0)
        except Exception:
            raise ApiError(400, "Не удалось прочитать файл Excel")
        return [[sh.text(r, c) for c in range(sh.ncols)] for r in range(sh.nrows)]
    raise ApiError(400, "Загрузите таблицу .xlsx или .xls")


def parse_excel(rows):
    """Строки таблицы по шаблону → (вопросы, ошибки). Вопросы — в формате редактора."""
    head = None
    for i, r in enumerate(rows[:15]):
        cells = [str(c or "").strip().lower() for c in r]
        if "тип" in cells and "вопрос" in cells:
            head = i
            col = dict((c, j) for j, c in enumerate(cells))
            break
    need(head is not None, "В таблице нет строки заголовков «Тип» и «Вопрос» — используйте шаблон", 400)
    ans_cols = [j for c, j in sorted(col.items(), key=lambda x: x[1]) if c.startswith("ответ")]
    out, errors = [], []
    for i, r in enumerate(rows[head + 1:], head + 2):
        def cell(name):
            j = col.get(name)
            return str(r[j]).strip() if j is not None and j < len(r) and r[j] is not None else ""
        tname = cell("тип").lower()
        text = cell("вопрос")
        answers = [str(r[j]).strip() for j in ans_cols if j < len(r) and str(r[j] or "").strip()]
        if not tname and not text:
            continue
        qtype = TYPE_ALIASES.get(tname)
        if not qtype:
            errors.append({"line": i, "text": text[:80], "msg": "Неизвестный тип «%s»" % tname})
            continue
        try:
            body, answer = _excel_question(qtype, text, answers)
        except ValueError as e:
            errors.append({"line": i, "text": text[:80], "msg": str(e)})
            continue
        pts = cell("баллы").replace(",", ".")
        task = cell("задание")
        var = cell("вариант")
        img = cell("картинка")
        out.append({"type": qtype, "text": body.get("text", text), "body": body, "answer": answer, "line": i,
                    "images": [x.strip() for x in re.split(r"[;,]", img) if x.strip()],
                    "points": float(pts) if re.match(r"^\d+(\.\d+)?$", pts) else None,
                    "task": int(float(task)) if re.match(r"^\d+(\.0)?$", task) else 1,
                    "variant": int(float(var)) if re.match(r"^\d+(\.0)?$", var) else 0})
    return out, errors


def _excel_question(qtype, text, answers):
    body, answer = {"text": text}, {}
    if qtype in ("single", "multi"):
        body["options"], answer["correct"] = [], []
        for i, a in enumerate(answers):
            ok = a.startswith("+")
            body["options"].append({"id": str(i), "text": a[1:].strip() if ok else a})
            if ok:
                answer["correct"].append(str(i))
        if not answer["correct"]:
            raise ValueError("Не отмечен верный ответ (+)")
        if qtype == "single" and len(answer["correct"]) > 1:
            raise ValueError("В вопросе с одним ответом отмечено несколько верных")
    elif qtype == "short":
        body["fields"], answer["fields"] = [], {}
        for i, a in enumerate(answers or []):
            m = re.match(r"^([^:]{1,60}):\s*(.+)$", a) if len(answers) > 1 else None
            label, val = (m.group(1).strip(), m.group(2)) if m else ("", a)
            body["fields"].append({"id": str(i), "label": label})
            answer["fields"][str(i)] = [v.strip() for v in val.split(";") if v.strip()]
        if not answers:
            raise ValueError("Укажите правильный ответ")
    elif qtype == "order":
        body["items"] = [{"id": str(i), "text": a} for i, a in enumerate(answers)]
    elif qtype == "chrono":
        ev = []
        for i, a in enumerate(answers):
            if "|" in a:
                dt, tx = a.split("|", 1)
                ev.append({"id": str(i), "text": tx.strip(), "date": dt.strip()})
            else:
                ev.append({"id": str(i), "text": a})
        body["events"] = ev
    elif qtype == "match":
        body["left"], body["right"], answer["pairs"] = [], [], {}
        for i, a in enumerate(answers):
            if "=" not in a:
                raise ValueError("Пара «%s» должна быть записана через «=»" % a)
            l, r = a.split("=", 1)
            body["left"].append({"id": "l%d" % i, "text": l.strip()})
            body["right"].append({"id": "r%d" % i, "text": r.strip()})
            answer["pairs"]["l%d" % i] = "r%d" % i
    elif qtype == "cloze":
        blanks, acc = [], {}
        n = [0]

        def repl(m):
            n[0] += 1
            k = "b%d" % n[0]
            parts = [p.strip() for p in m.group(1).split("|") if p.strip()]
            if len(parts) > 1:
                blanks.append({"id": k, "kind": "select", "choices": parts})
                acc[k] = [parts[0]]
            else:
                blanks.append({"id": k, "kind": "input"})
                acc[k] = [v.strip() for v in parts[0].split(";")] if parts else []
            return "{{%s}}" % k
        body["text"] = re.sub(r"\[([^\[\]]+)\]", repl, text)
        body["blanks"] = blanks
        answer["blanks"] = acc
    elif qtype == "likert":
        body["statements"] = [{"id": str(i), "text": a} for i, a in enumerate(answers)]
    elif qtype == "essay":
        answer["sample"] = answers[0] if answers else ""
    elif qtype == "file":
        body["accept"] = answers[0] if answers else ""
    return body, answer


@router.route("POST", "/api/import/excel")
def api_import_excel(req):
    d = req.json()
    files = _decode_upload(d)
    tables = [(n, b) for n, b in files if n.lower().endswith((".xlsx", ".xls"))]
    need(tables, "Загрузите таблицу .xlsx или .xls", 400)
    _t, images = _media_from_files(files)
    qs, errors = parse_excel(_read_table(*tables[0]))
    _tr(errors, req.lang)
    if not d.get("commit"):
        prev = []
        for q in qs:
            prev.append({"type": q["type"], "type_name": G.TYPE_NAMES[q["type"]], "text": q["text"], "line": q["line"],
                         "task": q["task"], "variant": q["variant"], "points": q["points"], "images": q["images"],
                         "missing": [n for n in q["images"] if n.lower() not in images]})
        return {"questions": prev, "errors": errors}
    need(qs, "Не удалось распознать ни одного вопроса", 400)
    if d.get("test_id"):
        tid = get_test(d["test_id"], req, write=True)["id"]
    else:
        title = (d.get("title") or "").strip() or os.path.splitext(tables[0][0])[0]
        tid = db().insert("tests", {"owner_id": req.user["id"], "title": title[:300], "subject": (d.get("subject") or "").strip(),
                                    "settings": json.dumps(E.DEFAULT_SETTINGS, ensure_ascii=False)})
    # задания по номерам из таблицы
    have = dict((k["num"], k["id"]) for k in db().q("SELECT id, num FROM tasks WHERE test_id=?", (tid,)))
    for n in sorted(set(q["task"] for q in qs)):
        if n not in have:
            have[n] = db().insert("tasks", {"test_id": tid, "num": n, "title": ""})
    for q in qs:
        q["_task"] = have[q["task"]]
    if not have:
        db().insert("tasks", {"test_id": tid, "num": 1, "title": ""})
    added, problems = _save_parsed(tid, qs, images)
    touch(tid)
    db().audit(req.user, req.ip, "test_import_excel", {"test": tid, "questions": added})
    return {"test_id": tid, "added": added, "errors": _tr(errors + problems, req.lang)}


@router.route("POST", "/api/import/test")
def api_import_test_file(req):
    d = req.json()
    files = _decode_upload(d)
    need(files, "Выберите файл", 400)
    name, data = files[0]
    low = name.lower()
    if low.endswith((".xlsx", ".xls")):
        return api_import_excel(req)
    if low.endswith((".txt", ".zip")) and not low.endswith(FILE_EXT):
        return api_import_text(req)
    doc = read_test_file(data)
    tid, errors = import_test_doc(doc, req.user["id"])
    db().audit(req.user, req.ip, "test_import", doc.get("test", {}).get("title"))
    return {"test_id": tid, "errors": errors}
