/* SchoolTest — список тестов, импорт, страница теста */
"use strict";
(function () {
  var h = ST.h, t = ST.t, api = ST.api;

  /* ---------------- список тестов ---------------- */
  A.route("tests", function (box, args, q) {
    var arch = q.archived === "1";
    A.head(box, arch ? t("Архив тестов") : t("Тесты"), A.isAdmin() ? t("Администратор видит тесты всех пользователей") : null, [
      h("button", { class: "pri", onclick: newTest }, "＋ " + t("Создать тест")),
      h("button", { onclick: importDialog }, "⬆ " + t("Импорт теста"))]);
    var search = h("input", { type: "search", placeholder: t("Поиск по названию или предмету"), style: { minWidth: "260px" } });
    var own = A.select([["all", t("Все доступные")], ["mine", t("Только мои")], ["shared", t("Общие (других учителей)")]], "all");
    var list = h("div");
    box.appendChild(h("div", { class: "bar" }, search, own, h("div", { class: "sp" }),
      h("a", { href: arch ? "#/tests" : "#/tests?archived=1" }, arch ? t("← К действующим тестам") : t("Архив"))));
    box.appendChild(list);
    return api("GET", "/api/tests" + (arch ? "?archived=1" : "")).then(function (tests) {
      function draw() {
        var f = search.value.trim().toLowerCase();
        var rows = tests.filter(function (x) {
          if (own.value === "mine" && !x.mine) return false;
          if (own.value === "shared" && x.mine) return false;
          return !f || (x.title + " " + (x.subject || "")).toLowerCase().indexOf(f) >= 0;
        });
        list.innerHTML = "";
        if (!rows.length) {
          list.appendChild(h("div", { class: "card empty" }, tests.length ? t("Ничего не найдено") :
            h("div", null, h("p", null, t("Тестов пока нет.")), h("p", null, t("Создайте тест вручную или загрузите готовый: файл SchoolTest, текст из Word, таблицу Excel.")))));
          return;
        }
        var grid = h("div", { class: "tlist" });
        rows.forEach(function (x) {
          var scale = x.settings.scale || {};
          grid.appendChild(h("div", { class: "tcard", onclick: function (e) { if (!e.target.closest("button")) A.go("#/test/" + x.id); } },
            h("h3", null, x.title),
            h("div", { class: "meta" }, [x.subject, x.grade ? ST.tf("{0} класс", x.grade) : null].filter(Boolean).join(" · ") || " "),
            h("div", { class: "meta" }, ST.tf("Вопросов: {0}", x.questions), " · ", ST.tf("проведено: {0}", x.runs),
              x.settings.time_limit ? " · " + ST.tf("{0} мин", x.settings.time_limit) : "",
              scale.mode === "norms" ? " · " + t("по нормам") : ""),
            !x.mine ? h("div", { class: "meta" }, "👤 " + x.owner, x.shared ? " · " + t("общий") : "") :
              (x.shared ? h("div", { class: "meta" }, t("Доступен другим учителям")) : null),
            h("div", { class: "acts" },
              h("button", { class: "sm pri", disabled: !x.questions || null, onclick: function () { A.startRun(x.id); } }, "▶ " + t("Провести")),
              h("button", { class: "sm", onclick: function () { A.go("#/test/" + x.id); } }, x.mine || A.isAdmin() ? t("Изменить") : t("Открыть")),
              h("button", { class: "sm", onclick: function () { copyTest(x); } }, t("Копия")))));
        });
        list.appendChild(grid);
      }
      search.addEventListener("input", draw);
      own.addEventListener("change", draw);
      draw();
    });
  });

  function newTest() {
    var title = h("input", { type: "text", style: { width: "100%" } });
    var subj = h("input", { type: "text" });
    var grade = h("input", { type: "number", min: 1, max: 11, style: { width: "90px" } });
    ST.modal(t("Новый тест"), h("div", { class: "form" }, A.field(t("Название"), title, "wide"), A.field(t("Предмет"), subj),
      A.isSchool() ? A.field(t("Класс (параллель)"), grade) : null),
      [{ text: t("Отмена"), value: null }, { text: t("Создать"), value: 1, cls: "pri" }]).then(function (v) {
      if (!v) return;
      api("POST", "/api/tests", { title: title.value, subject: subj.value, grade: grade.value ? +grade.value : null })
        .then(function (r) { A.go("#/test/" + r.id); }).catch(A.err);
    });
  }
  function copyTest(x) {
    api("POST", "/api/tests/" + x.id + "/copy", {}).then(function (r) { ST.toast(t("Копия создана")); A.go("#/test/" + r.id); }).catch(A.err);
  }

  /* ---------------- импорт ---------------- */
  function importDialog(testId) {
    testId = typeof testId === "number" ? testId : null;
    var body = h("div");
    var opts = [
      ["file", t("Файл теста SchoolTest (.stest)"), t("Тест, выгруженный из SchoolTest в этой или другой школе — со всеми картинками и настройками.")],
      ["text", t("Текст из Word или файл .txt"), t("Вопросы по простой разметке: «+» — верный ответ, «-» — неверный, «=» — короткий ответ, «1.», «2.» — порядок.")],
      ["excel", t("Таблица Excel по шаблону"), t("Любые типы вопросов, по одному в строке. Скачайте шаблон с примерами.")]];
    if (testId) opts.shift();
    var grid = h("div", { class: "typegrid" });
    var res = null;
    opts.forEach(function (o) {
      grid.appendChild(h("button", { type: "button", onclick: function () { res = o[0]; close.click(); } }, h("b", null, o[1]), h("small", null, o[2])));
    });
    body.appendChild(grid);
    body.appendChild(h("p", { class: "muted small" }, t("Импорт из MyTestX, «Ассистент II» и Moodle появится в следующей версии.")));
    var close;
    var p = ST.modal(testId ? t("Добавить вопросы из файла") : t("Импорт теста"), body, [{ text: t("Отмена"), value: null }]);
    close = document.querySelector(".modal .acts button");
    p.then(function () {
      if (res === "file") importFile();
      if (res === "text") importText(testId);
      if (res === "excel") importExcel(testId);
    });
  }
  A.importDialog = importDialog;

  function importFile() {
    ST.pickFiles(".stest,.json").then(function (files) {
      if (!files.length) return;
      return ST.readFile(files[0]).then(function (d) {
        return api("POST", "/api/import/test", { files: [d] }, { timeout: 180000 });
      }).then(function (r) {
        if (r.errors && r.errors.length) ST.modal(t("Импорт завершён с замечаниями"), h("ul", null, r.errors.map(function (e) { return h("li", null, e); })));
        else ST.toast(t("Тест импортирован"));
        A.go("#/test/" + r.test_id);
      });
    }).catch(A.err);
  }

  function previewList(r) {
    var box = h("div");
    var nq = r.questions.length;
    box.appendChild(h("p", null, h("b", null, ST.tf("Распознано вопросов: {0}", nq)),
      r.errors.length ? h("span", { class: "bad" }, " · " + ST.tf("не удалось разобрать: {0}", r.errors.length)) : null));
    if (r.errors.length) {
      box.appendChild(h("div", { class: "warnbox" }, h("b", null, t("Строки, которые не удалось разобрать:")),
        h("ul", null, r.errors.map(function (e) {
          return h("li", null, e.line ? ST.tf("Строка {0}: ", e.line) : "", h("i", null, e.text || ""), " — ", t(e.msg));
        }))));
    }
    var rows = r.questions.map(function (q, i) {
      var det = [];
      if (q.options) det.push(q.options.map(function (o) { return (o.correct ? "✓ " : "· ") + (o.text || ("[" + o.image + "]")); }).join("  "));
      if (q.items) det.push(q.items.map(function (x, k) { return (k + 1) + ". " + x; }).join("  "));
      if (q.fields) det.push(q.fields.map(function (f) { return (f.label ? f.label + ": " : "") + f.answers.join(" / "); }).join("; "));
      return h("tr", null, h("td", { class: "num" }, String(i + 1)),
        h("td", null, h("div", { html: ST.fmt(q.text) }), det.length ? h("div", { class: "muted small" }, det.join(" ")) : null,
          q.missing && q.missing.length ? h("div", { class: "bad small" }, t("Нет картинки:") + " " + q.missing.join(", ")) : null),
        h("td", null, t(q.type_name)),
        q.task != null ? h("td", { class: "num" }, String(q.task)) : null);
    });
    var hdr = ["№", t("Вопрос"), t("Тип")];
    if (r.questions.length && r.questions[0].task != null) hdr.push(t("Задание"));
    box.appendChild(A.table(hdr, rows, { empty: t("Вопросы не распознаны") }));
    ST.math(box);
    return box;
  }

  function importText(testId) {
    var ta = h("textarea", { rows: 14, style: { fontFamily: "Consolas,monospace", fontSize: "13px" },
      placeholder: "Какой месяц идет после марта?\n- январь\n+ апрель\n- июнь\n\nДлина сторон прямоугольника 3 и 4 см. Найдите площадь и периметр.\n= {площадь:} 12\n= {периметр:} 14" });
    var files = [];
    var fl = h("div", { class: "muted small" });
    var title = h("input", { type: "text" });
    function drawFiles() { fl.textContent = files.length ? t("Файлы:") + " " + files.map(function (f) { return f.name; }).join(", ") : ""; }
    var help = h("details", null, h("summary", null, t("Правила разметки")), h("div", { class: "small" },
      h("ul", null,
        h("li", null, t("Строка без значка в начале — текст вопроса (может занимать несколько строк).")),
        h("li", null, t("«?» на отдельной строке — начало вопроса в формате «Ассистент II», текст вопроса на следующей строке.")),
        h("li", null, t("«+ ответ» — верный вариант, «- ответ» — неверный. Один «+» — один верный ответ, несколько — несколько верных.")),
        h("li", null, t("«1. ответ», «2. ответ» — вопрос на порядок: цифра задаёт верное место, ученику варианты показываются вперемешку.")),
        h("li", null, t("«= ответ» — короткий ответ (допустимые варианты через «;»), «= {подпись:} ответ» — несколько полей.")),
        h("li", null, t("«[файл.jpg]» — картинка в вопросе, «+[файл.png]» и «-[файл.png]» — картинка как вариант ответа. Картинки загрузите вместе с текстом или архивом ZIP.")),
        h("li", null, t("Формулы записываются в LaTeX между \\( и \\), например \\(x^2+1\\).")))));
    var body = h("div", null,
      h("p", { class: "muted", style: { marginTop: 0 } }, t("Вставьте текст из Word или загрузите файл .txt (можно вместе с картинками или архивом ZIP).")),
      help, ta,
      h("div", { class: "bar", style: { marginTop: "8px" } },
        h("button", { type: "button", onclick: function () {
          ST.pickFiles(".txt,.zip,.png,.jpg,.jpeg,.gif,.bmp,.webp,.svg", true).then(function (fs) {
            return Promise.all(fs.map(ST.readFile)).then(function (ds) {
              ds.forEach(function (d) {
                files = files.filter(function (x) { return x.name !== d.name; });
                files.push(d);
                if (/\.txt$/i.test(d.name) && !ta.value.trim()) {
                  ta.value = ""; // текст прочитает сервер (кодировка UTF-8 или Windows-1251)
                  if (!title.value) title.value = d.name.replace(/\.txt$/i, "");
                }
              });
              drawFiles();
            });
          }).catch(A.err);
        } }, "📎 " + t("Файлы и картинки…")), fl),
      testId ? null : A.field(t("Название теста"), title));
    ST.modal(testId ? t("Вопросы из текста") : t("Тест из текста"), body, [{ text: t("Отмена"), value: null },
      { text: t("Распознать"), value: 1, cls: "pri" }], true).then(function (v) {
      if (!v) return;
      var payload = { text: ta.value, files: files };
      api("POST", "/api/import/text", payload, { timeout: 120000 }).then(function (r) {
        return ST.modal(t("Проверьте распознанные вопросы"), previewList(r), [{ text: t("Отмена"), value: null },
          { text: testId ? t("Добавить в тест") : t("Создать тест"), value: 1, cls: "pri" }], true).then(function (ok) {
          if (!ok || !r.questions.length) return;
          payload.commit = true;
          payload.test_id = testId;
          payload.title = title.value;
          return api("POST", "/api/import/text", payload, { timeout: 180000 }).then(function (res) {
            doneImport(res, testId);
          });
        });
      }).catch(A.err);
    });
  }

  function importExcel(testId) {
    var files = [];
    var fl = h("div", { class: "muted" }, t("Файл не выбран"));
    var body = h("div", null,
      h("p", { style: { marginTop: 0 } }, t("Заполните шаблон: одна строка — один вопрос. Тип вопроса пишется словами («Один», «Несколько», «Краткий», «Порядок», «Хронология», «Соответствие», «Пропуски», «Опрос», «Развёрнутый», «Файл»).")),
      h("div", { class: "bar" },
        h("button", { type: "button", onclick: function () { ST.download("/api/import/excel_template"); } }, "⬇ " + t("Скачать шаблон")),
        h("button", { type: "button", class: "pri", onclick: function () {
          ST.pickFiles(".xlsx,.xls,.png,.jpg,.jpeg,.gif,.bmp,.webp,.svg,.zip", true).then(function (fs) {
            return Promise.all(fs.map(ST.readFile)).then(function (ds) { files = ds; fl.textContent = ds.map(function (d) { return d.name; }).join(", "); });
          }).catch(A.err);
        } }, "📎 " + t("Выбрать таблицу (и картинки)…"))), fl);
    ST.modal(t("Вопросы из таблицы Excel"), body, [{ text: t("Отмена"), value: null }, { text: t("Распознать"), value: 1, cls: "pri" }])
      .then(function (v) {
        if (!v || !files.length) return;
        var payload = { files: files };
        api("POST", "/api/import/excel", payload, { timeout: 120000 }).then(function (r) {
          return ST.modal(t("Проверьте распознанные вопросы"), previewList(r), [{ text: t("Отмена"), value: null },
            { text: testId ? t("Добавить в тест") : t("Создать тест"), value: 1, cls: "pri" }], true).then(function (ok) {
            if (!ok || !r.questions.length) return;
            payload.commit = true;
            payload.test_id = testId;
            return api("POST", "/api/import/excel", payload, { timeout: 180000 }).then(function (res) { doneImport(res, testId); });
          });
        }).catch(A.err);
      });
  }

  function doneImport(res, testId) {
    var msg = ST.tf("Добавлено вопросов: {0}", res.added);
    if (res.errors && res.errors.length) {
      ST.modal(t("Импорт завершён с замечаниями"), h("div", null, h("p", null, msg),
        h("ul", null, res.errors.map(function (e) { return h("li", null, e.line ? ST.tf("Строка {0}: ", e.line) : "", e.text ? h("i", null, e.text + " — ") : "", t(e.msg)); }))));
    } else ST.toast(msg);
    if (testId) A.render(); else A.go("#/test/" + res.test_id);
  }

  /* ---------------- запуск теста ---------------- */
  A.startRun = function (testId) {
    api("GET", "/api/classes").then(function (classes) {
      if (!classes.length) { ST.modal(t("Нет списков"), h("p", null, A.N("no_classes") + ". " + t("Администратор добавляет их в разделе слева."))); return; }
      var cls = A.select([["", "— " + A.N("choose_class") + " —"]].concat(classes.map(function (c) {
        return [c.id, c.name + " (" + c.students + ")"];
      })), "");
      var mode = "online";
      var mOnline = h("input", { type: "radio", name: "rmode", checked: true, onchange: function () { mode = "online"; } });
      var mPaper = h("input", { type: "radio", name: "rmode", onchange: function () { mode = "paper"; } });
      var err = h("div", { class: "bad" });
      ST.modal(t("Провести тест"), h("div", null, A.field(A.N("class"), cls), h("div", { style: { height: "12px" } }),
        h("label", { class: "chk" }, mOnline, h("span", null, h("b", null, t("На компьютерах")), h("div", { class: "muted small" },
          t("Программа покажет код. Ученики открывают адрес программы, вводят код и выбирают себя в списке.")))),
        h("label", { class: "chk" }, mPaper, h("span", null, h("b", null, t("На бумаге")), h("div", { class: "muted small" },
          t("Печать вариантов и ключа ответов. Отметки вы вносите вручную после проверки.")))), err),
        [{ text: t("Отмена"), value: null }, { text: t("Начать"), value: 1, cls: "pri", check: function () {
          if (!cls.value) { err.textContent = A.N("choose_class"); return false; } return true;
        } }]).then(function (v) {
        if (!v) return;
        api("POST", "/api/runs", { test_id: testId, class_id: +cls.value, mode: mode }).then(function (r) {
          A.go("#/run/" + r.id + (mode === "paper" ? "/paper" : ""));
        }).catch(A.err);
      });
    }).catch(A.err);
  };

  /* ---------------- страница теста ---------------- */
  A.route("test", function (box, args) {
    var id = +args[0], tab = args[1] || "questions";
    return api("GET", "/api/tests/" + id).then(function (T) {
      A.curTest = T;
      var edit = T.can_edit;
      var acts = [
        h("button", { class: "pri", disabled: !T.questions || null, onclick: function () { A.startRun(T.id); } }, "▶ " + t("Провести")),
        h("button", { onclick: function () { ST.download("/api/tests/" + T.id + "/export"); } }, "⬇ " + t("Экспорт")),
        h("button", { onclick: function () { api("POST", "/api/tests/" + T.id + "/copy", {}).then(function (r) { ST.toast(t("Копия создана")); A.go("#/test/" + r.id); }).catch(A.err); } }, t("Копия"))];
      if (edit) acts.push(h("button", { class: "danger", onclick: function () { delTest(T); } }, t("Удалить")));
      A.head(box, T.title, [T.subject, T.grade ? ST.tf("{0} класс", T.grade) : null, !edit ? "👤 " + T.owner : null].filter(Boolean).join(" · "), acts);
      if (!edit) box.appendChild(h("div", { class: "infobox" }, t("Это тест другого учителя. Его можно провести или сделать копию, чтобы изменить.")));
      box.appendChild(A.tabs([["questions", "#/test/" + id, ST.tf("Вопросы ({0})", T.questions)], ["settings", "#/test/" + id + "/settings", t("Настройки")],
        ["preview", "#/test/" + id + "/preview", t("Как видит ученик")], ["runs", "#/test/" + id + "/runs", ST.tf("Проведения ({0})", T.runs)]], tab));
      if (T.warnings && T.warnings.length && tab !== "runs") {
        box.appendChild(h("div", { class: "warnbox" }, h("b", null, t("Обратите внимание:")), h("ul", null, T.warnings.map(function (w) { return h("li", null, t(w)); }))));
      }
      var pane = h("div");
      box.appendChild(pane);
      if (tab === "questions") A.questionsTab(pane, T, edit);
      else if (tab === "settings") settingsTab(pane, T, edit);
      else if (tab === "preview") previewTab(pane, T);
      else if (tab === "runs") return runsTab(pane, T);
    });
  });

  function delTest(T) {
    ST.confirm(t("Удалить тест?"), T.runs ? t("Тест уже проводился, поэтому он будет перенесён в архив вместе с результатами.") :
      t("Тест и все его вопросы будут удалены."), t("Удалить"), true).then(function (ok) {
      if (!ok) return;
      api("DELETE", "/api/tests/" + T.id).then(function () { A.go("#/tests"); }).catch(A.err);
    });
  }

  /* ---------------- настройки теста ---------------- */
  function settingsTab(pane, T, edit) {
    var S = JSON.parse(JSON.stringify(T.settings));
    var norms = A.me.norms;
    var title = h("input", { type: "text" }); title.value = T.title;
    var subj = h("input", { type: "text" }); subj.value = T.subject || "";
    var grade = h("input", { type: "number", min: 1, max: 11 }); grade.value = T.grade || "";
    var desc = h("textarea", { rows: 2 }); desc.value = T.description || "";
    var shared = A.check(t("Доступен другим учителям (они могут провести тест или сделать копию)"), T.shared);

    var scaleMode = A.select([["percent", t("По проценту выполнения")], ["norms", t("По нормам оценки результатов учебной деятельности")]], S.scale.mode || "percent");
    var normSel = A.select(norms.map(function (n) { return [n.id, t(n.name)]; }), S.scale.norm || norms[0].id);
    var normInfo = h("div", { class: "muted small" });
    var thrBox = h("div");
    var ownThr = !!S.scale.thresholds;
    var thr = (S.scale.thresholds || A.me.settings.default_scale).map(function (x) { return x.slice(); });
    function drawScale() {
      var isN = scaleMode.value === "norms";
      normSel.parentNode.classList.toggle("hidden", !isN);
      normInfo.classList.toggle("hidden", !isN);
      thrBox.classList.toggle("hidden", isN);
      var n = norms.filter(function (x) { return x.id === normSel.value; })[0];
      normInfo.innerHTML = "";
      if (n) {
        normInfo.appendChild(h("div", null, t(n.note)));
        normInfo.appendChild(h("div", null, t(n.kind === "tasks" ? "Баллы → отметка:" : "Процент → отметка:") + " " +
          n.table.map(function (r) { return r[1] + " — " + (n.kind === "tasks" ? t("от") + " " + r[0] : t("от") + " " + r[0] + " %"); }).join("; ")));
        if (n.kind === "tasks") normInfo.appendChild(h("div", { class: "warn" }, ST.tf("В тесте должно быть {0} заданий (по порядку уровней). Вопросы задания можно сделать банком: ученик получит случайные.", n.task_points.length)));
      }
      thrBox.innerHTML = "";
      var useOwn = A.check(t("Своя шкала для этого теста"), ownThr, function (v) { ownThr = v; drawScale(); },
        ownThr ? null : t("Сейчас используется шкала по умолчанию, которую задал администратор."));
      thrBox.appendChild(useOwn);
      var tb = h("div", { style: { display: "flex", gap: "6px", flexWrap: "wrap", marginTop: "6px" } });
      thr.forEach(function (r) {
        var inp = h("input", { type: "number", min: 0, max: 100, step: "0.5", style: { width: "64px" }, disabled: !ownThr || !edit || null });
        inp.value = r[0];
        inp.addEventListener("input", function () { r[0] = parseFloat(inp.value.replace(",", ".")) || 0; });
        tb.appendChild(h("label", { class: "f", style: { alignItems: "center" } }, h("b", { style: { color: "var(--brand)", fontSize: "15px" } }, String(r[1])), inp));
      });
      thrBox.appendChild(h("div", { class: "muted small", style: { marginTop: "6px" } }, t("Отметка — от какого процента выполнения:")));
      thrBox.appendChild(tb);
    }
    scaleMode.addEventListener("change", drawScale);
    normSel.addEventListener("change", drawScale);

    var rk = A.select(Object.keys(A.me.result_kinds).map(function (k) { return [k, t(A.me.result_kinds[k])]; }), S.result_kind || "mark");
    var pass = h("input", { type: "number", min: 1, max: 100, style: { width: "90px" } }); pass.value = S.pass_percent || 60;
    var tl = h("input", { type: "number", min: 0, max: 600, style: { width: "90px" } }); tl.value = S.time_limit || 0;
    var vars = h("input", { type: "number", min: 1, max: 10, style: { width: "90px" } }); vars.value = S.variants || 1;
    var show = A.select([["none", t("Ничего — результат сообщит учитель")], ["mark", t("Только итог (отметку)")],
      ["review", t("Итог и разбор ошибок с правильными ответами")]], S.show_result);
    var flags = {};
    function flag(k, label, hint) { var c = A.check(label, S[k], function (v) { S[k] = v; }, hint); flags[k] = c; return c; }

    var form = h("div", null,
      h("div", { class: "card" }, h("h2", { style: { marginTop: 0 } }, t("Описание")),
        h("div", { class: "form" }, A.field(t("Название"), title, "wide"), A.field(t("Предмет"), subj),
          A.isSchool() ? A.field(t("Класс (параллель)"), grade) : null, A.field(t("Описание или инструкция"), desc, "wide")), shared),
      h("div", { class: "card" }, h("h2", { style: { marginTop: 0 } }, t("Оценивание")),
        A.isEnterprise() ? h("div", { class: "form" }, A.field(t("Итог теста"), rk), A.field(t("Порог «сдал» / «зачтено», %"), pass)) : null,
        h("div", { class: "form", style: { marginTop: "8px" } }, A.field(t("Шкала отметок"), scaleMode), A.field(t("Нормы"), normSel, "wide")),
        normInfo, thrBox),
      h("div", { class: "card" }, h("h2", { style: { marginTop: 0 } }, t("Проведение и защита от списывания")),
        h("div", { class: "form" }, A.field(t("Время на тест, минут (0 — без ограничения)"), tl), A.field(t("Число вариантов"), vars),
          A.field(t("Что ученик видит после теста"), show, "wide")),
        h("div", { style: { marginTop: "10px" } },
          flag("shuffle_questions", t("Перемешивать вопросы"), t("При шкале по заданиям уровни идут по порядку, а вопросы внутри задания перемешиваются.")),
          flag("shuffle_options", t("Перемешивать варианты ответов")),
          flag("free_nav", t("Можно пропускать вопросы и возвращаться к ним"), t("Если выключено — вопросы проходятся строго по порядку, вернуться нельзя.")),
          flag("track_focus", t("Отмечать уход со страницы (переключение на другую вкладку или окно)")),
          flag("no_copy", t("Запретить копирование и выделение текста теста")))));
    pane.appendChild(form);
    drawScale();
    if (!edit) { form.querySelectorAll("input,select,textarea,button").forEach(function (e) { e.disabled = true; }); return; }
    pane.appendChild(h("div", { class: "bar" }, h("button", { class: "pri", onclick: function () {
      S.scale = { mode: scaleMode.value };
      if (scaleMode.value === "norms") S.scale.norm = normSel.value;
      else if (ownThr) S.scale.thresholds = thr;
      S.result_kind = A.isEnterprise() ? rk.value : "mark";
      S.pass_percent = +pass.value || 60;
      S.time_limit = +tl.value || 0;
      S.variants = +vars.value || 1;
      S.show_result = show.value;
      api("PUT", "/api/tests/" + T.id, { title: title.value, subject: subj.value, grade: grade.value ? +grade.value : null,
        description: desc.value, shared: shared.querySelector("input").checked ? 1 : 0, settings: S })
        .then(function () { ST.toast(t("Сохранено")); A.render(); }).catch(A.err);
    } }, t("Сохранить настройки"))));
  }

  /* ---------------- предпросмотр ---------------- */
  A.toPublic = function (q) {
    var b = q.body, out = { id: String(q.id), type: q.type, text: b.text || "", images: b.images || [] };
    if (b.audio && b.audio.media) out.audio = { media: b.audio.media, limit: b.audio.plays || 0, left: b.audio.plays || null };
    var shuffle = function (a) { a = a.slice(); for (var i = a.length - 1; i > 0; i--) { var j = Math.floor(Math.random() * (i + 1)); var x = a[i]; a[i] = a[j]; a[j] = x; } return a; };
    if (q.type === "single" || q.type === "multi") out.options = b.options;
    if (q.type === "short") out.fields = b.fields;
    if (q.type === "match") { out.left = b.left; out.right = shuffle(b.right); }
    if (q.type === "order") out.items = shuffle(b.items);
    if (q.type === "chrono") { out.items = shuffle(b.events); out.labels = { start: b.start_label, end: b.end_label }; }
    if (q.type === "cloze") out.blanks = b.blanks;
    if (q.type === "likert") { out.statements = b.statements; out.scale = b.scale; }
    if (q.type === "essay") out.min_words = b.min_words;
    if (q.type === "file") { out.task_files = b.task_files; out.accept = b.accept; out.max_mb = b.max_mb; }
    return out;
  };
  A.correctOf = function (q) {
    var a = q.answer || {};
    var first = function (m) { var o = {}; Object.keys(m || {}).forEach(function (k) { o[k] = (m[k] || [""])[0]; }); return o; };
    switch (q.type) {
      case "single": case "multi": return { options: a.correct || [] };
      case "short": return { fields: first(a.fields) };
      case "match": return { pairs: a.pairs || {} };
      case "order": case "chrono": return { order: a.order || [], dates: a.dates || {} };
      case "cloze": return { blanks: first(a.blanks) };
    }
    return {};
  };
  function previewTab(pane, T) {
    var qs = T.question_list;
    if (!qs.length) { pane.appendChild(h("div", { class: "card empty" }, t("В тесте нет вопросов"))); return; }
    var showKey = false;
    var list = h("div");
    var bar = h("div", { class: "bar" }, h("div", { class: "muted" }, t("Так вопросы выглядят у ученика. Ответы здесь не сохраняются.")),
      h("div", { class: "sp" }), A.check(t("Показать правильные ответы"), false, function (v) { showKey = v; draw(); }));
    function draw() {
      list.innerHTML = "";
      qs.forEach(function (q, i) {
        list.appendChild(h("div", { class: "card" }, h("div", { class: "muted small", style: { marginBottom: "8px" } },
          ST.tf("Вопрос {0}", i + 1) + " · " + t(ST.TYPE_NAMES[q.type])),
          ST.renderQuestion(A.toPublic(q), showKey && (q.type === "order" || q.type === "chrono") ? { order: q.answer.order, touched: true } : null, { readonly: showKey, review: showKey ? { correct: A.correctOf(q) } : null,
            onPlay: function () { return Promise.resolve({ left: null }); },
            onUpload: function () { return Promise.reject({ message: t("В предпросмотре файлы не загружаются") }); } })));
      });
    }
    pane.appendChild(bar);
    pane.appendChild(list);
    draw();
  }

  function runsTab(pane, T) {
    return api("GET", "/api/runs?test_id=" + T.id).then(function (runs) {
      pane.appendChild(A.runsTable(runs, true));
    });
  }
})();
