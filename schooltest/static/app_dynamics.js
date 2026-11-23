/* SchoolTest 1.5 — «Динамика класса»: линия среднего по тестам и освоение тем (чистый SVG) */
"use strict";
(function () {
  var h = ST.h, t = ST.t, api = ST.api;
  var NS = "http://www.w3.org/2000/svg";
  function el(name, attrs, kids) {
    var e = document.createElementNS(NS, name);
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    (kids || []).forEach(function (c) { e.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return e;
  }
  function colorOf(p) {      // тепловая шкала: красный → жёлтый → зелёный
    var x = Math.max(0, Math.min(100, p)) / 100;
    var hue = Math.round(120 * x);
    return "hsl(" + hue + ",65%," + (x < 0.5 ? 55 : 48) + "%)";
  }
  function dshort(d) { return d.slice(8, 10) + "." + d.slice(5, 7); }

  A.dynLine = function (series) {
    var W = 760, H = 300, L = 44, R = 16, T = 16, B = 46;
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, class: "dynchart", role: "img", "aria-label": t("Средний результат класса по тестам") });
    for (var g = 0; g <= 100; g += 20) {
      var y = T + (H - T - B) * (1 - g / 100);
      svg.appendChild(el("line", { x1: L, x2: W - R, y1: y, y2: y, stroke: "currentColor", "stroke-opacity": ".12" }));
      svg.appendChild(el("text", { x: L - 6, y: y + 4, "text-anchor": "end", "font-size": 11, fill: "currentColor", "fill-opacity": ".6" }, [g + "%"]));
    }
    var n = series.length, pts = series.map(function (s, i) {
      return { x: n === 1 ? (L + W - R) / 2 : L + (W - L - R) * i / (n - 1), y: T + (H - T - B) * (1 - s.avg / 100), s: s };
    });
    if (n > 1) svg.appendChild(el("polyline", { points: pts.map(function (p) { return p.x + "," + p.y; }).join(" "), fill: "none", stroke: "#2b6cb0", "stroke-width": 2.5 }));
    pts.forEach(function (p, i) {
      var c = el("circle", { cx: p.x, cy: p.y, r: 5, fill: "#2b6cb0" }, [el("title", {}, [p.s.title + " — " + p.s.avg + "% (" + p.s.n + ")"])]);
      svg.appendChild(c);
      svg.appendChild(el("text", { x: p.x, y: p.y - 10, "text-anchor": "middle", "font-size": 11, fill: "currentColor" }, [String(Math.round(p.s.avg))]));
      if (n <= 14 || i % Math.ceil(n / 14) === 0) svg.appendChild(el("text", { x: p.x, y: H - B + 16, "text-anchor": "middle", "font-size": 11, fill: "currentColor", "fill-opacity": ".7" }, [dshort(p.s.date)]));
    });
    return svg;
  };

  A.dynHeat = function (D) {
    var runs = D.series, topics = D.topics;
    var cw = Math.max(34, Math.min(70, Math.floor(560 / Math.max(1, runs.length)))), rh = 30, lw = 190;
    var W = lw + cw * runs.length + 150, H = 30 + rh * topics.length + 10;
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, class: "dynchart", role: "img", "aria-label": t("Освоение тем"), style: "min-width:" + Math.min(W, 900) + "px" });
    runs.forEach(function (r, j) {
      svg.appendChild(el("text", { x: lw + cw * j + cw / 2, y: 20, "text-anchor": "middle", "font-size": 11, fill: "currentColor", "fill-opacity": ".7" }, [dshort(r.date)]));
    });
    var ARROW = { up: ["▲ " + t("растёт"), "#1a7f2e"], down: ["▼ " + t("падает"), "#c0262d"], flat: ["● " + t("стоит"), "#8a6d00"], "new": ["· " + t("мало данных"), "#777"] };
    topics.forEach(function (tp, i) {
      var y = 30 + rh * i;
      svg.appendChild(el("text", { x: lw - 8, y: y + rh / 2 + 4, "text-anchor": "end", "font-size": 13, fill: "currentColor" }, [tp.tag.length > 26 ? tp.tag.slice(0, 25) + "…" : tp.tag]));
      var by = {};
      tp.points.forEach(function (p) { by[p.run_id] = p; });
      runs.forEach(function (r, j) {
        var p = by[r.run_id];
        if (!p) { svg.appendChild(el("rect", { x: lw + cw * j + 1, y: y + 1, width: cw - 2, height: rh - 2, rx: 3, fill: "currentColor", "fill-opacity": ".06" })); return; }
        svg.appendChild(el("rect", { x: lw + cw * j + 1, y: y + 1, width: cw - 2, height: rh - 2, rx: 3, fill: colorOf(p.pct) }, [el("title", {}, [tp.tag + ", " + r.title + ": " + p.pct + "%"])]));
        svg.appendChild(el("text", { x: lw + cw * j + cw / 2, y: y + rh / 2 + 4, "text-anchor": "middle", "font-size": 11, fill: "#111" }, [String(Math.round(p.pct))]));
      });
      var a = ARROW[tp.trend];
      svg.appendChild(el("text", { x: lw + cw * runs.length + 12, y: y + rh / 2 + 4, "font-size": 13, "font-weight": 600, fill: a[1] }, [a[0] + (tp.trend === "new" ? "" : " " + (tp.delta > 0 ? "+" : "") + tp.delta)]));
    });
    return svg;
  };

  A.dynBars = function (topics) {
    var lw = 190, W = 760, rh = 26, H = topics.length * rh + 8;
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, class: "dynchart", role: "img", "aria-label": t("Освоение тем сейчас") });
    topics.slice().sort(function (a, b) { return a.last - b.last; }).forEach(function (tp, i) {
      var y = 4 + i * rh, w = (W - lw - 60) * tp.last / 100;
      svg.appendChild(el("text", { x: lw - 8, y: y + 16, "text-anchor": "end", "font-size": 13, fill: "currentColor" }, [tp.tag.length > 26 ? tp.tag.slice(0, 25) + "…" : tp.tag]));
      svg.appendChild(el("rect", { x: lw, y: y + 3, width: Math.max(2, w), height: rh - 8, rx: 3, fill: colorOf(tp.last) }));
      svg.appendChild(el("text", { x: lw + w + 6, y: y + 16, "font-size": 12, fill: "currentColor" }, [tp.last + "%"]));
    });
    return svg;
  };

  A.route("dynamics", function (box, args, q) {
    A.head(box, t("Динамика класса"), t("Как меняются результаты класса от теста к тесту и какие темы осваиваются лучше или хуже."));
    box.appendChild(A.tabs([["runs", "#/runs", t("Запуски")], ["dyn", "#/dynamics", t("Динамика класса")]], "dyn"));
    var cls = A.select([["", t("Все")]], q.class_id || ""), per = A.select([["quarter", t("Четверть (3 мес.)")], ["half", t("Полугодие")], ["year", t("Год")], ["all", t("Всё время")]], q.period || "quarter");
    var subj = A.select([["", t("Все предметы")]], ""), tag = A.select([["", t("Все темы")]], "");
    var out = h("div");
    box.appendChild(h("div", { class: "bar" }, A.field(A.N("class"), cls), A.field(t("Период"), per), A.field(t("Предмет"), subj), A.field(t("Тема"), tag)));
    box.appendChild(out);
    function fill(sel, first, items, keep) {
      var cur = keep;
      sel.innerHTML = "";
      sel.appendChild(h("option", { value: "" }, first));
      items.forEach(function (x) { var o = h("option", { value: x[0] }, x[1]); sel.appendChild(o); });
      sel.value = cur || "";
    }
    var loaded = false;
    function load() {
      var u = "/api/dynamics?period=" + per.value + (cls.value ? "&class_id=" + cls.value : "") + (subj.value ? "&subject=" + encodeURIComponent(subj.value) : "") + (tag.value ? "&tag=" + encodeURIComponent(tag.value) : "");
      api("GET", u).then(function (D) {
        if (!loaded) { fill(subj, t("Все предметы"), D.subjects.map(function (s) { return [s, s]; }), subj.value); }
        fill(tag, t("Все темы"), D.tags.map(function (s) { return [s, s]; }), tag.value);
        loaded = true;
        out.innerHTML = "";
        if (!D.series.length) { out.appendChild(h("div", { class: "empty" }, t("За выбранный период нет завершённых тестов."))); return; }
        out.appendChild(h("div", { class: "card" }, h("h2", { style: { marginTop: 0 } }, t("Средний результат по тестам")), A.dynLine(D.series)));
        if (D.topics.length) {
          out.appendChild(h("div", { class: "card", style: { overflowX: "auto" } }, h("h2", { style: { marginTop: 0 } }, t("Освоение тем по тестам")),
            h("div", { class: "muted small" }, t("Тема — тег вопроса (задаётся в редакторе вопроса); если тегов нет, темой считается задание теста.")), A.dynHeat(D)));
          out.appendChild(h("div", { class: "card" }, h("h2", { style: { marginTop: 0 } }, t("Где слабее всего сейчас")), A.dynBars(D.topics)));
        }
      }).catch(A.err);
    }
    api("GET", A.yearQ("/api/classes")).then(function (cl) {
      cl.forEach(function (c) { cls.appendChild(h("option", { value: c.id }, c.name)); });
      cls.value = q.class_id || "";
      load();
    }).catch(A.err);
    [cls, per, subj, tag].forEach(function (s) { s.addEventListener("change", load); });
  });
})();
