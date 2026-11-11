# -*- coding: utf-8 -*-
"""Проверка ответов и перевод результата в отметку.

Типы вопросов:
  single   — один верный ответ          multi   — несколько верных ответов
  short    — короткий ответ (одно или несколько полей)
  match    — соответствие               order   — порядок
  chrono   — хронологическая рулетка (события на линии времени: что раньше, что позже)
  cloze    — пропуски в тексте (ввод или выбор слова)
  likert   — шкала Ликерта (опрос, не оценивается)
  essay    — развёрнутый ответ (проверяет учитель)
  file     — практическое задание с файлом (проверяет учитель)

Шкалы:
  percent — по проценту выполнения (по умолчанию 95 % → 10, 85 % → 9 … < 15 % → 1);
  norms   — по нормам оценки результатов учебной деятельности (методические
            указания Министерства образования Республики Беларусь от 15.09.2022).
"""
import re

TYPES = ["single", "multi", "short", "match", "order", "chrono", "cloze", "likert", "essay", "file", "code", "psy"]
AUTO_TYPES = {"single", "multi", "short", "match", "order", "chrono", "cloze", "code"}
MANUAL_TYPES = {"essay", "file"}
UNSCORED_TYPES = {"likert", "psy"}
PAPER_UNSUPPORTED = {"file", "code", "psy"}   # и вопросы со звуком


def is_manual(q):
    """Проверяет учитель: развёрнутый ответ, файл, задача с кодом в режиме ручной проверки."""
    return q["type"] in MANUAL_TYPES or (q["type"] == "code" and bool((q.get("answer") or {}).get("manual")))

TYPE_NAMES = {
    "single": "Один верный ответ", "multi": "Несколько верных ответов", "short": "Короткий ответ",
    "match": "Соответствие", "order": "Порядок", "chrono": "Хронологическая рулетка",
    "cloze": "Пропуски в тексте", "likert": "Шкала Ликерта (опрос)", "essay": "Развёрнутый ответ",
    "file": "Практическое задание с файлом", "code": "Код (программирование)",
    "psy": "Вопрос методики",
}

PERCENT_DEFAULT = [[95, 10], [85, 9], [75, 8], [65, 7], [55, 6], [45, 5], [35, 4], [25, 3], [15, 2], [0, 1]]

# Таблицы из методических указаний (2022). Пороги — нижняя граница диапазона.
NORMS = {
    "test_lang": {
        "name": "Тестовая работа — по проценту (белорусский и русский язык, V–XI классы)",
        "kind": "percent", "q_points": 2,
        "table": [[96, 10], [89, 9], [78, 8], [67, 7], [55, 6], [44, 5], [33, 4], [22, 3], [11, 2], [0, 1]],
        "note": "Каждое задание — 2 балла; частично верный ответ (не более одной ошибки) — 1 балл. "
                "Процент выполнения переводится в отметку по таблице.",
    },
    "complex_text": {
        "name": "Комплексная работа с текстом — по проценту (литературное чтение, I ступень)",
        "kind": "percent",
        "type_points": {"single": 1, "multi": 2, "short": 2, "cloze": 2, "match": 2, "order": 2, "chrono": 2,
                        "essay": 3, "file": 3},
        "table": [[100, 10], [90, 9], [80, 8], [70, 7], [60, 6], [50, 5], [40, 4], [30, 3], [20, 2], [0, 1]],
        "note": "Выбор одного ответа — 1 балл, нескольких — 2, краткий ответ — 2, развёрнутый — 3; "
                "за ответ с ошибками максимальный балл уменьшается.",
    },
    "five_general": {
        "name": "Работа из 5 заданий уровней I–V (II–III ступени; «Человек и мир», I ступень)",
        "kind": "tasks", "task_points": [2, 4, 6, 8, 10], "levels": [1, 2, 3, 4, 5],
        "table": [[29, 10], [24, 9], [19, 8], [15, 7], [12, 6], [9, 5], [6, 4], [3, 3], [2, 2], [1, 1]],
        "note": "Максимальные баллы за задания: 2, 4, 6, 8, 10 (всего 30).",
    },
    "five_math1": {
        "name": "Работа из 5 заданий уровней I–V (математика, I ступень)",
        "kind": "tasks", "task_points": [2, 4, 6, 8, 10], "levels": [1, 2, 3, 4, 5],
        "table": [[29, 10], [26, 9], [19, 8], [15, 7], [12, 6], [9, 5], [6, 4], [3, 3], [2, 2], [1, 1]],
        "note": "Максимальные баллы за задания: 2, 4, 6, 8, 10 (всего 30).",
    },
    "five_lang1": {
        "name": "Тестовая контрольная работа из 5 заданий (белорусский и русский язык, I ступень)",
        "kind": "tasks", "task_points": [2, 4, 6, 8, 10], "levels": [1, 2, 3, 4, 5],
        "table": [[29, 10], [26, 9], [22, 8], [17, 7], [12, 6], [9, 5], [6, 4], [3, 3], [2, 2], [1, 1]],
        "note": "Максимальные баллы за задания: 2, 4, 6, 8, 10 (всего 30).",
    },
    "combined_lang1": {
        "name": "Комбинированная работа (белорусский и русский язык, I ступень)",
        "kind": "tasks", "task_points": [4, 4, 4, 8, 10], "levels": [3, 3, 3, 4, 5],
        "table": [[29, 10], [26, 9], [22, 8], [17, 7], [12, 6], [9, 5], [6, 4], [3, 3], [2, 2], [1, 1]],
        "note": "Задания уровней III, III, III, IV, V: 4, 4, 4, 8, 10 баллов (всего 30).",
    },
    "ten": {
        "name": "Работа из 10 заданий (математика, физика, химия, биология, информатика, география и др.)",
        "kind": "tasks", "task_points": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10], "levels": None,
        "table": [[53, 10], [43, 9], [34, 8], [26, 7], [19, 6], [13, 5], [8, 4], [5, 3], [2, 2], [1, 1]],
        "note": "Максимальные баллы за задания: 1, 2, 3 … 10 (всего 55).",
    },
}

RESULT_KINDS = {"mark": "Отметка 1–10", "passfail": "Сдал / не сдал", "percent": "Процент выполнения",
                "credit": "Зачёт / незачёт"}


def round_half_up(x):
    return int(x + 0.5) if x >= 0 else -int(-x + 0.5)


# ---------------------------------------------------------------- нормализация ответов

_NUM = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")


def norm_text(s):
    s = str(s if s is not None else "").replace("ё", "е").replace("Ё", "Е")
    s = s.replace(" ", " ").replace("−", "-").replace("–", "-")
    s = re.sub(r"\s+", " ", s).strip().lower()
    s = s.rstrip(".")
    return s


def same_answer(given, accepted, tol=0.0):
    g = norm_text(given)
    if not g:
        return False
    for a in accepted or []:
        an = norm_text(a)
        if g == an:
            return True
        if _NUM.match(g) and _NUM.match(an):
            try:
                if abs(float(g.replace(",", ".")) - float(an.replace(",", "."))) <= (tol or 1e-9):
                    return True
            except ValueError:
                pass
    return False


# ---------------------------------------------------------------- проверка одного вопроса

def check(q, response):
    """Возвращает {"frac": 0..1, "errors": n, "parts": m} или None (не проверяется автоматически).
    frac — доля верного; errors — число ошибок (для правил частичного балла по нормам);
    parts — из скольких элементов состоит ответ."""
    t = q["type"]
    a = q.get("answer") or {}
    b = q.get("body") or {}
    r = response or {}
    if t in MANUAL_TYPES or t in UNSCORED_TYPES:
        return None
    if t == "code":
        # доля баллов лучшей посылки; подставляется сервером из таблицы посылок (attempts.regrade)
        if a.get("manual"):
            return None
        f = r.get("judged") if isinstance(r, dict) else None
        f = max(0.0, min(1.0, float(f or 0)))
        return {"frac": f, "errors": 0 if f >= 1 else 1, "parts": 1}
    if t == "single":
        ok = r.get("choice") is not None and str(r.get("choice")) in [str(x) for x in a.get("correct", [])]
        return {"frac": 1.0 if ok else 0.0, "errors": 0 if ok else 1, "parts": 1}
    if t == "multi":
        C = set(str(x) for x in a.get("correct", []))
        S = set(str(x) for x in (r.get("choices") or []))
        wrong, missed = len(S - C), len(C - S)
        mode = a.get("partial", "norms")
        if not S:
            return {"frac": 0.0, "errors": len(C), "parts": max(len(C), 1)}
        if wrong == 0 and missed == 0:
            frac = 1.0
        elif mode == "none":
            frac = 0.0
        elif mode == "proportional":
            frac = max(0.0, (len(S & C) - wrong) / float(len(C) or 1))
        else:   # norms: частично верный — не более одной ошибки
            frac = 0.5 if (wrong + missed == 1) else 0.0
        return {"frac": frac, "errors": wrong + missed, "parts": max(len(C), 2)}
    if t == "short":
        fields = b.get("fields") or [{"id": "1"}]
        acc = a.get("fields") or {}
        given = r.get("fields") or {}
        good = sum(1 for f in fields if same_answer(given.get(str(f["id"])), acc.get(str(f["id"])), a.get("tol", 0)))
        n = len(fields)
        return {"frac": good / float(n), "errors": n - good, "parts": n}
    if t == "match":
        pairs = a.get("pairs") or {}
        given = r.get("pairs") or {}
        n = len(pairs) or 1
        good = sum(1 for k, v in pairs.items() if str(given.get(str(k))) == str(v))
        frac = good / float(n)
        if not a.get("partial", True) and good < n:
            frac = 0.0
        return {"frac": frac, "errors": n - good, "parts": n}
    if t in ("order", "chrono"):
        right = [str(x) for x in a.get("order") or []]
        given = [str(x) for x in r.get("order") or []]
        n = len(right) or 1
        if given == right:
            return {"frac": 1.0, "errors": 0, "parts": n}
        mode = a.get("partial", "none")
        if mode == "positions":
            good = sum(1 for i, x in enumerate(right) if i < len(given) and given[i] == x)
            frac = good / float(n)
        elif mode == "pairs":
            # доля соседних пар верного ряда, стоящих в ответе в правильном порядке
            pos = dict((x, i) for i, x in enumerate(given))
            pairs = list(zip(right, right[1:]))
            good = sum(1 for x, y in pairs if x in pos and y in pos and pos[x] < pos[y])
            frac = good / float(len(pairs) or 1)
        else:
            frac = 0.0
        wrong = sum(1 for i, x in enumerate(right) if i >= len(given) or given[i] != x)
        return {"frac": frac, "errors": max(wrong, 1), "parts": n}
    if t == "cloze":
        blanks = b.get("blanks") or []
        acc = a.get("blanks") or {}
        given = r.get("blanks") or {}
        n = len(blanks) or 1
        good = sum(1 for bl in blanks if same_answer(given.get(str(bl["id"])), acc.get(str(bl["id"]))))
        return {"frac": good / float(n), "errors": n - good, "parts": n}
    return None


def is_answered(q, response):
    r = response or {}
    t = q["type"]
    if t == "single":
        return r.get("choice") not in (None, "")
    if t == "multi":
        return bool(r.get("choices"))
    if t == "short":
        return any(str(v).strip() for v in (r.get("fields") or {}).values())
    if t == "match":
        return any(v not in (None, "") for v in (r.get("pairs") or {}).values())
    if t in ("order", "chrono"):
        return bool(r.get("order")) and bool(r.get("touched", True))
    if t == "cloze":
        return any(str(v).strip() for v in (r.get("blanks") or {}).values())
    if t == "likert":
        return bool(r.get("values"))
    if t == "essay":
        return bool(str(r.get("text") or "").strip())
    if t == "file":
        return bool(r.get("file_id"))
    if t == "code":
        return bool(r.get("subs"))
    if t == "psy":
        return r.get("choice") not in (None, "")
    return False


# ---------------------------------------------------------------- баллы за вопрос по шкале

def question_points(q, scale):
    """Максимальный балл вопроса с учётом шкалы."""
    if q["type"] in UNSCORED_TYPES:
        return 0.0
    if scale.get("mode") == "norms":
        n = NORMS.get(scale.get("norm"))
        if n and n.get("q_points"):
            return float(n["q_points"])
        if n and n.get("type_points"):
            return float(n["type_points"].get(q["type"], 2))
    return float(q.get("points") or 1)


def award(q, res, maxp, scale):
    """Баллы за вопрос по результату проверки res (из check) и правилам шкалы."""
    if res is None:
        return None
    frac, errors, parts = res["frac"], res["errors"], res["parts"]
    norm = NORMS.get(scale.get("norm")) if scale.get("mode") == "norms" else None
    if norm and norm.get("q_points"):           # тестовая работа: 2 / 1 / 0
        if frac >= 1:
            return maxp
        if parts > 1 and errors == 1:
            return maxp / 2.0
        return 0.0
    if norm and norm.get("type_points"):        # комплексная работа: максимум уменьшается за ошибки
        if frac >= 1:
            return maxp
        if frac <= 0:
            return 0.0
        if maxp <= 1:
            return 0.0
        if maxp == 2:
            return 1.0
        return float(min(maxp - 1, max(1, round_half_up(frac * maxp))))
    return round(frac * maxp, 2)


# ---------------------------------------------------------------- отметка

def mark_from_table(value, table):
    for lo, mark in table:
        if value >= lo:
            return mark
    return table[-1][1] if table else 1


def norm_tasks_info(scale):
    n = NORMS.get(scale.get("norm"))
    return n if n and n["kind"] == "tasks" else None


def evaluate(items, scale, result_kind="mark", pass_percent=60):
    """Итог попытки.

    items — список словарей {task_num, maxp, got (баллы или None, если ещё не проверено),
            scored (bool — учитывается ли вопрос)}.
    Возвращает {score, max_score, percent, mark, pending}."""
    pending = any(it["scored"] and it["got"] is None for it in items)
    scored = [it for it in items if it["scored"]]
    tn = norm_tasks_info(scale)
    if tn:
        tp = tn["task_points"]
        by_task = {}
        for it in scored:
            by_task.setdefault(it["task_num"], []).append(it)
        total = 0.0
        for i, pts in enumerate(tp, start=1):
            qs = by_task.get(i, [])
            mx = sum(x["maxp"] for x in qs)
            got = sum((x["got"] or 0) for x in qs)
            total += pts * (got / mx) if mx else 0.0
        score = round_half_up(total)
        max_score = sum(tp)
        percent = 100.0 * score / max_score if max_score else 0.0
        mark = mark_from_table(score, tn["table"]) if score >= 1 else 1
    else:
        max_score = sum(x["maxp"] for x in scored)
        score = sum((x["got"] or 0) for x in scored)
        percent = 100.0 * score / max_score if max_score else 0.0
        if scale.get("mode") == "norms" and scale.get("norm") in NORMS:
            mark = mark_from_table(round_half_up(percent), NORMS[scale["norm"]]["table"])
        else:
            table = scale.get("thresholds") or PERCENT_DEFAULT
            mark = mark_from_table(percent + 1e-9, sorted(table, key=lambda x: -x[0]))
        score = round(score, 2)
    result = str(mark)
    if not scored:                      # только опросы — оценивать нечего
        return {"score": 0, "max_score": 0, "percent": None, "mark": None, "pending": False}
    if result_kind == "passfail":
        result = "сдал" if percent + 1e-9 >= pass_percent else "не сдал"
    elif result_kind == "credit":
        result = "зачтено" if percent + 1e-9 >= pass_percent else "не зачтено"
    elif result_kind == "percent":
        result = "%d %%" % round_half_up(percent)
    return {"score": score, "max_score": max_score, "percent": round(percent, 1),
            "mark": None if pending else result, "pending": pending}


def validate_scale(scale, task_nums):
    """Предупреждения о несоответствии теста выбранной шкале по нормам."""
    warn = []
    tn = norm_tasks_info(scale)
    if tn:
        need = len(tn["task_points"])
        if len(task_nums) != need:
            warn.append("Для шкалы «%s» в тесте должно быть %d заданий, сейчас — %d." % (tn["name"], need, len(task_nums)))
    if scale.get("mode") == "percent":
        th = scale.get("thresholds") or PERCENT_DEFAULT
        marks = [m for _p, m in th]
        if sorted(marks, reverse=True) != [m for _p, m in sorted(th, key=lambda x: -x[0])]:
            warn.append("Пороги шкалы должны убывать вместе с отметками.")
    return warn
