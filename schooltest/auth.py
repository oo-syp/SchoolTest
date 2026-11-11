# -*- coding: utf-8 -*-
"""Пользователи (администратор, учитель) и сессии. У учеников учётных записей нет."""
import binascii
import hashlib
import hmac
import os
import secrets
import string
import time

ROLES = {"admin": "Администратор", "teacher": "Учитель", "psychologist": "Педагог-психолог"}
SESSION_TTL = 12 * 3600
ITER = 120000


def hash_password(password, salt=None):
    if salt is None:
        salt = binascii.hexlify(os.urandom(16)).decode()
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode(), ITER)
    return binascii.hexlify(dk).decode(), salt


def check_password(password, pw_hash, salt):
    return hmac.compare_digest(hash_password(password, salt)[0], pw_hash)


def password_problem(pw):
    if len(pw or "") < 6:
        return "Пароль должен содержать не менее 6 символов"
    return None


def random_password(n=8):
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(n))


def ensure_admin(db):
    if db.val("SELECT COUNT(*) FROM users") == 0:
        h, s = hash_password("admin")
        db.ex("INSERT INTO users(login,pw_hash,pw_salt,full_name,role,must_change) VALUES('admin',?,?,'Администратор','admin',1)", (h, s))


def reset_admin(db):
    """Сброс пароля администратора из окна сервера (нужен доступ к компьютеру с программой)."""
    pw = random_password()
    h, s = hash_password(pw)
    row = db.one("SELECT id FROM users WHERE login='admin'")
    if row:
        db.ex("UPDATE users SET pw_hash=?, pw_salt=?, role='admin', active=1, must_change=1 WHERE id=?", (h, s, row["id"]))
    else:
        db.ex("INSERT INTO users(login,pw_hash,pw_salt,full_name,role,must_change) VALUES('admin',?,?,'Администратор','admin',1)", (h, s))
    db.ex("DELETE FROM sessions WHERE user_id=(SELECT id FROM users WHERE login='admin')")
    return pw


def login(db, name, password, ip):
    u = db.one("SELECT * FROM users WHERE login=? AND active=1", ((name or "").strip(),))
    if not u or not check_password(password or "", u["pw_hash"], u["pw_salt"]):
        return None
    token = secrets.token_urlsafe(32)
    now = time.time()
    db.ex("INSERT INTO sessions(token,user_id,created,seen,ip) VALUES(?,?,?,?,?)", (token, u["id"], now, now, ip))
    db.ex("UPDATE users SET last_login=CURRENT_TIMESTAMP WHERE id=?", (u["id"],))
    return token


def session_user(db, token):
    if not token:
        return None
    s = db.one("SELECT * FROM sessions WHERE token=?", (token,))
    if not s:
        return None
    now = time.time()
    if now - s["seen"] > SESSION_TTL:
        db.ex("DELETE FROM sessions WHERE token=?", (token,))
        return None
    if now - s["seen"] > 60:
        db.ex("UPDATE sessions SET seen=? WHERE token=?", (now, token))
    u = db.one("SELECT id, login, full_name, role, active, must_change FROM users WHERE id=?", (s["user_id"],))
    if not u or not u["active"]:
        return None
    return u


def logout(db, token):
    db.ex("DELETE FROM sessions WHERE token=?", (token,))


def is_admin(u):
    return bool(u) and u.get("role") == "admin"


def new_code(db):
    """6-значный код теста, не совпадающий с кодами открытых проведений."""
    while True:
        code = "".join(secrets.choice(string.digits) for _ in range(6))
        if code[0] != "0" and not db.val("SELECT 1 FROM runs WHERE code=? AND status='open'", (code,)):
            return code
