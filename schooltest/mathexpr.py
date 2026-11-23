# -*- coding: utf-8 -*-
"""Безопасное вычисление формул для числовых вопросов (без eval): только арифметика,
скобки, переменные-параметры и несколько функций."""
import ast
import math
import operator
import random
import re

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv}
_UN = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNC = {"sqrt": math.sqrt, "abs": abs, "sin": math.sin, "cos": math.cos, "tan": math.tan, "asin": math.asin,
         "acos": math.acos, "atan": math.atan, "log": math.log, "ln": math.log, "log10": math.log10,
         "log2": math.log2, "exp": math.exp, "floor": math.floor, "ceil": math.ceil, "round": round,
         "min": min, "max": max, "radians": math.radians, "degrees": math.degrees}
_CONST = {"pi": math.pi, "e": math.e}
MAX_LEN = 300


class FormulaError(ValueError):
    pass


def _norm(src):
    s = str(src or "").strip().replace("×", "*").replace("·", "*").replace("÷", "/")
    s = s.replace("−", "-").replace("^", "**").replace("√", "sqrt")
    return s


def _ev(node, env, depth=0):
    if depth > 40:
        raise FormulaError("Слишком сложная формула")
    if isinstance(node, ast.Expression):
        return _ev(node.body, env, depth + 1)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise FormulaError("Недопустимая константа")
    if type(node).__name__ == "Num":        # Python 3.7: ast.Num
        return node.n
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        if node.id in _CONST:
            return _CONST[node.id]
        raise FormulaError("Неизвестная переменная: " + node.id)
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        a, b = _ev(node.left, env, depth + 1), _ev(node.right, env, depth + 1)
        if isinstance(node.op, ast.Pow) and (abs(b) > 100 or abs(a) > 1e100):
            raise FormulaError("Слишком большая степень")
        return _BIN[type(node.op)](a, b)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UN:
        return _UN[type(node.op)](_ev(node.operand, env, depth + 1))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNC and not node.keywords:
        return _FUNC[node.func.id](*[_ev(x, env, depth + 1) for x in node.args])
    raise FormulaError("Недопустимое выражение")


def evaluate(src, env=None):
    s = _norm(src)
    if not s or len(s) > MAX_LEN:
        raise FormulaError("Пустая или слишком длинная формула")
    try:
        tree = ast.parse(s, mode="eval")
        v = _ev(tree, dict(env or {}))
        v = float(v)
    except FormulaError:
        raise
    except (SyntaxError, ValueError, ZeroDivisionError, OverflowError, TypeError) as e:
        raise FormulaError("Ошибка в формуле: %s" % e)
    if v != v or v in (float("inf"), float("-inf")):
        raise FormulaError("Результат не является числом")
    return v


_NAME = re.compile(r"^[A-Za-z_а-яА-Я][A-Za-z_0-9а-яА-Я]*$")


def _decimals(x):
    s = ("%.10f" % x).rstrip("0")
    return len(s.split(".")[1]) if "." in s else 0


def gen_vars(params, rng=None):
    """params: [{name,min,max,step}] → {name: число}. Значения лежат на сетке min + k*step."""
    rng = rng or random.SystemRandom()
    out = {}
    for p in params or []:
        name = str(p.get("name") or "").strip()
        if not _NAME.match(name):
            continue
        lo, hi = float(p.get("min", 0)), float(p.get("max", 0))
        st = float(p.get("step") or 1)
        if st <= 0:
            st = 1.0
        if hi < lo:
            lo, hi = hi, lo
        n = int((hi - lo) / st + 1e-9)
        v = lo + rng.randint(0, n) * st
        v = round(v, max(_decimals(st), _decimals(lo)))
        out[name] = int(v) if v == int(v) else v
    return out


def fmt(x, sig=None):
    """Число для показа: без хвостов, десятичная запятая не используется."""
    if sig:
        x = round_sig(x, sig)
    if x == int(x) and abs(x) < 1e15:
        return str(int(x))
    s = ("%.10g" % x)
    return s


def round_sig(x, n):
    if x == 0 or not n:
        return x
    return round(x, int(n) - 1 - int(math.floor(math.log10(abs(x)))))


def substitute(text, vars_):
    """Подставляет {имя} в тексте вопроса."""
    def rep(m):
        k = m.group(1)
        return fmt(vars_[k]) if k in (vars_ or {}) else m.group(0)
    return re.sub(r"\{([^{}]+)\}", rep, text or "")


_NUMRE = re.compile(r"^\s*([+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?)\s*(.*)$", re.S)


def parse_answer(raw):
    """'5,2 м/с' → (5.2, 'м/с'); None, если числа нет."""
    s = str(raw or "").replace("−", "-").replace("–", "-").replace(" ", " ").strip()
    s = re.sub(r"(?<=\d) (?=\d{3}\b)", "", s)         # 1 000 → 1000
    m = _NUMRE.match(s)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ".")), m.group(2).strip()
    except ValueError:
        return None


def _unit_norm(u):
    return re.sub(r"[\s.·*]", "", str(u or "").lower().replace("ё", "е"))


def check_numeric(raw, expected, a):
    """a: {tol_abs, tol_rel (%), ignore_units, unit, sig}. True/False."""
    p = parse_answer(raw)
    if p is None:
        return False
    g, rest = p
    unit = a.get("unit") or ""
    if rest:
        if not a.get("ignore_units") and _unit_norm(rest) != _unit_norm(unit):
            return False
    elif unit and a.get("require_unit"):
        return False
    sig = int(a.get("sig") or 0)
    e = expected
    if sig:
        g, e = round_sig(g, sig), round_sig(e, sig)
    tol = max(float(a.get("tol_abs") or 0), abs(e) * float(a.get("tol_rel") or 0) / 100.0, abs(e) * 1e-9, 1e-12)
    return abs(g - e) <= tol + 1e-12


def expected_value(a, vars_):
    return evaluate(a.get("formula"), vars_)
