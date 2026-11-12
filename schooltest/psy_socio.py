# -*- coding: utf-8 -*-
"""Социометрия: выбор одноклассников по критериям, социоматрица, статусы и индексы.

Методика групповая: индивидуальный результат — только сделанные выборы, выводы делаются
по классу в целом (социоматрица, статусные группы, взаимные выборы, микрогруппы, индексы).

Источники: школьный вариант социометрического теста (5–8 классы), список социометрических
критериев, Воронов Ю. С. «Социометрический метод исследования» (Смоленск, 2015) — индексы.
"""

# готовые критерии: (текст, знак) — «+» положительный выбор, «–» отрицательный
PRESET = [
    ("Кого из своих одноклассников ты пригласил бы на день рождения?", "pos", "эмоциональный лидер"),
    ("С кем из своих одноклассников ты пошёл бы в трудный поход?", "pos", "универсальный лидер"),
    ("С кем из своих одноклассников ты хотел бы работать, готовиться к чему-либо в паре?", "pos", "деловой лидер"),
    ("Если бы класс формировался заново, с кем бы ты хотел учиться вместе?", "pos", ""),
    ("Если бы класс формировался заново, с кем бы ты не хотел учиться вместе?", "neg", ""),
    ("Кого бы ты хотел выбрать старостой класса?", "pos", ""),
    ("Кого бы ты не хотел выбрать старостой класса?", "neg", ""),
    ("С кем из одноклассников тебе легко готовить общее дело?", "pos", ""),
    ("С кем из одноклассников тебе сложнее работать вместе?", "neg", ""),
    ("Кого из класса ты пригласил бы на встречу Нового года?", "pos", ""),
    ("Кого из класса ты не пригласил бы на встречу Нового года?", "neg", ""),
    ("Кого из одноклассников ты хотел бы видеть в составе вновь организованной группы?", "pos", ""),
    ("Кого из одноклассников ты не хотел бы видеть в составе вновь организованной группы?", "neg", ""),
    ("С кем из одноклассников тебя связывают дружеские отношения?", "pos", ""),
    ("Кто, по твоему мнению, выберет тебя?", "pos", "социальная рефлексия"),
    ("Кто, по твоему мнению, тебя не выберет?", "neg", "социальная рефлексия"),
]
DEFAULT = [0, 1, 2]

STATUS_ORDER = ["star", "pref", "acc", "half", "rej"]
STATUS_NAMES = {
    "star": "«Звёзды»", "pref": "«Предпочитаемые»", "acc": "«Принятые»",
    "half": "«Принято-непринятые»", "rej": "«Отвергнутые»",
}
STATUS_HELP = {
    "star": "лидеры с максимальным количеством выборов",
    "pref": "набрали половину или больше выборов от максимума",
    "acc": "имеют хотя бы один взаимный выбор",
    "half": "их выбирают, но сами они выбирают не тех, кто выбрал их",
    "rej": "не получили ни одного положительного выбора",
}

METHODS = {
    "socio": {
        "name": "Социометрия", "short": "Социометрия", "author": "Дж. Морено; школьный вариант",
        "block": "Отношения в коллективе", "kind": "group",
        "audience": "Учащиеся 5–11 классов; группа не менее 10 человек, существующая не менее года",
        "purpose": "Выявление социометрического статуса учащихся в коллективе, взаимных выборов и микрогрупп, "
                   "уровня сплочённости класса и социально-рефлексивных навыков учащихся.",
        "instruction": "Ответь, пожалуйста, на приведённые ниже вопросы. Постарайся быть искренним, иначе вся "
                       "работа потеряет смысл. Обещаем, что искренность не обернётся тебе во вред. "
                       "На каждый вопрос выбери из списка класса не более трёх одноклассников.",
        "count": 3, "answers": "Выбор одноклассников из списка класса", "ask": [], "show_default": "none",
        "criteria": PRESET, "default_criteria": DEFAULT,
        "note": "Результат — групповой: учащийся своих результатов не видит. Данные считаются достоверными, "
                "если опрос прошли почти все учащиеся класса: каждый неучаствующий искажает социоматрицу.",
    },
}
ORDER = ["socio"]


def criteria_of(settings):
    st = settings or {}
    cr = st.get("criteria")
    if not cr:
        cr = [{"text": PRESET[i][0], "sign": PRESET[i][1]} for i in DEFAULT]
    out = []
    for c in cr:
        if isinstance(c, dict) and (c.get("text") or "").strip():
            out.append({"text": c["text"].strip(), "sign": "neg" if c.get("sign") == "neg" else "pos"})
    return out or [{"text": PRESET[i][0], "sign": PRESET[i][1]} for i in DEFAULT]


def questions(mid, settings=None):
    st = settings or {}
    roster = st.get("roster") or []
    picks = int(st.get("picks") or 3)
    opts = [{"id": str(r["id"]), "text": r["name"]} for r in roster]
    qs = []
    for c in criteria_of(st):
        qs.append({"text": c["text"], "options": opts, "multi": True, "max": picks,
                   "hint": "Выберите не более %d одноклассников" % picks})
    return qs


def score(mid, multi, settings):
    """Индивидуальный результат — сделанные выборы; выводы строятся по классу."""
    cr = criteria_of(settings)
    picks = {}
    made_pos = made_neg = 0
    for i, c in enumerate(cr, 1):
        ids = multi.get(i) or []
        picks[str(i)] = ids
        if c["sign"] == "neg":
            made_neg += len(ids)
        else:
            made_pos += len(ids)
    res = {"method": mid, "answered": sum(1 for i in range(1, len(cr) + 1) if multi.get(i)), "total": len(cr),
           "scales": [], "text": [], "warnings": [], "picks": picks, "made_pos": made_pos, "made_neg": made_neg}
    res["summary"] = "Сделано выборов: %d положительных%s" % (
        made_pos, (", %d отрицательных" % made_neg) if made_neg else "")
    if res["answered"] < len(cr):
        res["warnings"].append("Отвечены не все вопросы (%d из %d)." % (res["answered"], len(cr)))
    res["chart"] = "none"
    return res


def headers(mid):
    return ["Отдано «+»", "Отдано «–»", "Получено «+»", "Получено «–»", "Взаимных «+»", "Статус"]


def values(res):
    """Заполняется в отчёте по классу; для одиночной попытки известны только отданные выборы."""
    g = res.get("group") or {}
    return [res.get("made_pos", 0), res.get("made_neg", 0), g.get("got_pos", ""), g.get("got_neg", ""),
            g.get("mutual_pos", ""), STATUS_NAMES.get(g.get("status"), "")]


def _fmt(x, digits=2):
    return round(x, digits)


def report(settings, people):
    """people — [{"id": sid, "name": фио, "res": результат или None}] в порядке списка класса.

    Возвращает социоматрицу, статусы, взаимные выборы, микрогруппы и индексы."""
    cr = criteria_of(settings)
    n = len(people)
    idx = dict((str(p["id"]), i) for i, p in enumerate(people))
    done = [bool(p.get("res")) for p in people]
    # матрица выборов: cell[i][j] = +1 / -1 / 0 (суммарно по всем критериям; «–» перебивает «+»)
    pos = [[0] * n for _ in range(n)]
    neg = [[0] * n for _ in range(n)]
    for i, p in enumerate(people):
        r = p.get("res") or {}
        picks = r.get("picks") or {}
        for k, ids in picks.items():
            try:
                c = cr[int(k) - 1]
            except (ValueError, IndexError):
                continue
            for sid in ids:
                j = idx.get(str(sid))
                if j is None or j == i:
                    continue
                if c["sign"] == "neg":
                    neg[i][j] += 1
                else:
                    pos[i][j] += 1
    cell = [[("-" if neg[i][j] else ("+" if pos[i][j] else "")) if i != j else "x" for j in range(n)] for i in range(n)]
    made_pos = [sum(1 for j in range(n) if cell[i][j] == "+") for i in range(n)]
    made_neg = [sum(1 for j in range(n) if cell[i][j] == "-") for i in range(n)]
    got_pos = [sum(1 for i in range(n) if cell[i][j] == "+") for j in range(n)]
    got_neg = [sum(1 for i in range(n) if cell[i][j] == "-") for j in range(n)]
    mut_pos = [[False] * n for _ in range(n)]
    mut_neg = [[False] * n for _ in range(n)]
    pairs_pos, pairs_neg = [], []
    for i in range(n):
        for j in range(i + 1, n):
            if cell[i][j] == "+" and cell[j][i] == "+":
                mut_pos[i][j] = mut_pos[j][i] = True
                pairs_pos.append((i, j))
            if cell[i][j] == "-" and cell[j][i] == "-":
                mut_neg[i][j] = mut_neg[j][i] = True
                pairs_neg.append((i, j))
    mutual_pos = [sum(1 for j in range(n) if mut_pos[i][j]) for i in range(n)]
    mutual_neg = [sum(1 for j in range(n) if mut_neg[i][j]) for i in range(n)]

    # статусные группы
    top = max(got_pos) if n else 0
    status = []
    for i in range(n):
        if got_pos[i] == 0:
            s = "rej"
        elif top and got_pos[i] == top:
            s = "star"
        elif top and got_pos[i] * 2 >= top:
            s = "pref"
        elif mutual_pos[i] > 0:
            s = "acc"
        else:
            s = "half"
        status.append(s)

    # микрогруппы — связные компоненты взаимных положительных выборов
    seen, groups = set(), []
    for i in range(n):
        if i in seen or mutual_pos[i] == 0:
            continue
        stack, comp = [i], []
        seen.add(i)
        while stack:
            v = stack.pop()
            comp.append(v)
            for j in range(n):
                if mut_pos[v][j] and j not in seen:
                    seen.add(j)
                    stack.append(j)
        if len(comp) >= 2:
            groups.append(sorted(comp))
    groups.sort(key=lambda g: -len(g))

    den = float(n * (n - 1)) if n > 1 else 1.0
    n_plus, n_minus = sum(made_pos), sum(made_neg)
    n_zero = max(0, int(den) - n_plus - n_minus)
    mp, mn = len(pairs_pos) * 2, len(pairs_neg) * 2
    group_idx = {
        "N": n, "done": sum(1 for d in done if d),
        "total_choices": int(den), "pos": n_plus, "neg": n_minus, "zero": n_zero,
        "pct_pos": _fmt(100.0 * n_plus / den, 1), "pct_neg": _fmt(100.0 * n_minus / den, 1),
        "pct_zero": _fmt(100.0 * n_zero / den, 1),
        "cohesion": _fmt(100.0 * (mp - mn) / den, 1),           # индекс сплочённости, %
        "mutuality": _fmt(mp / den, 3),                          # индекс групповой взаимности
        "satisfaction": _fmt(100.0 * sum(1 for i in range(n) if mutual_pos[i]) / (n or 1), 1),
        "pairs_pos": len(pairs_pos), "pairs_neg": len(pairs_neg),
    }
    d1 = float(n - 1) if n > 1 else 1.0
    rows = []
    for i, p in enumerate(people):
        rows.append({
            "id": p["id"], "name": p["name"], "done": done[i], "num": i + 1,
            "made_pos": made_pos[i], "made_neg": made_neg[i], "got_pos": got_pos[i], "got_neg": got_neg[i],
            "mutual_pos": mutual_pos[i], "mutual_neg": mutual_neg[i], "status": status[i],
            "status_name": STATUS_NAMES[status[i]],
            "iss": _fmt((got_pos[i] + got_neg[i]) / d1), "iss_pos": _fmt(got_pos[i] / d1), "iss_neg": _fmt(got_neg[i] / d1),
            "ipe": _fmt((made_pos[i] + made_neg[i]) / d1), "ipe_pos": _fmt(made_pos[i] / d1), "ipe_neg": _fmt(made_neg[i] / d1),
            "iv": _fmt((got_pos[i] - got_neg[i]) / d1), "ip": _fmt((made_pos[i] - made_neg[i]) / d1),
        })
    counts = dict((s, sum(1 for x in status if x == s)) for s in STATUS_ORDER)
    level = ("высокая" if group_idx["pct_pos"] >= 50 else "средняя" if group_idx["pct_pos"] >= 25 else "низкая")
    notes = []
    missing = [p["name"] for i, p in enumerate(people) if not done[i]]
    if missing:
        notes.append("Не прошли опрос: %s. Их выборы в матрице отсутствуют, поэтому статусы остальных "
                     "могут быть занижены." % ", ".join(missing))
    if n < 10:
        notes.append("В группе меньше 10 человек: социометрические показатели в малых группах неустойчивы.")
    if counts["rej"]:
        notes.append("Учащихся без единого положительного выбора: %d. С ними рекомендуется индивидуальная "
                     "и групповая коррекционная работа." % counts["rej"])
    return {
        "criteria": cr, "people": rows, "matrix": cell, "mutual": mut_pos, "mutual_neg": mut_neg,
        "pairs_pos": [[a, b] for a, b in pairs_pos], "pairs_neg": [[a, b] for a, b in pairs_neg],
        "groups": groups, "indices": group_idx, "counts": counts, "status_names": STATUS_NAMES,
        "status_help": STATUS_HELP, "status_order": STATUS_ORDER, "cohesion_level": level, "notes": notes,
    }


def key_rows(mid):
    return [
        {"name": "Социоматрица", "items": "строка — кто выбирает, столбец — кого выбирают; «+» положительный "
                                          "выбор, «–» отрицательный, пустая клетка — безразличный"},
        {"name": "«Звёзды»", "items": "получили максимальное число положительных выборов"},
        {"name": "«Предпочитаемые»", "items": "получили половину и больше от максимума"},
        {"name": "«Принятые»", "items": "имеют хотя бы один взаимный положительный выбор"},
        {"name": "«Принято-непринятые»", "items": "их выбирают, но взаимных выборов нет"},
        {"name": "«Отвергнутые»", "items": "не получили ни одного положительного выбора"},
        {"name": "Индекс сплочённости группы (ИС)", "items": "(взаимные «+» − взаимные «–») ÷ N(N−1) × 100 %"},
        {"name": "Индекс групповой взаимности (ИГВ)", "items": "число взаимно положительных выборов ÷ N(N−1)"},
        {"name": "Индекс социометрического статуса (ИСС)", "items": "полученные выборы ÷ (N−1)"},
        {"name": "Индекс психологической экспансивности (ИПЭ)", "items": "отданные выборы ÷ (N−1)"},
        {"name": "Индекс взаимности (ИВ) — авторитетность", "items": "(полученные «+» − полученные «–») ÷ (N−1)"},
        {"name": "Индекс позиции (ИП) — отношение к другим", "items": "(отданные «+» − отданные «–») ÷ (N−1)"},
    ]
