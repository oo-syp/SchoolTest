# -*- coding: utf-8 -*-
"""ШТУР-2 — школьный тест умственного развития, версия 2.0.

Восемь субтестов с отдельным временем на каждый, две параллельные формы (А и Б).
Субтесты 1–4 и 7–8 проверяются по ключу, субтест 6 — по числу, субтест 5 «Обобщения»
оценивается 2, 1 или 0 баллами по таблице возможных ответов (психолог может поправить оценку).

Источник: Логинова Г. П. Диагностика умственного развития детей подросткового возраста. — М.: МГППУ, 2002.
"""
import re

from . import shtur_data as D

LETTERS = ["а", "б", "в", "г", "д"]
ABC = {"а": "А", "б": "Б", "в": "В", "г": "Г", "д": "Д"}
MAX_TOTAL = 148          # 20 + 20 + 25 + 20 + 38 + 15 + 5 + 5
SUB_MAX = {1: 20, 2: 20, 3: 25, 4: 20, 5: 38, 6: 15, 7: 5, 8: 5}
CYCLE_MAX = {"hum": 33, "nat": 31, "phm": 19}
# уровень умственного развития по классу: (ниже — низкий, выше — высокий)
GRADE_LEVELS = {7: (21, 54), 8: (28, 65), 9: (32, 72), 10: (36, 80), 11: (36, 80)}

METHODS = {
    "shtur": {
        "name": "ШТУР-2 — школьный тест умственного развития", "short": "ШТУР-2",
        "author": "К. М. Гуревич, М. К. Акимова, Е. М. Борисова, В. Г. Зархин, В. Т. Козлова, Г. П. Логинова",
        "block": "Умственное развитие", "kind": "ind",
        "audience": "Учащиеся 12–15 лет (7–9 классы); шкала оценки дополнена данными для 10 класса",
        "purpose": "Диагностика умственного развития подростка относительно социально-психологического норматива: "
                   "осведомлённость, аналогии, классификации, обобщения, числовые ряды и пространственные "
                   "представления; выявление сильных и слабых сторон и предпочитаемого цикла знаний.",
        "instruction": "Сейчас вам будут предложены задания, которые предназначены для того, чтобы выявить ваши умения "
                       "рассуждать, сравнивать предметы и явления окружающего мира, находить в них общее и различное. "
                       "Вы будете выполнять разные наборы заданий. Перед каждым набором даётся описание заданий и "
                       "примеры. На каждый набор отводится ограниченное время. Все задания решайте строго по порядку, "
                       "не задерживайтесь слишком долго на одном задании. Старайтесь работать быстро и без ошибок.",
        "count": 129, "answers": "Выбор варианта, число или короткий ответ — в зависимости от субтеста",
        "ask": [], "show_default": "none", "timed": True,
        "note": "Тест групповой и жёстко регламентирован по времени: 54 минуты на восемь субтестов. Вернуться к "
                "предыдущему субтесту нельзя. Две формы (А и Б) параллельны: вторую удобно использовать при "
                "повторном обследовании. Субтест «Обобщения» оценивается 0, 1 или 2 баллами; программа подставляет "
                "оценку по таблице возможных ответов, а психолог проверяет и при необходимости меняет её.",
    },
}
ORDER = ["shtur"]


def form_of(settings):
    f = (settings or {}).get("form")
    return f if f in D.FORMS else "А"


def sections(settings=None):
    out = []
    timed = bool((settings or {}).get("timed", True))
    for num, name, a, b, mins in D.SUBTESTS:
        instr, examples = D.INSTR[num]
        out.append({"num": num, "title": "Субтест %d. %s" % (num, name), "from": a, "to": b,
                    "minutes": mins if timed else 0, "instruction": instr, "examples": examples,
                    "count": b - a + 1})
    return out


def questions(mid, settings=None):
    form = form_of(settings)
    qs = []
    for num, name, a, b, mins in D.SUBTESTS:
        for n in range(a, b + 1):
            t = D.TASKS[form][n]
            q = {"section": num, "text": t.get("text") or ""}
            opts = t.get("options") or []
            if num in (7, 8):
                q["options"] = [{"id": LETTERS[i], "text": ABC[LETTERS[i]]} for i in range(len(opts))]
                q["image"] = "/psy/shtur/%s.png" % t["image"]
            elif opts:
                q["options"] = [{"id": LETTERS[i], "text": opts[i]} for i in range(len(opts))]
            else:
                q["options"] = []
                q["input"] = "number" if num == 6 else "text"
                q["hint"] = "Следующее число ряда" if num == 6 else "Что общего между этими понятиями?"
            if num == 2:
                q["text"] = t.get("text") or ""
                q["hint"] = "Подберите слово, близкое по смыслу"
            if num == 4:
                q["hint"] = "Найдите лишнее слово"
            qs.append(q)
    return qs


# ---------------------------------------------------------------- субтест 5
_PUNCT = re.compile(r"[^0-9a-zа-я ]+")
_LEAD = re.compile(r"^(это|эти|они|общее|общее[—–-]? это)\s+")


def norm(s):
    s = (s or "").lower().replace("ё", "е")
    s = _PUNCT.sub(" ", s)
    s = " ".join(s.split())
    s = _LEAD.sub("", s)
    return s.strip()


def gen_score(form, num, text):
    """Оценка ответа субтеста 5: (балл, распознано ли автоматически)."""
    table = D.GENERALIZE[form].get(num) or {}
    t = norm(text)
    if not t:
        return 0, True
    for k in ("2", "1"):
        for phrase in table.get(k) or []:
            p = norm(phrase)
            if not p:
                continue
            if t == p or (len(p) >= 7 and p in t) or (len(t) >= 7 and t in p):
                return int(k), True
    for phrase in table.get("0") or []:
        p = norm(phrase)
        if p and t == p:
            return 0, True
    return 0, False


def _num(s):
    s = (s or "").strip().replace(",", ".").replace(" ", "")
    m = re.match(r"^[-+]?\d+(\.\d+)?$", s)
    if not m:
        return None
    v = float(s)
    return int(v) if v == int(v) else v


def score(mid, choices, texts, settings, extra=None, manual=None):
    settings = settings or {}
    manual = manual or {}
    form = form_of(settings)
    key = D.KEY[form]
    res = {"method": mid, "form": form, "total": 129, "scales": [], "text": [], "warnings": []}
    per = {}
    right = {}
    pending = []
    details5 = []
    answered = 0
    for num, name, a, b, mins in D.SUBTESTS:
        pts = 0
        for n in range(a, b + 1):
            if num == 5:
                ans = texts.get(n)
                if ans:
                    answered += 1
                auto, sure = gen_score(form, n, ans)
                mv = manual.get(n)
                val = int(mv) if mv is not None else auto
                val = max(0, min(2, val))
                right[n] = val
                pts += val
                if not sure and mv is None and ans:
                    pending.append(n)
                details5.append({"num": n, "task": D.TASKS[form][n]["text"], "answer": ans or "",
                                 "auto": auto, "manual": (int(mv) if mv is not None else None), "value": val,
                                 "sure": sure, "ref": D.GENERALIZE[form][n]})
            elif num == 6:
                ans = texts.get(n)
                if ans:
                    answered += 1
                ok = _num(ans) is not None and _num(ans) == _num(key.get(n))
                right[n] = 1 if ok else 0
                pts += right[n]
            else:
                ans = choices.get(n)
                if ans:
                    answered += 1
                ok = bool(ans) and str(ans) == str(key.get(n))
                right[n] = 1 if ok else 0
                pts += right[n]
        per[num] = pts
        pc = round(100.0 * pts / SUB_MAX[num], 1)
        res["scales"].append({"id": "s%d" % num, "name": "%d. %s" % (num, name), "value": pc, "min": 0, "max": 100,
                              "raw": pts, "raw_max": SUB_MAX[num], "level": "%d из %d" % (pts, SUB_MAX[num])})
    total = sum(per.values())
    pct = round(100.0 * total / MAX_TOTAL, 1)
    grade = 0
    try:
        grade = int(settings.get("grade") or 0)
    except (TypeError, ValueError):
        grade = 0
    lo, hi = GRADE_LEVELS.get(grade, (0, 0))
    if lo:
        lvl = "низкое" if pct < lo else ("относительно высокое" if pct > hi else "среднее")
        lvl_txt = "%s умственное развитие для %d класса (низкое — ниже %d %%, относительно высокое — выше %d %%)" % (
            lvl[0].upper() + lvl[1:], grade, lo, hi)
    else:
        lvl = ""
        lvl_txt = "Класс не указан, поэтому уровень по образовательно-возрастной шкале не определён."
    res["answered"] = answered
    res["raw"] = total
    res["max"] = MAX_TOTAL
    res["percent"] = pct
    res["per_sub"] = per
    res["level"] = lvl
    res["grade"] = grade
    res["details5"] = details5
    res["pending5"] = pending
    res["summary"] = "Выполнено %s %% теста (%d из %d баллов)%s" % (
        str(pct).replace(".", ","), total, MAX_TOTAL, (", " + lvl + " умственное развитие") if lvl else "")

    # циклы знаний
    cyc = []
    for cid in ("hum", "nat", "phm"):
        nums = D.CYCLES[form][cid]
        v = sum(right.get(n, 0) for n in nums)
        mx = CYCLE_MAX[cid]
        cyc.append({"id": cid, "name": D.CYCLE_NAMES[cid], "value": v, "max": mx, "percent": round(100.0 * v / mx, 1)})
    space = sum(right.get(n, 0) for n in range(120, 130))
    cyc.append({"id": "space", "name": "Пространственные представления", "value": space, "max": 10,
                "percent": round(100.0 * space / 10, 1)})
    aware = per[1] + per[2]
    cyc.append({"id": "hum_all", "name": "Общественно-гуманитарный с осведомлённостью", "value": cyc[0]["value"] + aware,
                "max": 73, "percent": round(100.0 * (cyc[0]["value"] + aware) / 73, 1)})
    cyc.append({"id": "phm_all", "name": "Физико-математический с числовыми рядами", "value": cyc[2]["value"] + per[6],
                "max": 34, "percent": round(100.0 * (cyc[2]["value"] + per[6]) / 34, 1)})
    res["cycles"] = cyc

    best = max(res["scales"], key=lambda s: s["value"])
    worst = min(res["scales"], key=lambda s: s["value"])
    res["text"].append({"title": "Уровень умственного развития", "body": lvl_txt +
                        " Общий балл теста принимается за норматив умственного развития: 148 баллов — это 100 %%, "
                        "с ними сравнивается число реально выполненных заданий."})
    if best["value"] != worst["value"]:
        res["text"].append({"title": "Структура умственного развития", "body":
            "Лучше всего выполнен субтест «%s» (%s %%), хуже всего — «%s» (%s %%). Сравнение субтестов на "
            "осведомлённость с субтестами на аналогии, классификации и обобщения показывает, что развито лучше — "
            "запас сведений или умение логически их обрабатывать; сравнение вербальных субтестов с субтестами 7 и 8 — "
            "соотношение словесного и пространственного мышления." %
            (best["name"], str(best["value"]).replace(".", ","), worst["name"], str(worst["value"]).replace(".", ","))})
    cbest = max(cyc[:3], key=lambda c: c["percent"])
    res["text"].append({"title": "Циклы знаний", "body":
        "Общественно-гуманитарный — %s %%, естественнонаучный — %s %%, физико-математический — %s %%, "
        "пространственные представления — %s %%. Выше других выполнен %s цикл; за этим может стоять как склонность "
        "к этой области знаний, так и предшествующая подготовка вне школы или влияние педагога." %
        tuple([str(c["percent"]).replace(".", ",") for c in cyc[:4]] + [cbest["name"].lower()])})
    res["text"].append({"title": "Как читать результат", "body":
        "Баллы субтестов переводятся в проценты от максимума субтеста, поэтому их можно сравнивать между собой. "
        "Субтест «Обобщения» оценивается 0, 1 или 2 баллами: 2 балла — обобщение по родовому признаку с указанием "
        "видового отличия, 1 балл — только родовое или только видовое обобщение, 0 — неправильный ответ. "
        "Глобальные оценки «лучше — хуже» мало что дают: важнее анализ того, какие субтесты и какие циклы знаний "
        "выполнены успешнее, и сравнение результата с результатами класса."})
    if pending:
        res["warnings"].append("Ответов субтеста «Обобщения», которые программа не нашла в таблице возможных ответов: "
                               "%d (задания %s). Проверьте их и при необходимости поставьте балл сами." %
                               (len(pending), ", ".join(str(x) for x in pending)))
    if answered < 100:
        res["warnings"].append("Выполнено только %d заданий из 129: вероятно, не хватило времени или обследование "
                               "прервано." % answered)
    res["chart"] = "bars"
    return res


def headers(mid):
    return ["1", "2", "3", "4", "5", "6", "7", "8", "Балл", "%", "Уровень"]


def values(res):
    per = res.get("per_sub") or {}
    return [per.get(i, "") for i in range(1, 9)] + [res.get("raw", ""), res.get("percent", ""), res.get("level", "")]


def short(res):
    return [str(res.get("percent", "")) + " %"]


def summary(mid, results):
    out, n = [], len(results)
    if not n:
        return out
    for i, (num, name, a, b, mins) in enumerate(D.SUBTESTS):
        vals = [s["value"] for r in results for s in r["scales"] if s["id"] == "s%d" % num]
        out.append({"name": "%d. %s, %%" % (num, name), "avg": round(sum(vals) / float(n), 1), "max": 100})
    pcts = [r.get("percent", 0) for r in results]
    out.append({"name": "Выполнение теста в целом, %", "avg": round(sum(pcts) / float(n), 1), "max": 100})
    for cid in ("hum", "nat", "phm", "space"):
        vals = [c["percent"] for r in results for c in (r.get("cycles") or []) if c["id"] == cid]
        if vals:
            nm = D.CYCLE_NAMES.get(cid, "Пространственные представления")
            out.append({"name": nm + ", %", "avg": round(sum(vals) / float(n), 1), "max": 100})
    for lv in ("низкое", "среднее", "относительно высокое"):
        out.append({"name": "Умственное развитие: " + lv, "count": sum(1 for r in results if r.get("level") == lv)})
    # подгруппы по приближению к нормативу (10 % / 20 % / 40 % / 20 % / 10 %)
    order = sorted(pcts, reverse=True)
    bounds, start = [], 0
    for share in (0.1, 0.2, 0.4, 0.2, 0.1):
        cnt = int(round(n * share))
        bounds.append(order[start:start + cnt])
        start += cnt
    if start < n:
        bounds[-1] += order[start:]
    names = ["1 — наиболее успешные (10 %)", "2 — близкие к успешным (20 %)", "3 — средние (40 %)",
             "4 — мало успешные (20 %)", "5 — наименее успешные (10 %)"]
    for nm, grp in zip(names, bounds):
        if grp:
            out.append({"name": "Подгруппа " + nm, "count": len(grp), "avg": round(sum(grp) / float(len(grp)), 1), "max": 100})
    return out


def key_rows(mid):
    rows = []
    for num, name, a, b, mins in D.SUBTESTS:
        rows.append({"name": "Субтест %d. %s" % (num, name),
                     "items": "задания %d–%d, %d мин, максимум %d баллов" % (a, b, mins, SUB_MAX[num])})
    rows.append({"name": "Всего", "items": "129 заданий, 54 минуты, максимум 148 баллов"})
    for f in D.FORMS:
        rows.append({"name": "Ответы формы %s, задания 1–85" % f,
                     "items": "; ".join("%d — %s" % (n, D.KEY[f][n]) for n in range(1, 86))})
        rows.append({"name": "Ответы формы %s, задания 105–129" % f,
                     "items": "; ".join("%d — %s" % (n, D.KEY[f][n]) for n in range(105, 130))})
    rows.append({"name": "Уровень по классу", "items": "низкое умственное развитие: 7 кл. ниже 21 %, 8 кл. ниже 28 %, "
                                                       "9 кл. ниже 32 %, 10 кл. ниже 36 %; относительно высокое: "
                                                       "7 кл. выше 54 %, 8 кл. выше 65 %, 9 кл. выше 72 %, 10 кл. выше 80 %"})
    return rows
