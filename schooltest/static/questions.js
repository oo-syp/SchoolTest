/* SchoolTest — отображение вопросов всех типов (ученик, предпросмотр, разбор).
   ST.renderQuestion(q, response, ctx) → элемент.
   ctx: {media(id) → url, onChange(response), onPlay(q) → Promise, onUpload(q, file) → Promise,
         readonly, review: {correct, frac, got, comment}} */
"use strict";
(function () {
  var h = ST.h, t = ST.t;
  var LETTERS = "АБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЭЮЯ";

  function img(ctx, id, cls) {
    return id ? h("img", { class: cls || "qimg", src: ctx.media(id), alt: "", loading: "lazy", draggable: "false" }) : null;
  }
  function content(ctx, item, cls) {
    var el = h("span", { class: cls || "ctext" });
    if (item.text) { el.innerHTML = ST.fmt(item.text); }
    if (item.image) el.appendChild(img(ctx, item.image, "optimg"));
    return el;
  }
  function copy(o) { return JSON.parse(JSON.stringify(o || {})); }

  ST.renderQuestion = function (q, response, ctx) {
    ctx = ctx || {};
    ctx.media = ctx.media || function (id) { return "/api/media/" + id; };
    var resp = copy(response);
    var ro = !!ctx.readonly;
    var rv = ctx.review || null;
    function changed() { if (!ro && ctx.onChange) ctx.onChange(copy(resp)); }

    var box = h("div", { class: "q q-" + q.type });
    if (q.type !== "cloze") box.appendChild(h("div", { class: "qtext", html: ST.fmt(q.text) }));
    if (q.images && q.images.length) box.appendChild(h("div", { class: "qimgs" }, q.images.map(function (m) { return img(ctx, m); })));
    if (q.audio) box.appendChild(audioBlock(q, ctx, ro));
    var body = h("div", { class: "qbody" });
    box.appendChild(body);
    var R = RENDER[q.type];
    if (R) R(q, resp, body, ctx, changed, ro, rv);
    if (rv && rv.comment) box.appendChild(h("div", { class: "rv-comment" }, h("b", null, t("Комментарий учителя:") + " "), rv.comment));
    ST.math(box);
    return box;
  };

  function audioBlock(q, ctx, ro) {
    var a = q.audio;
    var st = h("span", { class: "muted" });
    var player = null;
    function upd() {
      st.textContent = a.limit ? ST.tf("Осталось прослушиваний: {0}", a.left) : "";
    }
    upd();
    var btn = h("button", { type: "button", class: "pri", onclick: function () {
      if (player && !player.paused) { player.pause(); return; }
      if (a.limit && a.left <= 0) return;
      var go = ctx.onPlay ? ctx.onPlay(q) : Promise.resolve({ left: null });
      btn.disabled = true;
      go.then(function (r) {
        if (r && r.left != null) a.left = r.left;
        upd();
        player = player || new Audio(ctx.media(a.media));
        player.currentTime = 0;
        player.onended = function () { btn.disabled = a.limit && a.left <= 0; btn.textContent = "▶ " + t("Прослушать"); };
        btn.textContent = "■ " + t("Остановить");
        btn.disabled = false;
        return player.play();
      }).catch(function (e) { btn.disabled = false; ST.toast(e.message || t("Не удалось воспроизвести"), true); });
    } }, "▶ " + t("Прослушать"));
    if (a.limit && a.left <= 0) btn.disabled = true;
    if (ro) btn.disabled = !!(a.limit && a.left <= 0);
    return h("div", { class: "qaudio" }, btn, " ", st);
  }

  var RENDER = {};

  RENDER.single = RENDER.multi = function (q, resp, body, ctx, changed, ro, rv) {
    var multi = q.type === "multi";
    var name = "o" + q.id + Math.random().toString(36).slice(2, 6);
    var sel = multi ? (resp.choices || []) : (resp.choice != null ? [resp.choice] : []);
    var right = rv && rv.correct ? rv.correct.options || [] : null;
    if (multi && !ro) body.appendChild(h("div", { class: "hint" }, t("Выберите все верные ответы")));
    var list = h("div", { class: "opts" });
    q.options.forEach(function (o) {
      var inp = h("input", { type: multi ? "checkbox" : "radio", name: name, value: o.id, disabled: ro || null });
      inp.checked = sel.indexOf(o.id) >= 0;
      var cls = "opt" + (inp.checked ? " on" : "");
      if (right) {
        if (right.indexOf(o.id) >= 0) cls += " right";
        else if (inp.checked) cls += " wrong";
      }
      var lab = h("label", { class: cls }, inp, content(ctx, o));
      inp.addEventListener("change", function () {
        if (multi) {
          resp.choices = Array.prototype.filter.call(list.querySelectorAll("input"), function (x) { return x.checked; })
            .map(function (x) { return x.value; });
        } else resp.choice = o.id;
        list.querySelectorAll(".opt").forEach(function (l) { l.classList.toggle("on", l.querySelector("input").checked); });
        changed();
      });
      list.appendChild(lab);
    });
    body.appendChild(list);
  };

  RENDER.short = function (q, resp, body, ctx, changed, ro, rv) {
    resp.fields = resp.fields || {};
    var wrap = h("div", { class: "fields" });
    q.fields.forEach(function (f) {
      var inp = h("input", { type: "text", autocomplete: "off", spellcheck: "false", readonly: ro || null,
                             "aria-label": f.label || t("Ответ") });
      inp.value = resp.fields[f.id] || "";
      inp.addEventListener("input", function () { resp.fields[f.id] = inp.value; changed(); });
      var row = h("label", { class: "field" }, f.label ? h("span", { class: "flabel", html: ST.fmt(f.label) }) : null, inp);
      if (rv && rv.correct && rv.correct.fields) row.appendChild(h("span", { class: "rv-right" }, "✓ " + (rv.correct.fields[f.id] || "")));
      wrap.appendChild(row);
    });
    body.appendChild(wrap);
  };

  RENDER.match = function (q, resp, body, ctx, changed, ro, rv) {
    resp.pairs = resp.pairs || {};
    var right = q.right;
    var letter = {};
    right.forEach(function (r, i) { letter[r.id] = LETTERS[i] || String(i + 1); });
    var grid = h("div", { class: "match" });
    var lcol = h("div", { class: "mcol" }, h("div", { class: "mhead" }, t("Сопоставьте")));
    var rcol = h("div", { class: "mcol" }, h("div", { class: "mhead" }, t("Варианты")));
    q.left.forEach(function (l, i) {
      var s = h("select", { disabled: ro || null, "aria-label": String(i + 1) });
      s.appendChild(h("option", { value: "" }, "—"));
      right.forEach(function (r) { s.appendChild(h("option", { value: r.id }, letter[r.id])); });
      s.value = resp.pairs[l.id] || "";
      s.addEventListener("change", function () { resp.pairs[l.id] = s.value; changed(); });
      var row = h("div", { class: "mrow" }, h("b", { class: "mnum" }, (i + 1) + "."), content(ctx, l), h("span", { class: "msel" }, "→ ", s));
      if (rv && rv.correct && rv.correct.pairs) {
        var ok = rv.correct.pairs[l.id];
        row.classList.add(ok && resp.pairs[l.id] === ok ? "right" : "wrong");
        row.appendChild(h("span", { class: "rv-right" }, "✓ " + (letter[ok] || "")));
      }
      lcol.appendChild(row);
    });
    right.forEach(function (r) {
      rcol.appendChild(h("div", { class: "mrow" }, h("b", { class: "mnum" }, letter[r.id] + ")"), content(ctx, r)));
    });
    grid.appendChild(lcol);
    grid.appendChild(rcol);
    body.appendChild(grid);
  };

  RENDER.order = function (q, resp, body, ctx, changed, ro, rv) {
    var byId = {};
    q.items.forEach(function (x) { byId[x.id] = x; });
    var order = (resp.order && resp.order.length === q.items.length) ? resp.order.slice() : q.items.map(function (x) { return x.id; });
    if (!ro) body.appendChild(h("div", { class: "hint" }, t("Перетащите элементы, чтобы расставить их в правильном порядке")));
    var list = h("ol", { class: "olist" });
    function save() {
      resp.order = Array.prototype.map.call(list.children, function (c) { return c.dataset.id; });
      resp.touched = true;
      renum();
      changed();
    }
    function renum() {
      Array.prototype.forEach.call(list.children, function (c, i) {
        c.querySelector(".onum").textContent = i + 1;
        var b = c.querySelectorAll("button");
        if (b.length) { b[0].disabled = i === 0; b[1].disabled = i === list.children.length - 1; }
      });
    }
    order.forEach(function (id) {
      var x = byId[id];
      if (!x) return;
      var li = h("li", { class: "ocard", "data-id": id }, h("span", { class: "grip", "aria-hidden": "true" }, "⋮⋮"),
                 h("b", { class: "onum" }), content(ctx, x));
      if (!ro) {
        li.appendChild(h("span", { class: "obtns" },
          h("button", { type: "button", class: "sm ghost", title: t("Выше"), "aria-label": t("Выше"), onclick: function () {
            if (li.previousElementSibling) { list.insertBefore(li, li.previousElementSibling); save(); }
          } }, "▲"),
          h("button", { type: "button", class: "sm ghost", title: t("Ниже"), "aria-label": t("Ниже"), onclick: function () {
            if (li.nextElementSibling) { list.insertBefore(li.nextElementSibling, li); save(); }
          } }, "▼")));
      }
      list.appendChild(li);
    });
    renum();
    body.appendChild(list);
    if (!ro) ST.sortable([list], { onChange: save });
    if (rv && rv.correct && rv.correct.order) body.appendChild(correctList(ctx, rv.correct.order, byId, null));
  };

  function correctList(ctx, order, byId, dates) {
    var ol = h("ol", { class: "rv-order" });
    order.forEach(function (id) {
      if (!byId[id]) return;
      ol.appendChild(h("li", null, content(ctx, byId[id]), dates && dates[id] ? h("span", { class: "pill" }, dates[id]) : null));
    });
    return h("div", { class: "rv-box" }, h("b", null, t("Правильный порядок:")), ol);
  }

  /* Хронологическая рулетка: события перетаскиваются на линию времени (раньше ← → позже). */
  RENDER.chrono = function (q, resp, body, ctx, changed, ro, rv) {
    var byId = {};
    q.items.forEach(function (x) { byId[x.id] = x; });
    var placed = (resp.order || []).filter(function (id) { return byId[id]; });
    var rest = q.items.map(function (x) { return x.id; }).filter(function (id) { return placed.indexOf(id) < 0; });
    var narrow = window.innerWidth < 700;
    if (!ro) body.appendChild(h("div", { class: "hint" }, narrow ?
      t("Перетащите события на линию времени: раньше — выше, позже — ниже. Можно также нажать на событие, чтобы поставить его в конец линии.") :
      t("Перетащите события на линию времени: раньше — слева, позже — справа. Можно также нажать на событие, чтобы поставить его в конец линии.")));
    var tray = h("div", { class: "ctray", "aria-label": t("События") });
    var line = h("div", { class: "cline", "aria-label": t("Линия времени") });
    var lab = q.labels || {};
    var wrap = h("div", { class: "chrono" },
      h("div", { class: "ctray-wrap" }, h("div", { class: "clabel" }, t("События")), tray),
      h("div", { class: "cline-wrap" },
        h("div", { class: "cends" }, h("span", null, (narrow ? "▲ " : "◀ ") + (lab.start || t("Раньше"))), h("span", null, narrow ? "▼ " + (lab.end || t("Позже")) : (lab.end || t("Позже")) + " ▶")),
        h("div", { class: "caxis" }), line,
        h("div", { class: "cempty" }, t("Перетащите события сюда"))));
    function card(id) {
      var el = h("div", { class: "ccard", "data-id": id }, content(ctx, byId[id]));
      if (!ro) {
        el.appendChild(h("span", { class: "cbtns" },
          h("button", { type: "button", class: "sm ghost cl", title: t("Раньше"), "aria-label": t("Раньше"), onclick: function () {
            if (el.previousElementSibling) { line.insertBefore(el, el.previousElementSibling); save(); }
          } }, narrow ? "▲" : "◀"),
          h("button", { type: "button", class: "sm ghost cr", title: t("Позже"), "aria-label": t("Позже"), onclick: function () {
            if (el.nextElementSibling) { line.insertBefore(el.nextElementSibling, el); save(); }
          } }, narrow ? "▼" : "▶"),
          h("button", { type: "button", class: "sm ghost cx", title: t("Убрать с линии"), "aria-label": t("Убрать с линии"), onclick: function () {
            tray.appendChild(el); save();
          } }, "✕")));
      }
      return el;
    }
    placed.forEach(function (id) { line.appendChild(card(id)); });
    rest.forEach(function (id) { tray.appendChild(card(id)); });
    function save() {
      resp.order = Array.prototype.map.call(line.children, function (c) { return c.dataset.id; });
      resp.touched = true;
      sync();
      changed();
    }
    function sync() {
      wrap.classList.toggle("has", line.children.length > 0);
      wrap.classList.toggle("done", tray.children.length === 0);
      Array.prototype.forEach.call(line.children, function (c, i) { c.dataset.n = i + 1; });
    }
    sync();
    body.appendChild(wrap);
    if (!ro) {
      ST.sortable([line, tray], {
        axis: function (c) { return c === line ? (window.innerWidth < 700 ? "y" : "x") : "wrap"; },
        onChange: save,
        onTap: function (el, from) { if (from === tray) { line.appendChild(el); save(); } }
      });
    }
    if (rv && rv.correct && rv.correct.order) {
      var ok = JSON.stringify(placed) === JSON.stringify(rv.correct.order);
      wrap.classList.add(ok ? "right" : "wrong");
      body.appendChild(correctList(ctx, rv.correct.order, byId, rv.correct.dates));
    }
  };

  RENDER.cloze = function (q, resp, body, ctx, changed, ro, rv) {
    resp.blanks = resp.blanks || {};
    var blanks = {};
    (q.blanks || []).forEach(function (b) { blanks[b.id] = b; });
    var parts = String(q.text || "").split(/\{\{([^}]+)\}\}/);
    var el = h("div", { class: "qtext cloze" });
    parts.forEach(function (p, i) {
      if (i % 2 === 0) { if (p) el.appendChild(h("span", { html: ST.fmt(p) })); return; }
      var b = blanks[p];
      if (!b) return;
      var c;
      if (b.kind === "select") {
        c = h("select", { disabled: ro || null, "aria-label": t("Пропуск") });
        c.appendChild(h("option", { value: "" }, "…"));
        b.choices.forEach(function (ch) { c.appendChild(h("option", { value: ch }, ch)); });
        c.value = resp.blanks[b.id] || "";
        c.addEventListener("change", function () { resp.blanks[b.id] = c.value; changed(); });
      } else {
        c = h("input", { type: "text", class: "blank", autocomplete: "off", spellcheck: "false", readonly: ro || null,
                         "aria-label": t("Пропуск") });
        c.value = resp.blanks[b.id] || "";
        var fit = function () { c.style.width = Math.max(5, Math.min(30, (c.value || "").length + 2)) + "ch"; };
        fit();
        c.addEventListener("input", function () { resp.blanks[b.id] = c.value; fit(); changed(); });
      }
      el.appendChild(c);
      if (rv && rv.correct && rv.correct.blanks) el.appendChild(h("span", { class: "rv-right" }, " ✓ " + (rv.correct.blanks[b.id] || "") + " "));
    });
    var box = body.parentNode;
    box.insertBefore(el, box.firstChild);
  };

  RENDER.likert = function (q, resp, body, ctx, changed, ro) {
    resp.values = resp.values || {};
    var tbl = h("table", { class: "likert" });
    var head = h("tr", null, h("th"));
    q.scale.forEach(function (s) { head.appendChild(h("th", null, s)); });
    tbl.appendChild(h("thead", null, head));
    var tb = h("tbody");
    q.statements.forEach(function (st) {
      var tr = h("tr", null, h("td", { class: "lst", html: ST.fmt(st.text) }));
      var nm = "l" + q.id + st.id;
      q.scale.forEach(function (s, i) {
        var inp = h("input", { type: "radio", name: nm, value: i, disabled: ro || null, "aria-label": s });
        inp.checked = resp.values[st.id] === i;
        inp.addEventListener("change", function () { resp.values[st.id] = i; changed(); });
        tr.appendChild(h("td", { class: "lc", "data-label": s }, h("label", null, inp)));
      });
      tb.appendChild(tr);
    });
    tbl.appendChild(tb);
    body.appendChild(h("div", { class: "lwrap" }, tbl));
  };

  RENDER.essay = function (q, resp, body, ctx, changed, ro, rv) {
    var ta = h("textarea", { rows: 8, readonly: ro || null, "aria-label": t("Ответ"), spellcheck: "true" });
    ta.value = resp.text || "";
    var cnt = h("div", { class: "muted small" });
    function count() {
      var n = (ta.value.match(/[^\s]+/g) || []).length;
      cnt.textContent = ST.tf("Слов: {0}", n) + (q.min_words ? " " + ST.tf("(не меньше {0})", q.min_words) : "");
      cnt.classList.toggle("warn", !!(q.min_words && n < q.min_words));
    }
    count();
    ta.addEventListener("input", function () { resp.text = ta.value; count(); changed(); });
    body.appendChild(ta);
    body.appendChild(cnt);
    if (!ro) body.appendChild(h("div", { class: "hint" }, t("Ответ проверит учитель.")));
    if (rv && rv.got != null) body.appendChild(h("div", { class: "rv-box" }, ST.tf("Баллы: {0}", rv.got)));
  };

  RENDER.file = function (q, resp, body, ctx, changed, ro, rv) {
    if (q.task_files && q.task_files.length) {
      body.appendChild(h("div", { class: "tfiles" }, h("b", null, t("Файлы задания:") + " "),
        q.task_files.map(function (m) { return h("a", { class: "btn sm", href: ctx.media(m), download: "" }, "⬇ " + t("Скачать")); })));
    }
    var cur = h("div", { class: "fcur" }, resp.name ? ST.tf("Загружен файл: {0}", resp.name) : t("Файл ещё не загружен"));
    body.appendChild(cur);
    if (!ro) {
      var btn = h("button", { type: "button", class: "pri", onclick: function () {
        ST.pickFiles(q.accept ? q.accept.split(",").map(function (x) { x = x.trim(); return x.charAt(0) === "." ? x : "." + x; }).join(",") : "")
          .then(function (files) {
            if (!files.length) return;
            var f = files[0];
            if (f.size > (q.max_mb || 10) * 1024 * 1024) { ST.toast(ST.tf("Файл больше {0} МБ", q.max_mb || 10), true); return; }
            btn.disabled = true;
            cur.textContent = t("Загрузка…");
            return ctx.onUpload(q, f).then(function (r) {
              resp.file_id = r.file_id;
              resp.name = r.name;
              cur.textContent = ST.tf("Загружен файл: {0}", r.name);
              changed();
            });
          }).catch(function (e) { cur.textContent = e.message; ST.toast(e.message, true); })
          .then(function () { btn.disabled = false; });
      } }, resp.name ? t("Заменить файл") : t("Выбрать файл"));
      body.appendChild(btn);
      body.appendChild(h("div", { class: "hint" }, (q.accept ? ST.tf("Допустимые типы: {0}. ", q.accept) : "") +
        ST.tf("Размер — до {0} МБ. Ответ проверит учитель.", q.max_mb || 10)));
    }
    if (rv && rv.got != null) body.appendChild(h("div", { class: "rv-box" }, ST.tf("Баллы: {0}", rv.got)));
  };

  /* ---------------- вопрос методики (психодиагностика): крупные кнопки, переход дальше после ответа ---------------- */
  RENDER.psy = function (q, resp, body, ctx, changed, ro) {
    var list = h("div", { class: "psy-opts" + (q.options.length > 2 ? " col" : "") });
    q.options.forEach(function (o) {
      var b = h("button", { type: "button", class: "psy-opt" + (resp.choice === o.id ? " on" : ""), disabled: ro || null,
                            "aria-pressed": resp.choice === o.id ? "true" : "false" }, o.text);
      b.addEventListener("click", function () {
        resp.choice = o.id;
        list.querySelectorAll(".psy-opt").forEach(function (x) { x.classList.remove("on"); x.setAttribute("aria-pressed", "false"); });
        b.classList.add("on");
        b.setAttribute("aria-pressed", "true");
        changed();
        if (ctx.onAutoNext) setTimeout(ctx.onAutoNext, 180);
      });
      list.appendChild(b);
    });
    body.appendChild(list);
  };

  /* ---------------- задача с кодом (как на contest.yandex.ru) ---------------- */
  var LANG_NAMES = { fpc: "Free Pascal", pabc: "PascalABC.NET", py: "Python 3", cpp: "C++ (20)" };
  var LANG_EXT = { fpc: ".pas,.pp,.dpr,.lpr", pabc: ".pas", py: ".py", cpp: ".cpp,.cc,.cxx,.c,.h" };
  ST.VERDICT = { OK: "Полное решение", PT: "Частичное решение", WA: "Неправильный ответ", TL: "Превышено ограничение времени",
    ML: "Превышено ограничение памяти", RE: "Ошибка во время выполнения", CE: "Ошибка компиляции", OL: "Слишком большой вывод",
    SE: "Ошибка проверяющей системы", NC: "Компилятор не настроен", DEP: "Не проверялась: не пройдены необходимые подзадачи",
    SENT: "Решение принято на проверку" };
  ST.verdictClass = function (v) { return v === "OK" ? "ok" : v === "PT" ? "warn" : v === "SENT" ? "" : v ? "bad" : ""; };
  function pre(text, cls) { return h("pre", { class: "io" + (cls ? " " + cls : "") }, text == null ? "" : String(text)); }
  function copyBtn(text) {
    return h("button", { type: "button", class: "sm ghost", title: t("Копировать"), onclick: function () {
      try { navigator.clipboard.writeText(text); ST.toast(t("Скопировано")); } catch (e) {}
    } }, "⧉");
  }
  ST.codeStatement = function (q) {
    var box = h("div", { class: "code-st" });
    var lim = h("table", { class: "lim" }, h("tbody", null,
      h("tr", null, h("td", null, t("Ограничение времени")), h("td", null, ST.tf("{0} с", String(q.time_limit || 1).replace(".", ",")))),
      h("tr", null, h("td", null, t("Ограничение памяти")), h("td", null, ST.tf("{0} МБ", q.memory || 256))),
      h("tr", null, h("td", null, t("Ввод")), h("td", null, t("стандартный ввод или input.txt"))),
      h("tr", null, h("td", null, t("Вывод")), h("td", null, t("стандартный вывод или output.txt")))));
    box.appendChild(lim);
    if (q.input_format) box.appendChild(h("div", null, h("h4", null, t("Формат ввода")), h("div", { class: "st-txt", html: ST.fmt(q.input_format) })));
    if (q.output_format) box.appendChild(h("div", null, h("h4", null, t("Формат вывода")), h("div", { class: "st-txt", html: ST.fmt(q.output_format) })));
    if (q.subtasks && q.subtasks.length) {
      box.appendChild(h("h4", null, t("Система оценки")));
      box.appendChild(h("table", { class: "t subt" }, h("thead", null, h("tr", null, h("th", null, t("Подзадача")), h("th", null, t("Баллы")),
        h("th", null, t("Необходимые подзадачи")), h("th", null, t("Ограничения")))),
        h("tbody", null, q.subtasks.map(function (s, i) {
          return h("tr", null, h("td", { class: "num" }, String(i + 1) + (s.name && !/^Подзадача/.test(s.name) ? " — " + s.name : "")),
            h("td", { class: "num" }, String(s.points).replace(".", ",")), h("td", null, (s.deps || []).join(", ") || "–"),
            h("td", { html: ST.fmt(s.limits || "") }));
        }))));
    }
    if (q.examples && q.examples.length) {
      box.appendChild(h("h4", null, q.examples.length > 1 ? t("Примеры") : t("Пример")));
      q.examples.forEach(function (ex) {
        box.appendChild(h("div", { class: "ex" }, h("div", null, h("div", { class: "exh" }, t("Ввод"), " ", copyBtn(ex.in)), pre(ex.in)),
          h("div", null, h("div", { class: "exh" }, t("Вывод"), " ", copyBtn(ex.out)), pre(ex.out))));
      });
    }
    if (q.notes) box.appendChild(h("div", null, h("h4", null, t("Примечания")), h("div", { class: "st-txt", html: ST.fmt(q.notes) })));
    return box;
  };
  ST.codeEditor = function (value, opts) {
    opts = opts || {};
    var ta = h("textarea", { class: "code-ed", spellcheck: "false", autocomplete: "off", autocapitalize: "off", wrap: "off",
                             rows: opts.rows || 16, readonly: opts.readonly || null, "aria-label": t("Код программы") });
    ta.value = value || "";
    ta.addEventListener("keydown", function (e) {
      if (e.key === "Tab" && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        var s = ta.selectionStart, en = ta.selectionEnd, v = ta.value;
        if (e.shiftKey) {
          var ls = v.lastIndexOf("\n", s - 1) + 1;
          if (v.substr(ls, 4) === "    ") { ta.value = v.slice(0, ls) + v.slice(ls + 4); ta.setSelectionRange(Math.max(ls, s - 4), Math.max(ls, en - 4)); }
        } else {
          ta.value = v.slice(0, s) + "    " + v.slice(en);
          ta.setSelectionRange(s + 4, s + 4);
        }
        ta.dispatchEvent(new Event("input"));
      } else if (e.key === "Enter" && !e.ctrlKey) {
        var p = ta.selectionStart, val = ta.value, line = val.slice(val.lastIndexOf("\n", p - 1) + 1, p);
        var ind = (/^\s*/.exec(line) || [""])[0];
        if (/[:{]\s*$|\b(begin|do|then|else|repeat|of)\s*$/i.test(line)) ind += "    ";
        if (ind) {
          e.preventDefault();
          ta.value = val.slice(0, p) + "\n" + ind + val.slice(ta.selectionEnd);
          ta.setSelectionRange(p + 1 + ind.length, p + 1 + ind.length);
          ta.dispatchEvent(new Event("input"));
        }
      } else if (e.key === "Enter" && e.ctrlKey && opts.onCtrlEnter) {
        e.preventDefault();
        opts.onCtrlEnter();
      }
    });
    return ta;
  };
  ST.subDetails = function (s, full) {
    var d = s.details || {};
    var box = h("div", { class: "sub-det" });
    if (d.compile) box.appendChild(h("div", null, h("b", null, s.verdict === "CE" || s.verdict === "NC" ? t("Ошибка компиляции") : t("Сообщения компилятора")), pre(d.compile)));
    if (d.fail && !d.groups) box.appendChild(h("div", null, ST.tf("Первый непройденный тест: {0} — {1}", d.fail.test, t(ST.VERDICT[d.fail.status] || d.fail.status))));
    (d.groups || []).forEach(function (g) {
      var head = h("div", { class: "grp-h" }, h("b", null, t(g.name)), " ",
        g.sample ? h("span", { class: "muted small" }, t("(без баллов)")) : h("span", { class: "pill " + (g.got >= g.points && g.points > 0 ? "ok" : g.got > 0 ? "warn" : "bad") },
          ST.tf("{0} из {1}", String(Math.round(g.got * 100) / 100).replace(".", ","), String(g.points).replace(".", ","))),
        " ", h("span", { class: ST.verdictClass(g.status) }, g.status === "OK" ? t("пройдена") : t(ST.VERDICT[g.status] || g.status)));
      var tests = h("div", { class: "tests" }, (g.tests || []).map(function (x) {
        return h("span", { class: "tchip " + (x.status === "OK" ? "ok" : "bad"), title: t(ST.VERDICT[x.status] || x.status) + " · " + x.time + " с · " +
          Math.round((x.memory || 0) / 1048576) + " МБ" }, String(x.n) + " " + x.status);
      }));
      var gb = h("div", { class: "grp" }, head, tests);
      (g.tests || []).forEach(function (x) {
        if ((g.sample || full) && x.status !== "OK" && (x.input != null || x.stderr)) {
          gb.appendChild(h("details", null, h("summary", { class: "small" }, ST.tf("Тест {0}: подробности", x.n)),
            x.input != null ? h("div", { class: "ex" }, h("div", null, h("div", { class: "exh" }, t("Ввод")), pre(x.input)),
              h("div", null, h("div", { class: "exh" }, t("Ожидаемый вывод")), pre(x.expected)),
              h("div", null, h("div", { class: "exh" }, t("Вывод программы")), pre(x.output))) : null,
            x.stderr ? pre(x.stderr, "err") : null));
        }
      });
      box.appendChild(gb);
    });
    if (d.time != null && s.status === "done") box.appendChild(h("div", { class: "muted small" },
      ST.tf("Наибольшее время: {0} с, память: {1} МБ", String(Math.round(d.time * 1000) / 1000).replace(".", ","), Math.round((d.memory || 0) / 1048576))));
    return box;
  };
  ST.subsTable = function (items, opts) {
    opts = opts || {};
    if (!items.length) return h("div", { class: "muted small" }, t("Посылок пока нет."));
    var tb = h("tbody");
    items.forEach(function (s) {
      var total = s.points_total;
      var pts = s.frac != null && s.status === "done" ? (total ? String(Math.round(s.frac * total * 100) / 100).replace(".", ",") :
        Math.round(s.frac * 100) + " %") : "";
      var vr = s.status !== "done" ? h("span", { class: "muted" }, s.status === "running" ? t("Проверяется…") : t("В очереди…")) :
        h("span", { class: ST.verdictClass(s.verdict) }, t(ST.VERDICT[s.verdict] || s.verdict_name || s.verdict || ""));
      var test = s.details && s.details.fail ? String(s.details.fail.test) : "";
      var row = h("tr", null, h("td", null, new Date(s.created_at * 1000).toLocaleTimeString().slice(0, 8)), h("td", null, "#" + s.id),
        h("td", null, LANG_NAMES[s.lang] || s.lang_name || s.lang), h("td", null, vr), h("td", { class: "num" }, test), h("td", { class: "num" }, pts),
        h("td", null, h("button", { type: "button", class: "sm ghost", onclick: function () {
          det.classList.toggle("hidden");
          if (!det.firstChild) {
            det.appendChild(h("td", { colspan: 7 }, ST.subDetails(s, opts.full),
              s.code != null ? h("details", null, h("summary", { class: "small" }, t("Код посылки")), pre(s.code, "src")) :
              opts.loadCode ? h("button", { type: "button", class: "sm", onclick: function (e) {
                var b = e.target;
                opts.loadCode(s).then(function (code) { b.replaceWith(pre(code, "src")); }).catch(function (er) { ST.toast(er.message, true); });
              } }, t("Показать код")) : null));
          }
        } }, t("отчёт"))));
      var det = h("tr", { class: "hidden subdet" });
      tb.appendChild(row);
      tb.appendChild(det);
    });
    return h("div", { class: "tw" }, h("table", { class: "t subs" }, h("thead", null, h("tr", null,
      [t("Время"), "ID", t("Язык"), t("Вердикт"), t("Тест"), t("Баллы"), ""].map(function (x) { return h("th", null, x); }))), tb));
  };

  RENDER.code = function (q, resp, body, ctx, changed, ro, rv) {
    body.appendChild(ST.codeStatement(q));
    var langs = (q.languages && q.languages.length ? q.languages : ["fpc", "pabc", "py", "cpp"]);
    var subsBox = h("div", { class: "subs-box" });
    var poll = null;
    function loadSubs() {
      if (!ctx.loadSubs) return;
      ctx.loadSubs(q).then(function (r) {
        var items = r.items || r;
        subsBox.innerHTML = "";
        if (r.left != null) subsBox.appendChild(h("div", { class: "muted small" }, ST.tf("Осталось посылок: {0}", r.left)));
        subsBox.appendChild(ST.subsTable(items, { full: !!ctx.fullSubs, loadCode: ctx.loadCode }));
        clearTimeout(poll);
        if (items.some(function (s) { return s.status !== "done"; }) && document.body.contains(subsBox)) poll = setTimeout(loadSubs, 1500);
        if (ctx.onSubs) ctx.onSubs(items);
      }).catch(function () {});
    }
    if (!ro && ctx.onSubmit) {
      var key = "st_code_" + (ctx.draftKey || "") + "_" + q.id;
      var saved = {};
      try { saved = JSON.parse(localStorage.getItem(key) || "{}"); } catch (e) {}
      var lang = A_select(langs.map(function (l) { return [l, LANG_NAMES[l] || l]; }), saved.lang || langs[0]);
      var ed = ST.codeEditor(saved.code || "", { onCtrlEnter: function () { send(); } });
      function store() { try { localStorage.setItem(key, JSON.stringify({ lang: lang.value, code: ed.value })); } catch (e) {} }
      ed.addEventListener("input", store);
      lang.addEventListener("change", store);
      var sendBtn = h("button", { type: "button", class: "pri", onclick: function () { send(); } }, t("Отправить"));
      var fileBtn = h("button", { type: "button", onclick: function () {
        ST.pickFiles(LANG_EXT[lang.value] || "").then(function (fs) {
          if (!fs.length) return;
          var r = new FileReader();
          r.onload = function () { ed.value = String(r.result); store(); };
          r.readAsText(fs[0]);
        });
      } }, t("Загрузить из файла"));
      function send() {
        if (!ed.value.trim()) { ST.toast(t("Напишите решение"), true); return; }
        sendBtn.disabled = true;
        ctx.onSubmit(q, lang.value, ed.value).then(function () {
          ST.toast(t("Решение отправлено на проверку"));
          resp.subs = (resp.subs || 0) + 1;
          if (ctx.onChange) ctx.onChange(copy(resp));
          loadSubs();
        }).catch(function (e) { ST.toast(e.message, true); }).then(function () { setTimeout(function () { sendBtn.disabled = false; }, 2500); });
      }
      body.appendChild(h("div", { class: "code-ans" }, h("h4", null, t("Ответ")),
        h("div", { class: "bar" }, h("label", { class: "muted" }, t("Язык") + " ", lang), h("div", { class: "sp" }), fileBtn), ed,
        h("div", { class: "bar" }, sendBtn, h("span", { class: "muted small" }, t("Ctrl+Enter — отправить. Код сохраняется на этом устройстве.")),
          q.manual ? h("span", { class: "pill" }, t("Решение также проверит учитель")) : null)));
    }
    if (ctx.loadSubs) {
      body.appendChild(h("h4", null, t("Посылки")));
      body.appendChild(subsBox);
      loadSubs();
    }
    if (rv && rv.got != null) body.appendChild(h("div", { class: "rv-box" }, ST.tf("Баллы: {0}", rv.got)));
  };
  function A_select(options, value) {
    var s = h("select");
    options.forEach(function (o) { s.appendChild(h("option", { value: o[0] }, o[1])); });
    if (value != null) s.value = value;
    if (!s.value && options.length) s.value = options[0][0];
    return s;
  }

  ST.TYPE_NAMES = {
    single: "Один верный ответ", multi: "Несколько верных ответов", short: "Короткий ответ", match: "Соответствие",
    order: "Порядок", chrono: "Хронологическая рулетка", cloze: "Пропуски в тексте", likert: "Шкала Ликерта (опрос)",
    essay: "Развёрнутый ответ", file: "Практическое задание с файлом", code: "Код (программирование)", psy: ""
  };
})();
