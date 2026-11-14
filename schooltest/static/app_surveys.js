/* SchoolTest — конструктор анкет (1.3): список, редактор, проведение по коду, результаты */
"use strict";
(function () {
  var h = ST.h, t = ST.t, api = ST.api;

  var TYPE_NAMES = { single: t("Один вариант"), multi: t("Несколько вариантов"), likert: t("Шкала"), open: t("Открытый ответ") };
  var AUD_NAMES = { class: t("Учащиеся по списку класса"), anon: t("Анонимно по коду"), staff: t("Педагоги") };

  /* ---------------- список анкет ---------------- */
  A.route("surveys", function (box) {
    A.head(box, t("Анкеты"), t("Конструктор анкет: вопросы с вариантами, шкалой или открытым ответом, без баллов."),
      [h("button", { class: "pri", onclick: newSurvey }, "＋ " + t("Создать анкету"))]);
    var list = h("div");
    box.appendChild(list);
    return api("GET", "/api/surveys").then(function (r) {
      if (!r.items.length) { list.appendChild(h("div", { class: "card empty" }, t("Анкет пока нет."))); return; }
      var grid = h("div", { class: "tlist" });
      r.items.forEach(function (s) {
        grid.appendChild(h("div", { class: "tcard", onclick: function () { A.go("#/survey/" + s.id); } },
          h("h3", null, s.title), h("div", { class: "meta" }, ST.tf("Вопросов: {0}", s.questions), " · ", AUD_NAMES[s.audience] || s.audience),
          h("div", { class: "acts" }, h("button", { class: "sm", onclick: function (e) { e.stopPropagation(); A.go("#/survey/" + s.id); } }, t("Открыть")))));
      });
      list.appendChild(grid);
    });
  });

  function newSurvey() {
    var title = h("input", { type: "text", style: { width: "100%" } });
    ST.modal(t("Новая анкета"), A.field(t("Название"), title, "wide"),
      [{ text: t("Отмена"), value: null }, { text: t("Создать"), value: 1, cls: "pri" }]).then(function (v) {
      if (!v || !title.value.trim()) return;
      api("POST", "/api/surveys", { title: title.value.trim() }).then(function (r) { A.go("#/survey/" + r.id); }).catch(A.err);
    });
  }

  /* ---------------- вопрос: редактор ---------------- */
  function questionEditor(existing) {
    var qtype = h("select", null, Object.keys(TYPE_NAMES).map(function (k) { return h("option", { value: k }, TYPE_NAMES[k]); }));
    qtype.value = (existing && existing.type) || "single";
    var text = h("textarea", { rows: 2, style: { width: "100%" } }, (existing && existing.text) || "");
    var opts = h("textarea", { rows: 4, style: { width: "100%" }, placeholder: t("По одному варианту в строке") },
      existing && existing.options ? existing.options.map(function (o) { return o.text; }).join("\n") : "");
    var optsRow = h("div", null, A.field(t("Варианты ответа"), opts, "wide"),
      h("div", { class: "muted small" }, t("Для шкалы можно оставить пустым — будет стандартная 5-балльная шкала согласия.")));
    function syncOpts() { optsRow.style.display = qtype.value === "open" ? "none" : ""; }
    qtype.addEventListener("change", syncOpts);
    syncOpts();
    var required = h("input", { type: "checkbox" });
    required.checked = !existing || existing.required !== false;
    var body = h("div", { class: "form" }, A.field(t("Тип вопроса"), qtype, "wide"), A.field(t("Текст вопроса"), text, "wide"),
      optsRow, h("label", { class: "chk" }, required, h("span", null, t("Обязательный вопрос"))));
    return ST.modal(existing ? t("Изменить вопрос") : t("Новый вопрос"), body,
      [{ text: t("Отмена"), value: null }, { text: t("Сохранить"), value: 1, cls: "pri" }]).then(function (v) {
      if (!v) return undefined;
      if (!text.value.trim()) { ST.toast(t("Укажите текст вопроса"), true); return undefined; }
      var options = opts.value.split("\n").map(function (x) { return x.trim(); }).filter(Boolean);
      return { type: qtype.value, text: text.value.trim(), options: options, required: required.checked };
    });
  }

  /* ---------------- страница анкеты ---------------- */
  A.route("survey", function (box, args) {
    var id = +args[0];
    return api("GET", "/api/surveys/" + id).then(function (s) {
      var title = h("input", { type: "text", value: s.title, style: { width: "100%" } });
      var desc = h("textarea", { rows: 2, style: { width: "100%" } }, s.description || "");
      var aud = A.select(Object.keys(AUD_NAMES).map(function (k) { return [k, AUD_NAMES[k]]; }), s.audience);
      A.head(box, t("Анкета"), null, [h("button", { class: "pri", disabled: !s.items.length || null, onclick: function () { startSurveyRun(s); } }, "▶ " + t("Провести"))]);

      box.appendChild(h("div", { class: "card" }, h("div", { class: "form" },
        A.field(t("Название"), title, "wide"), A.field(t("Описание"), desc, "wide"),
        A.field(t("Кому предлагается код"), aud, "wide")),
        h("button", { class: "sm", style: { marginTop: "8px" }, onclick: function () {
          api("PUT", "/api/surveys/" + s.id, { title: title.value, description: desc.value, audience: aud.value })
            .then(function () { ST.toast(t("Сохранено")); }).catch(A.err);
        } }, t("Сохранить"))));

      var qbox = h("div", { class: "card" });
      box.appendChild(qbox);
      function drawQ() {
        qbox.innerHTML = "";
        qbox.appendChild(h("h2", { style: { marginTop: 0 } }, t("Вопросы")));
        s.items.forEach(function (q, i) {
          qbox.appendChild(h("div", { class: "qrow", style: { padding: "8px 0", borderBottom: "1px solid var(--line)" } },
            h("div", null, h("b", null, (i + 1) + ". " + q.text), " ", h("span", { class: "pill" }, TYPE_NAMES[q.type])),
            q.options && q.options.length ? h("div", { class: "muted small" }, q.options.map(function (o) { return o.text; }).join(" · ")) : null,
            h("div", { class: "acts" },
              h("button", { class: "sm", onclick: function () {
                questionEditor(q).then(function (v) { if (!v) return; api("PUT", "/api/survey_questions/" + q.id, v).then(function (nq) {
                  s.items[i] = nq; drawQ();
                }).catch(A.err); });
              } }, t("Изменить")),
              h("button", { class: "sm", onclick: function () {
                api("DELETE", "/api/survey_questions/" + q.id).then(function () { s.items.splice(i, 1); drawQ(); }).catch(A.err);
              } }, t("Удалить")))));
        });
        qbox.appendChild(h("button", { class: "sm pri", style: { marginTop: "8px" }, onclick: function () {
          questionEditor().then(function (v) { if (!v) return; api("POST", "/api/surveys/" + s.id + "/questions", v).then(function (nq) {
            s.items.push(nq); drawQ();
          }).catch(A.err); });
        } }, "＋ " + t("Добавить вопрос")));
      }
      drawQ();

      var rbox = h("div", { class: "card" });
      box.appendChild(rbox);
      function drawRuns() {
        rbox.innerHTML = "";
        rbox.appendChild(h("h2", { style: { marginTop: 0 } }, t("Проведения")));
        api("GET", "/api/surveys/" + s.id + "/runs").then(function (r) {
          rbox.appendChild(A.table([t("Код"), t("Статус"), t("Ответов"), ""], r.items.map(function (run) {
            return [run.code, run.status === "open" ? t("Открыто") : t("Закрыто"), String(run.responses),
              h("div", { class: "acts" },
                h("button", { class: "sm", onclick: function () { showSurveyResults(run.id); } }, t("Результаты")),
                run.status === "open" ? h("button", { class: "sm", onclick: function () {
                  api("POST", "/api/survey_runs/" + run.id + "/close").then(drawRuns).catch(A.err);
                } }, t("Закрыть")) : null)];
          })));
        });
      }
      drawRuns();

      function startSurveyRun(s) {
        function go(classId) {
          api("POST", "/api/surveys/" + s.id + "/runs", { class_id: classId || null }).then(function (r) {
            ST.modal(t("Анкета начата"), h("div", null, h("p", null, t("Код для перехода на устройствах:")),
              h("div", { style: { fontSize: "32px", fontWeight: "bold", letterSpacing: "4px", textAlign: "center" } }, r.code),
              h("p", { class: "muted small" }, t("Респонденты открывают адрес программы, выбирают «Анкета» и вводят код."))),
              [{ text: t("Готово"), value: 1, cls: "pri" }]).then(drawRuns);
          }).catch(A.err);
        }
        if (s.audience !== "class") { go(null); return; }
        api("GET", A.yearQ("/api/classes")).then(function (classes) {
          if (!classes.length) { go(null); return; }
          var cls = A.select([["", "— " + t("без привязки к списку") + " —"]].concat(classes.map(function (c) { return [c.id, c.name]; })), "");
          ST.modal(t("Провести анкету"), A.field(t("Класс"), cls, "wide"),
            [{ text: t("Отмена"), value: null }, { text: t("Начать"), value: 1, cls: "pri" }]).then(function (v) {
            if (v) go(cls.value ? +cls.value : null);
          });
        });
      }
    });
  });

  function showSurveyResults(rid) {
    api("GET", "/api/survey_runs/" + rid).then(function (r) {
      var body = h("div", null, h("p", null, ST.tf("Всего ответов: {0}", r.total)));
      r.report.forEach(function (item) {
        body.appendChild(h("div", { style: { margin: "10px 0" } }, h("b", null, item.question.text),
          item.counts ? h("ul", null, item.counts.map(function (c) { return h("li", null, c.option + ": " + c.n); })) :
            h("ul", null, (item.texts || []).map(function (x) { return h("li", null, x); }))));
      });
      ST.modal(t("Результаты анкеты"), body, [{ text: t("Закрыть"), value: null }], true);
    }).catch(A.err);
  }
})();
