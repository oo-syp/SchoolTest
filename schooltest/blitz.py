# -*- coding: utf-8 -*-
"""Блиц-опрос (в духе Kahoot!): вопросы идут строго по таймеру, ход игры вычисляется
из времени старта, поэтому фоновых потоков не нужно. Публичный экран — /blitz/<код>/screen
(без входа), обновляется по Server-Sent Events. Результаты попадают в обычные попытки."""
import json
import queue
import threading
import time

from . import attempts as A
from . import engine as E, grading as G
from .web import router, ApiError, db, need, app
from . import api_student as S

COUNTDOWN = 5          # секунд до первого вопроса
REVEAL = 7             # показ правильного ответа и рейтинга
DEFAULT_SECONDS = 20
MIN_SECONDS = 5
GAMES = {}
LOCK = threading.RLock()
CHOICE = ("single", "multi")
SUPPORTED = ("single", "multi", "short", "num")


class Game(object):
    def __init__(self, run_id):
        self.run_id = run_id
        self.start = None          # момент начала первого вопроса (после обратного отсчёта)
        self.answers = {}          # qid -> {attempt_id: (response, elapsed)}
        self.finalized = False
        self.clients = set()


def is_blitz(snap):
    return bool(snap["test"]["settings"].get("blitz"))


def game_for(run_id):
    with LOCK:
        g = GAMES.get(run_id)
        if not g:
            if len(GAMES) > 100:
                GAMES.clear()
            g = GAMES[run_id] = Game(run_id)
        return g


def _timeline(snap):
    """[(qid, длительность)] — общий порядок вопросов блица."""
    st = snap["test"]["settings"]
    base = max(MIN_SECONDS, int(st.get("blitz_seconds") or DEFAULT_SECONDS))
    out = []
    for q in snap["questions"]:
        if q["type"] in SUPPORTED:
            out.append((q["id"], max(MIN_SECONDS, int(q["body"].get("time") or base))))
    return out


def _phase(g, snap, now=None):
    now = now or time.time()
    tl = _timeline(snap)
    if g.start is None:
        return {"phase": "lobby", "n": len(tl)}
    t = now - g.start
    if t < 0:
        return {"phase": "countdown", "left": -t, "n": len(tl)}
    for i, (qid, d) in enumerate(tl):
        if t < d:
            return {"phase": "question", "i": i, "qid": qid, "left": d - t, "dur": d, "elapsed": t, "n": len(tl)}
        t -= d
        if t < REVEAL:
            return {"phase": "reveal", "i": i, "qid": qid, "left": REVEAL - t, "dur": d, "n": len(tl),
                    "last": i == len(tl) - 1}
        t -= REVEAL
    return {"phase": "done", "n": len(tl)}


def _answer_points(q, resp, elapsed, dur):
    res = G.check(q, resp)
    if not res:
        return 0
    return int(round(1000 * res["frac"] * (1 - 0.5 * min(1.0, max(0.0, elapsed / float(dur))))))


def _scores(g, snap, upto_i):
    """Очки по ходу игры: {attempt_id: сумма} для вопросов с номером ≤ upto_i."""
    qs = E.qmap(snap)
    tl = _timeline(snap)
    tot = {}
    for i, (qid, d) in enumerate(tl):
        if i > upto_i:
            break
        for aid, (resp, el) in (g.answers.get(qid) or {}).items():
            tot[aid] = tot.get(aid, 0) + _answer_points(qs[qid], resp, el, d)
    return tot


def _names(run_id):
    return dict((r["id"], r["student_name"]) for r in db().q("SELECT id, student_name FROM attempts WHERE run_id=?", (run_id,)))


def _ranking(g, snap, upto_i, limit=10):
    names = _names(g.run_id)
    tot = _scores(g, snap, upto_i)
    for aid in names:
        tot.setdefault(aid, 0)
    rows = sorted(tot.items(), key=lambda kv: (-kv[1], names.get(kv[0], "")))
    return [{"aid": aid, "name": names.get(aid, "?"), "score": sc, "place": i + 1} for i, (aid, sc) in enumerate(rows)][:limit if limit else None]


def _histogram(q, answers):
    b = q["body"]
    if q["type"] not in CHOICE:
        return None
    cnt = dict((str(o["id"]), 0) for o in b.get("options", []))
    for resp, _el in answers.values():
        r = resp or {}
        ch = [r.get("choice")] if q["type"] == "single" else (r.get("choices") or [])
        for c in ch:
            if c is not None and str(c) in cnt:
                cnt[str(c)] += 1
    return cnt


def public_state(run, g, snap, full=False):
    """Состояние для экрана и учеников. Правильные ответы — только в фазе reveal/done."""
    ph = _phase(g, snap)
    st = snap["test"]["settings"]
    qs = E.qmap(snap)
    out = {"phase": ph["phase"], "title": snap["test"]["title"], "n": ph["n"], "code": run["code"],
           "joined": db().val("SELECT COUNT(*) FROM attempts WHERE run_id=?", (run["id"],)) or 0}
    if ph["phase"] in ("countdown",):
        out["left"] = round(ph["left"], 1)
    if ph["phase"] in ("question", "reveal"):
        q = qs[ph["qid"]]
        pq = E.public_question(q, {"o": {}})
        pq = {"id": pq["id"], "type": pq["type"], "text": pq["text"], "options": pq.get("options"),
              "fields": pq.get("fields"), "unit": pq.get("unit")}
        answers = g.answers.get(ph["qid"]) or {}
        out.update({"i": ph["i"], "q": pq, "left": round(ph["left"], 1), "dur": ph["dur"], "answered": len(answers),
                    "hist": _histogram(q, answers)})
        if ph["phase"] == "reveal":
            out["correct"] = E.correct_view(q)
            out["top"] = _ranking(g, snap, ph["i"], 5)
            out["last"] = ph.get("last", False)
    if ph["phase"] == "done":
        out["top"] = _ranking(g, snap, 10 ** 6, 10)
    return out


def finalize(run, g, snap):
    """Игра окончена: завершить попытки (ответы уже в таблице answers) — отметки появятся в журнале результатов."""
    with LOCK:
        if g.finalized:
            return
        g.finalized = True
    for a in db().q("SELECT id FROM attempts WHERE run_id=? AND status='active'", (run["id"],)):
        A.finish(a["id"], "blitz")


def _tick(run, g, snap):
    if _phase(g, snap)["phase"] == "done":
        finalize(run, g, snap)


def _run_by_code(code):
    code = "".join(ch for ch in str(code or "") if ch.isdigit())
    run = db().one("SELECT * FROM runs WHERE code=? AND mode='online'", (code,)) if code else None
    if not run:
        return None, None
    snap = A.snapshot_for(run["id"])
    return (run, snap) if snap and is_blitz(snap) else (None, None)


# ------------------------------------------------------------------ SSE и экран (без входа)

def public_get(h, path, query):
    parts = [x for x in path.split("/") if x]
    if len(parts) != 3 or parts[0] != "blitz":
        return h._send(404, "Не найдено", "text/plain; charset=utf-8")
    run, snap = _run_by_code(parts[1])
    if not run:
        return h._send(404, "Блиц-опрос с таким кодом не найден", "text/plain; charset=utf-8")
    if parts[2] == "screen":
        return h._send(200, SCREEN_HTML.replace("__CODE__", parts[1]).encode("utf-8"), "text/html; charset=utf-8",
                       [("Cache-Control", "no-store")])
    if parts[2] == "state":
        g = game_for(run["id"])
        _tick(run, g, snap)
        return h._send(200, json.dumps(public_state(run, g, snap), ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8", [("Cache-Control", "no-store")])
    if parts[2] == "events":
        return _events(h, run, snap)
    return h._send(404, "Не найдено", "text/plain; charset=utf-8")


def _events(h, run, snap):
    g = game_for(run["id"])
    q = queue.Queue(maxsize=20)
    with LOCK:
        if len(g.clients) >= 40:
            return h._send(503, "Слишком много экранов", "text/plain; charset=utf-8")
        g.clients.add(q)
    try:
        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream; charset=utf-8")
        h.send_header("Cache-Control", "no-cache")
        h.send_header("Connection", "close")
        h.send_header("X-Accel-Buffering", "no")
        h.end_headers()
        h.close_connection = True
        h.wfile.write(b"retry: 2000\n\n")
        last, idle = None, 0
        while True:
            _tick(run, g, snap)
            st = public_state(run, g, snap)
            # «left» меняется каждую секунду — экран считает таймер сам, поэтому в сравнении его нет
            key = json.dumps(dict((k, v) for k, v in st.items() if k != "left"), sort_keys=True, ensure_ascii=False)
            if key != last or idle >= 10:
                h.wfile.write(("event: state\ndata: %s\n\n" % json.dumps(st, ensure_ascii=False)).encode("utf-8"))
                h.wfile.flush()
                last, idle = key, 0
            try:
                q.get(timeout=0.5)
            except queue.Empty:
                idle += 0.5
    except (OSError, ValueError):
        pass
    finally:
        with LOCK:
            g.clients.discard(q)


def _poke(g):
    with LOCK:
        for q in list(g.clients):
            try:
                q.put_nowait(1)
            except queue.Full:
                pass


# ------------------------------------------------------------------ ведущий (учитель)

def _run_for_teacher(req, rid):
    from .api_runs import get_run
    r = get_run(rid, req)
    snap = A.snapshot_for(r["id"])
    need(is_blitz(snap), "Это не блиц-опрос", 400)
    return r, snap


@router.route("GET", "/api/runs/:rid/blitz")
def api_blitz_state(req, rid):
    r, snap = _run_for_teacher(req, rid)
    g = game_for(r["id"])
    _tick(r, g, snap)
    st = public_state(r, g, snap)
    st["players"] = [x["student_name"] for x in db().q("SELECT student_name FROM attempts WHERE run_id=? ORDER BY id", (r["id"],))]
    st["screen"] = "/blitz/%s/screen" % r["code"]
    st["skipped"] = [q["id"] for q in snap["questions"] if q["type"] not in SUPPORTED]
    return st


@router.route("POST", "/api/runs/:rid/blitz")
def api_blitz_action(req, rid):
    r, snap = _run_for_teacher(req, rid)
    g = game_for(r["id"])
    act = (req.json() or {}).get("action")
    now = time.time()
    ph = _phase(g, snap, now)
    if act == "start":
        need(ph["phase"] == "lobby", "Игра уже идёт", 409)
        need(ph["n"] > 0, "В тесте нет вопросов, подходящих для блица", 400)
        g.start = now + COUNTDOWN
    elif act == "skip":
        need(ph["phase"] in ("question", "reveal"), "Сейчас пропускать нечего", 409)
        g.start -= ph["left"]
    elif act == "reset":
        need(not db().val("SELECT COUNT(*) FROM attempts WHERE run_id=? AND status='finished'", (r["id"],)),
             "Игра уже завершена: результаты записаны", 409)
        g.start = None
        g.answers = {}
        db().ex("DELETE FROM answers WHERE attempt_id IN (SELECT id FROM attempts WHERE run_id=?)", (r["id"],))
    else:
        raise ApiError(400, "Неизвестное действие")
    _poke(g)
    return api_blitz_state(req, rid)


# ------------------------------------------------------------------ ученик

@router.route("GET", "/api/s/blitz/:aid", public=True)
def s_blitz_state(req, aid):
    a, _w = S._attempt(req, aid)
    run = db().one("SELECT * FROM runs WHERE id=?", (a["run_id"],))
    snap = A.snapshot_for(run["id"])
    need(is_blitz(snap), "Это не блиц-опрос", 400)
    g = game_for(run["id"])
    _tick(run, g, snap)
    st = public_state(run, g, snap)
    ph = _phase(g, snap)
    mine = None
    if ph["phase"] in ("question", "reveal"):
        mine = (g.answers.get(ph["qid"]) or {}).get(a["id"])
        st["my"] = None if not mine else mine[0]
        if ph["phase"] == "reveal":
            res = G.check(E.qmap(snap)[ph["qid"]], mine[0]) if mine else None
            st["my_ok"] = bool(res and res["frac"] >= 1)
            st["my_points"] = _answer_points(E.qmap(snap)[ph["qid"]], mine[0], mine[1], ph["dur"]) if mine else 0
    upto = ph.get("i", -1) if ph["phase"] == "reveal" else (10 ** 6 if ph["phase"] == "done" else ph.get("i", 0) - 1)
    full = _ranking(g, snap, upto, 0)
    me = [x for x in full if x["aid"] == a["id"]]
    st["me"] = {"score": me[0]["score"], "place": me[0]["place"], "of": len(full)} if me else None
    if st["phase"] != "done":
        st.pop("top", None) if st["phase"] != "reveal" else None
    st["student"] = a["student_name"]
    st["attempt_status"] = a["status"]
    return st


@router.route("PUT", "/api/s/blitz/:aid/answer", public=True)
def s_blitz_answer(req, aid):
    a, _w = S._attempt(req, aid)
    run = db().one("SELECT * FROM runs WHERE id=?", (a["run_id"],))
    snap = A.snapshot_for(run["id"])
    need(is_blitz(snap), "Это не блиц-опрос", 400)
    g = game_for(run["id"])
    ph = _phase(g, snap)
    d = req.json() or {}
    need(ph["phase"] == "question" and str(d.get("qid")) == ph["qid"], "Время на этот вопрос вышло", 409)
    q = E.qmap(snap)[ph["qid"]]
    resp = d.get("response")
    raw = json.dumps(resp, ensure_ascii=False)
    need(len(raw) <= 4096, "Слишком большой ответ", 413)
    with LOCK:
        cur = g.answers.setdefault(ph["qid"], {})
        need(a["id"] not in cur, "Ответ уже принят", 409)
        need(G.is_answered(q, resp), "Выберите или введите ответ", 400)
        cur[a["id"]] = (resp, ph["elapsed"])
    db().ex("INSERT INTO answers(attempt_id,qid,response,updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(attempt_id,qid) DO UPDATE SET response=excluded.response, updated_at=excluded.updated_at",
            (a["id"], ph["qid"], raw, time.time()))
    _poke(g)
    return {"ok": True}


SCREEN_HTML = r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Блиц-опрос</title>
<style>
*{box-sizing:border-box}body{margin:0;font:22px/1.35 system-ui,Segoe UI,Arial,sans-serif;background:#2b1b59;color:#fff;min-height:100vh;display:flex;flex-direction:column}
header{display:flex;justify-content:space-between;align-items:center;padding:14px 28px;background:rgba(0,0,0,.25)}
header b{font-size:26px}main{flex:1;padding:24px 28px;display:flex;flex-direction:column;gap:18px}
.q{font-size:clamp(28px,4vw,52px);font-weight:700;text-align:center;background:#fff;color:#222;border-radius:14px;padding:22px 26px}
.timer{font-size:56px;font-weight:800;min-width:90px;text-align:center}
.bar{height:12px;background:rgba(255,255,255,.25);border-radius:6px;overflow:hidden}.bar i{display:block;height:100%;background:#ffd24a;transition:width .3s linear}
.opts{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.opt{border-radius:12px;padding:18px 22px;font-size:clamp(20px,2.6vw,34px);font-weight:600;position:relative;overflow:hidden;min-height:84px;display:flex;align-items:center;gap:14px}
.opt .fill{position:absolute;left:0;bottom:0;height:8px;background:rgba(255,255,255,.85);transition:width .4s}
.opt .cnt{margin-left:auto;font-size:34px;font-weight:800}.opt.dim{opacity:.35}.opt.ok{outline:6px solid #fff}
.c0{background:#e21b3c}.c1{background:#1368ce}.c2{background:#d89e00}.c3{background:#26890c}.c4{background:#864cbf}.c5{background:#0aa3a3}
.big{font-size:clamp(40px,8vw,120px);font-weight:800;text-align:center;margin:auto}.code{font-size:clamp(50px,10vw,150px);letter-spacing:.1em}
.rank{width:100%;max-width:900px;margin:0 auto;display:flex;flex-direction:column;gap:10px}
.row{display:flex;gap:16px;background:rgba(255,255,255,.14);border-radius:10px;padding:12px 20px;font-size:30px;align-items:center}
.row b{width:44px}.row span{margin-left:auto;font-weight:800}.row.p1{background:#ffd24a;color:#222}
.meta{text-align:center;opacity:.85}.ans{text-align:center;font-size:34px;background:rgba(255,255,255,.14);border-radius:12px;padding:20px}
</style></head><body>
<header><b id="ttl">Блиц-опрос</b><span id="meta"></span></header>
<main id="m"><div class="big">…</div></main>
<script>
(function(){
var CODE="__CODE__",S=null,at=0,m=document.getElementById("m");
function esc(s){return String(s==null?"":s).replace(/[&<>"]/g,function(c){return{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
function left(){return S&&S.left!=null?Math.max(0,S.left-(Date.now()-at)/1000):0}
function rank(top){return '<div class="rank">'+top.map(function(r){return '<div class="row p'+r.place+'"><b>'+r.place+'</b>'+esc(r.name)+'<span>'+r.score+'</span></div>'}).join("")+'</div>'}
function draw(){
  if(!S)return;
  document.getElementById("ttl").textContent=S.title;
  document.getElementById("meta").textContent="Код: "+S.code+" · участников: "+S.joined;
  var h="";
  if(S.phase==="lobby")h='<div class="big">Присоединяйтесь!<br><span class="code">'+esc(S.code)+'</span><div class="meta">Участников: '+S.joined+'</div></div>';
  else if(S.phase==="countdown")h='<div class="big">Начинаем через<br>'+Math.ceil(left())+'</div>';
  else if(S.phase==="done")h='<div class="big" style="margin:0">Итоги</div>'+rank(S.top||[]);
  else{
    var q=S.q,rev=S.phase==="reveal",dur=S.dur||20,pct=rev?0:Math.max(0,left()/dur*100);
    h='<div style="display:flex;gap:20px;align-items:center"><div class="meta">'+(S.i+1)+' / '+S.n+'</div><div class="bar" style="flex:1"><i style="width:'+pct+'%"></i></div><div class="timer">'+(rev?"":Math.ceil(left()))+'</div></div>';
    h+='<div class="q">'+esc(q.text)+'</div>';
    if(q.options){
      var tot=0,mx=1;for(var k in S.hist){tot+=S.hist[k];mx=Math.max(mx,S.hist[k])}
      h+='<div class="opts">'+q.options.map(function(o,i){
        var n=(S.hist||{})[o.id]||0,ok=rev&&(S.correct.options||[]).map(String).indexOf(String(o.id))>=0;
        return '<div class="opt c'+(i%6)+(rev&&!ok?" dim":"")+(ok?" ok":"")+'">'+esc(o.text)+'<span class="cnt">'+n+'</span><i class="fill" style="width:'+(n/mx*100)+'%"></i></div>'}).join("")+'</div>';
    }else if(rev){h+='<div class="ans">Правильный ответ: <b>'+esc((S.correct.value!=null?S.correct.value+(S.correct.unit?" "+S.correct.unit:""):Object.keys(S.correct.fields||{}).map(function(k){return S.correct.fields[k]}).join("; ")))+'</b></div>'}
    h+='<div class="meta">Ответили: '+S.answered+' из '+S.joined+'</div>';
    if(rev&&S.top)h+=rank(S.top);
  }
  m.innerHTML=h;
}
var es=new EventSource("/blitz/"+CODE+"/events");
es.addEventListener("state",function(e){S=JSON.parse(e.data);at=Date.now();draw()});
setInterval(draw,250);
})();
</script></body></html>"""
