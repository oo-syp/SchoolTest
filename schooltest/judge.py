# -*- coding: utf-8 -*-
"""Проверка решений задач с кодом (как на contest.yandex.ru).

Языки: Free Pascal, PascalABC.NET, Python 3, C++ (20). Компиляторы ищутся на компьютере,
где запущен SchoolTest (стандартные папки установки и PATH); путь можно указать вручную
в настройках. Для Python, если он не установлен, используется Python 3.8, встроенный в
SchoolTest.exe.

Запуск решения:
  * Windows — объект задания (Job Object): ограничение памяти, одного процесса, процессорного
    времени, без окон и ошибок Windows; процесс создаётся приостановленным, включается в задание
    и только потом запускается;
  * Linux (разработка) — setrlimit.
Ввод подаётся и в стандартный поток, и в файл input.txt; вывод берётся из output.txt, если
программа его создала, иначе из стандартного потока.
"""
import glob
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

IS_WIN = os.name == "nt"
MAX_OUTPUT = 64 * 1024 * 1024
COMPILE_TIMEOUT = 60

LANGS = [
    {"id": "fpc", "name": "Free Pascal", "ext": "pas"},
    {"id": "pabc", "name": "PascalABC.NET", "ext": "pas"},
    {"id": "py", "name": "Python 3", "ext": "py"},
    {"id": "cpp", "name": "C++ (20)", "ext": "cpp"},
]
LANG_IDS = [x["id"] for x in LANGS]
LANG_NAMES = dict((x["id"], x["name"]) for x in LANGS)

VERDICTS = {
    "OK": "Принято", "WA": "Неправильный ответ", "TL": "Превышено ограничение времени",
    "ML": "Превышено ограничение памяти", "RE": "Ошибка во время выполнения", "CE": "Ошибка компиляции",
    "OL": "Слишком большой вывод", "PE": "Неверный формат вывода", "PT": "Частичное решение",
    "SE": "Ошибка проверяющей системы", "NC": "Компилятор не настроен",
}

DEFAULT_FLAGS = {
    "fpc": "-O2 -Mobjfpc -Sh -XS",
    "pabc": "",
    "py": "",
    "cpp": "-std=c++20 -O2 -static",
}


# ------------------------------------------------------------------ поиск компиляторов
def _which(name):
    return shutil.which(name)


def _env(name, default=""):
    return os.environ.get(name) or default


def _globs(patterns):
    out = []
    for p in patterns:
        out += sorted(glob.glob(p), reverse=True)
    return [x for x in out if os.path.isfile(x)]


def candidates(lang):
    """Возможные пути к компилятору/интерпретатору (найденные на этом компьютере)."""
    pf = [_env("ProgramFiles", r"C:\Program Files"), _env("ProgramFiles(x86)", r"C:\Program Files (x86)"),
          _env("ProgramW6432", r"C:\Program Files")]
    local = _env("LOCALAPPDATA", os.path.expanduser("~"))
    found = []
    if lang == "fpc":
        if IS_WIN:
            found += _globs([r"C:\FPC\*\bin\*\fpc.exe", r"C:\Lazarus\fpc\*\bin\*\fpc.exe", r"D:\FPC\*\bin\*\fpc.exe"] +
                            [os.path.join(p, r"Lazarus\fpc\*\bin\*\fpc.exe") for p in pf] +
                            [os.path.join(p, r"FreePascal\bin\*\fpc.exe") for p in pf])
        w = _which("fpc")
        if w:
            found.insert(0, w)
    elif lang == "pabc":
        if IS_WIN:
            found += _globs([os.path.join(p, r"PascalABC.NET\pabcnetcclear.exe") for p in pf] +
                            [os.path.join(p, r"PascalABC.NET\pabcnetc.exe") for p in pf] +
                            [r"C:\PascalABC.NET\pabcnetcclear.exe"])
        for n in ("pabcnetcclear", "pabcnetc"):
            w = _which(n)
            if w:
                found.append(w)
    elif lang == "py":
        if IS_WIN:
            found += _globs([os.path.join(local, r"Programs\Python\Python3*\python.exe"), r"C:\Python3*\python.exe"] +
                            [os.path.join(p, r"Python3*\python.exe") for p in pf])
            w = _which("python")
            if w and "WindowsApps" not in w:
                found.insert(0, w)
        else:
            w = _which("python3")
            if w:
                found.insert(0, w)
        found.append("builtin")
    elif lang == "cpp":
        if IS_WIN:
            found += _globs([r"C:\msys64\ucrt64\bin\g++.exe", r"C:\msys64\mingw64\bin\g++.exe", r"C:\msys64\mingw32\bin\g++.exe",
                             r"C:\mingw64\bin\g++.exe", r"C:\MinGW\bin\g++.exe", r"C:\w64devkit\bin\g++.exe",
                             r"C:\TDM-GCC-64\bin\g++.exe", r"C:\TDM-GCC-32\bin\g++.exe"] +
                            [os.path.join(p, r"CodeBlocks\MinGW\bin\g++.exe") for p in pf] +
                            [os.path.join(p, r"Dev-Cpp\MinGW64\bin\g++.exe") for p in pf] +
                            [os.path.join(p, r"mingw-w64\*\mingw64\bin\g++.exe") for p in pf])
        w = _which("g++")
        if w:
            found.insert(0, w)
    seen, out = set(), []
    for f in found:
        k = f.lower() if IS_WIN else f
        if k not in seen:
            seen.add(k)
            out.append(f)
    return out


def builtin_python_available():
    return bool(getattr(sys, "frozen", False)) or bool(sys.executable)


class Config(object):
    """Пути и ключи компиляторов (настройки администратора) + автопоиск."""

    def __init__(self, settings=None):
        s = settings or {}
        self.paths = dict(s.get("paths") or {})
        self.flags = dict(DEFAULT_FLAGS)
        self.flags.update(dict((k, v) for k, v in (s.get("flags") or {}).items() if isinstance(v, str)))
        self.disabled = set(s.get("disabled") or [])

    def path(self, lang):
        p = self.paths.get(lang)
        if p and (p == "builtin" or os.path.isfile(p)):
            return p
        c = candidates(lang)
        return c[0] if c else None


def _split_flags(s):
    return [x for x in re.findall(r'"[^"]*"|\S+', s or "") if x]


def _short_err(text, limit=4000):
    text = text or ""
    if len(text) > limit:
        text = text[:limit] + "\n…"
    return text


def tool_version(lang, path):
    """Строка версии — для проверки в настройках."""
    try:
        if path == "builtin":
            return "Python %d.%d.%d (встроенный в SchoolTest)" % sys.version_info[:3]
        if lang == "fpc":
            args = [path, "-iV"]
        elif lang == "pabc":
            return os.path.basename(path)
        else:
            args = [path, "--version"]
        p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20,
                           creationflags=_NOWIN, stdin=subprocess.DEVNULL)
        out = p.stdout.decode("utf-8", "replace").strip().splitlines()
        return (out[0] if out else "").strip()[:200]
    except Exception as e:  # noqa
        return "ошибка: %s" % e


_NOWIN = 0x08000000 if IS_WIN else 0   # CREATE_NO_WINDOW


# ------------------------------------------------------------------ компиляция
def compile_source(lang, code, workdir, cfg):
    """Возвращает (команда запуска [list] | None, сообщение компилятора, verdict|None)."""
    path = cfg.path(lang)
    if not path or lang in cfg.disabled:
        return None, "Компилятор «%s» не найден на компьютере с SchoolTest. Обратитесь к учителю." % LANG_NAMES.get(lang, lang), "NC"
    ext = dict((x["id"], x["ext"]) for x in LANGS)[lang]
    src = os.path.join(workdir, "solution." + ext)
    with open(src, "w", encoding="utf-8", newline="\n") as f:
        f.write(code)
    exe = os.path.join(workdir, "solution.exe" if IS_WIN else "solution")
    flags = _split_flags(cfg.flags.get(lang, ""))
    if lang == "py":
        try:
            compile(code, "solution.py", "exec")
        except SyntaxError as e:
            return None, "Синтаксическая ошибка, строка %s: %s\n%s" % (e.lineno, e.msg, (e.text or "").rstrip()), "CE"
        except ValueError as e:
            return None, str(e), "CE"
        if path == "builtin":
            if getattr(sys, "frozen", False):
                return [sys.executable, "--pyrun", src], "", None
            return [sys.executable, "-I", "-X", "utf8", src], "", None
        return [path, "-I", "-X", "utf8"] + flags + [src], "", None
    if lang == "fpc":
        args = [path] + flags + ["-o" + exe, src]
    elif lang == "pabc":
        args = [path] + flags + [src]
        exe = os.path.join(workdir, "solution.exe")
    else:
        args = [path] + flags + ["-o", exe, src]
    env = dict(os.environ)
    if IS_WIN and lang == "cpp":   # библиотеки MinGW рядом с компилятором
        env["PATH"] = os.path.dirname(path) + os.pathsep + env.get("PATH", "")
    try:
        p = subprocess.run(args, cwd=workdir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=COMPILE_TIMEOUT,
                           creationflags=_NOWIN, stdin=subprocess.DEVNULL, env=env)
    except subprocess.TimeoutExpired:
        return None, "Компиляция заняла больше %d секунд" % COMPILE_TIMEOUT, "CE"
    except OSError as e:
        return None, "Не удалось запустить компилятор: %s" % e, "NC"
    out = p.stdout.decode("utf-8", "replace")
    if IS_WIN and "\ufffd" in out:
        out = p.stdout.decode("cp866", "replace")
    out = out.replace(workdir + os.sep, "").replace(workdir, "")
    if lang == "cpp" and p.returncode != 0 and "c++20" in " ".join(flags) and "unrecognized" in out and "c++20" in out:
        # старый g++ (до 10): c++2a
        args = [a.replace("c++20", "c++2a") for a in args]
        p = subprocess.run(args, cwd=workdir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=COMPILE_TIMEOUT,
                           creationflags=_NOWIN, stdin=subprocess.DEVNULL, env=env)
        out = p.stdout.decode("utf-8", "replace").replace(workdir + os.sep, "")
    if p.returncode != 0 or not os.path.isfile(exe):
        if lang == "pabc" and os.path.isfile(exe) and "Ошибк" not in out and "rror" not in out:
            pass
        else:
            return None, _short_err(out.strip() or "Код возврата компилятора %s" % p.returncode), "CE"
    # сообщения FPC об успешной сборке ученику не нужны
    if lang == "fpc":
        out = "\n".join(l for l in out.splitlines() if re.search(r"(Warning|Note|Hint|Error|Fatal)", l))
    return [exe], _short_err(out.strip()), None


# ------------------------------------------------------------------ запуск с ограничениями
if IS_WIN:
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll = ctypes.WinDLL("ntdll")

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                                       "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION), ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    class JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
        _fields_ = [("TotalUserTime", ctypes.c_longlong), ("TotalKernelTime", ctypes.c_longlong),
                    ("ThisPeriodTotalUserTime", ctypes.c_longlong), ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
                    ("TotalPageFaultCount", wintypes.DWORD), ("TotalProcesses", wintypes.DWORD),
                    ("ActiveProcesses", wintypes.DWORD), ("TotalTerminatedProcesses", wintypes.DWORD)]

    class JOBOBJECT_BASIC_UI_RESTRICTIONS(ctypes.Structure):
        _fields_ = [("UIRestrictionsClass", wintypes.DWORD)]

    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _k32.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
    _k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]

    _LIMIT_PROCESS_TIME = 0x2
    _LIMIT_ACTIVE_PROCESS = 0x8
    _LIMIT_PROCESS_MEMORY = 0x100
    _LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x400
    _LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    _CREATE_SUSPENDED = 0x4
    _CREATE_BREAKAWAY_FROM_JOB = 0x01000000
    _SEM_FLAGS = 0x0001 | 0x0002 | 0x8000   # без окон «Программа не отвечает» / ошибок


def _check_size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def run_limited(cmd, workdir, stdin_path, stdout_path, stderr_path, tl, ml_mb, env=None):
    """Запуск одного теста. Возвращает {status: ok|tl|ml|re|ol, time, memory, exit}."""
    tl = float(tl)
    wall = max(tl * 3, tl + 2.0)
    ml = int(ml_mb) * 1024 * 1024
    env = env or dict(os.environ)
    res = {"status": "ok", "time": 0.0, "memory": 0, "exit": 0}
    fin = open(stdin_path, "rb")
    fout = open(stdout_path, "wb")
    ferr = open(stderr_path, "wb")
    try:
        if IS_WIN:
            return _run_win(cmd, workdir, fin, fout, ferr, tl, wall, ml, env, res, stdout_path)
        return _run_posix(cmd, workdir, fin, fout, ferr, tl, wall, ml, env, res, stdout_path)
    finally:
        for f in (fin, fout, ferr):
            try:
                f.close()
            except Exception:
                pass


def _run_win(cmd, workdir, fin, fout, ferr, tl, wall, ml, env, res, stdout_path):
    job = _k32.CreateJobObjectW(None, None)
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    bl = info.BasicLimitInformation
    bl.LimitFlags = (_LIMIT_PROCESS_TIME | _LIMIT_ACTIVE_PROCESS | _LIMIT_PROCESS_MEMORY |
                     _LIMIT_DIE_ON_UNHANDLED_EXCEPTION | _LIMIT_KILL_ON_JOB_CLOSE)
    bl.PerProcessUserTimeLimit = int((tl + 0.5) * 10 ** 7)
    bl.ActiveProcessLimit = 1
    info.ProcessMemoryLimit = ml + 16 * 1024 * 1024
    _k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
    # без буфера обмена, смены настроек системы и экрана, завершения сеанса Windows
    ui = JOBOBJECT_BASIC_UI_RESTRICTIONS(0x80 | 0x10 | 0x08 | 0x04 | 0x02)
    _k32.SetInformationJobObject(job, 4, ctypes.byref(ui), ctypes.sizeof(ui))
    old_mode = _k32.SetErrorMode(_SEM_FLAGS)
    try:
        try:
            p = subprocess.Popen(cmd, cwd=workdir, stdin=fin, stdout=fout, stderr=ferr, env=env,
                                 creationflags=_CREATE_SUSPENDED | _NOWIN | _CREATE_BREAKAWAY_FROM_JOB)
        except OSError:
            p = subprocess.Popen(cmd, cwd=workdir, stdin=fin, stdout=fout, stderr=ferr, env=env,
                                 creationflags=_CREATE_SUSPENDED | _NOWIN)
    finally:
        _k32.SetErrorMode(old_mode)
    try:
        in_job = bool(_k32.AssignProcessToJobObject(job, int(p._handle)))
        _ntdll.NtResumeProcess(int(p._handle))
        start = time.time()
        while True:
            try:
                p.wait(timeout=0.05)
                break
            except subprocess.TimeoutExpired:
                pass
            if time.time() - start > wall:
                res["status"] = "tl"
                _k32.TerminateJobObject(job, 1)
                p.wait()
                break
            if _check_size(stdout_path) > MAX_OUTPUT:
                res["status"] = "ol"
                _k32.TerminateJobObject(job, 1)
                p.wait()
                break
        acc = JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
        _k32.QueryInformationJobObject(job, 1, ctypes.byref(acc), ctypes.sizeof(acc), None)
        ext = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        _k32.QueryInformationJobObject(job, 9, ctypes.byref(ext), ctypes.sizeof(ext), None)
        res["time"] = (acc.TotalUserTime + acc.TotalKernelTime) / 1e7
        res["memory"] = int(ext.PeakProcessMemoryUsed)
        if not in_job:      # SchoolTest сам запущен внутри задания (Windows 7) — время по процессу
            ft = [wintypes.FILETIME() for _ in range(4)]
            if _k32.GetProcessTimes(int(p._handle), *[ctypes.byref(x) for x in ft]):
                res["time"] = sum((x.dwHighDateTime << 32 | x.dwLowDateTime) for x in ft[2:]) / 1e7
        res["exit"] = p.returncode
        code = p.returncode & 0xFFFFFFFF if p.returncode is not None else 0
        if res["status"] == "ok":
            if res["time"] > tl:
                res["status"] = "tl"
            elif res["memory"] > ml or (code != 0 and res["memory"] > ml * 0.9):
                res["status"] = "ml"
            elif code == 1816:   # ERROR_NOT_ENOUGH_QUOTA — исчерпан лимит процессорного времени задания
                res["status"] = "tl"
            elif code != 0:
                res["status"] = "re"
        return res
    finally:
        _k32.CloseHandle(job)


def _run_posix(cmd, workdir, fin, fout, ferr, tl, wall, ml, env, res, stdout_path):
    import resource
    import signal

    def limits():
        cpu = int(tl) + 1
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
        mem = ml + 64 * 1024 * 1024
        try:
            resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
        except (ValueError, OSError):
            pass
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT + 1, MAX_OUTPUT + 1))
        try:
            resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
        except (ValueError, OSError):
            pass
        os.setsid()

    p = subprocess.Popen(cmd, cwd=workdir, stdin=fin, stdout=fout, stderr=ferr, env=env, preexec_fn=limits)
    box = {}

    def waiter():
        try:
            box["r"] = os.wait4(p.pid, 0)
        except ChildProcessError:
            box["r"] = None

    th = threading.Thread(target=waiter, daemon=True)
    th.start()
    th.join(wall)
    if th.is_alive():
        res["status"] = "tl"
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
        th.join(5)
    r = box.get("r")
    p.returncode = 0
    if r:
        _pid, status, ru = r
        res["time"] = ru.ru_utime + ru.ru_stime
        res["memory"] = ru.ru_maxrss * 1024
        sig = os.WTERMSIG(status) if os.WIFSIGNALED(status) else 0
        code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else -sig
        res["exit"] = code
        if res["status"] == "ok":
            if res["time"] > tl or sig == signal.SIGXCPU:
                res["status"] = "tl"
            elif sig == signal.SIGXFSZ or _check_size(stdout_path) > MAX_OUTPUT:
                res["status"] = "ol"
            elif res["memory"] > ml:
                res["status"] = "ml"
            elif code != 0:
                err = b""
                try:
                    with open(ferr.name, "rb") as f:
                        err = f.read(4000)
                except OSError:
                    pass
                res["status"] = "ml" if (b"MemoryError" in err or b"bad_alloc" in err or b"Heap overflow" in err
                                         or b"Runtime error 203" in err) else "re"
    return res


# ------------------------------------------------------------------ проверка вывода
def _num(s):
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def check_output(out, ans, mode="tokens", eps=1e-6):
    """True, если вывод совпадает с ответом. mode: tokens | lines | float."""
    if mode == "lines":
        a = [l.rstrip() for l in out.replace("\r\n", "\n").split("\n")]
        b = [l.rstrip() for l in ans.replace("\r\n", "\n").split("\n")]
        while a and not a[-1]:
            a.pop()
        while b and not b[-1]:
            b.pop()
        return a == b
    ta, tb = out.split(), ans.split()
    if len(ta) != len(tb):
        return False
    if mode == "float":
        for x, y in zip(ta, tb):
            if x == y:
                continue
            fx, fy = _num(x), _num(y)
            if fx is None or fy is None or abs(fx - fy) > eps * max(1.0, abs(fy)):
                return False
        return True
    return ta == tb


def _read(path, limit=None):
    try:
        with open(path, "rb") as f:
            data = f.read() if limit is None else f.read(limit)
    except OSError:
        return ""
    for enc in ("utf-8", "cp1251"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", "replace")


def task_groups(spec):
    """Группы тестов: [{name, points, deps, tests, sample}] — примеры (0 баллов) и подзадачи."""
    groups = []
    ex = [t for t in spec.get("examples") or [] if (t.get("in") or "") or (t.get("out") or "")]
    if ex and spec.get("check_examples", True):
        groups.append({"name": "Примеры", "points": 0, "deps": [], "tests": ex, "sample": True, "idx": 0})
    subs = spec.get("subtasks") or []
    for i, s in enumerate(subs, 1):
        groups.append({"name": s.get("name") or "Подзадача %d" % i, "points": float(s.get("points") or 0),
                       "deps": [int(x) for x in s.get("deps") or [] if str(x).isdigit()], "tests": s.get("tests") or [],
                       "sample": False, "idx": i})
    return groups


def judge(spec, lang, code, workroot, cfg, progress=None):
    """Полная проверка решения.

    spec — условие и тесты: {time_limit, memory, checker, eps, scoring: subtasks|tests, examples, subtasks}.
    Возвращает {verdict, frac, compile, groups: [{name, points, got, status, tests: [...]}], time, memory}."""
    tl = float(spec.get("time_limit") or 1)
    ml = int(spec.get("memory") or 256)
    mode = spec.get("checker") or "tokens"
    eps = float(spec.get("eps") or 1e-6)
    groups = task_groups(spec)
    wd = tempfile.mkdtemp(prefix="st_", dir=workroot)
    out = {"verdict": "SE", "frac": 0.0, "compile": "", "groups": [], "time": 0.0, "memory": 0}
    try:
        cmd, msg, bad = compile_source(lang, code, wd, cfg)
        out["compile"] = msg
        if bad:
            out["verdict"] = bad
            return out
        env = dict(os.environ)
        env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"})
        if cmd[0] == sys.executable and getattr(sys, "frozen", False):
            env["_MEIPASS2"] = getattr(sys, "_MEIPASS", "")
        if IS_WIN and lang == "cpp":
            env["PATH"] = os.path.dirname(cfg.path("cpp") or "") + os.pathsep + env.get("PATH", "")
        rundir = os.path.join(wd, "run")
        total_points = sum(g["points"] for g in groups) or 0
        passed = {}
        first_fail = None
        tnum = 0
        for g in groups:
            gres = {"name": g["name"], "points": g["points"], "got": 0, "status": "OK", "tests": [], "sample": g["sample"],
                    "idx": g["idx"]}
            blocked = [d for d in g["deps"] if not passed.get(d)]
            ok_all = True
            skip = bool(blocked) and spec.get("scoring") != "tests"   # подзадача не зачтётся — тесты не запускаем
            for t in ([] if skip else g["tests"]):
                tnum += 1
                if os.path.isdir(rundir):
                    shutil.rmtree(rundir, ignore_errors=True)
                os.makedirs(rundir)
                inp = t.get("in") or ""
                if inp and not inp.endswith("\n"):
                    inp += "\n"
                for name in ("input.txt",):
                    with open(os.path.join(rundir, name), "w", encoding="utf-8", newline="\n") as f:
                        f.write(inp)
                stdin_p = os.path.join(wd, "stdin.txt")
                with open(stdin_p, "w", encoding="utf-8", newline="\n") as f:
                    f.write(inp)
                r = run_limited(cmd, rundir, stdin_p, os.path.join(wd, "stdout.txt"), os.path.join(wd, "stderr.txt"),
                                tl, ml, env)
                outp = os.path.join(rundir, "output.txt")
                got = _read(outp) if _check_size(outp) else _read(os.path.join(wd, "stdout.txt"))
                st = {"ok": "OK", "tl": "TL", "ml": "ML", "re": "RE", "ol": "OL"}[r["status"]]
                if st == "OK" and not check_output(got, t.get("out") or "", mode, eps):
                    st = "WA"
                tr = {"n": tnum, "status": st, "time": round(r["time"], 3), "memory": r["memory"]}
                if st == "RE":
                    tr["stderr"] = _short_err(_read(os.path.join(wd, "stderr.txt"), 8000), 2000)
                    tr["exit"] = r["exit"]
                if g["sample"]:
                    tr["input"] = inp[:2000]
                    tr["expected"] = (t.get("out") or "")[:2000]
                    tr["output"] = got[:2000]
                gres["tests"].append(tr)
                out["time"] = max(out["time"], r["time"])
                out["memory"] = max(out["memory"], r["memory"])
                if progress:
                    progress(tnum)
                if st != "OK":
                    ok_all = False
                    if first_fail is None:
                        first_fail = (st, tnum)
                    if spec.get("scoring") != "tests":
                        break      # подзадача уже не зачтена — остальные тесты группы не нужны
            if spec.get("scoring") == "tests" and not g["sample"]:
                n = len(g["tests"]) or 1
                good = sum(1 for x in gres["tests"] if x["status"] == "OK")
                gres["got"] = g["points"] * good / float(n)
                gres["status"] = "OK" if good == len(g["tests"]) else ("PT" if good else gres["tests"][-1]["status"] if gres["tests"] else "OK")
            else:
                if blocked:
                    gres["status"] = "DEP"
                elif not ok_all:
                    gres["status"] = [x for x in gres["tests"] if x["status"] != "OK"][0]["status"]
                gres["got"] = g["points"] if (ok_all and not blocked) else 0
            passed[g["idx"]] = ok_all and not blocked
            out["groups"].append(gres)
        got = sum(x["got"] for x in out["groups"])
        if total_points > 0:
            out["frac"] = round(got / total_points, 6)
        else:
            out["frac"] = 1.0 if first_fail is None else 0.0
        if first_fail is None:
            out["verdict"] = "OK"
        elif out["frac"] > 0:
            out["verdict"] = "PT"
            out["fail"] = {"status": first_fail[0], "test": first_fail[1]}
        else:
            out["verdict"] = first_fail[0]
            out["fail"] = {"status": first_fail[0], "test": first_fail[1]}
        return out
    except Exception as e:  # noqa
        out["verdict"] = "SE"
        out["compile"] = "Ошибка проверяющей системы: %s" % e
        return out
    finally:
        shutil.rmtree(wd, ignore_errors=True)


def run_custom(lang, code, inputs, workroot, cfg, tl=2, ml=256):
    """Запуск программы на произвольных входных данных (учитель: получить ответы эталонным решением)."""
    wd = tempfile.mkdtemp(prefix="st_", dir=workroot)
    try:
        cmd, msg, bad = compile_source(lang, code, wd, cfg)
        if bad:
            return {"verdict": bad, "compile": msg, "outputs": []}
        env = dict(os.environ)
        env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
        if cmd[0] == sys.executable and getattr(sys, "frozen", False):
            env["_MEIPASS2"] = getattr(sys, "_MEIPASS", "")
        outs = []
        rundir = os.path.join(wd, "run")
        for inp in inputs:
            if os.path.isdir(rundir):
                shutil.rmtree(rundir, ignore_errors=True)
            os.makedirs(rundir)
            if inp and not inp.endswith("\n"):
                inp += "\n"
            with open(os.path.join(rundir, "input.txt"), "w", encoding="utf-8", newline="\n") as f:
                f.write(inp)
            stdin_p = os.path.join(wd, "stdin.txt")
            with open(stdin_p, "w", encoding="utf-8", newline="\n") as f:
                f.write(inp)
            r = run_limited(cmd, rundir, stdin_p, os.path.join(wd, "stdout.txt"), os.path.join(wd, "stderr.txt"), tl, ml, env)
            outp = os.path.join(rundir, "output.txt")
            got = _read(outp) if _check_size(outp) else _read(os.path.join(wd, "stdout.txt"))
            outs.append({"status": {"ok": "OK", "tl": "TL", "ml": "ML", "re": "RE", "ol": "OL"}[r["status"]], "output": got,
                         "time": round(r["time"], 3), "stderr": _short_err(_read(os.path.join(wd, "stderr.txt"), 4000), 1500)})
        return {"verdict": "OK", "compile": msg, "outputs": outs}
    finally:
        shutil.rmtree(wd, ignore_errors=True)


# ------------------------------------------------------------------ очередь проверки
class Queue(object):
    """Фоновая очередь посылок: несколько потоков-проверяющих, состояние — в базе."""

    def __init__(self, workers=2):
        self.q = queue.Queue()
        self.workers = []
        self.n = max(1, int(workers))
        self.handler = None
        self.lock = threading.Lock()
        self.busy = {}

    def start(self, handler):
        self.handler = handler
        for i in range(self.n):
            th = threading.Thread(target=self._loop, daemon=True, name="judge-%d" % i)
            th.start()
            self.workers.append(th)

    def put(self, sid):
        self.q.put(sid)

    def _loop(self):
        while True:
            sid = self.q.get()
            try:
                self.handler(sid)
            except Exception as e:  # noqa
                sys.stderr.write("Ошибка проверки посылки %s: %s\n" % (sid, e))


def pyrun(path):
    """SchoolTest.exe --pyrun solution.py — запуск решения встроенным Python."""
    import runpy
    sys.argv = [path]
    sys.path.insert(0, os.path.dirname(os.path.abspath(path)))
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        runpy.run_path(path, run_name="__main__")
    except SystemExit as e:
        code = e.code
        sys.stdout.flush()
        os._exit(code if isinstance(code, int) else (0 if code is None else 1))
    except BaseException:
        import traceback
        traceback.print_exc()
        sys.stdout.flush()
        os._exit(1)
    sys.stdout.flush()
    os._exit(0)


def summary_json(res):
    return json.dumps(res, ensure_ascii=False)
