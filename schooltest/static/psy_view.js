/* SchoolTest — результат психодиагностической методики: шкалы, диаграмма, круг Айзенка, интерпретация.
   ST.psyResult(res, opts) → элемент; ST.psyResultHtml(res) → HTML для печати. */
"use strict";
(function () {
  var h = ST.h, t = ST.t;
  var NS = "http://www.w3.org/2000/svg";

  function svgEl(tag, attrs, text) {
    var e = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    if (text != null) e.textContent = text;
    return e;
  }

  function barsSvg(scales) {
    var n = scales.length;
    var longest = Math.max.apply(null, scales.map(function (s) { return String(s.name).length; }));
    var rowH = n > 10 ? 22 : 30, labW = Math.min(330, Math.max(120, longest * (n > 10 ? 6.8 : 7.6) + 12)), W = 720, barW = W - labW - 70, H = n * rowH + 24;
    var useCoef = scales.every(function (s) { return s.coef != null; });
    var mn = useCoef ? 0 : Math.min.apply(null, scales.map(function (s) { return s.min || 0; }));
    var mx = useCoef ? 1 : Math.max.apply(null, scales.map(function (s) { return s.max || 1; }));
    var svg = svgEl("svg", { viewBox: "0 0 " + W + " " + H, width: "100%", role: "img", "aria-label": t("Диаграмма шкал"),
                             style: "max-width:" + W + "px;font-family:inherit" });
    var x0 = labW + (mn < 0 ? barW * (-mn) / (mx - mn) : 0);
    function X(v) { return labW + barW * (v - mn) / ((mx - mn) || 1); }
    // сетка
    var step = mx - mn > 12 ? 4 : mx - mn > 5 ? 2 : (mx - mn) <= 1 ? 0.25 : 1;
    for (var g = mn; g <= mx + 1e-9; g += step) {
      svg.appendChild(svgEl("line", { x1: X(g), x2: X(g), y1: 4, y2: H - 18, stroke: g === 0 ? "#9aa5ad" : "#e3e7ea", "stroke-width": 1 }));
      svg.appendChild(svgEl("text", { x: X(g), y: H - 4, "text-anchor": "middle", "font-size": 11, fill: "#6b7680" }, String(Math.round(g * 100) / 100).replace(".", ",")));
    }
    var top = Math.max.apply(null, scales.map(function (s) { return s.value; }));
    scales.forEach(function (s, i) {
      var y = 6 + i * rowH;
      var v = s.coef != null ? s.coef : s.value;
      var a = Math.min(X(0 < mn ? mn : 0), X(v)), b = Math.max(X(0 < mn ? mn : 0), X(v));
      var col = s.value === top && top > (s.min || 0) ? "#1f7a6d" : (v < 0 ? "#c0563f" : "#5aa89c");
      svg.appendChild(svgEl("text", { x: labW - 8, y: y + rowH * 0.62, "text-anchor": "end", "font-size": n > 10 ? 12 : 14, fill: "#1d2a33" }, s.name));
      svg.appendChild(svgEl("rect", { x: a, y: y + 3, width: Math.max(2, b - a), height: rowH - 8, rx: 3, fill: col }));
      svg.appendChild(svgEl("text", { x: b + 6, y: y + rowH * 0.62, "font-size": 13, "font-weight": 600, fill: "#1d2a33" },
        String(v).replace(".", ",")));
    });
    if (mn < 0) svg.appendChild(svgEl("line", { x1: x0, x2: x0, y1: 2, y2: H - 18, stroke: "#4b5560", "stroke-width": 1.5 }));
    return svg;
  }

  function eysenckSvg(res) {
    var E = 0, N = 0, maxE = 21, maxN = 23;
    res.scales.forEach(function (s) { if (s.id === "E") { E = s.value; maxE = s.max; } if (s.id === "N") { N = s.value; maxN = s.max; } });
    var S = 340, c = S / 2, r = 140;
    var svg = svgEl("svg", { viewBox: "0 0 " + S + " " + S, width: S, height: S, role: "img", "aria-label": t("Круг Айзенка"), style: "max-width:100%" });
    svg.appendChild(svgEl("circle", { cx: c, cy: c, r: r, fill: "#f7faf9", stroke: "#9aa5ad", "stroke-width": 1.5 }));
    svg.appendChild(svgEl("line", { x1: c - r, x2: c + r, y1: c, y2: c, stroke: "#9aa5ad" }));
    svg.appendChild(svgEl("line", { x1: c, x2: c, y1: c - r, y2: c + r, stroke: "#9aa5ad" }));
    var q = [["Холерик", c + r * 0.45, c - r * 0.45], ["Сангвиник", c + r * 0.45, c + r * 0.5], ["Флегматик", c - r * 0.45, c + r * 0.5], ["Меланхолик", c - r * 0.45, c - r * 0.45]];
    q.forEach(function (x) { svg.appendChild(svgEl("text", { x: x[1], y: x[2], "text-anchor": "middle", "font-size": 13, fill: "#56636d" }, t(x[0]))); });
    svg.appendChild(svgEl("text", { x: c, y: 14, "text-anchor": "middle", "font-size": 12, fill: "#56636d" }, t("Нестабильность")));
    svg.appendChild(svgEl("text", { x: c, y: S - 4, "text-anchor": "middle", "font-size": 12, fill: "#56636d" }, t("Стабильность")));
    svg.appendChild(svgEl("text", { x: 4, y: c - 6, "font-size": 12, fill: "#56636d" }, t("Интроверт")));
    svg.appendChild(svgEl("text", { x: S - 4, y: c - 6, "text-anchor": "end", "font-size": 12, fill: "#56636d" }, t("Экстраверт")));
    // центр — 12 баллов по обеим шкалам
    var px = c + (E - 12) / Math.max(12, maxE - 12) * r, py = c - (N - 12) / Math.max(12, maxN - 12) * r;
    px = Math.max(c - r, Math.min(c + r, px)); py = Math.max(c - r, Math.min(c + r, py));
    svg.appendChild(svgEl("line", { x1: px - 8, x2: px + 8, y1: py - 8, y2: py + 8, stroke: "#c0392b", "stroke-width": 3 }));
    svg.appendChild(svgEl("line", { x1: px - 8, x2: px + 8, y1: py + 8, y2: py - 8, stroke: "#c0392b", "stroke-width": 3 }));
    return svg;
  }

  ST.psyResult = function (res, opts) {
    opts = opts || {};
    var box = h("div", { class: "psy-res" });
    if (!res) { box.appendChild(h("div", { class: "muted" }, t("Результат не рассчитан"))); return box; }
    box.appendChild(h("div", { class: "psy-sum" }, res.summary || ""));
    (res.warnings || []).forEach(function (w) { box.appendChild(h("div", { class: "warnbox" }, t(w))); });
    var chart = h("div", { class: "psy-chart" });
    if (res.chart === "eysenck") {
      chart.appendChild(eysenckSvg(res));
      chart.appendChild(barsSvg(res.scales));
    } else chart.appendChild(barsSvg(res.method === "ki144" ? res.scales.slice().sort(function (a, b) { return b.value - a.value; }) : res.scales));
    box.appendChild(chart);
    var tb = h("tbody");
    res.scales.forEach(function (s) {
      tb.appendChild(h("tr", null, h("td", null, s.name), h("td", { class: "num" }, String(s.coef != null ? s.coef : s.value).replace(".", ",")),
        h("td", { class: "num muted" }, (s.min || 0) + "…" + s.max), h("td", null, s.level || "")));
    });
    if (!opts.noTable) box.appendChild(h("div", { class: "tw" }, h("table", { class: "t" }, h("thead", null, h("tr", null,
      h("th", null, t("Шкала")), h("th", null, t("Балл")), h("th", null, t("Диапазон")), h("th", null, t("Уровень")))), tb)));
    (res.text || []).forEach(function (p) {
      box.appendChild(h("div", { class: "psy-txt" }, h("h3", null, p.title), h("p", null, p.body)));
    });
    return box;
  };

  ST.psyResultHtml = function (res) {
    var el = ST.psyResult(res);
    return el.outerHTML;
  };
})();
