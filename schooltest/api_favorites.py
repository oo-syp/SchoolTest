# -*- coding: utf-8 -*-
"""Избранное (1.3): педагог закрепляет тесты и методики психодиагностики — своё у каждого пользователя."""
import time

from .web import router, db, need


@router.route("GET", "/api/favorites")
def api_favorites_list(req):
    kind = req.arg("kind")
    sql = "SELECT kind, ref FROM favorites WHERE user_id=?"
    args = [req.user["id"]]
    if kind:
        sql += " AND kind=?"
        args.append(kind)
    rows = db().q(sql, tuple(args))
    return {"items": [{"kind": r["kind"], "ref": r["ref"]} for r in rows]}


@router.route("POST", "/api/favorites/toggle")
def api_favorites_toggle(req):
    d = req.json()
    kind = (d.get("kind") or "").strip()
    ref = str(d.get("ref") or "").strip()
    need(kind in ("test", "psy") and ref, "Некорректные данные", 400)
    row = db().one("SELECT 1 FROM favorites WHERE user_id=? AND kind=? AND ref=?", (req.user["id"], kind, ref))
    if row:
        db().ex("DELETE FROM favorites WHERE user_id=? AND kind=? AND ref=?", (req.user["id"], kind, ref))
        return {"favorite": False}
    db().ex("INSERT INTO favorites(user_id, kind, ref, created_at) VALUES(?,?,?,?)",
            (req.user["id"], kind, ref, time.time()))
    return {"favorite": True}
