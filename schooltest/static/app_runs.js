/* SchoolTest — проведение теста, наблюдение, проверка, результаты, бумажный тест */
"use strict";
(function () {
  var h = ST.h, t = ST.t, api = ST.api;
  var STATUS = { absent: "не начинал(а)", active: "проходит", finished: "завершил(а)", allowed: "разрешено повторно" };

  A.runsTable = function (runs, noTest) {
    return A.table([t("Дата"), noTest ? null : t("Тест"), A.N("class"), t("Способ"), t("Выполнили"), t("На проверке"), t("Статус"), ""].filter(function (x) { return x !== null; }),
      runs.map(function (r) {
        var cells = [A.date(r.created_at, true)];
        if (!noTest) cells.push(h("a", { href: "#/run/" + r.id }, r.title));
        cells.push(r.class_name, r.mode === "paper" ? t("на бумаге") : t("на компьютерах"), String(r.finished || 0),
          r.pending ? h("span", { class: "pill warn" }, String(r.pending)) : "",
          r.status === "open" ? h("span", { class: "pill ok" }, t("идёт") + (r.code ? " · " + r.code : "")) : h("span", { class: "pill" }, t("завершён")),
          h("a", { class: "btn sm", href: "#/run/" + r.id + (r.mode === "paper" ? "/paper" : "") }, t("Открыть")));
        return h("tr", null, cells.map(function (c) { return h("td", null, c); }));
      }), { empty: t("Тест ещё не проводился") });
  };

  A.route("runs", function (box, args, q) {
    A.head(box, t("Проведение и результаты"), t("Все запуски тестов. Откройте запуск, чтобы наблюдать, проверять и смотреть отчёты."));
    var st = A.select([["", t("Все")], ["open", t("Идут сейчас")], ["closed", t("Завершённые")]], q.status || "");
    var mine = A.isAdmin() ? A.check(t("Только мои"), q.mine === "1") : null;
    var list = h("div");
    box.appendChild(h("div", { class: "bar" }, st, mine));
    box.appendChild(list);
    function load() {
      var url = A.yearQ("/api/runs?" + (st.value ? "status=" + st.value + "&" : "") + (mine && mine.querySelector("input").checked ? "mine=1" : ""));
      api("GET", url).then(function (runs) { list.innerHTML = ""; list.appendChild(A.runsTable(runs)); }).catch(A.err);
    }
    st.addEventListener("change", load);
    if (mine) mine.addEventListener("change", load);
    load();
  });

  /* ---------------- запуск ---------------- */
  A.route("run", function (box, args) {
    var id = +args[0], tab = args[1] || "monitor";
    return api("GET", "/api/runs/" + id).then(function (R) {
      if (R.mode === "paper" && tab === "monitor") tab = "paper";
      var acts = [];
      if (R.mode === "online") {
        if (R.status === "open") acts.push(h("button", { onclick: function () { extend(R, null); } }, "⏱ " + t("Добавить время всем")),
          h("button", { class: "danger", onclick: function () { closeRun(R); } }, "■ " + t("Завершить тест")));
        else acts.push(h("button", { onclick: function () {
          api("POST", "/api/runs/" + R.id + "/reopen", {}).then(function () { ST.toast(t("Тест снова открыт")); A.render(); }).catch(A.err);
        } }, t("Открыть снова")));
      }
      acts.push(h("button", { class: "danger ghost", onclick: function () {
        ST.confirm(t("Удалить запуск?"), t("Будут удалены все попытки и ответы учеников этого запуска."), t("Удалить"), true).then(function (ok) {
          if (ok) api("DELETE", "/api/runs/" + R.id).then(function () { A.go("#/runs"); }).catch(A.err);
        });
      } }, t("Удалить")));
      A.head(box, R.title, R.class_name + " · " + A.date(R.created_at, true) + (A.isAdmin() && R.teacher ? " · " + R.teacher : ""), acts);
      var tabs = [];
      if (R.mode === "online") tabs.push(["monitor", "#/run/" + id, t("Наблюдение")]);
      else tabs.push(["paper", "#/run/" + id + "/paper", t("Бумажный тест")]);
      if (R.mode === "online") tabs.push(["check", "#/run/" + id + "/check", t("Проверка") + (R.pending ? " (" + R.pending + ")" : "")]);
      tabs.push(["results", "#/run/" + id + "/results", t("Результаты")]);
      if (R.mode === "online") tabs.push(["analysis", "#/run/" + id + "/analysis", t("Анализ вопросов")]);
      if (A.isSchool()) tabs.push(["sg", "#/run/" + id + "/sg", t("В журнал SchoolGrade")]);
      box.appendChild(A.tabs(tabs, tab));
      var pane = h("div");
      box.appendChild(pane);
      if (tab === "monitor") monitor(pane, R);
      else if (tab === "check") return check(pane, R);
      else if (tab === "results") return report(pane, "/api/runs/" + id + "/results");
      else if (tab === "analysis") return report(pane, "/api/runs/" + id + "/analysis");
      else if (tab === "sg") return sgTab(pane, R);
      else if (tab === "paper") return paper(pane, R);
    });
  });

  function report(pane, url) {
    return api("GET", url).then(function (rep) { pane.appendChild(A.reportView(rep, url + "?format=xlsx")); });
  }

  function extend(R, sid, name) {
    var m = h("input", { type: "number", min: 1, max: 240, style: { width: "100px" } });
    m.value = 5;
    ST.modal(sid ? ST.tf("Добавить время: {0}", name) : t("Добавить время всем, кто проходит тест"), A.field(t("Минут"), m),
      [{ text: t("Отмена"), value: null }, { text: t("Добавить"), value: 1, cls: "pri" }]).then(function (v) {
      if (!v) return;
      api("POST", "/api/runs/" + R.id + "/extend", { student_id: sid, minutes: +m.value || 5 }).then(function () { ST.toast(t("Время добавлено")); }).catch(A.err);
    });
  }
  function closeRun(R) {
    ST.confirm(t("Завершить тест?"), t("Все, кто ещё проходит тест, будут завершены с текущими ответами. Код перестанет действовать."), t("Завершить"), true)
      .then(function (ok) { if (ok) api("POST", "/api/runs/" + R.id + "/close", {}).then(A.render).catch(A.err); });
  }

  /* ---------------- наблюдение ---------------- */
  A.runMonitor = function (pane, R) { return monitor(pane, R); };
  A.extendRun = function (R) { return extend(R, null); };
  A.closeRun = function (R) { return closeRun(R); };
  function monitor(pane, R0) {
    var head = h("div");
    var tbl = h("div");
    pane.appendChild(head);
    pane.appendChild(tbl);
    var timer = null;
    var local = /^(127\.|localhost)/.test(location.hostname);
    function addr() {
      if (!local) return [location.protocol + "//" + location.host];
      return A.me.urls && A.me.urls.length ? A.me.urls : [t("адрес показан в окне программы SchoolTest")];
    }
    function draw(R) {
      head.innerHTML = "";
      var st = R.students;
      var cnt = { absent: 0, active: 0, finished: 0 };
      st.forEach(function (s) { cnt[s.status] = (cnt[s.status] || 0) + 1; });
      if (R.status === "open") {
        head.appendChild(h("div", { class: "monhead" },
          h("div", null, h("div", { class: "muted small" }, t("Код теста")), h("div", { class: "code-big" }, R.code)),
          h("div", { class: "addr" }, h("div", { class: "muted small" }, t("Ученикам открыть в браузере")),
            addr().map(function (u) { return h("div", null, h("b", { style: { fontSize: "18px" } }, u)); }),
            h("div", { class: "muted small" }, t("и ввести код"))),
          h("div", { class: "mtiles" },
            h("div", { class: "tile" }, h("b", null, String(cnt.active)), h("span", null, t("проходят"))),
            h("div", { class: "tile" }, h("b", null, String(cnt.finished)), h("span", null, t("завершили"))),
            h("div", { class: "tile" }, h("b", null, String(cnt.absent)), h("span", null, t("не начинали"))))));
      } else {
        head.appendChild(h("div", { class: "infobox" }, t("Тест завершён. Ученики больше не могут войти. Отчёты — на вкладках выше.")));
      }
      var rows = st.map(function (s, i) {
        var prog = s.total ? h("div", { title: s.answered + " / " + s.total }, h("div", { class: "small" }, s.answered + " / " + s.total),
          h("div", { class: "bar-mini" }, h("i", { style: { width: (100 * s.answered / s.total) + "%" } }))) : "";
        var status = h("span", null, s.status === "active" ? h("span", { class: "st-dot" + (s.online ? " on" : ""), title: s.online ? t("на связи") : t("нет связи") }) : null,
          t(STATUS[s.status] || s.status), s.num > 1 ? " (" + ST.tf("попытка {0}", s.num) + ")" : "");
        var acts = h("td", { class: "acts" });
        if (s.waiting) acts.appendChild(h("button", { class: "sm pri", onclick: function () {
          api("POST", "/api/runs/" + R.id + "/allow", { student_id: s.student_id }).then(function () { ST.toast(t("Разрешено")); load(); }).catch(A.err);
        } }, t("Разрешить продолжить")));
        if (s.status === "active" && R.settings.time_limit) acts.appendChild(h("button", { class: "sm", onclick: function () { extend(R, s.student_id, s.name); } }, "⏱"));
        if (s.status === "active") acts.appendChild(h("button", { class: "sm", title: t("Завершить попытку"), onclick: function () {
          ST.confirm(t("Завершить попытку?"), s.name, t("Завершить"), true).then(function (ok) {
            if (ok) api("POST", "/api/runs/" + R.id + "/stop", { student_id: s.student_id }).then(load).catch(A.err);
          });
        } }, "■"));
        if (s.status === "finished" && R.status === "open") acts.appendChild(h("button", { class: "sm", title: t("Разрешить пройти ещё раз"), onclick: function () {
          ST.confirm(t("Разрешить пройти тест ещё раз?"), s.name + ". " + t("Засчитывается последняя попытка."), t("Разрешить")).then(function (ok) {
            if (ok) api("POST", "/api/runs/" + R.id + "/retake", { student_id: s.student_id }).then(load).catch(A.err);
          });
        } }, "↻"));
        if (s.attempt_id) acts.appendChild(R.kind === "psy" ? (s.status === "finished" ? h("a", { class: "btn sm", href: "#/psyres/" + s.attempt_id }, t("Результат")) : null) :
          h("a", { class: "btn sm", href: "#/attempt/" + s.attempt_id }, t("Ответы")));
        var mark = s.status === "finished" ? (s.pending ? h("span", { class: "pill warn" }, t("на проверке")) : h("span", { class: "mark" }, s.mark || "")) : "";
        var tr = h("tr", { class: s.waiting ? "wait" : null },
          h("td", { class: "num" }, String(i + 1)), h("td", null, h("a", { href: (R.kind === "psy" ? "#/psystudent/" : "#/student/") + s.student_id }, s.name),
            s.waiting ? h("div", { class: "small warn" }, t("Просит продолжить на другом устройстве")) : null),
          h("td", null, status), h("td", null, prog),
          h("td", { class: "num" }, s.time_left != null ? ST.fmtTime(s.time_left) : ""),
          h("td", { class: "num" }, s.focus_lost ? h("span", { class: "pill " + (s.focus_lost > 2 ? "bad" : "warn") }, String(s.focus_lost)) : ""),
          h("td", { class: "num" }, s.percent != null && s.status === "finished" ? A.num(s.percent) + " %" : ""),
          h("td", { class: "num" }, mark), acts);
        return tr;
      });
      tbl.innerHTML = "";
      tbl.appendChild(A.table(["№", A.N("student"), t("Состояние"), t("Ответы"), t("Осталось"), t("Уходы со страницы"), "%", t("Итог"), ""], rows,
        { empty: t("В списке нет учеников") }));
    }
    function load() {
      return api("GET", "/api/runs/" + R0.id).then(draw).catch(function (e) { if (e.status !== 0) A.err(e); });
    }
    draw(R0);
    timer = setInterval(function () { if (!document.hidden) load(); }, 4000);
    A.onLeave(function () { clearInterval(timer); });
  }

  /* ---------------- проверка развёрнутых ответов ---------------- */
  function check(pane, R) {
    return api("GET", "/api/runs/" + R.id + "/check").then(function (items) {
      if (!items.length) { pane.appendChild(h("div", { class: "card empty" }, t("Нет ответов, которые нужно проверять вручную."))); return; }
      var onlyNew = A.check(t("Только непроверенные"), true, draw);
      var list = h("div");
      pane.appendChild(h("div", { class: "bar" }, onlyNew, h("div", { class: "sp" }),
        h("span", { class: "muted" }, ST.tf("Всего ответов: {0}", items.length))));
      pane.appendChild(list);
      function draw() {
        list.innerHTML = "";
        var only = onlyNew.querySelector("input").checked;
        var groups = {};
        var order = [];
        items.forEach(function (it) {
          if (only && it.manual != null) return;
          if (!groups[it.qid]) { groups[it.qid] = []; order.push(it.qid); }
          groups[it.qid].push(it);
        });
        if (!order.length) { list.appendChild(h("div", { class: "card empty" }, t("Все ответы проверены."))); return; }
        order.forEach(function (qid) {
          var g = groups[qid], q = g[0].question;
          var card = h("div", { class: "card" }, h("div", { class: "muted small" }, t(ST.TYPE_NAMES[q.type])),
            h("div", { class: "qtext", html: ST.fmt(q.body.text) }),
            q.answer && q.answer.sample ? h("details", null, h("summary", null, t("Образец ответа / критерии")), h("div", { class: "answer-box" }, q.answer.sample)) : null);
          g.forEach(function (it) { card.appendChild(gradeItem(it, function () { it.manual = it._new; })); });
          list.appendChild(card);
        });
        ST.math(list);
      }
      draw();
    });
  }
  function codeSubs(it) {
    var box = h("div", { class: "answer-box" }, t("Загрузка посылок…"));
    api("GET", "/api/attempts/" + it.attempt_id + "/subs?qid=" + encodeURIComponent(it.qid)).then(function (items) {
      box.innerHTML = "";
      var best = items.filter(function (x) { return x.status === "done"; }).sort(function (a, b) { return (b.frac || 0) - (a.frac || 0) || b.id - a.id; })[0];
      if (best) box.appendChild(h("div", { class: "muted small" }, ST.tf("Лучшая посылка #{0}: {1}, автопроверка — {2} %", best.id,
        t(ST.VERDICT[best.verdict] || best.verdict), Math.round((best.frac || 0) * 100))));
      if (best) box.appendChild(h("pre", { class: "io src" }, best.code));
      box.appendChild(h("details", null, h("summary", { class: "small" }, ST.tf("Все посылки: {0}", items.length)), ST.subsTable(items, { full: true })));
    }).catch(function (e) { box.textContent = e.message; });
    return box;
  }
  function gradeItem(it, onSaved) {
    var pts = h("input", { type: "number", min: 0, max: it.maxp, step: "0.5", class: "pts" });
    pts.value = it.manual != null ? it.manual : "";
    var com = h("input", { type: "text", placeholder: t("Комментарий для ученика (необязательно)"), style: { flex: 1, minWidth: "200px" } });
    com.value = it.comment || "";
    var saved = h("span", { class: "ok small" });
    var ans = it.response || {};
    var content = it.question.type === "code" ? codeSubs(it) : it.question.type === "essay" ? h("div", { class: "answer-box" }, ans.text || "—") :
      h("div", { class: "answer-box" }, (it.files && it.files.length) ? it.files.map(function (f) {
        return h("button", { class: "sm", onclick: function () { ST.download("/api/uploads/" + f.id); } }, "⬇ " + f.name + " (" + Math.ceil(f.size / 1024) + " КБ)");
      }) : t("Файл не загружен"));
    function save() {
      api("PUT", "/api/attempts/" + it.attempt_id + "/grade", { qid: it.qid, points: pts.value, comment: com.value }).then(function (r) {
        it._new = pts.value === "" ? null : +pts.value;
        if (onSaved) onSaved();
        saved.textContent = "✓ " + t("сохранено") + (r.mark && !r.pending ? " · " + ST.tf("итог: {0}", r.mark) : "");
      }).catch(A.err);
    }
    return h("div", { class: "chk-item" }, h("b", null, it.student), it.noContent ? null : content,
      h("div", { class: "gr" }, h("span", null, t("Баллы:")), pts, h("span", { class: "muted" }, ST.tf("из {0}", A.num(it.maxp))),
        it.maxp >= 1 ? h("button", { class: "sm", onclick: function () { pts.value = it.maxp; save(); } }, t("Максимум")) : null,
        h("button", { class: "sm", onclick: function () { pts.value = 0; save(); } }, "0"),
        com, h("button", { class: "sm pri", onclick: save }, t("Сохранить")), saved));
  }

  /* ---------------- ответы одного ученика ---------------- */
  A.route("attempt", function (box, args) {
    return api("GET", "/api/attempts/" + args[0]).then(function (D) {
      A.head(box, D.student_name, D.run.title + " · " + D.run.class_name, [
        h("a", { class: "btn", href: "#/run/" + D.run.id }, "← " + t("К запуску"))]);
      var mark = D.manual_mark || D.mark;
      var markInp = h("input", { type: "text", style: { width: "110px" }, placeholder: mark || "" });
      markInp.value = D.manual_mark || "";
      box.appendChild(h("div", { class: "tiles" },
        h("div", { class: "tile" }, h("b", null, D.status === "finished" ? (D.pending_manual && !D.manual_mark ? "…" : (mark || "—")) : t(STATUS[D.status] || D.status)), h("span", null, t("Итог"))),
        h("div", { class: "tile" }, h("b", null, A.num(D.score) + " / " + A.num(D.max_score)), h("span", null, t("Баллы"))),
        h("div", { class: "tile" }, h("b", null, D.percent != null ? A.num(D.percent) + " %" : "—"), h("span", null, t("Выполнено"))),
        h("div", { class: "tile" }, h("b", null, String(D.focus_lost || 0)), h("span", null, t("Уходов со страницы"))),
        h("div", { class: "tile" }, h("b", null, D.started_at && D.finished_at ? ST.fmtTime(D.finished_at - D.started_at) : "—"), h("span", null, t("Время")))));
      box.appendChild(h("div", { class: "bar" }, h("span", null, t("Исправить итоговую отметку вручную:")), markInp,
        h("button", { class: "sm", onclick: function () {
          api("PUT", "/api/attempts/" + D.id + "/mark", { mark: markInp.value }).then(function () { ST.toast(t("Сохранено")); A.render(); }).catch(A.err);
        } }, t("Сохранить")), h("span", { class: "muted small" }, t("Пусто — отметка по шкале теста."))));
      D.items.forEach(function (it, i) {
        var q = A.toPublic(it.question);
        if (it.order && it.order.options) q.options = sortBy(q.options, it.order.options);
        if (it.order && it.order.items) q.items = sortBy(q.items, it.order.items);
        if (it.order && it.order.right) q.right = sortBy(q.right, it.order.right);
        var got = it.manual != null ? it.manual : it.auto;
        var pill = it.question.type === "likert" ? null : h("span", { class: "pill " + (got == null ? "warn" : got >= it.maxp ? "ok" : got > 0 ? "warn" : "bad") },
          got == null ? t("не проверено") : ST.tf("{0} из {1} б.", A.num(got), A.num(it.maxp)));
        var card = h("div", { class: "card" }, h("div", { class: "bar" }, h("b", null, ST.tf("Вопрос {0}", i + 1)),
          h("span", { class: "muted small" }, t(ST.TYPE_NAMES[it.question.type])), h("div", { class: "sp" }), pill),
          ST.renderQuestion(q, it.response, { readonly: true, review: { correct: A.correctOf(it.question), comment: it.comment },
            fullSubs: true, loadSubs: function (qq) { return api("GET", "/api/attempts/" + D.id + "/subs?qid=" + encodeURIComponent(qq.id)); } }));
        if (it.question.type === "code") card.appendChild(h("div", { class: "bar" }, h("button", { class: "sm", onclick: function () {
          api("POST", "/api/runs/" + D.run.id + "/rejudge", { attempt_id: D.id, qid: String(it.question.id) }).then(function (r) {
            ST.toast(ST.tf("Отправлено на перепроверку: {0}", r.queued)); setTimeout(A.render, 1500);
          }).catch(A.err);
        } }, "⟳ " + t("Перепроверить посылки"))));
        if (it.question.type !== "likert" && D.status === "finished") {
          var row = { attempt_id: D.id, qid: String(it.question.id), maxp: it.maxp, manual: it.manual, comment: it.comment,
                      response: it.response, files: it.files, question: it.question, student: it.manual_type ? t("Оценка учителя") : t("Исправить баллы (автопроверка)"), noContent: it.question.type === "essay" || !it.manual_type };
          if (it.manual_type) card.appendChild(gradeItem(row));
          else card.appendChild(h("details", null, h("summary", { class: "muted small" }, t("Исправить баллы вручную")), gradeItem(row)));
        }
        box.appendChild(card);
      });
      if (D.focus_log && D.focus_log.length) {
        var EV = { blur: "переключился на другое окно", hidden: "свернул или скрыл страницу", visible: "вернулся на страницу",
                   "finish:student": "завершил тест", "finish:timeout": "время вышло", "finish:teacher": "завершено учителем", "finish:closed": "тест закрыт" };
        box.appendChild(h("details", { class: "card" }, h("summary", null, t("Журнал ухода со страницы")),
          h("ul", null, D.focus_log.map(function (e) { return h("li", null, A.date(e.t, true).split(" ")[1] + new Date(e.t * 1000).toTimeString().slice(5, 8) + " — " + t(EV[e.e] || e.e)); }))));
      }
      ST.math(box);
    });
  });
  function sortBy(items, order) {
    var pos = {};
    order.forEach(function (id, i) { pos[id] = i; });
    return (items || []).slice().sort(function (a, b) { return (pos[a.id] != null ? pos[a.id] : 99) - (pos[b.id] != null ? pos[b.id] : 99); });
  }

  /* ---------------- SchoolGrade ---------------- */
  function sgTab(pane, R) {
    return api("GET", "/api/runs/" + R.id + "/sg").then(function (D) {
      pane.appendChild(h("p", null, ST.tf("Отметок к отправке: {0}", D.marks.length) + (D.sent ? " · " + ST.tf("отправлено {0}", A.date(D.sent, true)) : "")));
      if (D.skipped.length) pane.appendChild(h("div", { class: "warnbox" }, h("b", null, t("Не будут отправлены:")),
        h("ul", null, D.skipped.map(function (s) { return h("li", null, s.name + " — " + t(s.reason)); }))));
      if (D.network) {
        var card = h("div", { class: "card" }, h("h2", { style: { marginTop: 0 } }, t("Отправить в журнал по сети")));
        if (D.network_error) card.appendChild(h("div", { class: "warnbox" }, t(D.network_error)));
        else if (!D.assignments.length) card.appendChild(h("div", { class: "warnbox" }, t("В SchoolGrade у этого класса нет предметов.")));
        else {
          var asg = A.select(D.assignments.map(function (x) { return [x.id, x.subject + (x.group ? " (" + x.group + ")" : "") + (x.teacher ? " — " + x.teacher : "")]; }));
          var date = h("input", { type: "date" }); date.value = D.date;
          var title = h("input", { type: "text" }); title.value = D.title;
          var over = A.check(t("Заменить отметки, если в этот день по этой работе они уже стоят"), false);
          card.appendChild(h("div", { class: "form" }, A.field(t("Предмет"), asg, "wide"), A.field(t("Дата урока"), date), A.field(t("Название работы"), title)));
          card.appendChild(over);
          card.appendChild(h("button", { class: "pri", disabled: !D.marks.length || null, onclick: function () {
            api("POST", "/api/runs/" + R.id + "/sg_send", { assignment_id: +asg.value, date: date.value, title: title.value,
              overwrite: over.querySelector("input").checked }).then(function (r) {
              var msg = ST.tf("В журнал записано отметок: {0}", r.saved);
              if (r.problems && r.problems.length) ST.modal(t("Отправлено с замечаниями"), h("div", null, h("p", null, msg),
                h("ul", null, r.problems.map(function (p) { return h("li", null, (p.name || "") + " — " + t(p.reason || p)); }))));
              else ST.toast(msg);
            }).catch(A.err);
          } }, t("Отправить отметки")));
        }
        pane.appendChild(card);
      }
      pane.appendChild(h("div", { class: "card" }, h("h2", { style: { marginTop: 0 } }, t("Файлом")),
        h("p", { class: "muted" }, t("Скачайте файл отметок и загрузите его в SchoolGrade: «Журнал» → «Загрузить отметки SchoolTest». Подходит, если программы не связаны по сети.")),
        h("button", { onclick: function () { ST.download("/api/runs/" + R.id + "/sg_file"); } }, "⬇ " + t("Скачать файл отметок"))));
      if (!D.network) pane.appendChild(h("p", { class: "muted small" }, t("Связь по сети настраивает администратор: «Настройки» → SchoolGrade.")));
    });
  }

  /* ---------------- бумажный тест ---------------- */
  function paper(pane, R) {
    var copies = h("input", { type: "number", min: 1, max: 60, style: { width: "90px" } });
    copies.value = Math.max(R.settings.variants || 1, 2);
    var cardPrint = h("div", { class: "card" }, h("h2", { style: { marginTop: 0 } }, t("1. Печать вариантов и ключа")),
      h("p", { class: "muted" }, t("Варианты формируются с учётом перемешивания вопросов и ответов из настроек теста. Каждый экземпляр получает свой номер в ключе.")),
      h("div", { class: "bar" }, A.field(t("Экземпляров"), copies),
        h("button", { class: "pri", onclick: function () { printPaper(R, +copies.value || 1, false); } }, "🖶 " + t("Варианты для учеников")),
        h("button", { onclick: function () { printPaper(R, +copies.value || 1, true); } }, "🖶 " + t("Ключ ответов"))));
    pane.appendChild(cardPrint);
    var marksCard = h("div", { class: "card" }, h("h2", { style: { marginTop: 0 } }, t("2. Отметки после проверки")));
    pane.appendChild(marksCard);
    var inputs = {};
    R.students.forEach(function (s) {
      var i = h("input", { type: "text", style: { width: "90px" } });
      i.value = s.status === "finished" ? (s.mark || "") : "";
      inputs[s.student_id] = i;
    });
    marksCard.appendChild(A.table(["№", A.N("student"), t("Отметка")], R.students.map(function (s, k) {
      return h("tr", null, h("td", { class: "num" }, String(k + 1)), h("td", null, s.name), h("td", null, inputs[s.student_id]));
    })));
    marksCard.appendChild(h("div", { class: "bar", style: { marginTop: "10px" } }, h("button", { class: "pri", onclick: function () {
      var marks = {};
      Object.keys(inputs).forEach(function (k) { marks[k] = inputs[k].value.trim(); });
      api("PUT", "/api/runs/" + R.id + "/paper_marks", { marks: marks }).then(function (r) { ST.toast(ST.tf("Сохранено отметок: {0}", r.saved)); }).catch(A.err);
    } }, t("Сохранить отметки")), h("span", { class: "muted small" }, t("Отметки можно отправить в SchoolGrade на соседней вкладке."))));
  }

  var LET = "АБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЭЮЯ";
  function printPaper(R, copies, key) {
    api("GET", "/api/runs/" + R.id + "/paper?copies=" + copies).then(function (P) {
      var esc = ST.esc, fmt = ST.fmt;
      var img = function (id) { return "<img src='/api/media/" + id + "' style='max-height:160px;max-width:60%;display:block;margin:4px 0'>"; };
      var warn = "";
      if (P.excluded.length) {
        warn = "<div class='noprint' style='border:1px solid #c90;background:#fff6dd;padding:8px;margin-bottom:12px'><b>" + esc(t("Не вошли в печатный вариант (нельзя выполнить на бумаге):")) +
          "</b><ul>" + P.excluded.map(function (x) { return "<li>" + esc(x.text) + " — " + esc(t(x.type)) + "</li>"; }).join("") + "</ul></div>";
      }
      var html = warn;
      if (!key) {
        P.copies.forEach(function (c, ci) {
          html += "<div class='" + (ci < P.copies.length - 1 ? "pb" : "") + "'><h1>" + esc(P.title) + "</h1><div class='sub'>" + esc([P.subject, P.class].filter(Boolean).join(" · ")) +
            " · " + esc(ST.tf("Вариант {0}", c.variant)) + " · " + esc(ST.tf("экземпляр № {0}", c.copy)) + "</div>" +
            "<p>" + esc(t("Фамилия, имя")) + ": ______________________________ " + esc(t("Дата")) + ": __________</p>";
          c.items.forEach(function (it, i) { html += paperQuestion(it.q, i + 1, img); });
          html += "</div>";
        });
        A.printHtml(P.title, html, ".pq{margin:10px 0 14px;page-break-inside:avoid}.pq .n{font-weight:bold}.opts div{margin:2px 0 2px 18px}.line{border-bottom:1px solid #000;height:22px}");
      } else {
        html += "<h1>" + esc(t("Ключ ответов")) + ": " + esc(P.title) + "</h1><div class='sub'>" + esc(P.class) + "</div>";
        P.copies.forEach(function (c) {
          html += "<h2>" + esc(ST.tf("Экземпляр № {0}", c.copy)) + " · " + esc(ST.tf("Вариант {0}", c.variant)) + "</h2><table><tr><th>№</th><th>" + esc(t("Ответ")) + "</th></tr>";
          c.items.forEach(function (it, i) { html += "<tr><td>" + (i + 1) + "</td><td>" + paperKey(it) + "</td></tr>"; });
          html += "</table>";
        });
        A.printHtml(t("Ключ ответов"), html);
      }
      function paperKey(it) {
        var q = it.q, k = it.key, a = it.answer;
        if (q.type === "single" || q.type === "multi") return q.options.map(function (o, i) { return k.options.indexOf(o.id) >= 0 ? (i + 1) : null; }).filter(Boolean).join(", ");
        if (q.type === "short") return q.fields.map(function (f) { return (f.label ? esc(f.label) + ": " : "") + esc((a.fields[f.id] || []).join(" / ")); }).join("; ");
        if (q.type === "match") return q.left.map(function (l, i) { var r = k.pairs[l.id]; var j = q.right.map(function (x) { return x.id; }).indexOf(r); return (i + 1) + "–" + (LET[j] || "?"); }).join(", ");
        if (q.type === "order" || q.type === "chrono") {
          var pos = {}; q.items.forEach(function (x, i) { pos[x.id] = LET[i]; });
          return k.order.map(function (id) { return pos[id]; }).join(" → ");
        }
        if (q.type === "cloze") return q.blanks.map(function (b, i) { return (i + 1) + ") " + esc((a.blanks[b.id] || []).join(" / ")); }).join("; ");
        if (q.type === "essay") return a.sample ? esc(a.sample) : esc(t("проверяет учитель"));
        if (q.type === "likert") return esc(t("опрос, не оценивается"));
        return "";
      }
    }).catch(A.err);
  }
  function paperQuestion(q, n, img) {
    var esc = ST.esc, fmt = ST.fmt;
    var s = "<div class='pq'><span class='n'>" + n + ".</span> ";
    if (q.type === "cloze") {
      var k = 0;
      s += fmt(q.text).replace(/\{\{([^}]+)\}\}/g, function (m, id) {
        k++;
        var b = (q.blanks || []).filter(function (x) { return x.id === id; })[0];
        return "<b>(" + k + ")</b> " + (b && b.kind === "select" ? "[" + b.choices.map(esc).join(" / ") + "]" : "________");
      });
    } else s += fmt(q.text);
    (q.images || []).forEach(function (m) { s += img(m); });
    var opt = function (o) { return (o.text ? fmt(o.text) : "") + (o.image ? img(o.image) : ""); };
    if (q.type === "single" || q.type === "multi") {
      s += "<div class='opts'><i>" + esc(q.type === "multi" ? t("Отметьте все верные ответы:") : t("Отметьте один верный ответ:")) + "</i>" +
        q.options.map(function (o, i) { return "<div>" + (q.type === "multi" ? "☐" : "○") + " " + (i + 1) + ") " + opt(o) + "</div>"; }).join("") + "</div>";
    } else if (q.type === "short") {
      s += q.fields.map(function (f) { return "<p>" + (f.label ? fmt(f.label) + ": " : esc(t("Ответ")) + ": ") + "____________________</p>"; }).join("");
    } else if (q.type === "match") {
      s += "<table><tr><td style='width:50%'>" + q.left.map(function (l, i) { return (i + 1) + ") " + opt(l); }).join("<br>") + "</td><td>" +
        q.right.map(function (r, i) { return LET[i] + ") " + opt(r); }).join("<br>") + "</td></tr></table><p>" + esc(t("Ответ")) + ": " +
        q.left.map(function (_l, i) { return (i + 1) + "–___"; }).join("  ") + "</p>";
    } else if (q.type === "order" || q.type === "chrono") {
      s += "<div class='opts'><i>" + esc(q.type === "chrono" ? t("Расположите события в хронологическом порядке (от раннего к позднему):") :
        t("Расположите в правильном порядке:")) + "</i>" + q.items.map(function (x, i) { return "<div>" + LET[i] + ") " + opt(x) + "</div>"; }).join("") +
        "</div><p>" + esc(t("Ответ")) + ": " + q.items.map(function () { return "___"; }).join(" → ") + "</p>";
    } else if (q.type === "likert") {
      s += "<table><tr><th></th>" + q.scale.map(function (x) { return "<th>" + esc(x) + "</th>"; }).join("") + "</tr>" +
        q.statements.map(function (st) { return "<tr><td>" + fmt(st.text) + "</td>" + q.scale.map(function () { return "<td style='text-align:center'>○</td>"; }).join("") + "</tr>"; }).join("") + "</table>";
    } else if (q.type === "essay") {
      s += "<div class='line'></div><div class='line'></div><div class='line'></div><div class='line'></div><div class='line'></div>";
    }
    return s + "</div>";
  }

  /* ---------------- история ученика ---------------- */
  A.route("student", function (box, args) {
    var url = "/api/students/" + args[0] + "/history";
    return api("GET", url).then(function (rep) {
      A.head(box, rep.title, rep.subtitle);
      box.appendChild(A.reportView(rep, url + "?format=xlsx"));
    });
  });
})();
