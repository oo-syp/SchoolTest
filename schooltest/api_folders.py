# -*- coding: utf-8 -*-
"""Каталогизация тестов (1.3): общие на школу папки произвольной вложенности.

Тест без folder_id считается лежащим в «корневой» папке (папки не требуется создавать).
Папки общие для всех педагогов — переименовать/удалить папку может любой учитель или психолог,
но переместить в неё тест может только тот, кто вправе редактировать сам тест (владелец или администратор).
"""
import json

from .web import router, db, need, is_admin
from . import api_tests


def _tree(kind):
    rows = db().q("SELECT * FROM folders WHERE kind=? ORDER BY sort, name COLLATE NOCASE", (kind,))
    by_parent = {}
    for r in rows:
        by_parent.setdefault(r["parent_id"], []).append(r)
    counts = dict((r["folder_id"], r["n"]) for r in db().q(
        "SELECT folder_id, COUNT(*) n FROM tests WHERE archived=0 GROUP BY folder_id") ) if kind == "test" else {}

    def build(pid):
        out = []
        for r in by_parent.get(pid, []):
            node = dict(r)
            node["count"] = counts.get(r["id"], 0)
            node["children"] = build(r["id"])
            out.append(node)
        return out

    return build(None)


@router.route("GET", "/api/folders")
def api_folders_list(req):
    kind = req.arg("kind") or "test"
    root_count = db().val("SELECT COUNT(*) FROM tests WHERE archived=0 AND folder_id IS NULL") if kind == "test" else 0
    return {"tree": _tree(kind), "root_count": root_count}


@router.route("POST", "/api/folders")
def api_folder_add(req):
    need(req.user and req.user["role"] in ("teacher", "psychologist", "admin"), "Недостаточно прав")
    d = req.json()
    name = (d.get("name") or "").strip()
    need(name, "Укажите название папки", 400)
    parent_id = d.get("parent_id") or None
    if parent_id is not None:
        need(db().one("SELECT id FROM folders WHERE id=?", (parent_id,)), "Родительская папка не найдена", 404)
    fid = db().insert("folders", {"parent_id": parent_id, "kind": d.get("kind") or "test", "name": name})
    db().audit(req.user, req.ip, "folder_add", name)
    return {"id": fid}


@router.route("PUT", "/api/folders/:fid")
def api_folder_put(req, fid):
    need(req.user and req.user["role"] in ("teacher", "psychologist", "admin"), "Недостаточно прав")
    f = db().one("SELECT * FROM folders WHERE id=?", (int(fid),))
    need(f, "Папка не найдена", 404)
    d = req.json()
    row = {}
    if "name" in d:
        name = (d.get("name") or "").strip()
        need(name, "Укажите название папки", 400)
        row["name"] = name
    if "parent_id" in d:
        pid = d.get("parent_id") or None
        if pid is not None:
            need(int(pid) != int(fid), "Папка не может быть вложена сама в себя", 400)
            chain = set()
            cur = db().one("SELECT id, parent_id FROM folders WHERE id=?", (pid,))
            while cur:
                need(cur["id"] != int(fid), "Нельзя переместить папку внутрь её собственной подпапки", 400)
                chain.add(cur["id"])
                cur = db().one("SELECT id, parent_id FROM folders WHERE id=?", (cur["parent_id"],)) if cur["parent_id"] else None
        row["parent_id"] = pid
    if "sort" in d:
        row["sort"] = int(d["sort"] or 0)
    if row:
        db().update("folders", int(fid), row)
    return {"ok": True}


@router.route("DELETE", "/api/folders/:fid")
def api_folder_delete(req, fid):
    need(req.user and req.user["role"] in ("teacher", "psychologist", "admin"), "Недостаточно прав")
    f = db().one("SELECT * FROM folders WHERE id=?", (int(fid),))
    need(f, "Папка не найдена", 404)
    with db().tx():
        db().ex("UPDATE tests SET folder_id=NULL WHERE folder_id=?", (int(fid),))
        db().ex("UPDATE folders SET parent_id=NULL WHERE parent_id=?", (int(fid),))
        db().ex("DELETE FROM folders WHERE id=?", (int(fid),))
    db().audit(req.user, req.ip, "folder_delete", f["name"])
    return {"ok": True}


@router.route("POST", "/api/tests/:tid/move")
def api_test_move(req, tid):
    """Переместить тест в папку (null — в корень)."""
    t = api_tests.get_test(tid, req, write=True)
    d = req.json()
    fid = d.get("folder_id") or None
    if fid is not None:
        need(db().one("SELECT id FROM folders WHERE id=?", (fid,)), "Папка не найдена", 404)
    db().update("tests", t["id"], {"folder_id": fid})
    return {"ok": True}
