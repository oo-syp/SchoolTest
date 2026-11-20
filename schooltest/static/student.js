/* SchoolTest — страница ученика */
"use strict";
(function () {
  var h = ST.h, t = ST.t, api = ST.api;
  var app = document.getElementById("app");
  var PUB = {};
  var S = null;           // состояние попытки с сервера
  var cur = 0;            // текущий вопрос (индекс в плане)
  var pending = {};       // несохранённые ответы: qid → ответ
  var saving = false, saveTimer = null, retryTimer = null, saveFailed = false;
  var tick = null, pingTimer = null, deadline = null, waitTimer = null;
  var secEnd = null, secBusy = false, secTick = null;   // субтест с отдельным временем (ШТУР-2)
  var TERMS = {
    school: { cls: "класса", list: "Выберите себя в списке класса" },
    vuz: { cls: "группы", list: "Выберите себя в списке группы" },
    enterprise: { cls: "подразделения", list: "Выберите себя в списке" }
  };

  function store(v) {
    try { if (v) localStorage.setItem("st_cur", JSON.stringify(v)); else localStorage.removeItem("st_cur"); } catch (e) {}
  }
  function stored() { try { return JSON.parse(localStorage.getItem("st_cur") || "null"); } catch (e) { return null; } }

  function clearTimers() {
    clearInterval(tick); clearInterval(pingTimer); clearInterval(waitTimer); clearTimeout(retryTimer); clearInterval(secTick);
    tick = pingTimer = waitTimer = retryTimer = secTick = null;
  }

  /* ---------------- шапка ---------------- */
  function topbar(extra) {
    var langs = null;
    if (PUB.student_lang_switch !== false) {
      langs = h("div", { class: "langs", role: "group", "aria-label": "Мова / Язык" },
        ["ru", "be"].map(function (l) {
          return h("button", { type: "button", class: ST.lang === l ? "on" : null, onclick: function () {
            if (ST.lang === l) return;
            ST.setLang(l);
            rerender();
          } }, l === "ru" ? "Рус" : "Бел");
        }));
    }
    return h("div", { class: "top" },
      h("div", { class: "logo" }, h("img", { src: "/icon.svg", alt: "" }),
        h("div", null, "SchoolTest", PUB.school_name ? h("small", null, PUB.school_name) : null)),
      h("div", { class: "sp" }), extra || null, langs);
  }
  var rerender = function () {};

  /* ---------------- вход по коду ---------------- */
  function screenCode(msg, code) {
    clearTimers();
    rerender = function () { screenCode(err.textContent, inp.value); };
    var inp = h("input", { type: "text", inputmode: "numeric", autocomplete: "off", maxlength: 6, placeholder: "000000",
                           "aria-label": t("Код теста") });
    inp.value = code || "";
    var err = h("div", { class: "err", role: "alert" }, msg || "");
    var btn = h("button", { class: "pri", type: "submit" }, t("Войти"));
    var form = h("form", { class: "enter", onsubmit: function (e) {
      e.preventDefault();
      var c = inp.value.replace(/\D/g, "");
      if (c.length !== 6) { err.textContent = t("Код теста — 6 цифр"); inp.focus(); return; }
      btn.disabled = true;
      api("POST", "/api/s/join", { code: c }).then(function (r) { screenStudents(c, r); })
        .catch(function (e2) {
          if (e2.status === 404) {
            api("POST", "/api/sv/join", { code: c }).then(function (sv) { screenSurvey(c, sv); })
              .catch(function () { err.textContent = e2.message; btn.disabled = false; });
          } else { err.textContent = e2.message; btn.disabled = false; }
        });
    } },
      h("h1", null, t("Вход в тест")),
      h("p", null, t("Введите код, который показал учитель")),
      h("div", { class: "codebox" }, inp), btn, err);
    inp.addEventListener("input", function () { inp.value = inp.value.replace(/\D/g, "").slice(0, 6); });
    app.innerHTML = "";
    app.appendChild(topbar());
    app.appendChild(h("div", { class: "wrap" }, form));
    setTimeout(function () { inp.focus(); }, 50);
  }

  /* ---------------- выбор себя в списке ---------------- */
  function screenStudents(code, info) {
    rerender = function () { screenStudents(code, info); };
    var terms = TERMS[PUB.org_type] || TERMS.school;
    var q = h("input", { type: "search", class: "search", placeholder: t("Поиск по фамилии"), "aria-label": t("Поиск по фамилии") });
    var grid = h("div", { class: "studs" });
    var err = h("div", { class: "err", role: "alert" });
    function draw() {
      var f = q.value.trim().toLowerCase();
      grid.innerHTML = "";
      info.students.filter(function (s) { return !f || s.name.toLowerCase().indexOf(f) >= 0; }).forEach(function (s) {
        grid.appendChild(h("button", { type: "button", onclick: function () { choose(s); } }, s.name));
      });
    }
    function choose(s) {
      var ask = info.run.ask || [];
      var gender = h("select", null, h("option", { value: "" }, "—"), h("option", { value: "m" }, t("мужской")), h("option", { value: "f" }, t("женский")));
      var age = h("input", { type: "number", min: 6, max: 99, style: { width: "90px" } });
      var body = ask.length ? h("div", null, h("p", { style: { marginTop: 0 } }, s.name),
        ask.indexOf("gender") >= 0 ? h("label", { class: "f" }, t("Пол"), gender) : null, h("div", { style: { height: "8px" } }),
        ask.indexOf("age") >= 0 ? h("label", { class: "f" }, t("Полных лет"), age) : null) : s.name;
      var conf = ask.length ? ST.modal(t("Это вы?"), body, [{ text: t("Отмена"), value: null }, { text: info.run.psy ? t("Да, начать") : t("Да, начать тест"), value: 1, cls: "pri",
        check: function () { if ((ask.indexOf("gender") >= 0 && !gender.value) || (ask.indexOf("age") >= 0 && !age.value)) { ST.toast(t("Укажите пол и возраст"), true); return false; } return true; } }]) :
        ST.confirm(t("Это вы?"), s.name, info.run.psy ? t("Да, начать") : t("Да, начать тест"));
      conf.then(function (ok) {
        if (!ok) return;
        api("POST", "/api/s/start", { code: code, student_id: s.id, extra: ask.length ? { gender: gender.value, age: age.value } : null }).then(function (r) {
          store({ code: code, aid: r.attempt_id });
          if (r.waiting) screenWaiting(r.attempt_id, s.name); else loadState(r.attempt_id);
        }).catch(function (e) { err.textContent = e.message; });
      });
    }
    q.addEventListener("input", draw);
    draw();
    var run = info.run;
    var meta = [run.class, ST.tf(run.psy ? "утверждений: {0}" : "вопросов: {0}", run.questions)];
    if (run.time_limit) meta.push(ST.tf("время: {0} мин", run.time_limit));
    app.innerHTML = "";
    app.appendChild(topbar(h("button", { class: "sm", onclick: function () { screenCode(); } }, "← " + t("Другой код"))));
    app.appendChild(h("div", { class: "wrap" },
      h("div", { class: "who-head" }, h("h1", null, run.title), h("div", { class: "muted" }, meta.join(" · "))),
      h("h2", null, t(terms.list)), q, err, grid));
  }

  /* ---------------- анкета (конструктор анкет, 1.3) ---------------- */
  function screenSurvey(code, sv) {
    clearTimers();
    rerender = function () { screenSurvey(code, sv); };
    var answers = {};
    var nameInput = sv.audience !== "anon" ? h("input", { type: "text", placeholder: t("Фамилия Имя"), style: { width: "100%" } }) : null;
    var err = h("div", { class: "err", role: "alert" });
    var qlist = h("div", { class: "wrap" });
    sv.items.forEach(function (q) {
      var qid = String(q.id);
      var field;
      if (q.type === "open") {
        field = h("textarea", { rows: 3, style: { width: "100%" }, oninput: function (e) { answers[qid] = e.target.value; } });
      } else if (q.type === "multi") {
        var cur = [];
        field = h("div", null, (q.options || []).map(function (o) {
          var cb = h("input", { type: "checkbox" });
          cb.addEventListener("change", function () {
            if (cb.checked) cur.push(o.id); else cur = cur.filter(function (x) { return x !== o.id; });
            answers[qid] = cur.slice();
          });
          return h("label", { class: "chk" }, cb, h("span", null, o.text));
        }));
      } else {
        field = h("div", null, (q.options || []).map(function (o) {
          var rb = h("input", { type: "radio", name: "sq" + qid });
          rb.addEventListener("change", function () { answers[qid] = o.id; });
          return h("label", { class: "chk" }, rb, h("span", null, o.text));
        }));
      }
      qlist.appendChild(h("div", { class: "qcard" }, h("div", { class: "rvhead" }, h("b", null, q.text),
        q.required ? h("span", { class: "pill" }, t("обязательно")) : null), field));
    });
    var btn = h("button", { class: "pri", onclick: function () {
      btn.disabled = true;
      api("POST", "/api/sv/" + sv.run_id + "/submit", { respondent: nameInput ? nameInput.value : "", answers: answers })
        .then(function () { screenSurveyDone(); })
        .catch(function (e) { err.textContent = e.message; btn.disabled = false; });
    } }, t("Отправить"));
    app.innerHTML = "";
    app.appendChild(topbar(h("button", { class: "sm", onclick: function () { screenCode(); } }, "← " + t("Другой код"))));
    app.appendChild(h("div", { class: "wrap" },
      h("div", { class: "who-head" }, h("h1", null, sv.title), sv.description ? h("div", { class: "muted" }, sv.description) : null),
      nameInput ? h("div", { class: "qcard" }, h("label", null, h("div", null, t("Ваше имя")), nameInput)) : null));
    app.appendChild(qlist);
    app.appendChild(h("div", { class: "wrap" }, err, btn));
  }

  function screenSurveyDone() {
    rerender = screenSurveyDone;
    app.innerHTML = "";
    app.appendChild(topbar());
    app.appendChild(h("div", { class: "wrap" }, h("div", { class: "result" }, h("h1", null, t("Спасибо!")),
      h("p", null, t("Ваши ответы сохранены.")),
      h("p", null, h("button", { onclick: function () { screenCode(); } }, t("Выйти"))))));
  }

  /* ---------------- ожидание разрешения учителя ---------------- */
  function screenWaiting(aid, name) {
    clearTimers();
    rerender = function () { screenWaiting(aid, name); };
    app.innerHTML = "";
    app.appendChild(topbar());
    app.appendChild(h("div", { class: "wrap" }, h("div", { class: "wait" }, h("div", { class: "spin" }),
      h("h1", null, t("Тест уже начат на другом устройстве")),
      h("p", null, name ? name + ". " : "", t("Попросите учителя разрешить продолжить тест на этом компьютере. Страница обновится сама.")),
      h("button", { onclick: function () { store(null); screenCode(); } }, t("Отмена")))));
    waitTimer = setInterval(function () {
      api("GET", "/api/s/a/" + aid).then(function (st) {
        if (st.status !== "waiting") { clearInterval(waitTimer); applyState(st); }
      }).catch(function (e) { if (e.status === 403 || e.status === 404) { clearInterval(waitTimer); store(null); screenCode(e.message); } });
    }, 3000);
  }

  /* ---------------- прохождение ---------------- */
  function loadState(aid) {
    return api("GET", "/api/s/a/" + aid).then(applyState).catch(function (e) {
      if (e.network) { app.innerHTML = ""; app.appendChild(topbar()); app.appendChild(h("div", { class: "wrap" },
        h("div", { class: "wait" }, h("h1", null, t("Нет связи с сервером")), h("p", null, t("Проверьте подключение к сети и обновите страницу.")),
          h("button", { class: "pri", onclick: function () { loadState(aid); } }, t("Повторить"))))); return; }
      store(null);
      screenCode(e.message);
    });
  }

  function applyState(st) {
    if (st.status === "waiting") return screenWaiting(st.attempt_id, st.student);
    S = st;
    if (st.status !== "active") return screenResult();
    if (!st.free_nav) cur = st.cur;
    else if (cur >= st.total || cur < 0 || !S._seen) cur = st.cur || 0;
    S._seen = true;
    deadline = st.time_left != null ? Date.now() + st.time_left * 1000 : null;
    secEnd = (st.psy && st.psy.sec_left != null) ? Date.now() + st.psy.sec_left * 1000 : null;
    if (secs()) {
      var av = secList();
      if (!av.length || st.psy.sec_left === 0) cur = -1;    // субтест не начат или его время вышло
      else if (av.indexOf(cur) < 0) cur = av[0];
    }
    screenTest();
    startTimers();
  }

  /* субтест закончился: показываем описание следующего, время ещё не идёт */
  function endSection() {
    if (secBusy || cur < 0) return;
    secBusy = true;
    flush().catch(function () {}).then(function () {
      secBusy = false;
      secEnd = null;
      clearInterval(secTick);
      secTick = null;
      cur = -1;
      drawQuestion();
    });
  }

  function nextSection() {
    if (secBusy) return;
    secBusy = true;
    flush().then(function () {
      return api("POST", "/api/s/a/" + S.attempt_id + "/section", { sec: secNow() + 1 });
    }).then(function (st) { secBusy = false; cur = -1; applyState(st); })
      .catch(function (e) { secBusy = false; if (e.code === "finished") loadState(S.attempt_id); else ST.toast(e.message, true); });
  }

  function qAt(i) {
    for (var k = 0; k < S.questions.length; k++) if (S.questions[k].index === i) return S.questions[k];
    return null;
  }
  function isAnswered(qid) { return S.answered.indexOf(qid) >= 0; }
  function markAnswered(q, resp) {
    var ok = answeredLocal(q, resp);
    var i = S.answered.indexOf(q.id);
    if (ok && i < 0) S.answered.push(q.id);
    if (!ok && i >= 0) S.answered.splice(i, 1);
  }
  function answeredLocal(q, r) {
    r = r || {};
    switch (q.type) {
      case "single": return r.choice != null && r.choice !== "";
      case "multi": return !!(r.choices && r.choices.length);
      case "short": return Object.keys(r.fields || {}).some(function (k) { return String(r.fields[k]).trim(); });
      case "match": return Object.keys(r.pairs || {}).some(function (k) { return r.pairs[k]; });
      case "order": case "chrono": return !!(r.order && r.order.length && r.touched);
      case "cloze": return Object.keys(r.blanks || {}).some(function (k) { return String(r.blanks[k]).trim(); });
      case "likert": return Object.keys(r.values || {}).length > 0;
      case "essay": return !!String(r.text || "").trim();
      case "file": return !!r.file_id;
      case "code": return !!r.subs;
      case "psy":
        if (q.multi) return !!(r.choices && r.choices.length);
        if (q.input) return !!String(r.text || "").trim();
        return r.choice != null && r.choice !== "";
    }
    return false;
  }

  /* субтесты с отдельным временем (ШТУР-2) */
  function secs() { return (S.psy && S.psy.sections) || null; }
  function secNow() { return secs() ? (S.psy.sec || 0) : 0; }
  function secInfo() { var a = secs(); return a && secNow() > 0 ? a[secNow() - 1] : null; }
  function secList() {
    return S.questions.slice().sort(function (a, b) { return a.index - b.index; }).map(function (q) { return q.index; });
  }

  var body, saveEl, navEl, timerEl;

  function screenTest() {
    rerender = screenTest;
    var nocopy = S.no_copy;
    document.body.classList.toggle("nocopy", !!nocopy);
    saveEl = h("div", { class: "save", "aria-live": "polite" });
    timerEl = deadline ? h("div", { class: "timer", title: t("Осталось времени") }) : null;
    var langs = topbar().querySelector(".langs");
    var head = h("div", { class: "thead" }, h("div", { class: "thead-in" },
      h("div", null, h("div", { class: "ttl" }, S.title), h("div", { class: "stu" }, S.student)),
      h("div", { class: "sp" }), saveEl, timerEl, langs,
      h("button", { class: "pri", onclick: askFinish }, S.psy ? t("Завершить") : t("Завершить тест"))));
    navEl = h("div", { class: "navq", role: "navigation", "aria-label": t("Вопросы") });
    body = h("div");
    app.innerHTML = "";
    app.appendChild(head);
    app.appendChild(h("div", { class: "wrap" }, navEl, body));
    drawSave();
    drawTimer();
    drawQuestion();
  }

  function secExample(txt) {
    var box = h("div", { class: "secex" });
    String(txt).split("\n").forEach(function (line) {
      var m = /^@(\S+)$/.exec(line.trim());
      if (m) box.appendChild(h("img", { src: "/psy/shtur/" + m[1] + ".png", alt: t("Пример"), loading: "lazy" }));
      else box.appendChild(h("div", null, line));
    });
    return box;
  }

  function drawSectionIntro() {
    var all = secs(), n = secNow(), nxt = all[n] || null;
    body.innerHTML = "";
    if (!nxt) {
      body.appendChild(h("div", { class: "secbox" }, h("h2", null, t("Все субтесты выполнены")),
        h("p", null, t("Нажмите «Завершить», чтобы отправить работу психологу.")),
        h("button", { class: "pri", onclick: nextSection }, t("Завершить"))));
      window.scrollTo(0, 0);
      return;
    }
    var box = h("div", { class: "secbox" },
      h("div", { class: "muted small" }, ST.tf("Субтест {0} из {1}", n + 1, all.length)),
      h("h2", null, nxt.title),
      h("p", null, nxt.instruction),
      h("div", { class: "muted small" }, ST.tf("Заданий: {0}", nxt.count) +
        (nxt.minutes ? " · " + ST.tf("время: {0} мин", nxt.minutes) : "")));
    (nxt.examples || []).forEach(function (e, i) {
      box.appendChild(h("div", { class: "muted small" }, ST.tf("Пример {0}", i + 1)));
      box.appendChild(secExample(e));
    });
    box.appendChild(h("p", { class: "hint" }, nxt.minutes
      ? t("Время пойдёт сразу после нажатия кнопки. Когда оно закончится, субтест закроется, и вернуться к нему будет нельзя.")
      : t("Вернуться к этому субтесту после его завершения будет нельзя.")));
    box.appendChild(h("button", { class: "pri", onclick: nextSection }, t("Начать субтест") + " →"));
    body.appendChild(box);
    window.scrollTo(0, 0);
  }

  function drawSecTimer() {
    var el = navEl && navEl.querySelector(".sectimer");
    if (!el) return;
    if (secEnd == null) { el.textContent = ""; return; }
    var left = Math.max(0, Math.round((secEnd - Date.now()) / 1000));
    el.textContent = t("Осталось") + " " + Math.floor(left / 60) + ":" + ("0" + (left % 60)).slice(-2);
    el.classList.toggle("low", left <= 30);
    if (left <= 0 && !secBusy) endSection();
  }

  function drawNav() {
    navEl.innerHTML = "";
    if (secs()) {
      var all = secs(), n = secNow(), av = secList(), info = secInfo();
      navEl.appendChild(h("div", { style: { flex: 1 } },
        h("div", { class: "secmeta" },
          h("span", { class: "muted small" }, (cur >= 0 && info) ? info.title : t("Описание субтеста")),
          h("span", { class: "sp", style: { flex: 1 } }),
          h("span", { class: "sectimer" })),
        h("div", { class: "progress" }, h("i", { style: { width: (100 * Math.max(0, cur < 0 ? n : n - 1) / all.length) + "%" } }))));
      if (cur >= 0 && av.length) {
        var btns = h("div", { class: "navq", style: { padding: 0, marginTop: "6px" } });
        av.forEach(function (i) {
          var q = qAt(i);
          var cls = (i === cur ? "cur" : "") + (q && isAnswered(q.id) ? " ans" : "");
          btns.appendChild(h("button", { type: "button", class: cls.trim() || null,
                                         onclick: function () { go(i); } }, String(i + 1)));
        });
        navEl.appendChild(btns);
      }
      drawSecTimer();
      return;
    }
    if (S.psy) {        // методика: вместо 57–144 кнопок — полоса прогресса
      navEl.appendChild(h("div", { style: { flex: 1 } },
        h("div", { class: "muted small" }, ST.tf("Отвечено: {0} из {1}", S.answered.length, S.total)),
        h("div", { class: "progress" }, h("i", { style: { width: (100 * S.answered.length / S.total) + "%" } }))));
      return;
    }
    if (!S.free_nav) {
      navEl.appendChild(h("div", { style: { flex: 1 } },
        h("div", { class: "muted small" }, ST.tf("Вопрос {0} из {1}. Вопросы проходятся по порядку, вернуться к предыдущим нельзя.", cur + 1, S.total)),
        h("div", { class: "progress" }, h("i", { style: { width: (100 * cur / S.total) + "%" } }))));
      return;
    }
    for (var i = 0; i < S.total; i++) {
      (function (i) {
        var q = qAt(i);
        var cls = (i === cur ? "cur" : "") + (q && isAnswered(q.id) ? " ans" : "");
        navEl.appendChild(h("button", { type: "button", class: cls.trim() || null, "aria-current": i === cur ? "step" : null,
                                        onclick: function () { go(i); } }, String(i + 1)));
      })(i);
    }
  }

  function drawQuestion() {
    drawNav();
    if (secs() && (secNow() === 0 || cur < 0 || !qAt(cur))) { drawSectionIntro(); return; }
    var q = qAt(cur);
    body.innerHTML = "";
    if (!q) { body.appendChild(h("div", { class: "qcard" }, t("Вопрос не найден"))); return; }
    var resp = pending[q.id] !== undefined ? pending[q.id] : (S.responses[q.id] || null);
    var el = ST.renderQuestion(q, resp, {
      media: function (id) { return "/api/s/media/" + id + "?a=" + S.attempt_id; },
      onChange: function (r) {
        S.responses[q.id] = r;
        markAnswered(q, r);
        if (q.type !== "code") queueSave(q.id, r, q.type === "essay" || q.type === "short" || q.type === "cloze" ? 700 : 0);
        updNavBtn(q);
        updFoot(q);
      },
      hideOption: (S.psy && S.psy.self) ? function (o) { return String(o.id) === String(S.psy.self); } : null,
      onAutoNext: (q.type === "psy" && !q.multi) ? function () { if (qAt(cur) === q) step(1); else updFoot(q); } : null,
      draftKey: S.attempt_id,
      onSubmit: function (qq, lang, code) { return api("POST", "/api/s/a/" + S.attempt_id + "/submit", { qid: qq.id, lang: lang, code: code }); },
      loadSubs: function (qq) { return api("GET", "/api/s/a/" + S.attempt_id + "/subs?qid=" + encodeURIComponent(qq.id)); },
      loadCode: function (sub) {
        return api("GET", "/api/s/a/" + S.attempt_id + "/subs?qid=" + encodeURIComponent(q.id) + "&code=" + sub.id).then(function (r) {
          var x = r.items.filter(function (i) { return i.id === sub.id; })[0];
          return x && x.code != null ? x.code : "";
        });
      },
      onPlay: function (qq) { return api("POST", "/api/s/a/" + S.attempt_id + "/play", { qid: qq.id }); },
      onUpload: function (qq, f) {
        return ST.readFile(f).then(function (d) {
          return api("POST", "/api/s/a/" + S.attempt_id + "/upload", { qid: qq.id, name: d.name, data: d.data }, { timeout: 180000 });
        });
      }
    });
    var foot = h("div", { class: "qfoot" });
    if (S.psy) {
      var answeredAny = S.answered.length > 0;
      var si = secs() ? secInfo() : null;
      body.appendChild(h("details", { class: "psy-intro", open: (!secs() && !answeredAny) || null },
        h("summary", null, (si ? si.title : S.psy.name) + " — " + t("инструкция")),
        h("p", { style: { marginBottom: 0 } }, si ? si.instruction : S.psy.instruction)));
    }
    var numTxt;
    if (secs()) {
      var av0 = secList(), info0 = secInfo();
      numTxt = ST.tf("Задание {0} из {1}", av0.indexOf(cur) + 1, av0.length) + (info0 ? " · " + info0.title : "");
    } else numTxt = ST.tf(S.psy ? "{0} из {1}" : "Вопрос {0} из {1}", cur + 1, S.total);
    var card = h("div", { class: "qcard" + (q.type === "code" ? " code-wide" : "") },
      h("div", { class: "qnum" }, h("b", null, numTxt),
        h("span", null, secs() ? "" : t(ST.TYPE_NAMES[q.type] || ""))),
      el, foot);
    body.appendChild(card);
    updFoot(q);
    window.scrollTo(0, 0);
  }

  function updNavBtn(q) {
    if (S.psy || secs()) { drawNav(); return; }
    if (!S.free_nav) return;
    var b = navEl.children[cur];
    if (b) b.classList.toggle("ans", isAnswered(q.id));
  }

  /* шаг вперёд/назад с учётом субтеста */
  function step(d) {
    if (secs()) {
      var av = secList(), k = av.indexOf(cur);
      if (k < 0) return;
      if (k + d < 0) return;
      if (k + d >= av.length) { if (d > 0) endSection(); return; }
      go(av[k + d]);
      return;
    }
    if (cur + d >= 0 && cur + d < S.total) go(cur + d);
  }

  function updFoot(q) {
    var foot = body.querySelector(".qfoot");
    if (!foot) return;
    foot.innerHTML = "";
    if (secs()) {
      var av = secList(), k = av.indexOf(cur), lastInSec = k >= av.length - 1;
      foot.appendChild(h("button", { type: "button", disabled: k <= 0 || null, onclick: function () { step(-1); } }, "← " + t("Назад")));
      foot.appendChild(h("div", { class: "sp" }));
      foot.appendChild(h("button", { type: "button", class: "pri", onclick: function () { step(1); } },
        lastInSec ? t("Закончить субтест") + " →" : (isAnswered(q.id) ? t("Далее") + " →" : t("Пропустить") + " →")));
      return;
    }
    var last = cur >= S.total - 1;
    if (S.free_nav) {
      foot.appendChild(h("button", { type: "button", disabled: cur === 0 || null, onclick: function () { go(cur - 1); } }, "← " + t("Назад")));
      foot.appendChild(h("div", { class: "sp" }));
      if (!last) foot.appendChild(h("button", { type: "button", class: "pri", onclick: function () { go(cur + 1); } },
        isAnswered(q.id) ? t("Далее") + " →" : t("Пропустить") + " →"));
      else foot.appendChild(h("button", { type: "button", class: "pri", onclick: askFinish }, t("Завершить тест")));
    } else {
      foot.appendChild(h("div", { class: "sp" }));
      var ok = isAnswered(q.id);
      if (!last) foot.appendChild(h("button", { type: "button", class: "pri", disabled: !ok || null, onclick: function () { strictNext(); } },
        t("Ответить и перейти дальше") + " →"));
      else foot.appendChild(h("button", { type: "button", class: "pri", disabled: !ok || null, onclick: askFinish }, t("Завершить тест")));
      if (!ok) foot.appendChild(h("div", { class: "hint", style: { width: "100%", textAlign: "right" } }, t("Ответьте на вопрос, чтобы перейти к следующему")));
    }
  }

  function go(i) {
    if (i < 0 || i >= S.total) return;
    cur = i;
    drawQuestion();
    api("POST", "/api/s/a/" + S.attempt_id + "/nav", { cur: i }).catch(function () {});   // место для продолжения после сбоя
  }

  function strictNext() {
    flush().then(function () {
      return api("POST", "/api/s/a/" + S.attempt_id + "/nav", { cur: cur + 1 });
    }).then(function (st) {
      S.questions = st.questions; S.responses = st.responses; S.answered = st.answered; cur = st.cur;
      drawQuestion();
    }).catch(handleErr);
  }

  /* ---------------- сохранение ответов ---------------- */
  function queueSave(qid, resp, delay) {
    pending[qid] = resp;
    drawSave();
    clearTimeout(saveTimer);
    saveTimer = setTimeout(flush, delay || 0);
  }
  function flush() {
    clearTimeout(saveTimer);
    var ids = Object.keys(pending);
    if (!ids.length) return Promise.resolve();
    if (saving) return new Promise(function (res) { setTimeout(function () { flush().then(res, res); }, 300); });
    saving = true;
    var qid = ids[0], resp = pending[qid];
    return api("PUT", "/api/s/a/" + S.attempt_id + "/answer", { qid: qid, response: resp }, { timeout: 15000 }).then(function () {
      if (pending[qid] === resp) delete pending[qid];
      saving = false;
      saveFailed = false;
      drawSave();
      return flush();
    }, function (e) {
      saving = false;
      if (e.network || e.status >= 500) {
        saveFailed = true;
        drawSave();
        clearTimeout(retryTimer);
        retryTimer = setTimeout(flush, 3000);
        return Promise.reject(e);
      }
      delete pending[qid];
      drawSave();
      handleErr(e);
      return Promise.reject(e);
    });
  }
  function drawSave() {
    if (!saveEl) return;
    var n = Object.keys(pending).length;
    saveEl.className = "save" + (saveFailed ? " bad" : "");
    saveEl.textContent = saveFailed ? t("Нет связи — ответы сохранятся, когда связь появится") :
      (n ? t("Сохранение…") : t("Ответы сохранены"));
  }
  window.addEventListener("beforeunload", function (e) {
    if (S && S.status === "active" && Object.keys(pending).length) { flush(); e.preventDefault(); e.returnValue = ""; }
  });

  function handleErr(e) {
    if (e.code === "finished" || e.status === 409 && /заверш|время|скончы|час/i.test(e.message)) {
      return loadState(S.attempt_id);
    }
    if (e.code === "other_device") { store(null); clearTimers(); return screenCode(e.message); }
    ST.toast(e.message, true);
  }

  /* ---------------- таймер, связь, уход со страницы ---------------- */
  function drawTimer() {
    if (!timerEl || !deadline) return;
    var left = (deadline - Date.now()) / 1000;
    timerEl.textContent = ST.fmtTime(left);
    timerEl.classList.toggle("low", left <= 60);
    if (left <= 0) {
      clearInterval(tick);
      tick = null;
      flush().catch(function () {}).then(function () { setTimeout(function () { loadState(S.attempt_id); }, 1500); });
    }
  }
  function startTimers() {
    clearTimers();
    if (deadline) tick = setInterval(drawTimer, 500);
    if (secEnd != null) secTick = setInterval(drawSecTimer, 500);
    pingTimer = setInterval(function () {
      api("POST", "/api/s/a/" + S.attempt_id + "/ping", {}).then(function (r) {
        if (r.status !== "active") return loadState(S.attempt_id);
        if (r.time_left != null) {
          var d2 = Date.now() + r.time_left * 1000;
          if (!deadline || Math.abs(d2 - deadline) > 3000) {      // учитель продлил время
            var had = !!deadline;
            deadline = d2;
            if (!had) { screenTest(); }
            if (!tick) tick = setInterval(drawTimer, 500);
          }
        }
        if (saveFailed) flush().catch(function () {});
      }).catch(function (e) { if (e.code === "other_device") handleErr(e); });
    }, 20000);
  }

  var blurTimer = null;
  function focusEvent(ev) {
    if (!S || S.status !== "active" || !S.track_focus) return;
    api("POST", "/api/s/a/" + S.attempt_id + "/focus", { e: ev }).catch(function () {});
  }
  document.addEventListener("visibilitychange", function () { focusEvent(document.hidden ? "hidden" : "visible"); });
  window.addEventListener("blur", function () {
    clearTimeout(blurTimer);
    blurTimer = setTimeout(function () { if (!document.hidden) focusEvent("blur"); }, 250);
  });
  window.addEventListener("focus", function () { clearTimeout(blurTimer); });
  ["copy", "cut", "contextmenu", "selectstart", "dragstart"].forEach(function (ev) {
    document.addEventListener(ev, function (e) {
      if (!S || S.status !== "active" || !S.no_copy) return;
      if (e.target.closest && e.target.closest("input,textarea") && ev !== "contextmenu" && ev !== "copy" && ev !== "cut") return;
      if (ev === "dragstart" && e.target.closest && e.target.closest("[data-id]")) return;
      e.preventDefault();
    });
  });

  /* ---------------- завершение ---------------- */
  function askFinish() {
    if (secs()) {
      ST.confirm(t("Завершение методики"), t("Оставшиеся субтесты выполнены не будут, вернуться к ним нельзя. Завершить?"), t("Завершить"))
        .then(function (ok) {
          if (!ok) return;
          flush().catch(function () {}).then(function () {
            return api("POST", "/api/s/a/" + S.attempt_id + "/finish", {}).then(applyState);
          }).catch(handleErr);
        });
      return;
    }
    var missing = [];
    for (var i = 0; i < S.total; i++) {
      var q = qAt(i);
      if (S.free_nav ? (q && !isAnswered(q.id)) : false) missing.push(i + 1);
    }
    var txt = missing.length ? ST.tf("Нет ответа на вопросы: {0}. Завершить тест?", missing.join(", ")) :
      t("После завершения изменить ответы будет нельзя. Завершить тест?");
    if (S.psy && missing.length) txt = ST.tf("Нет ответа на вопросы: {0}. Ответьте, пожалуйста, на все вопросы — иначе результат будет неточным. Завершить?", missing.join(", "));
    else if (S.psy) txt = t("Все ответы даны. Завершить?");
    ST.confirm(t("Завершение теста"), txt, t("Завершить")).then(function (ok) {
      if (!ok) return;
      flush().catch(function () {}).then(function () {
        if (Object.keys(pending).length) { ST.toast(t("Ответы ещё не сохранены — проверьте связь и попробуйте снова"), true); return; }
        return api("POST", "/api/s/a/" + S.attempt_id + "/finish", {}).then(applyState);
      }).catch(handleErr);
    });
  }

  function screenResult() {
    clearTimers();
    document.body.classList.remove("nocopy");
    rerender = screenResult;
    var r = S.result || {};
    var box = h("div", { class: "result" }, h("h1", null, S.psy ? t("Готово, спасибо!") : t("Тест завершён")), h("div", { class: "muted" }, S.title + " · " + S.student));
    if (S.psy) {
      if (r.psy) box.appendChild(h("div", { style: { textAlign: "left", marginTop: "14px" } }, ST.psyResult(r.psy)));
      else box.appendChild(h("p", null, t("Ответы сохранены. Результаты обсудит с вами педагог-психолог.")));
    } else if (r.show === "none") {
      box.appendChild(h("p", null, t("Ответы сохранены. Результат сообщит учитель.")));
    } else if (r.pending) {
      box.appendChild(h("p", null, t("Часть ответов проверит учитель. Итоговый результат появится после проверки.")));
    } else if (r.mark != null) {
      var isNum = /^\d+$/.test(String(r.mark));
      var label = r.result_kind === "passfail" || r.result_kind === "credit" ? t(String(r.mark)) : String(r.mark);
      box.appendChild(h("div", { class: "bigmark" + (isNum ? "" : " text") }, label));
      if (r.percent != null) box.appendChild(h("div", { class: "muted" },
        ST.tf("Выполнено: {0} % · баллов: {1} из {2}", fmtNum(r.percent), fmtNum(r.score), fmtNum(r.max_score))));
    }
    box.appendChild(h("p", null, h("button", { onclick: function () { store(null); S = null; screenCode(); } }, t("Выйти"))));
    app.innerHTML = "";
    app.appendChild(topbar());
    var w = h("div", { class: "wrap" }, box);
    if (r.review) {
      var rv = h("div", { class: "review" }, h("h2", null, t("Разбор ответов")));
      r.review.forEach(function (q, i) {
        var frac = q.frac;
        var status = frac == null ? (q.got != null ? ST.tf("Баллы: {0}", fmtNum(q.got)) : "") :
          frac >= 1 ? "✓ " + t("Верно") : frac > 0 ? "◐ " + t("Частично верно") : "✗ " + t("Неверно");
        var cls = frac == null ? "pill" : frac >= 1 ? "pill ok" : frac > 0 ? "pill warn" : "pill bad";
        rv.appendChild(h("div", { class: "qcard" },
          h("div", { class: "rvhead" }, h("b", null, ST.tf("Вопрос {0}", i + 1)), status ? h("span", { class: cls }, status) : null),
          ST.renderQuestion(q, q.response, { readonly: true, media: function (id) { return "/api/s/media/" + id + "?a=" + S.attempt_id; },
                                             review: { correct: q.correct, frac: q.frac, got: q.got, comment: q.comment } })));
      });
      w.appendChild(rv);
    }
    app.appendChild(w);
  }
  function fmtNum(v) { return v == null ? "" : String(Math.round(v * 100) / 100).replace(".", ","); }

  /* ---------------- запуск ---------------- */
  api("GET", "/api/public").then(function (p) {
    PUB = p || {};
    var saved = ST.savedLang();
    ST.setLang(PUB.student_lang_switch !== false && saved ? saved : (PUB.lang || "ru"));
    document.title = "SchoolTest" + (PUB.school_name ? " — " + PUB.school_name : "");
    var s = stored();
    var m = /[?&]code=(\d{6})/.exec(location.search);
    if (s && s.aid) loadState(s.aid);
    else screenCode("", m ? m[1] : "");
  }).catch(function (e) {
    app.innerHTML = "";
    app.appendChild(h("div", { class: "wait" }, h("h1", null, t("Нет связи с сервером")), h("p", null, e.message),
      h("button", { class: "pri", onclick: function () { location.reload(); } }, t("Повторить"))));
  });
})();
