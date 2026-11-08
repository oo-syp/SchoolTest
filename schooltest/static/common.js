/* SchoolTest — общие функции интерфейса ученика и учителя */
"use strict";
var ST = window.ST = {};

/* ---------------- язык ---------------- */
ST.lang = "ru";
ST.t = function (s) {
  if (ST.lang === "be" && window.ST_BE && Object.prototype.hasOwnProperty.call(window.ST_BE, s)) return window.ST_BE[s];
  return s;
};
var t = ST.t;
ST.tf = function (s) {               // t() с подстановкой {0}, {1}
  var a = arguments, r = t(s);
  return r.replace(/\{(\d)\}/g, function (m, i) { return a[+i + 1] != null ? a[+i + 1] : ""; });
};
ST.setLang = function (l) {
  ST.lang = l === "be" ? "be" : "ru";
  try { localStorage.setItem("st_lang", ST.lang); } catch (e) {}
  document.documentElement.lang = ST.lang;
};
ST.savedLang = function () { try { return localStorage.getItem("st_lang"); } catch (e) { return null; } };

/* ---------------- запросы ---------------- */
ST.api = function (method, url, data, opts) {
  opts = opts || {};
  return new Promise(function (resolve, reject) {
    var x = new XMLHttpRequest();
    x.open(method, url, true);
    x.setRequestHeader("X-SchoolTest", "1");
    x.setRequestHeader("X-Lang", ST.lang);
    if (data !== undefined && data !== null) x.setRequestHeader("Content-Type", "application/json");
    x.timeout = opts.timeout || 30000;
    if (opts.blob) x.responseType = "blob";
    x.onload = function () {
      if (opts.blob && x.status === 200) return resolve({ blob: x.response, name: ST.fileName(x) });
      var body = null;
      try { body = opts.blob ? null : JSON.parse(x.responseText || "null"); } catch (e) {}
      if (x.status >= 200 && x.status < 300) return resolve(body);
      if (opts.blob && x.response && x.response.text) {
        return x.response.text().then(function (txt) {
          var b2 = null; try { b2 = JSON.parse(txt); } catch (e) {}
          reject({ status: x.status, message: (b2 && b2.error) || t("Ошибка") + " " + x.status });
        });
      }
      reject({ status: x.status, message: (body && body.error) || t("Ошибка") + " " + x.status, code: body && body.code });
    };
    x.onerror = function () { reject({ status: 0, network: true, message: t("Нет связи с сервером") }); };
    x.ontimeout = function () { reject({ status: 0, network: true, message: t("Сервер не отвечает") }); };
    x.send(data !== undefined && data !== null ? JSON.stringify(data) : null);
  });
};
ST.fileName = function (x) {
  var cd = x.getResponseHeader("Content-Disposition") || "";
  var m = /filename\*=UTF-8''([^;]+)/.exec(cd);
  return m ? decodeURIComponent(m[1]) : "file";
};
ST.download = function (url) {
  return ST.api("GET", url, null, { blob: true, timeout: 120000 }).then(function (r) {
    var a = document.createElement("a");
    a.href = URL.createObjectURL(r.blob);
    a.download = r.name;
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 2000);
  }).catch(function (e) { ST.toast(e.message, true); });
};
ST.readFile = function (file) {
  return new Promise(function (resolve, reject) {
    var r = new FileReader();
    r.onload = function () { var s = String(r.result); resolve({ name: file.name, data: s.slice(s.indexOf(",") + 1), size: file.size }); };
    r.onerror = function () { reject({ message: t("Не удалось прочитать файл") }); };
    r.readAsDataURL(file);
  });
};
ST.pickFiles = function (accept, multiple) {
  return new Promise(function (resolve) {
    var inp = document.createElement("input");
    inp.type = "file";
    if (accept) inp.accept = accept;
    inp.multiple = !!multiple;
    inp.style.display = "none";
    document.body.appendChild(inp);       // в некоторых браузерах input вне документа не срабатывает
    inp.onchange = function () {
      var files = Array.prototype.slice.call(inp.files || []);
      inp.remove();
      resolve(files);
    };
    inp.click();
  });
};

/* ---------------- элементы ---------------- */
ST.h = function (tag, attrs) {
  var el = document.createElement(tag);
  if (attrs) for (var k in attrs) {
    var v = attrs[k];
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k === "html") el.innerHTML = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.slice(0, 2) === "on") el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (var i = 2; i < arguments.length; i++) ST.append(el, arguments[i]);
  return el;
};
ST.append = function (el, c) {
  if (c == null || c === false) return;
  if (Array.isArray(c)) { c.forEach(function (x) { ST.append(el, x); }); return; }
  el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
};
var h = ST.h;
ST.esc = function (s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
};

/* Текст вопроса: формулы \( \), \[ \], $$ $$ остаются для KaTeX, **жирный**, перевод строк. */
var MATH_RE = /(\\\([\s\S]+?\\\)|\\\[[\s\S]+?\\\]|\$\$[\s\S]+?\$\$)/;
ST.fmt = function (text) {
  return String(text || "").split(MATH_RE).map(function (part, i) {
    if (i % 2) return ST.esc(part);
    return ST.esc(part).replace(/\*\*([^*\n]+)\*\*/g, "<b>$1</b>").replace(/__([^_\n]+)__/g, "<u>$1</u>").replace(/\n/g, "<br>");
  }).join("");
};
ST.rich = function (tag, text, cls) {
  var el = h(tag, { class: cls || null, html: ST.fmt(text) });
  ST.math(el);
  return el;
};
ST.math = function (el) {
  if (!window.renderMathInElement || !el) return el;
  try {
    window.renderMathInElement(el, {
      delimiters: [{ left: "$$", right: "$$", display: true }, { left: "\\[", right: "\\]", display: true },
                   { left: "\\(", right: "\\)", display: false }],
      throwOnError: false, ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code", "option", "input"]
    });
  } catch (e) {}
  return el;
};
ST.hasMath = function (s) { return MATH_RE.test(String(s || "")); };

/* ---------------- сообщения ---------------- */
var toastTimer = null;
ST.toast = function (msg, err) {
  var old = document.querySelector(".toast");
  if (old) old.remove();
  var el = h("div", { class: "toast" + (err ? " err" : ""), role: "status", text: msg });
  document.body.appendChild(el);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(function () { el.remove(); }, err ? 6000 : 3000);
};
ST.modal = function (title, body, buttons, wide) {
  return new Promise(function (resolve) {
    var bg = h("div", { class: "modal-bg" });
    var box = h("div", { class: "modal" + (wide ? " wide" : ""), role: "dialog", "aria-modal": "true" });
    var acts = h("div", { class: "acts" });
    function close(v) { bg.remove(); document.removeEventListener("keydown", onKey); resolve(v); }
    function onKey(e) { if (e.key === "Escape") close(null); }
    (buttons || [{ text: t("Закрыть"), value: null }]).forEach(function (b) {
      acts.appendChild(h("button", { class: b.cls || null, onclick: function () {
        if (b.check && !b.check()) return;
        close(b.value);
      } }, b.text));
    });
    box.appendChild(h("h2", null, title));
    ST.append(box, body);
    box.appendChild(acts);
    bg.appendChild(box);
    bg.addEventListener("mousedown", function (e) { if (e.target === bg) bg._down = true; });
    bg.addEventListener("click", function (e) { if (e.target === bg && bg._down && !wide) close(null); bg._down = false; });
    document.addEventListener("keydown", onKey);
    document.body.appendChild(bg);
    var f = box.querySelector("input,select,textarea");
    if (f) setTimeout(function () { f.focus(); }, 30);
    ST.math(box);
  });
};
ST.confirm = function (title, text, okText, danger) {
  return ST.modal(title, h("p", null, text), [
    { text: t("Отмена"), value: false },
    { text: okText || t("Да"), value: true, cls: danger ? "danger" : "pri" }]);
};

/* ---------------- перетаскивание (мышь, палец, перо) ----------------
   ST.sortable(контейнеры, {onChange, axis(контейнер) -> "x"|"y"|"wrap"})
   Карточки — дочерние элементы с атрибутом data-id. */
ST.sortable = function (containers, opts) {
  opts = opts || {};
  var drag = null;
  function axisOf(c) { return (opts.axis && opts.axis(c)) || "y"; }
  function indexAt(c, x, y) {
    var kids = Array.prototype.filter.call(c.children, function (k) { return k.dataset.id && k !== drag.el && !k.classList.contains("dd-ph"); });
    var ax = axisOf(c);
    for (var i = 0; i < kids.length; i++) {
      var r = kids[i].getBoundingClientRect();
      if (ax === "x" && x < r.left + r.width / 2) return kids[i];
      if (ax === "y" && y < r.top + r.height / 2) return kids[i];
      if (ax === "wrap" && (y < r.top || (y < r.bottom && x < r.left + r.width / 2))) return kids[i];
    }
    return null;
  }
  function over(x, y) {
    for (var i = 0; i < containers.length; i++) {
      var r = containers[i].getBoundingClientRect();
      if (x >= r.left - 12 && x <= r.right + 12 && y >= r.top - 12 && y <= r.bottom + 12) return containers[i];
    }
    return null;
  }
  function down(e) {
    var card = e.target.closest("[data-id]");
    if (!card || containers.indexOf(card.parentNode) < 0) return;
    if (e.target.closest("button,input,select,textarea,a")) return;
    if (e.button != null && e.button !== 0) return;
    e.preventDefault();
    var r = card.getBoundingClientRect();
    drag = { el: card, from: card.parentNode, dx: e.clientX - r.left, dy: e.clientY - r.top, sx: e.clientX, sy: e.clientY,
             moved: false, pid: e.pointerId, w: r.width, h: r.height };
    try { card.setPointerCapture(e.pointerId); } catch (er) {}
  }
  function move(e) {
    if (!drag || e.pointerId !== drag.pid) return;
    if (!drag.moved) {
      if (Math.abs(e.clientX - drag.sx) + Math.abs(e.clientY - drag.sy) < 6) return;
      drag.moved = true;
      drag.ph = h("div", { class: "dd-ph" });
      drag.ph.style.width = drag.w + "px";
      drag.ph.style.height = drag.h + "px";
      drag.el.parentNode.insertBefore(drag.ph, drag.el);
      drag.el.classList.add("dd-drag");
      drag.el.style.width = drag.w + "px";
      document.body.classList.add("dd-on");
    }
    drag.el.style.left = (e.clientX - drag.dx) + "px";
    drag.el.style.top = (e.clientY - drag.dy) + "px";
    var c = over(e.clientX, e.clientY);
    if (c) {
      var before = indexAt(c, e.clientX, e.clientY);
      if (before) c.insertBefore(drag.ph, before); else c.appendChild(drag.ph);
    }
    // прокрутка у края экрана
    if (e.clientY < 40) window.scrollBy(0, -12); else if (e.clientY > window.innerHeight - 40) window.scrollBy(0, 12);
  }
  function up(e) {
    if (!drag || e.pointerId !== drag.pid) return;
    var d = drag;
    drag = null;
    if (!d.moved) { if (opts.onTap) opts.onTap(d.el, d.from); return; }
    d.el.classList.remove("dd-drag");
    d.el.style.left = d.el.style.top = d.el.style.width = "";
    document.body.classList.remove("dd-on");
    d.ph.parentNode.insertBefore(d.el, d.ph);
    d.ph.remove();
    if (opts.onChange) opts.onChange(d.el, d.from, d.el.parentNode);
  }
  containers.forEach(function (c) {
    c.addEventListener("pointerdown", down);
    c.addEventListener("pointermove", move);
    c.addEventListener("pointerup", up);
    c.addEventListener("pointercancel", up);
  });
};

ST.fmtTime = function (sec) {
  sec = Math.max(0, Math.floor(sec));
  var hh = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60;
  return (hh ? hh + ":" + (m < 10 ? "0" : "") : "") + m + ":" + (s < 10 ? "0" : "") + s;
};
ST.plural = function (n, one, few, many) {
  var a = Math.abs(n) % 100, b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b > 1 && b < 5) return few;
  if (b === 1) return one;
  return many;
};
