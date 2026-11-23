# -*- coding: utf-8 -*-
"""Динамика класса (1.5): средний результат класса по тестам во времени и освоение тем
(тема — тег вопроса; если тегов нет, темой считается задание теста)."""
import time

from . import attempts as A, grading as G
from .web import router, db, need, is_admin

PERIODS = {"quarter": 92, "half": 183, "year": 366, "all": 0}


def _topics_of(q, task_titles):
    tags = q["body"].get("tags") or []
    if tags:
        return tags
    ttl = task_titles.get(q["task_id"])
    return [ttl] if ttl else []


@router.route("GET", "/api/dynamics")
def api_dynamics(req):
    cid = req.arg("class_id")
    period = req.arg("period") or "quarter"
    need(period in PERIODS, "Неизвестный период", 400)
    where, args = ["r.mode='online'", "COALESCE(r.kind,'')<>'psy'", "r.test_id IS NOT NULL"], []
    if not is_admin(req):
        where.append("r.teacher_id=?")
        args.append(req.user["id"])
    if PERIODS[period]:
        where.append("r.created_at>=?")
        args.append(time.time() - PERIODS[period] * 86400)
    if cid:
        where.append("r.class_id=?")
        args.append(int(cid))
    runs = db().q("SELECT r.*, c.name AS class_name FROM runs r LEFT JOIN classes c ON c.id=r.class_id WHERE " + " AND ".join(where)
                  + " ORDER BY r.created_at", tuple(args))
    subj_f, tag_f = (req.arg("subject") or "").strip(), (req.arg("tag") or "").strip()
    series, topics, subjects, all_tags = [], {}, set(), set()
    for r in runs:
        snap = A.snapshot_for(r["id"])
        if not snap:
            continue
        subj = snap["test"].get("subject") or ""
        if subj:
            subjects.add(subj)
        if subj_f and subj != subj_f:
            continue
        scale = snap["test"]["settings"]["scale"]
        qs = dict((q["id"], q) for q in snap["questions"])
        titles = dict((t["id"], t["title"]) for t in snap["tasks"] if t.get("title"))
        atts = db().q("SELECT id, percent FROM attempts WHERE run_id=? AND status='finished' AND paper=0 AND percent IS NOT NULL", (r["id"],))
        if not atts:
            continue
        for q in qs.values():
            all_tags.update(_topics_of(q, titles))
        per_tag = {}
        for a in atts:
            for row in db().q("SELECT qid, auto, manual FROM answers WHERE attempt_id=?", (a["id"],)):
                q = qs.get(row["qid"])
                if not q or q["type"] in G.UNSCORED_TYPES:
                    continue
                got = row["manual"] if row["manual"] is not None else row["auto"]
                if got is None:
                    continue
                mx = G.question_points(q, scale)
                for tg in _topics_of(q, titles):
                    d = per_tag.setdefault(tg, [0.0, 0.0])
                    d[0] += got
                    d[1] += mx
        if tag_f and tag_f not in per_tag:
            continue
        pcts = [a["percent"] for a in atts]
        series.append({"run_id": r["id"], "date": time.strftime("%Y-%m-%d", time.localtime(r["created_at"])),
                       "title": r["title"], "class": r["class_name"], "subject": subj, "n": len(atts),
                       "avg": round(sum(pcts) / len(pcts), 1)})
        for tg, (g, m) in per_tag.items():
            if m > 0 and (not tag_f or tg == tag_f):
                topics.setdefault(tg, []).append({"run_id": r["id"], "date": series[-1]["date"], "pct": round(100.0 * g / m, 1)})
    out = []
    for tg, pts in sorted(topics.items()):
        trend, delta = "new", 0.0
        if len(pts) >= 2:
            half = max(1, len(pts) // 2)
            first = sum(p["pct"] for p in pts[:half]) / half
            last = sum(p["pct"] for p in pts[-half:]) / half
            delta = round(last - first, 1)
            trend = "up" if delta >= 5 else ("down" if delta <= -5 else "flat")
        out.append({"tag": tg, "points": pts, "last": pts[-1]["pct"], "trend": trend, "delta": delta})
    return {"series": series, "topics": out, "subjects": sorted(subjects), "tags": sorted(all_tags), "period": period}
