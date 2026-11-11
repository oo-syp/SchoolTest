/* SchoolTest — задачи с кодом: редактор задачи, проверка эталонным решением, компиляторы */
"use strict";
(function () {
  var h = ST.h, t = ST.t, api = ST.api;
  var LANGS = [["fpc", "Free Pascal"], ["pabc", "PascalABC.NET"], ["py", "Python 3"], ["cpp", "C++ (20)"]];

  A.blankCode = function () {
    return { text: "", images: [], input_format: "", output_format: "", notes: "", examples: [{ in: "", out: "" }],
             time_limit: 1, memory: 256, languages: LANGS.map(function (l) { return l[0]; }), feedback: "full", max_submissions: 0 };
  };

  function ta(value, rows, ph, oninput, mono) {
    var x = h("textarea", { rows: rows || 3, placeholder: ph || "", spellcheck: mono ? "false" : null, class: mono ? "mono" : null });
    x.value = value || "";
    x.addEventListener("input", function () { oninput(x.value); });
    return x;
  }
  function num(value, min, max, step, oninput, w) {
    var x = h("input", { type: "number", min: min, max: max, step: step || 1, style: { width: (w || 90) + "px" } });
    x.value = value;
    x.addEventListener("input", function () { oninput(x.value); });
    return x;
  }

  /* редактор тестов одной подзадачи */
  function testsDialog(st) {
    var tests = (st.tests || []).map(function (x) { return { in: x.in, out: x.out }; });
    var list = h("div", { class: "tlist" });
    function draw() {
      list.innerHTML = "";
      if (!tests.length) list.appendChild(h("div", { class: "empty" }, t("Тестов нет")));
      tests.forEach(function (x, i) {
        list.appendChild(h("div", { class: "trow" }, h("b", null, String(i + 1)),
          h("div", null, h("div", { class: "muted small" }, t("Входные данные")), ta(x.in, 3, "", function (v) { x.in = v; }, true)),
          h("div", null, h("div", { class: "muted small" }, t("Правильный ответ")), ta(x.out, 3, "", function (v) { x.out = v; }, true)),
          h("button", { type: "button", class: "sm ghost danger", title: t("Удалить"), onclick: function () { tests.splice(i, 1); draw(); } }, "✕")));
      });
    }
    draw();
    var body = h("div", null,
      h("div", { class: "bar" }, h("button", { type: "button", class: "sm", onclick: function () { tests.push({ in: "", out: "" }); draw(); } }, "＋ " + t("Тест")),
        h("button", { type: "button", class: "sm", onclick: function () {
          zipTests().then(function (groups) {
            if (!groups) return;
            groups.forEach(function (g) { tests = tests.concat(g.tests); });
            draw();
          }).catch(A.err);
        } }, "⬆ " + t("Добавить из ZIP")),
        h("span", { class: "muted small" }, t("Сравнение — по словам (лишние пробелы и переводы строк не учитываются), если в настройках не выбрано другое."))),
      list);
    return ST.modal(ST.tf("Тесты: {0}", st.name || t("подзадача")), body, [{ text: t("Отмена"), value: null }, { text: t("Готово"), value: 1, cls: "pri" }], true)
      .then(function (v) { if (v) st.tests = tests.filter(function (x) { return (x.in || "").trim() || (x.out || "").trim(); }); return v; });
  }

  function zipTests() {
    return ST.pickFiles(".zip").then(function (fs) {
      if (!fs.length) return null;
      return ST.readFile(fs[0]).then(function (d) { return api("POST", "/api/judge/tests_zip", { data: d.data }, { timeout: 120000 }); })
        .then(function (r) {
          ST.toast(ST.tf("Загружено тестов: {0}", r.groups.reduce(function (s, g) { return s + g.tests.length; }, 0)));
          return r.groups;
        });
    });
  }

  /* специфика спецификации для проверки */
  function specOf(b, a) {
    return { time_limit: +b.time_limit || 1, memory: +b.memory || 256, checker: a.checker || "tokens", eps: +a.eps || 1e-6,
             scoring: a.scoring || "subtasks", examples: b.examples || [], subtasks: a.subtasks || [], check_examples: a.check_examples !== false };
  }

  A.codeUI = function (box, b, a, later) {
    if (!b.examples) { var bl = A.blankCode(); Object.keys(bl).forEach(function (k) { if (b[k] == null) b[k] = bl[k]; }); }
    a.subtasks = a.subtasks || [];
    a.scoring = a.scoring || "subtasks";
    a.checker = a.checker || "tokens";
    a.solution = a.solution || { lang: "py", code: "" };
    if (a.check_examples == null) a.check_examples = true;

    box.appendChild(h("div", { class: "form" },
      A.field(t("Формат ввода"), ta(b.input_format, 3, t("В первой строке вводятся…"), function (v) { b.input_format = v; later(); }), "wide"),
      A.field(t("Формат вывода"), ta(b.output_format, 2, t("Выведите одно число…"), function (v) { b.output_format = v; later(); }), "wide"),
      A.field(t("Примечания (необязательно)"), ta(b.notes, 2, "", function (v) { b.notes = v; later(); }), "wide")));

    /* примеры */
    var exBox = h("div", { class: "sec" }, h("b", null, t("Примеры (видны ученику)")));
    var exList = h("div");
    function drawEx() {
      exList.innerHTML = "";
      b.examples.forEach(function (x, i) {
        exList.appendChild(h("div", { class: "trow" }, h("b", null, String(i + 1)),
          h("div", null, h("div", { class: "muted small" }, t("Ввод")), ta(x.in, 3, "", function (v) { x.in = v; later(); }, true)),
          h("div", null, h("div", { class: "muted small" }, t("Вывод")), ta(x.out, 3, "", function (v) { x.out = v; later(); }, true)),
          h("button", { type: "button", class: "sm ghost danger", onclick: function () { b.examples.splice(i, 1); drawEx(); later(); } }, "✕")));
      });
    }
    drawEx();
    exBox.appendChild(exList);
    exBox.appendChild(h("div", { class: "bar" }, h("button", { type: "button", class: "sm", onclick: function () { b.examples.push({ in: "", out: "" }); drawEx(); later(); } }, "＋ " + t("Пример")),
      A.check(t("Проверять решение и на примерах (без баллов)"), a.check_examples, function (v) { a.check_examples = v; })));
    box.appendChild(exBox);

    /* ограничения и языки */
    var langBox = h("div", { class: "langs-chk" });
    LANGS.forEach(function (l) {
      langBox.appendChild(A.check(l[1], b.languages.indexOf(l[0]) >= 0, function (on) {
        b.languages = b.languages.filter(function (x) { return x !== l[0]; });
        if (on) b.languages.push(l[0]);
        b.languages.sort(function (x, y) { return LANGS.map(function (z) { return z[0]; }).indexOf(x) - LANGS.map(function (z) { return z[0]; }).indexOf(y); });
        later();
      }));
    });
    var eps = num(a.eps || 0.000001, 0, 1, "any", function (v) { a.eps = parseFloat(String(v).replace(",", ".")) || 1e-6; }, 120);
    var epsF = A.field(t("Погрешность"), eps);
    epsF.classList.toggle("hidden", a.checker !== "float");
    box.appendChild(h("div", { class: "sec" }, h("b", null, t("Ограничения и проверка")),
      h("div", { class: "form" },
        A.field(t("Время на тест, с"), num(b.time_limit, 0.1, 20, 0.1, function (v) { b.time_limit = parseFloat(String(v).replace(",", ".")) || 1; later(); })),
        A.field(t("Память, МБ"), num(b.memory, 16, 1024, 1, function (v) { b.memory = parseInt(v, 10) || 256; later(); })),
        A.field(t("Сравнение ответа"), A.select([["tokens", t("По словам и числам (пробелы не важны)")], ["lines", t("Построчно, точно")],
          ["float", t("Числа с погрешностью")]], a.checker, function (v) { a.checker = v; epsF.classList.toggle("hidden", v !== "float"); })),
        epsF,
        A.field(t("Начисление баллов"), A.select([["subtasks", t("За подзадачу целиком (как на олимпиаде)")], ["tests", t("За каждый пройденный тест")]],
          a.scoring, function (v) { a.scoring = v; })),
        A.field(t("Что видит ученик о посылке"), A.select([["full", t("Баллы по подзадачам и номер теста")], ["verdict", t("Только итог и баллы")],
          ["none", t("Только «принято на проверку»")]], b.feedback, function (v) { b.feedback = v; })),
        A.field(t("Наибольшее число посылок (0 — без ограничения)"), num(b.max_submissions, 0, 500, 1, function (v) { b.max_submissions = parseInt(v, 10) || 0; }))),
      h("div", null, h("div", { class: "muted small" }, t("Разрешённые языки")), langBox),
      A.check(t("Проверю решение сам (автопроверка — только подсказка учителю)"), a.manual, function (v) { a.manual = v; })));

    /* подзадачи */
    var stBox = h("div", { class: "sec" }, h("b", null, t("Подзадачи и тесты (ученик тестов не видит)")));
    var stList = h("div");
    function drawSt() {
      stList.innerHTML = "";
      if (!a.subtasks.length) stList.appendChild(h("div", { class: "muted small" }, t("Добавьте подзадачу и тесты к ней или загрузите тесты из ZIP-архива.")));
      var total = 0;
      a.subtasks.forEach(function (st, i) {
        total += +st.points || 0;
        var deps = h("input", { type: "text", placeholder: "1, 2", style: { width: "80px" } });
        deps.value = (st.deps || []).join(", ");
        deps.addEventListener("input", function () { st.deps = deps.value.split(/[^\d]+/).filter(Boolean).map(Number).filter(function (n) { return n > 0 && n <= i; }); later(); });
        var nm = h("input", { type: "text", placeholder: ST.tf("Подзадача {0}", i + 1), style: { width: "150px" } });
        nm.value = st.name || "";
        nm.addEventListener("input", function () { st.name = nm.value; later(); });
        var lim = h("input", { type: "text", placeholder: t("Ограничения, например N ≤ 100"), style: { flex: 1, minWidth: "160px" } });
        lim.value = st.limits || "";
        lim.addEventListener("input", function () { st.limits = lim.value; later(); });
        stList.appendChild(h("div", { class: "strow" }, h("b", null, String(i + 1)), nm,
          h("label", { class: "muted small" }, t("Баллы") + " ", num(st.points, 0, 1000, "any", function (v) { st.points = parseFloat(String(v).replace(",", ".")) || 0; drawTotal(); later(); }, 70)),
          h("label", { class: "muted small" }, t("Нужны подзадачи") + " ", deps), lim,
          h("button", { type: "button", class: "sm", onclick: function () { testsDialog(st).then(drawSt); } }, ST.tf("Тесты: {0}", (st.tests || []).length)),
          h("button", { type: "button", class: "sm ghost danger", onclick: function () { a.subtasks.splice(i, 1); drawSt(); later(); } }, "✕")));
      });
      totalEl.textContent = a.subtasks.length ? ST.tf("Всего баллов: {0}. Балл за вопрос теста масштабируется пропорционально.", String(total).replace(".", ",")) : "";
    }
    var totalEl = h("div", { class: "muted small" });
    function drawTotal() { var s = 0; a.subtasks.forEach(function (x) { s += +x.points || 0; }); totalEl.textContent = ST.tf("Всего баллов: {0}. Балл за вопрос теста масштабируется пропорционально.", String(s).replace(".", ",")); }
    stBox.appendChild(stList);
    stBox.appendChild(totalEl);
    stBox.appendChild(h("div", { class: "bar" },
      h("button", { type: "button", class: "sm", onclick: function () { a.subtasks.push({ name: "", points: 0, deps: [], tests: [], limits: "" }); drawSt(); later(); } }, "＋ " + t("Подзадача")),
      h("button", { type: "button", class: "sm", onclick: function () {
        zipTests().then(function (groups) {
          if (!groups) return;
          groups.forEach(function (g) { a.subtasks.push({ name: g.name || "", points: 0, deps: [], tests: g.tests, limits: "" }); });
          if (a.subtasks.every(function (x) { return !x.points; })) a.subtasks.forEach(function (x) { x.points = Math.round(10000 / a.subtasks.length) / 100; });
          drawSt(); later();
        }).catch(A.err);
      } }, "⬆ " + t("Тесты из ZIP")),
      h("span", { class: "muted small" }, t("Архив: пары 01 и 01.a, 1.in и 1.out или input1.txt и output1.txt; папки в архиве — подзадачи."))));
    box.appendChild(stBox);
    drawSt();

    /* эталонное решение */
    var solLang = A.select(LANGS, a.solution.lang || "py", function (v) { a.solution.lang = v; });
    var solEd = ST.codeEditor(a.solution.code || "", { rows: 10 });
    solEd.addEventListener("input", function () { a.solution.code = solEd.value; });
    var res = h("div");
    var checkBtn = h("button", { type: "button", class: "pri sm", onclick: function () {
      if (!solEd.value.trim()) { ST.toast(t("Напишите решение"), true); return; }
      checkBtn.disabled = true;
      res.innerHTML = "";
      res.appendChild(h("div", { class: "muted" }, t("Проверка…")));
      api("POST", "/api/judge/check", { lang: solLang.value, code: solEd.value, spec: specOf(b, a) }, { timeout: 600000 }).then(function (r) {
        res.innerHTML = "";
        res.appendChild(h("div", { class: "bar" }, h("b", { class: ST.verdictClass(r.verdict) }, t(ST.VERDICT[r.verdict] || r.verdict)),
          h("span", null, ST.tf("доля баллов: {0} %", Math.round((r.frac || 0) * 100)))));
        res.appendChild(ST.subDetails({ details: r, status: "done", verdict: r.verdict }, true));
      }).catch(function (e) { res.innerHTML = ""; A.err(e); }).then(function () { checkBtn.disabled = false; });
    } }, "▶ " + t("Проверить на тестах"));
    var fillBtn = h("button", { type: "button", class: "sm", onclick: function () {
      if (!solEd.value.trim()) { ST.toast(t("Напишите решение"), true); return; }
      var all = [];
      b.examples.forEach(function (x) { all.push(x); });
      a.subtasks.forEach(function (s) { (s.tests || []).forEach(function (x) { all.push(x); }); });
      var empty = all.filter(function (x) { return !(x.out || "").trim(); });
      var which = empty.length ? empty : all;
      ST.confirm(t("Получить ответы решением?"), empty.length ? ST.tf("Будут заполнены пустые ответы: {0}.", empty.length) :
        ST.tf("Пустых ответов нет. Перезаписать все ответы ({0})?", all.length), t("Выполнить")).then(function (ok) {
        if (!ok) return;
        fillBtn.disabled = true;
        api("POST", "/api/judge/answers", { lang: solLang.value, code: solEd.value, inputs: which.map(function (x) { return x.in; }),
          time_limit: Math.max(2, +b.time_limit * 2), memory: b.memory }, { timeout: 600000 }).then(function (r) {
          if (r.verdict !== "OK") { ST.modal(t("Ошибка компиляции"), h("pre", { class: "io err" }, r.compile || r.verdict)); return; }
          var bad = 0;
          r.outputs.forEach(function (o, i) { if (o.status === "OK") which[i].out = o.output.replace(/\s+$/, "") + "\n"; else bad++; });
          drawEx(); drawSt(); later();
          ST.toast(ST.tf("Ответы получены: {0}", r.outputs.length - bad) + (bad ? " · " + ST.tf("с ошибкой: {0}", bad) : ""), !!bad);
        }).catch(A.err).then(function () { fillBtn.disabled = false; });
      });
    } }, t("Заполнить ответы тестов"));
    box.appendChild(h("details", { class: "sec", open: a.solution.code ? true : null },
      h("summary", null, h("b", null, t("Эталонное решение (видит только учитель)"))),
      h("div", { class: "bar" }, h("label", { class: "muted" }, t("Язык") + " ", solLang), checkBtn, fillBtn,
        h("span", { class: "muted small" }, t("Проверка идёт на этом компьютере теми же компиляторами, что и у учеников."))),
      solEd, res));
  };

  A.buildCode = function (b, a, need) {
    var body = { input_format: b.input_format || "", output_format: b.output_format || "", notes: b.notes || "",
                 examples: (b.examples || []).filter(function (x) { return (x.in || "").trim() || (x.out || "").trim(); }),
                 time_limit: +b.time_limit || 1, memory: +b.memory || 256, languages: b.languages || [], feedback: b.feedback || "full",
                 max_submissions: +b.max_submissions || 0 };
    var ans = { scoring: a.scoring, checker: a.checker, eps: a.eps, manual: !!a.manual, check_examples: a.check_examples !== false,
                subtasks: (a.subtasks || []).map(function (s) { return { name: s.name || "", points: +s.points || 0, deps: s.deps || [], tests: s.tests || [], limits: s.limits || "" }; }),
                solution: a.solution && a.solution.code ? a.solution : null };
    need(body.languages.length, "Разрешите хотя бы один язык программирования");
    need(ans.subtasks.some(function (s) { return s.tests.length; }) || ans.manual || body.examples.length, "Добавьте тесты (или включите ручную проверку)");
    return { body: body, answer: ans };
  };

  /* ---------------- компиляторы (администрирование) ---------------- */
  A.route("compilers", function (box) {
    A.head(box, t("Компиляторы"), t("Языки для задач с кодом. Решения учеников компилируются и запускаются на этом компьютере."));
    return api("GET", "/api/compilers?versions=1", null, { timeout: 60000 }).then(function (C) {
      var admin = A.isAdmin();
      var edits = {};
      var HINT = {
        fpc: "Бесплатно: freepascal.org (установщик для Windows) или Lazarus. Обычно C:\\FPC\\3.2.2\\bin\\i386-win32\\fpc.exe",
        pabc: "Бесплатно: pascalabc.net. Нужен pabcnetcclear.exe из папки PascalABC.NET и .NET Framework 4.x.",
        py: "Если Python не установлен, используется встроенный Python 3.8 (запасной вариант, медленнее при запуске). Установщик: python.org.",
        cpp: "Компилятор g++ версии 10 и новее для C++20: MinGW-w64 (winlibs.com, MSYS2) или Code::Blocks / Dev-C++ (с ними — c++2a)."
      };
      C.langs.forEach(function (L) {
        var path = h("input", { type: "text", style: { width: "100%" }, placeholder: L.path || t("не найден"), disabled: !admin || null });
        path.value = L.custom || "";
        var flags = h("input", { type: "text", style: { width: "100%" }, placeholder: L.default_flags, disabled: !admin || null });
        flags.value = L.flags || "";
        var en = A.check(t("Разрешить"), L.enabled !== false || !L.path, null);
        edits[L.id] = { path: path, flags: flags, en: en };
        var out = h("div");
        var st = L.path ? h("span", { class: "pill ok" }, t("найден")) : h("span", { class: "pill bad" }, t("не найден"));
        box.appendChild(h("div", { class: "card" },
          h("div", { class: "bar" }, h("h2", { style: { margin: 0 } }, L.name), st, h("div", { class: "sp" }),
            h("button", { class: "sm", onclick: function () {
              out.innerHTML = "";
              out.appendChild(h("div", { class: "muted" }, t("Компиляция и запуск…")));
              api("POST", "/api/compilers/test", { lang: L.id }, { timeout: 120000 }).then(function (r) {
                out.innerHTML = "";
                out.appendChild(h("div", null, h("b", { class: r.verdict === "OK" ? "ok" : "bad" }, r.verdict === "OK" ? t("Работает") : t(ST.VERDICT[r.verdict] || r.name)),
                  " · " + ST.tf("{0} с", String(r.seconds).replace(".", ","))));
                if (r.compile) out.appendChild(h("pre", { class: "io" + (r.verdict === "OK" ? "" : " err") }, r.compile));
              }).catch(function (e) { out.innerHTML = ""; A.err(e); });
            } }, t("Проверить"))),
          h("div", { class: "muted small" }, L.path ? (L.path === "builtin" ? t("Встроенный Python") : L.path) + (L.version ? " · " + L.version : "") : t(HINT[L.id])),
          L.path ? h("div", { class: "muted small" }, t(HINT[L.id])) : null,
          admin ? h("div", { class: "form", style: { marginTop: "8px" } },
            A.field(t("Путь вручную (пусто — найти автоматически)"), path, "wide"),
            A.field(t("Ключи компиляции"), flags, "wide"), en) : null,
          L.candidates.length > 1 && admin ? h("div", { class: "muted small" }, t("Найдено также:") + " ", L.candidates.map(function (c) {
            return h("a", { href: "javascript:void 0", style: { marginRight: "10px" }, onclick: function () { path.value = c; } }, c === "builtin" ? t("встроенный") : c);
          })) : null, out));
      });
      if (admin) {
        var wk = h("input", { type: "number", min: 1, max: 8, style: { width: "80px" } });
        wk.value = C.workers;
        box.appendChild(h("div", { class: "card" }, h("div", { class: "form" }, A.field(t("Одновременно проверяемых посылок"), wk)),
          h("p", { class: "muted small" }, t("Больше — быстрее очередь на уроке, но выше нагрузка на компьютер. Обычно 2–4.")),
          h("button", { class: "pri", onclick: function () {
            var langs = {};
            Object.keys(edits).forEach(function (k) {
              langs[k] = { path: edits[k].path.value, flags: edits[k].flags.value, enabled: edits[k].en.querySelector("input").checked };
            });
            api("PUT", "/api/compilers", { langs: langs, workers: +wk.value || 2 }).then(function () { ST.toast(t("Сохранено")); A.render(); }).catch(A.err);
          } }, t("Сохранить"))));
        box.appendChild(h("div", { class: "infobox" }, t("Решения учеников запускаются с ограничением времени, памяти и числа процессов, без окон и без доступа к рабочему столу. Отдельной «песочницы» для файлов нет: используйте для сервера SchoolTest учётную запись Windows без прав администратора.")));
      }
    });
  });
})();
