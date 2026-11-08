/* SchoolTest — редактор вопросов теста */
"use strict";
(function () {
  var h = ST.h, t = ST.t, api = ST.api;
  var ROMAN = ["", "I", "II", "III", "IV", "V"];
  var TYPE_HINT = {
    single: "Ученик выбирает один вариант",
    multi: "Ученик отмечает все верные варианты",
    short: "Число или слово; несколько полей",
    match: "Пары «левое — правое»",
    order: "Расставить элементы по порядку",
    chrono: "События на ленте времени: что раньше, что позже",
    cloze: "Вписать или выбрать слова в тексте",
    likert: "Опрос: согласие по шкале, без оценки",
    essay: "Свободный ответ, проверяет учитель",
    file: "Ученик загружает файл с решением"
  };
  var TYPES = ["single", "multi", "short", "match", "order", "chrono", "cloze", "likert", "essay", "file"];

  function normOf(T) {
    var sc = T.settings.scale || {};
    if (sc.mode !== "norms") return null;
    return A.me.norms.filter(function (n) { return n.id === sc.norm; })[0] || null;
  }
  function plainText(s) {
    return String(s || "").replace(/\{\{[^}]+\}\}/g, "___");
  }

  /* ---------------- вкладка «Вопросы» ---------------- */
  A.questionsTab = function (pane, T, edit) {
    var norm = normOf(T);
    var nvar = T.settings.variants || 1;
    var byTask = {};
    T.question_list.forEach(function (q) { (byTask[q.task_id] = byTask[q.task_id] || []).push(q); });
    if (edit) {
      pane.appendChild(h("div", { class: "bar" },
        h("button", { onclick: function () { A.importDialog(T.id); } }, "⬆ " + t("Добавить из файла или текста")),
        h("div", { class: "sp" }),
        h("span", { class: "muted small" }, norm ? t(norm.name) : t("Баллы задаются для каждого вопроса"))));
    }
    var n = 0;
    T.tasks.forEach(function (k, ti) {
      var qs = byTask[k.id] || [];
      var ttl = h("input", { type: "text", class: "ttitle", placeholder: t("Название задания (необязательно)"), disabled: !edit || null });
      ttl.value = k.title || "";
      ttl.addEventListener("change", function () { api("PUT", "/api/tasks/" + k.id, { title: ttl.value }).catch(A.err); });
      var pick = h("input", { type: "number", min: 0, style: { width: "64px" }, disabled: !edit || null, title: t("Сколько вопросов выдавать из банка (0 — все)") });
      pick.value = k.pick || 0;
      pick.addEventListener("change", function () { api("PUT", "/api/tasks/" + k.id, { pick: +pick.value || 0 }).then(A.render).catch(A.err); });
      var lvl = null;
      if (norm && norm.kind === "tasks") {
        var pts = norm.task_points[ti];
        lvl = h("span", { class: "pill" }, (norm.levels ? ST.tf("уровень {0}", ROMAN[norm.levels[ti]] || "") + " · " : "") +
          (pts != null ? ST.tf("{0} б.", pts) : t("лишнее задание")));
      }
      var head = h("div", { class: "task-head" }, h("b", null, ST.tf("Задание {0}", k.num)), lvl, ttl, h("div", { class: "sp" }),
        h("label", { class: "muted small", style: { display: "flex", alignItems: "center", gap: "6px" } }, t("Выдавать из банка:"), pick,
          h("span", null, ST.tf("из {0}", qs.length))),
        edit && T.tasks.length > 1 ? h("button", { class: "sm ghost danger", title: t("Удалить задание"), onclick: function () {
          ST.confirm(t("Удалить задание?"), t("Вопросы задания перейдут в первое задание."), t("Удалить"), true).then(function (ok) {
            if (ok) api("DELETE", "/api/tasks/" + k.id).then(A.render).catch(A.err);
          });
        } }, "✕") : null);
      var tbox = h("div", { class: "task" }, head);
      qs.forEach(function (q, qi) {
        n++;
        var meta = [t(ST.TYPE_NAMES[q.type])];
        if (q.type !== "likert") meta.push(norm && norm.kind !== "tasks" ? t("баллы по нормам") : ST.tf("{0} б.", A.num(q.points)));
        if (nvar > 1) meta.push(q.variant ? ST.tf("вариант {0}", q.variant) : t("все варианты"));
        if ((q.body.images || []).length) meta.push("🖼");
        if (q.body.audio) meta.push("🔊");
        var row = h("div", { class: "qrow" }, h("div", { class: "qn" }, String(n)),
          h("div", { class: "qmain", onclick: function () { if (edit) editQuestion(T, q); } },
            h("div", { class: "qt", html: ST.fmt(plainText(q.body.text) || "(" + t("без текста") + ")") }),
            h("div", { class: "qmeta" }, meta.map(function (m) { return h("span", null, m); }))),
          edit ? h("div", { class: "qacts" },
            h("button", { class: "sm ghost", title: t("Выше"), disabled: (qi === 0 && ti === 0) || null, onclick: function () { move(T, q, -1); } }, "▲"),
            h("button", { class: "sm ghost", title: t("Ниже"), onclick: function () { move(T, q, 1); } }, "▼"),
            h("button", { class: "sm ghost", title: t("Копия"), onclick: function () {
              api("POST", "/api/questions/" + q.id + "/copy", {}).then(A.render).catch(A.err);
            } }, "⧉"),
            h("button", { class: "sm ghost danger", title: t("Удалить"), onclick: function () {
              ST.confirm(t("Удалить вопрос?"), plainText(q.body.text).slice(0, 120), t("Удалить"), true).then(function (ok) {
                if (ok) api("DELETE", "/api/questions/" + q.id).then(A.render).catch(A.err);
              });
            } }, "✕")) : null);
        tbox.appendChild(row);
      });
      if (!qs.length) tbox.appendChild(h("div", { class: "empty" }, t("В задании нет вопросов")));
      if (edit) tbox.appendChild(h("div", { class: "addq" }, h("button", { class: "pri sm", onclick: function () { chooseType(T, k.id); } }, "＋ " + t("Вопрос"))));
      pane.appendChild(tbox);
    });
    ST.math(pane);
    if (edit) {
      pane.appendChild(h("div", { class: "bar" }, h("button", { onclick: function () {
        api("POST", "/api/tests/" + T.id + "/tasks", {}).then(A.render).catch(A.err);
      } }, "＋ " + t("Задание")), h("span", { class: "muted small" },
        t("Задания объединяют вопросы. Из задания можно выдавать ученику несколько случайных вопросов (банк вопросов)."))));
    }
  };

  function move(T, q, dir) {
    var list = T.question_list.slice();
    var tasks = T.tasks.map(function (k) { return k.id; });
    list.sort(function (a, b) { return tasks.indexOf(a.task_id) - tasks.indexOf(b.task_id) || a.sort - b.sort || a.id - b.id; });
    var i = list.indexOf(q);
    var items = list.map(function (x) { return { id: x.id, task_id: x.task_id }; });
    var j = i + dir;
    if (j < 0) return;
    if (j >= items.length || items[j].task_id !== q.task_id) {
      // переход в соседнее задание
      var ti = tasks.indexOf(q.task_id) + dir;
      if (ti < 0 || ti >= tasks.length) return;
      items[i].task_id = tasks[ti];
      if (dir < 0) { /* в конец предыдущего задания: порядок уже верный */ }
    } else {
      var x = items[i]; items[i] = items[j]; items[j] = x;
    }
    api("PUT", "/api/tests/" + T.id + "/order", { items: items }).then(A.render).catch(A.err);
  }

  function chooseType(T, taskId) {
    var grid = h("div", { class: "typegrid" });
    var chosen = null, closeBtn;
    TYPES.forEach(function (ty) {
      grid.appendChild(h("button", { type: "button", onclick: function () { chosen = ty; closeBtn.click(); } },
        h("b", null, t(ST.TYPE_NAMES[ty])), h("small", null, t(TYPE_HINT[ty]))));
    });
    var p = ST.modal(t("Тип вопроса"), grid, [{ text: t("Отмена"), value: null }], true);
    closeBtn = document.querySelector(".modal .acts button");
    p.then(function () {
      if (chosen) editQuestion(T, { type: chosen, task_id: taskId, points: defaultPoints(chosen), variant: 0, body: blankBody(chosen), answer: {} });
    });
  }
  function defaultPoints(ty) { return ty === "likert" ? 0 : (ty === "multi" || ty === "match" || ty === "order" || ty === "chrono" ? 2 : 1); }
  function blankBody(ty) {
    var b = { text: "", images: [] };
    if (ty === "single" || ty === "multi") b.options = [{ id: "a", text: "" }, { id: "b", text: "" }, { id: "c", text: "" }, { id: "d", text: "" }];
    if (ty === "short") b.fields = [{ id: "f1", label: "" }];
    if (ty === "match") { b.left = [{ id: "l1", text: "" }, { id: "l2", text: "" }, { id: "l3", text: "" }]; b.right = [{ id: "r1", text: "" }, { id: "r2", text: "" }, { id: "r3", text: "" }]; }
    if (ty === "order") b.items = [{ id: "i1", text: "" }, { id: "i2", text: "" }, { id: "i3", text: "" }];
    if (ty === "chrono") b.events = [{ id: "e1", text: "", date: "" }, { id: "e2", text: "", date: "" }, { id: "e3", text: "", date: "" }];
    if (ty === "likert") { b.statements = [{ id: "s1", text: "" }]; b.scale = ["Полностью не согласен", "Скорее не согласен", "Затрудняюсь ответить", "Скорее согласен", "Полностью согласен"].map(t); }
    if (ty === "file") { b.max_mb = 10; b.accept = ""; b.task_files = []; }
    return b;
  }

  /* ---------------- загрузка медиа ---------------- */
  function upload(T, accept, kind) {
    return ST.pickFiles(accept).then(function (files) {
      if (!files.length) return null;
      return ST.readFile(files[0]).then(function (d) {
        return api("POST", "/api/tests/" + T.id + "/media", { name: d.name, data: d.data, kind: kind }, { timeout: 180000 });
      });
    });
  }
  var IMG = ".png,.jpg,.jpeg,.gif,.webp,.svg,.bmp";

  /* ---------------- редактор вопроса ---------------- */
  function editQuestion(T, q0) {
    var q = JSON.parse(JSON.stringify(q0));
    var b = q.body, a = q.answer || {};
    var norm = normOf(T);
    var uid = 0;
    function nid(p) { uid++; return (p || "n") + Date.now().toString(36) + uid; }

    // приведение к виду редактора
    if (q.type === "order") b.items = orderBy(b.items, a.order);
    if (q.type === "chrono") { b.events = orderBy(b.events, a.order).map(function (e) { e.date = (a.dates || {})[e.id] || e.date || ""; return e; }); }
    if (q.type === "single" || q.type === "multi") { a.correct = a.correct || []; a.partial = a.partial || "norms"; }
    if (q.type === "short") { a.fields = a.fields || {}; }
    if (q.type === "match") {
      a.pairs = a.pairs || {};
      // пары по строкам: правый элемент строки — пара левого; лишние правые — отдельным списком
      var used = {};
      b.rows = b.left.map(function (l) {
        var rid = a.pairs[l.id];
        var r = b.right.filter(function (x) { return x.id === rid; })[0] || { id: nid("r"), text: "" };
        used[r.id] = 1;
        return { l: l, r: r };
      });
      b.extra = b.right.filter(function (r) { return !used[r.id]; });
    }
    if (q.type === "cloze") b.cloze = clozeToText(b.text, b.blanks || [], a.blanks || {});

    var prevBox = h("div");
    var form = h("div");
    function refresh() {
      var built;
      try { built = build(); } catch (e) { prevBox.innerHTML = ""; prevBox.appendChild(h("div", { class: "muted" }, e.message)); return; }
      prevBox.innerHTML = "";
      var pq = A.toPublic({ id: "p", type: q.type, body: built.body, answer: built.answer });
      if (q.type === "order" || q.type === "chrono") pq.items = (q.type === "order" ? built.body.items : built.body.events).slice();
      if (q.type === "match") pq.right = built.body.right;
      var cr = correctFromBuilt(built);
      var resp = cr.order ? { order: cr.order, touched: true } : null;
      prevBox.appendChild(ST.renderQuestion(pq, resp, { review: { correct: correctFromBuilt(built) }, readonly: true,
        onPlay: function () { return Promise.resolve({ left: null }); } }));
    }
    var refreshT = null;
    function later() { clearTimeout(refreshT); refreshT = setTimeout(refresh, 250); }

    // --- текст вопроса с панелью
    var text = h("textarea", { rows: q.type === "cloze" ? 6 : 4, "aria-label": t("Текст вопроса") });
    text.value = q.type === "cloze" ? b.cloze : (b.text || "");
    text.addEventListener("input", function () { if (q.type === "cloze") b.cloze = text.value; else b.text = text.value; later(); });
    var thumbs = h("div", { class: "thumbs" });
    function drawThumbs() {
      thumbs.innerHTML = "";
      (b.images || []).forEach(function (m, i) {
        thumbs.appendChild(h("div", { class: "th" }, h("img", { src: "/api/media/" + m, alt: "" }),
          h("button", { type: "button", title: t("Убрать"), onclick: function () { b.images.splice(i, 1); drawThumbs(); later(); } }, "×")));
      });
    }
    var audioInfo = h("span", { class: "muted small" });
    var plays = h("input", { type: "number", min: 0, max: 20, style: { width: "64px" } });
    plays.value = b.audio ? b.audio.plays || 0 : 2;
    plays.addEventListener("input", function () { if (b.audio) b.audio.plays = +plays.value || 0; });
    var audioRow = h("div", { class: "bar hidden" }, "🔊 ", audioInfo, h("label", { class: "muted small", style: { display: "flex", gap: "6px", alignItems: "center" } },
      t("Прослушиваний (0 — без ограничения):"), plays),
      h("button", { type: "button", class: "sm danger", onclick: function () { delete b.audio; drawAudio(); } }, t("Убрать звук")));
    function drawAudio() {
      audioRow.classList.toggle("hidden", !b.audio);
      if (b.audio) audioInfo.textContent = t("Звук прикреплён") + " (#" + b.audio.media + ")";
    }
    var tb = h("div", { class: "tb" },
      h("button", { type: "button", onclick: function () { A.insertFormula(text); } }, "ƒx " + t("Формула")),
      h("button", { type: "button", onclick: function () {
        upload(T, IMG, "image").then(function (m) { if (m) { b.images = (b.images || []).concat([m.id]); drawThumbs(); later(); } }).catch(A.err);
      } }, "🖼 " + t("Картинка")),
      h("button", { type: "button", onclick: function () {
        upload(T, ".mp3,.wav,.ogg,.m4a,.aac,.webm", "audio").then(function (m) {
          if (m) { b.audio = { media: m.id, plays: +plays.value || 0 }; drawAudio(); later(); }
        }).catch(A.err);
      } }, "🔊 " + t("Звук")),
      h("button", { type: "button", title: t("Жирный текст: **так**"), onclick: function () { wrapSel(text, "**", "**"); } }, h("b", null, "Ж")),
      q.type === "cloze" ? h("button", { type: "button", onclick: function () { wrapSel(text, "[", "]"); } }, "[ ] " + t("Пропуск")) : null);
    form.appendChild(A.field(q.type === "cloze" ? t("Текст с пропусками") : t("Текст вопроса"), h("div", null, tb, text)));
    if (q.type === "cloze") form.appendChild(h("div", { class: "muted small" },
      t("Пропуск — слово в квадратных скобках: «Столица Беларуси — [Минск]». Несколько допустимых ответов — через «;»: [1812;1812 год]. Выбор из списка — через «|», первым верный: [Минск|Брест|Гродно].")));
    form.appendChild(thumbs);
    form.appendChild(audioRow);
    drawThumbs();
    drawAudio();

    // --- часть, зависящая от типа
    var part = h("div", { class: "sec" });
    form.appendChild(part);
    var TYPE_UI = {
      single: optionsUI, multi: optionsUI, short: shortUI, match: matchUI, order: orderUI, chrono: chronoUI,
      cloze: function () {}, likert: likertUI, essay: essayUI, file: fileUI
    };
    TYPE_UI[q.type](part);

    // --- баллы, вариант, задание
    var pts = h("input", { type: "number", min: 0, max: 100, step: "0.5", style: { width: "90px" } });
    pts.value = q.points != null ? q.points : 1;
    var variant = A.select([[0, t("Все варианты")]].concat(Array.apply(null, Array(Math.max(1, T.settings.variants || 1))).map(function (_x, i) {
      return [i + 1, ST.tf("Вариант {0}", i + 1)];
    })), q.variant || 0);
    var task = A.select(T.tasks.map(function (k) { return [k.id, ST.tf("Задание {0}", k.num) + (k.title ? " — " + k.title : "")]; }), q.task_id);
    var bottom = h("div", { class: "form sec" },
      q.type === "likert" ? null : (norm && norm.kind !== "tasks" ? h("div", { class: "muted small" }, t("Баллы за вопрос определяются нормами оценки, выбранными в настройках теста.")) :
        A.field(t("Баллы за вопрос"), pts)),
      (T.settings.variants || 1) > 1 ? A.field(t("Вариант"), variant) : null,
      T.tasks.length > 1 ? A.field(t("Задание"), task) : null);
    form.appendChild(bottom);

    var layout = h("div", { class: "qed" }, form, h("div", { class: "prev" }, h("h3", null, t("Предпросмотр с правильным ответом")), prevBox));
    var err = h("div", { class: "bad", role: "alert" });
    ST.modal((q.id ? t("Вопрос") : t("Новый вопрос")) + " — " + t(ST.TYPE_NAMES[q.type]), h("div", null, layout, err),
      [{ text: t("Отмена"), value: null }, { text: t("Сохранить"), value: 1, cls: "pri", check: function () {
        var built;
        try { built = build(); } catch (e) { err.textContent = e.message; return false; }
        var payload = { type: q.type, body: built.body, answer: built.answer, points: +pts.value || 0, variant: +variant.value || 0, task_id: +task.value };
        var req = q.id ? api("PUT", "/api/questions/" + q.id, payload) : api("POST", "/api/tests/" + T.id + "/questions", payload);
        req.then(function () { closeModal(); ST.toast(t("Вопрос сохранён")); A.render(); }).catch(function (e) { err.textContent = e.message; });
        return false;
      } }], true);
    var modalBg = document.querySelectorAll(".modal-bg");
    modalBg = modalBg[modalBg.length - 1];
    function closeModal() { if (modalBg) modalBg.remove(); }
    refresh();

    /* ---- интерфейсы типов ---- */
    function itemList(container, items, opts) {
      // opts: {placeholder, correct: fn(item)→bool|null, onCorrect, image, ordered, extraFields(item)→[nodes], min}
      var list = h("div", { class: "items" });
      function draw() {
        list.innerHTML = "";
        items.forEach(function (it, i) {
          var row = h("div", { class: "item" });
          if (opts.correct) {
            var c = h("input", { type: opts.radio ? "radio" : "checkbox", class: "ok", name: "ok" + uid, title: t("Верный ответ") });
            c.checked = opts.correct(it);
            c.addEventListener("change", function () { opts.onCorrect(it, c.checked); draw(); later(); });
            row.appendChild(c);
          }
          if (opts.ordered) row.appendChild(h("b", { style: { minWidth: "22px", color: "var(--brand2)" } }, (i + 1) + "."));
          if (opts.before) opts.before(it).forEach(function (n2) { row.appendChild(n2); });
          var mi = A.mathInput(it.text, opts.placeholder ? opts.placeholder(i) : "", function (v) { it.text = v; later(); });
          row.appendChild(mi);
          if (opts.image) {
            if (it.image) row.appendChild(h("img", { class: "thumb", src: "/api/media/" + it.image, alt: "" }));
            row.appendChild(h("button", { type: "button", class: "sm ghost", title: it.image ? t("Убрать картинку") : t("Картинка"), onclick: function () {
              if (it.image) { delete it.image; draw(); later(); return; }
              upload(T, IMG, "image").then(function (m) { if (m) { it.image = m.id; draw(); later(); } }).catch(A.err);
            } }, it.image ? "🖼✕" : "🖼"));
          }
          if (opts.ordered) {
            row.appendChild(h("button", { type: "button", class: "sm ghost", disabled: i === 0 || null, onclick: function () {
              items.splice(i - 1, 0, items.splice(i, 1)[0]); draw(); later(); } }, "▲"));
            row.appendChild(h("button", { type: "button", class: "sm ghost", disabled: i === items.length - 1 || null, onclick: function () {
              items.splice(i + 1, 0, items.splice(i, 1)[0]); draw(); later(); } }, "▼"));
          }
          row.appendChild(h("button", { type: "button", class: "sm ghost danger", title: t("Удалить"), disabled: items.length <= (opts.min || 1) || null,
            onclick: function () { items.splice(i, 1); draw(); later(); } }, "✕"));
          list.appendChild(row);
        });
      }
      draw();
      container.appendChild(list);
      container.appendChild(h("button", { type: "button", class: "sm", onclick: function () {
        items.push(opts.make ? opts.make() : { id: nid(), text: "" }); draw(); later();
        var inps = list.querySelectorAll(".mi input");
        if (inps.length) inps[inps.length - 1].focus();
      } }, "＋ " + (opts.addText || t("Добавить"))));
      return draw;
    }

    function optionsUI(box) {
      var multi = q.type === "multi";
      box.appendChild(h("b", null, multi ? t("Варианты ответа — отметьте все верные") : t("Варианты ответа — отметьте верный")));
      itemList(box, b.options, {
        radio: !multi, image: true, min: 2, addText: t("Вариант"),
        placeholder: function (i) { return ST.tf("Вариант {0}", i + 1); },
        correct: function (it) { return a.correct.indexOf(it.id) >= 0; },
        onCorrect: function (it, on) {
          if (!multi) a.correct = on ? [it.id] : [];
          else if (on && a.correct.indexOf(it.id) < 0) a.correct.push(it.id);
          else if (!on) a.correct = a.correct.filter(function (x) { return x !== it.id; });
        }
      });
      box.appendChild(A.check(t("Не перемешивать варианты (например, «все ответы верны»)"), b.keep_order, function (v) { b.keep_order = v; }));
      if (multi) {
        box.appendChild(A.field(t("Частично верный ответ"), A.select([
          ["norms", t("По нормам: одна ошибка — половина баллов")], ["proportional", t("Пропорционально числу верных отметок")],
          ["none", t("Только полностью верный ответ")]], a.partial, function (v) { a.partial = v; later(); })));
      }
    }

    function shortUI(box) {
      box.appendChild(h("b", null, t("Поля ответа")));
      box.appendChild(h("div", { class: "muted small" }, t("Регистр букв и лишние пробелы не учитываются. Несколько допустимых ответов — через «;». Числа сравниваются как числа (2,5 = 2.5).")));
      b.fields.forEach(function (f) { f.answers = f.answers != null ? f.answers : (a.fields[f.id] || []).join("; "); f.text = f.text != null ? f.text : (f.label || ""); });
      itemList(box, b.fields, {
        addText: t("Поле"), make: function () { return { id: nid("f"), label: "", text: "", answers: "" }; },
        placeholder: function () { return t("Подпись поля (необязательно), например «площадь»"); },
        before: function () { return []; }
      });
      // поле «ответ» добавляется к каждой строке отдельно
      var rows = box.querySelectorAll(".item");
      Array.prototype.forEach.call(rows, function (row, i) { addAnswerInput(row, b.fields[i]); });
      var obs = new MutationObserver(function () {
        Array.prototype.forEach.call(box.querySelectorAll(".item"), function (row, i) { if (!row.querySelector(".ans")) addAnswerInput(row, b.fields[i]); });
      });
      obs.observe(box, { childList: true, subtree: true });
      var tol = h("input", { type: "number", min: 0, step: "any", style: { width: "110px" } });
      tol.value = a.tol || 0;
      tol.addEventListener("input", function () { a.tol = parseFloat(tol.value.replace(",", ".")) || 0; });
      box.appendChild(h("div", { style: { marginTop: "8px" } }, A.field(t("Допустимая погрешность для чисел (0 — точно)"), tol)));
    }
    function addAnswerInput(row, f) {
      if (!f) return;
      var inp = h("input", { type: "text", class: "ans", placeholder: t("Правильный ответ"), style: { flex: 1, minWidth: 0 } });
      inp.value = f.answers || "";
      inp.addEventListener("input", function () { f.answers = inp.value; later(); });
      row.insertBefore(inp, row.lastChild);
    }

    function matchUI(box) {
      box.appendChild(h("b", null, t("Пары: слева — элемент, справа — его пара")));
      var list = h("div", { class: "items" });
      function draw() {
        list.innerHTML = "";
        b.rows.forEach(function (r, i) {
          list.appendChild(h("div", { class: "item" }, h("b", { style: { minWidth: "22px" } }, (i + 1) + "."),
            A.mathInput(r.l.text, t("Левый элемент"), function (v) { r.l.text = v; later(); }), "→",
            A.mathInput(r.r.text, t("Пара"), function (v) { r.r.text = v; later(); }),
            h("button", { type: "button", class: "sm ghost danger", disabled: b.rows.length <= 2 || null, onclick: function () { b.rows.splice(i, 1); draw(); later(); } }, "✕")));
        });
      }
      draw();
      box.appendChild(list);
      box.appendChild(h("button", { type: "button", class: "sm", onclick: function () {
        b.rows.push({ l: { id: nid("l"), text: "" }, r: { id: nid("r"), text: "" } }); draw(); later();
      } }, "＋ " + t("Пара")));
      var ex = h("div", { class: "sec" }, h("b", null, t("Лишние варианты справа (необязательно)")));
      itemList(ex, b.extra, { min: 0, addText: t("Лишний вариант"), placeholder: function () { return t("Вариант без пары"); } });
      box.appendChild(ex);
      box.appendChild(A.check(t("Частичный балл за верные пары"), a.partial !== false, function (v) { a.partial = v; }));
    }

    function partialOrder(box) {
      box.appendChild(A.field(t("Частично верный ответ"), A.select([["none", t("Только полностью верный порядок")],
        ["positions", t("Пропорционально числу элементов на своих местах")], ["pairs", t("Пропорционально верно расположенным соседним парам")]],
        a.partial || "none", function (v) { a.partial = v; })));
    }
    function orderUI(box) {
      box.appendChild(h("b", null, t("Элементы в правильном порядке")));
      box.appendChild(h("div", { class: "muted small" }, t("Ученик увидит их вперемешку.")));
      itemList(box, b.items, { ordered: true, image: true, min: 2, addText: t("Элемент"), placeholder: function (i) { return ST.tf("Элемент {0}", i + 1); } });
      partialOrder(box);
    }
    function chronoUI(box) {
      box.appendChild(h("b", null, t("События от самого раннего к самому позднему")));
      box.appendChild(h("div", { class: "muted small" }, t("Ученик перетаскивает события на ленту времени. Даты ученик не видит — они показываются в разборе после теста.")));
      var redraw = itemList(box, b.events, {
        ordered: true, image: true, min: 2, addText: t("Событие"), make: function () { return { id: nid("e"), text: "", date: "" }; },
        placeholder: function () { return t("Событие"); },
        before: function (ev) {
          var d = h("input", { type: "text", class: "date", placeholder: t("Дата"), title: t("Дата (необязательно)") });
          d.value = ev.date || "";
          d.addEventListener("input", function () { ev.date = d.value; later(); });
          return [d];
        }
      });
      box.appendChild(h("button", { type: "button", class: "sm", style: { marginLeft: "6px" }, onclick: function () {
        var num = function (s) { var m = /-?\d+/.exec(String(s || "").replace(/\s/g, "")); var v = m ? +m[0] : NaN; if (/до н\.?\s*э|да н\.?\s*э|BC/i.test(s)) v = -v; return v; };
        b.events.sort(function (x, y) { var p = num(x.date), r = num(y.date); return (isNaN(p) ? 1e9 : p) - (isNaN(r) ? 1e9 : r); });
        redraw(); later();
      } }, t("Упорядочить по датам")));
      var sl = h("input", { type: "text", placeholder: t("Раньше") }); sl.value = b.start_label || "";
      var el = h("input", { type: "text", placeholder: t("Позже") }); el.value = b.end_label || "";
      sl.addEventListener("input", function () { b.start_label = sl.value; later(); });
      el.addEventListener("input", function () { b.end_label = el.value; later(); });
      box.appendChild(h("div", { class: "form", style: { marginTop: "10px" } }, A.field(t("Подпись начала ленты"), sl), A.field(t("Подпись конца ленты"), el)));
      partialOrder(box);
    }
    function likertUI(box) {
      box.appendChild(h("b", null, t("Утверждения")));
      itemList(box, b.statements, { addText: t("Утверждение"), placeholder: function () { return t("Утверждение"); } });
      var sc = h("div", { class: "sec" }, h("b", null, t("Шкала ответов")));
      var scale = b.scale.map(function (s) { return { id: nid("s"), text: s }; });
      b._scale = scale;
      itemList(sc, scale, { min: 2, addText: t("Значение"), placeholder: function (i) { return ST.tf("Значение {0}", i + 1); } });
      box.appendChild(sc);
      box.appendChild(h("div", { class: "muted small" }, t("Опрос не оценивается. Ответы видны в анализе вопросов.")));
    }
    function essayUI(box) {
      var mw = h("input", { type: "number", min: 0, style: { width: "90px" } }); mw.value = b.min_words || 0;
      mw.addEventListener("input", function () { b.min_words = +mw.value || 0; });
      var sample = h("textarea", { rows: 3 }); sample.value = a.sample || "";
      sample.addEventListener("input", function () { a.sample = sample.value; });
      box.appendChild(h("div", { class: "form" }, A.field(t("Минимум слов (подсказка ученику, 0 — нет)"), mw),
        A.field(t("Образец ответа или критерии (видит только учитель)"), sample, "wide")));
    }
    function fileUI(box) {
      var files = h("div", { class: "thumbs" });
      function draw() {
        files.innerHTML = "";
        (b.task_files || []).forEach(function (m, i) {
          files.appendChild(h("span", { class: "pill" }, h("a", { href: "/api/media/" + m, target: "_blank" }, ST.tf("файл #{0}", m)), " ",
            h("button", { type: "button", class: "sm ghost", onclick: function () { b.task_files.splice(i, 1); draw(); } }, "×")));
        });
      }
      draw();
      var acc = h("input", { type: "text", placeholder: ".docx, .xlsx, .pdf" }); acc.value = b.accept || "";
      acc.addEventListener("input", function () { b.accept = acc.value; });
      var mx = h("input", { type: "number", min: 1, max: 20, style: { width: "90px" } }); mx.value = b.max_mb || 10;
      mx.addEventListener("input", function () { b.max_mb = +mx.value || 10; });
      var sample = h("textarea", { rows: 3 }); sample.value = a.sample || "";
      sample.addEventListener("input", function () { a.sample = sample.value; });
      box.appendChild(h("b", null, t("Файлы задания (ученик скачивает их)")));
      box.appendChild(files);
      box.appendChild(h("button", { type: "button", class: "sm", onclick: function () {
        upload(T, "", "file").then(function (m) { if (m) { b.task_files = (b.task_files || []).concat([m.id]); draw(); } }).catch(A.err);
      } }, "📎 " + t("Прикрепить файл задания")));
      box.appendChild(h("div", { class: "form", style: { marginTop: "10px" } },
        A.field(t("Допустимые типы файлов ответа (пусто — документы, таблицы, картинки, архивы, программы)"), acc, "wide"),
        A.field(t("Наибольший размер, МБ"), mx), A.field(t("Критерии проверки (видит только учитель)"), sample, "wide")));
    }

    /* ---- сборка вопроса для сохранения ---- */
    function build() {
      var body = { text: b.text || "", images: b.images || [] }, ans = {};
      if (b.audio) body.audio = b.audio;
      var ty = q.type;
      function need(c, m) { if (!c) throw new Error(t(m)); }
      if (ty === "single" || ty === "multi") {
        body.options = b.options.filter(function (o) { return (o.text || "").trim() || o.image; });
        body.keep_order = !!b.keep_order;
        ans.correct = a.correct.filter(function (id) { return body.options.some(function (o) { return o.id === id; }); });
        ans.partial = a.partial;
        need(body.options.length >= 2, "Добавьте хотя бы два варианта ответа");
        need(ans.correct.length, "Отметьте верный ответ");
      } else if (ty === "short") {
        body.fields = b.fields.map(function (f) { return { id: f.id, label: (f.text != null ? f.text : f.label) || "" }; });
        ans.fields = {};
        b.fields.forEach(function (f) {
          var v = String(f.answers || "").split(";").map(function (x) { return x.trim(); }).filter(Boolean);
          need(v.length, "Укажите правильный ответ для каждого поля");
          ans.fields[f.id] = v;
        });
        ans.tol = a.tol || 0;
      } else if (ty === "match") {
        var rows = b.rows.filter(function (r) { return (r.l.text || "").trim() || (r.r.text || "").trim(); });
        need(rows.length >= 2, "Добавьте хотя бы две пары");
        rows.forEach(function (r) { need((r.l.text || "").trim() && (r.r.text || "").trim(), "Заполните обе части каждой пары"); });
        body.left = rows.map(function (r) { return { id: r.l.id, text: r.l.text }; });
        body.right = rows.map(function (r) { return { id: r.r.id, text: r.r.text }; })
          .concat(b.extra.filter(function (x) { return (x.text || "").trim(); }).map(function (x) { return { id: x.id, text: x.text }; }));
        ans.pairs = {};
        rows.forEach(function (r) { ans.pairs[r.l.id] = r.r.id; });
        ans.partial = a.partial !== false;
      } else if (ty === "order") {
        body.items = b.items.filter(function (x) { return (x.text || "").trim() || x.image; });
        need(body.items.length >= 2, "Добавьте хотя бы два элемента");
        ans.partial = a.partial || "none";
      } else if (ty === "chrono") {
        body.events = b.events.filter(function (x) { return (x.text || "").trim() || x.image; });
        need(body.events.length >= 2, "Добавьте хотя бы два события");
        body.start_label = b.start_label || ""; body.end_label = b.end_label || "";
        ans.partial = a.partial || "none";
      } else if (ty === "cloze") {
        var parsed = textToCloze(b.cloze || "");
        body.text = parsed.text; body.blanks = parsed.blanks; ans.blanks = parsed.answers;
        need(parsed.blanks.length, "Отметьте пропуски в тексте квадратными скобками");
      } else if (ty === "likert") {
        body.statements = b.statements.filter(function (x) { return (x.text || "").trim(); });
        body.scale = (b._scale || []).map(function (x) { return x.text; }).filter(function (x) { return (x || "").trim(); });
        need(body.statements.length, "Добавьте хотя бы одно утверждение");
        need(body.scale.length >= 2, "В шкале нужно хотя бы два значения");
      } else if (ty === "essay") {
        body.min_words = b.min_words || 0; ans.sample = a.sample || "";
      } else if (ty === "file") {
        body.task_files = b.task_files || []; body.accept = b.accept || ""; body.max_mb = b.max_mb || 10; ans.sample = a.sample || "";
      }
      return { body: body, answer: ans };
    }
    function correctFromBuilt(bt) {
      var x = bt.answer, ty = q.type;
      if (ty === "single" || ty === "multi") return { options: x.correct };
      if (ty === "short") { var f = {}; Object.keys(x.fields).forEach(function (k) { f[k] = x.fields[k][0]; }); return { fields: f }; }
      if (ty === "match") return { pairs: x.pairs };
      if (ty === "order") return { order: bt.body.items.map(function (i) { return i.id; }) };
      if (ty === "chrono") {
        var dates = {};
        bt.body.events.forEach(function (e) { if (e.date) dates[e.id] = e.date; });
        return { order: bt.body.events.map(function (i) { return i.id; }), dates: dates };
      }
      if (ty === "cloze") { var bl = {}; Object.keys(x.blanks).forEach(function (k) { bl[k] = x.blanks[k][0]; }); return { blanks: bl }; }
      return {};
    }
  }

  function orderBy(items, order) {
    items = (items || []).slice();
    if (!order || !order.length) return items;
    var pos = {};
    order.forEach(function (id, i) { pos[id] = i; });
    return items.sort(function (x, y) { return (pos[x.id] != null ? pos[x.id] : 999) - (pos[y.id] != null ? pos[y.id] : 999); });
  }
  function wrapSel(ta, l, r) {
    var s = ta.selectionStart, e = ta.selectionEnd, v = ta.value;
    ta.value = v.slice(0, s) + l + v.slice(s, e) + r + v.slice(e);
    ta.focus();
    ta.setSelectionRange(s + l.length, e + l.length);
    ta.dispatchEvent(new Event("input", { bubbles: true }));
  }
  /* пропуски: {{id}} ⇄ [ответ] / [верный|другой|другой] */
  function clozeToText(text, blanks, answers) {
    var by = {};
    blanks.forEach(function (b) { by[b.id] = b; });
    return String(text || "").replace(/\{\{([^}]+)\}\}/g, function (m, id) {
      var b = by[id];
      if (!b) return m;
      var right = answers[id] || [];
      if (b.kind === "select") {
        var ch = (b.choices || []).filter(function (c) { return c !== right[0]; });
        return "[" + [right[0]].concat(ch).join("|") + "]";
      }
      return "[" + right.join(";") + "]";
    });
  }
  function textToCloze(src) {
    var blanks = [], answers = {}, n = 0;
    var text = src.replace(/(^|[^\\])\[([^\[\]\n]+)\]/g, function (m, pre, inner) {
      n++;
      var id = "b" + n;
      var parts = inner.split("|").map(function (x) { return x.trim(); }).filter(Boolean);
      if (parts.length > 1) { blanks.push({ id: id, kind: "select", choices: parts }); answers[id] = [parts[0]]; }
      else { blanks.push({ id: id, kind: "input" }); answers[id] = inner.split(";").map(function (x) { return x.trim(); }).filter(Boolean); }
      return pre + "{{" + id + "}}";
    });
    return { text: text, blanks: blanks, answers: answers };
  }
})();
