# -*- coding: utf-8 -*-
"""Беларускі пераклад. Адзін слоўнік (static/be.tsv) для сервера і браўзера:
сервер перакладае свае паведамленні і справаздачы, а браўзер атрымлівае слоўнік як /i18n_be.js."""
import json
import os
import re
import sys

_BE = None
_PATTERNS = None


def _path():
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "static", "be.tsv")


def table():
    global _BE, _PATTERNS
    if _BE is None:
        be, pats = {}, []
        try:
            with open(_path(), encoding="utf-8") as f:
                for line in f:
                    line = line.rstrip("\n").rstrip("\r")
                    if not line or line.startswith("#") or "\t" not in line:
                        continue
                    ru, tr = line.split("\t", 1)
                    be[ru] = tr
                    if "%s" in ru or "%d" in ru:
                        rx = "^" + re.escape(ru).replace("%s", "(.*?)").replace("%d", r"(-?\d+)") + "$"
                        pats.append((re.compile(rx, re.S), tr))
        except OSError:
            pass
        pats.sort(key=lambda p: -len(p[0].pattern))
        _BE, _PATTERNS = be, pats
    return _BE


def msg(text, lang):
    """Перевод готового (уже подставленного) сообщения на белорусский."""
    if lang != "be" or not isinstance(text, str) or not text:
        return text
    be = table()
    if text in be:
        return be[text]
    for rx, tr in _PATTERNS:
        m = rx.match(text)
        if m:
            parts = iter(msg(g, lang) for g in m.groups())
            return re.sub(r"%[sd]", lambda _m: next(parts, ""), tr)
    return text


def report(rep, lang):
    """Перевод справаздачы: загалоўкі, назва, падзагаловак і стандартныя значэнні ў ячэйках."""
    if lang != "be":
        return rep
    rep = dict(rep)
    for k in ("title", "subtitle", "name"):
        if rep.get(k):
            rep[k] = msg(rep[k], lang)
    rep["headers"] = [msg(h, lang) for h in rep.get("headers", [])]
    rep["rows"] = [[msg(c, lang) if isinstance(c, str) else c for c in r] for r in rep.get("rows", [])]
    return rep


def js():
    """Слоўнік для браўзера (без шаблонаў сервера з %s)."""
    data = dict((k, v) for k, v in table().items() if "%s" not in k and "%d" not in k)
    return "window.ST_BE = " + json.dumps(data, ensure_ascii=False) + ";\n"
