# -*- coding: utf-8 -*-
"""База данных SchoolTest (SQLite, один файл рядом с программой)."""
import json
import os
import sqlite3
import threading
import time

SCHEMA_VERSION = 2

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    login TEXT NOT NULL UNIQUE COLLATE NOCASE,
    pw_hash TEXT NOT NULL, pw_salt TEXT NOT NULL,
    full_name TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'teacher',
    active INTEGER NOT NULL DEFAULT 1,
    must_change INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    last_login TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created REAL NOT NULL, seen REAL NOT NULL, ip TEXT
);

CREATE TABLE IF NOT EXISTS classes (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    grade INTEGER,
    sg_id INTEGER,
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY,
    class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
    last_name TEXT NOT NULL DEFAULT '', first_name TEXT NOT NULL DEFAULT '', middle_name TEXT NOT NULL DEFAULT '',
    sg_id INTEGER,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_students_class ON students(class_id);

CREATE TABLE IF NOT EXISTS tests (
    id INTEGER PRIMARY KEY,
    owner_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    title TEXT NOT NULL DEFAULT '',
    subject TEXT NOT NULL DEFAULT '',
    grade INTEGER,
    description TEXT NOT NULL DEFAULT '',
    settings TEXT NOT NULL DEFAULT '{}',
    shared INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- задания теста (разделы): уровень I–V для оценки по нормам, банк — выбор pick вопросов
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY,
    test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
    num INTEGER NOT NULL DEFAULT 1,
    title TEXT NOT NULL DEFAULT '',
    level INTEGER,
    pick INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_tasks_test ON tasks(test_id, num);

CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY,
    test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    variant INTEGER NOT NULL DEFAULT 0,
    type TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '{}',
    answer TEXT NOT NULL DEFAULT '{}',
    points REAL NOT NULL DEFAULT 1,
    sort INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_questions_test ON questions(test_id, task_id, sort);

CREATE TABLE IF NOT EXISTS media (
    id INTEGER PRIMARY KEY,
    test_id INTEGER REFERENCES tests(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    mime TEXT NOT NULL DEFAULT 'application/octet-stream',
    size INTEGER NOT NULL DEFAULT 0,
    sha1 TEXT,
    data BLOB
);
CREATE INDEX IF NOT EXISTS ix_media_test ON media(test_id);

-- проведение теста: снимок теста на момент запуска хранится в snapshot
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    test_id INTEGER REFERENCES tests(id) ON DELETE SET NULL,
    class_id INTEGER REFERENCES classes(id) ON DELETE SET NULL,
    teacher_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    title TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT 'online',
    code TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    snapshot TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    closed_at REAL,
    sg_sent TEXT
);
CREATE INDEX IF NOT EXISTS ix_runs_code ON runs(code, status);

CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    student_id INTEGER REFERENCES students(id) ON DELETE SET NULL,
    student_name TEXT NOT NULL DEFAULT '',
    num INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'active',
    variant INTEGER NOT NULL DEFAULT 1,
    plan TEXT NOT NULL DEFAULT '[]',
    cur INTEGER NOT NULL DEFAULT 0,
    device TEXT,
    pending_device TEXT,
    started_at REAL, deadline REAL, finished_at REAL, last_seen REAL,
    focus_lost INTEGER NOT NULL DEFAULT 0,
    focus_log TEXT NOT NULL DEFAULT '[]',
    score REAL, max_score REAL, percent REAL,
    mark TEXT,
    manual_mark TEXT,
    pending_manual INTEGER NOT NULL DEFAULT 0,
    paper INTEGER NOT NULL DEFAULT 0,
    UNIQUE(run_id, student_id, num)
);
CREATE INDEX IF NOT EXISTS ix_attempts_run ON attempts(run_id);
CREATE INDEX IF NOT EXISTS ix_attempts_student ON attempts(student_id);

CREATE TABLE IF NOT EXISTS answers (
    attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
    qid TEXT NOT NULL,
    response TEXT,
    auto REAL,
    manual REAL,
    comment TEXT NOT NULL DEFAULT '',
    plays INTEGER NOT NULL DEFAULT 0,
    updated_at REAL,
    PRIMARY KEY(attempt_id, qid)
);

CREATE TABLE IF NOT EXISTS uploads (
    id INTEGER PRIMARY KEY,
    attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
    qid TEXT NOT NULL,
    name TEXT NOT NULL, mime TEXT NOT NULL, size INTEGER NOT NULL,
    data BLOB,
    created_at REAL
);

-- учебные годы (1.1): классы принадлежат году, ученик переводится копией с тем же person_id
CREATE TABLE IF NOT EXISTS years (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    start_date TEXT, end_date TEXT,
    current INTEGER NOT NULL DEFAULT 0
);

-- посылки решений задач с кодом (1.1)
CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY,
    attempt_id INTEGER REFERENCES attempts(id) ON DELETE CASCADE,
    qid TEXT NOT NULL,
    lang TEXT NOT NULL,
    code TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    verdict TEXT,
    frac REAL,
    details TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    judged_at REAL
);
CREATE INDEX IF NOT EXISTS ix_subs_attempt ON submissions(attempt_id, qid);
CREATE INDEX IF NOT EXISTS ix_subs_status ON submissions(status);

CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY,
    at TEXT DEFAULT CURRENT_TIMESTAMP,
    user_id INTEGER, login TEXT, ip TEXT, action TEXT, details TEXT
);
"""


class Database(object):
    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init()

    def _init(self):
        with self.lock:
            self.conn.executescript(SCHEMA)
            if self.conn.execute("SELECT 1 FROM meta WHERE key='schema'").fetchone() is None:
                self.conn.execute("INSERT INTO meta(key,value) VALUES('schema',?)", (str(SCHEMA_VERSION),))
                self.conn.execute("INSERT OR IGNORE INTO meta(key,value) VALUES('app','SchoolTest')")
            self._migrate()

    def _cols(self, table):
        return [r[1] for r in self.conn.execute("PRAGMA table_info(%s)" % table)]

    def _migrate(self):
        """Обновление базы прежних версий: недостающие столбцы и учебный год для существующих классов."""
        add = [("classes", "year_id", "INTEGER REFERENCES years(id)"),
               ("students", "person_id", "INTEGER"),
               ("runs", "kind", "TEXT NOT NULL DEFAULT 'test'"),
               ("attempts", "psy", "TEXT"),
               ("attempts", "extra", "TEXT NOT NULL DEFAULT '{}'")]
        for table, col, decl in add:
            if col not in self._cols(table):
                self.conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, decl))
        self.conn.execute("CREATE INDEX IF NOT EXISTS ix_classes_year ON classes(year_id)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS ix_students_person ON students(person_id)")
        self.conn.execute("UPDATE students SET person_id=id WHERE person_id IS NULL")
        if self.conn.execute("SELECT COUNT(*) FROM years").fetchone()[0] == 0:
            y = time.localtime()
            start = y.tm_year if y.tm_mon >= 8 else y.tm_year - 1
            self.conn.execute("INSERT INTO years(name,start_date,end_date,current) VALUES(?,?,?,1)",
                              ("%d/%d" % (start, start + 1), "%d-09-01" % start, "%d-08-31" % (start + 1)))
        if self.conn.execute("SELECT COUNT(*) FROM years WHERE current=1").fetchone()[0] == 0:
            self.conn.execute("UPDATE years SET current=1 WHERE id=(SELECT MAX(id) FROM years)")
        cur = self.conn.execute("SELECT id FROM years WHERE current=1").fetchone()[0]
        self.conn.execute("UPDATE classes SET year_id=? WHERE year_id IS NULL", (cur,))
        self.conn.execute("UPDATE meta SET value=? WHERE key='schema'", (str(SCHEMA_VERSION),))

    def current_year(self):
        return self.val("SELECT id FROM years WHERE current=1") or self.val("SELECT MAX(id) FROM years")

    # ------------------------------------------------------------ helpers
    def q(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        with self.lock:
            r = self.conn.execute(sql, args).fetchone()
            return dict(r) if r else None

    def val(self, sql, args=()):
        with self.lock:
            r = self.conn.execute(sql, args).fetchone()
            return r[0] if r else None

    def ex(self, sql, args=()):
        with self.lock:
            return self.conn.execute(sql, args).lastrowid

    def tx(self):
        return _Tx(self)

    def insert(self, table, row):
        cols = list(row)
        return self.ex("INSERT INTO %s(%s) VALUES(%s)" % (table, ",".join(cols), ",".join("?" * len(cols))),
                       [row[c] for c in cols])

    def update(self, table, rid, row, key="id"):
        if not row:
            return
        self.ex("UPDATE %s SET %s WHERE %s=?" % (table, ",".join(c + "=?" for c in row), key),
                list(row.values()) + [rid])

    # ------------------------------------------------------------ settings
    def get_setting(self, key, default=None):
        v = self.val("SELECT value FROM settings WHERE key=?", (key,))
        if v is None:
            return default
        try:
            return json.loads(v)
        except ValueError:
            return v

    def set_setting(self, key, value):
        self.ex("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value, ensure_ascii=False)))

    def audit(self, user, ip, action, details=""):
        try:
            if not isinstance(details, str):
                details = json.dumps(details, ensure_ascii=False)
            self.ex("INSERT INTO audit(user_id,login,ip,action,details) VALUES(?,?,?,?,?)",
                    (user and user.get("id"), user and user.get("login"), ip, action, details[:4000]))
        except Exception:
            pass

    # ------------------------------------------------------------ резервные копии
    def backup(self, dest_dir, label="manual"):
        if not os.path.isdir(dest_dir):
            os.makedirs(dest_dir)
        dest = os.path.join(dest_dir, "schooltest_{}_{}.db".format(time.strftime("%Y-%m-%d_%H-%M-%S"), label))
        with self.lock:
            target = sqlite3.connect(dest)
            try:
                self.conn.backup(target)
            finally:
                target.close()
        return dest

    def prune_backups(self, dest_dir, keep=30):
        try:
            files = sorted(f for f in os.listdir(dest_dir) if f.startswith("schooltest_") and f.endswith(".db"))
            for f in files[:-keep]:
                os.remove(os.path.join(dest_dir, f))
        except OSError:
            pass

    def restore(self, src):
        with self.lock:
            check = sqlite3.connect(src)
            try:
                tables = [r[0] for r in check.execute("SELECT name FROM sqlite_master WHERE type='table'")]
                if "attempts" not in tables or "questions" not in tables:
                    raise ValueError("Файл не является базой SchoolTest")
                check.backup(self.conn)
            finally:
                check.close()
            self._init()

    def close(self):
        with self.lock:
            self.conn.close()


class _Tx(object):
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        self.db.lock.acquire()
        self.db.conn.execute("BEGIN IMMEDIATE")
        return self.db

    def __exit__(self, et, ev, tb):
        try:
            self.db.conn.execute("COMMIT" if et is None else "ROLLBACK")
        finally:
            self.db.lock.release()
        return False
