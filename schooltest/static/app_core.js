/* SchoolTest — интерфейс учителя: каркас, навигация, общие элементы, редактор формул */
"use strict";
var A = window.A = { routes: {}, me: null };
(function () {
  var h = ST.h, t = ST.t, api = ST.api;

  /* ---------------- названия по типу организации ---------------- */
  var TERMS = {
    school: {
      teacher: "Учитель", teachers: "Учителя", student: "Ученик", students: "Ученики", class: "Класс", classes: "Классы",
      class_gen: "класса", in_class: "в классе", choose_class: "Выберите класс", new_class: "Новый класс",
      no_classes: "Классов пока нет", students_of: "Ученики класса", student_gen: "ученика", students_gen: "учеников",
      add_student: "Добавить ученика", history: "История ученика", class_results: "Результаты класса"
    },
    vuz: {
      teacher: "Преподаватель", teachers: "Преподаватели", student: "Студент", students: "Студенты", class: "Группа", classes: "Группы",
      class_gen: "группы", in_class: "в группе", choose_class: "Выберите группу", new_class: "Новая группа",
      no_classes: "Групп пока нет", students_of: "Студенты группы", student_gen: "студента", students_gen: "студентов",
      add_student: "Добавить студента", history: "История студента", class_results: "Результаты группы"
    },
    enterprise: {
      teacher: "Ответственное лицо", teachers: "Ответственные лица", student: "Работник", students: "Работники",
      class: "Подразделение", classes: "Подразделения", class_gen: "подразделения", in_class: "в подразделении",
      choose_class: "Выберите подразделение", new_class: "Новое подразделение", no_classes: "Подразделений пока нет",
      students_of: "Работники подразделения", student_gen: "работника", students_gen: "работников",
      add_student: "Добавить работника", history: "История работника", class_results: "Результаты подразделения"
    }
  };
  A.N = function (k) {
    var org = (A.me && A.me.settings.org_type) || "school";
    return t((TERMS[org] || TERMS.school)[k] || k);
  };
  A.isSchool = function () { return ((A.me && A.me.settings.org_type) || "school") === "school"; };
  A.isEnterprise = function () { return A.me && A.me.settings.org_type === "enterprise"; };
  A.isAdmin = function () { return A.me && A.me.user.role === "admin"; };
  A.isPsy = function () { return A.me && (A.me.user.role === "psychologist" || A.me.user.role === "admin"); };
  /* учебный год: выбранный в боковой панели (по умолчанию — текущий) */
  A.yearId = function () {
    var v = null;
    try { v = +localStorage.getItem("st_year"); } catch (e) {}
    if (v && A.me.years.some(function (y) { return y.id === v; })) return v;
    return A.me.current_year;
  };
  A.year = function () { var id = A.yearId(); return A.me.years.filter(function (y) { return y.id === id; })[0] || {}; };
  A.isArchiveYear = function () { return A.yearId() !== A.me.current_year; };
  A.yearQ = function (url) { return url + (url.indexOf("?") >= 0 ? "&" : "?") + "year_id=" + A.yearId(); };

  /* ---------------- навигация ---------------- */
  A.route = function (name, fn) { A.routes[name] = fn; };
  A.go = function (hash) { if (location.hash === hash) render(); else location.hash = hash; };
  function parseHash() {
    var raw = location.hash.replace(/^#\/?/, "");
    var q = {}, i = raw.indexOf("?");
    if (i >= 0) {
      raw.slice(i + 1).split("&").forEach(function (p) {
        var kv = p.split("=");
        if (kv[0]) q[decodeURIComponent(kv[0])] = decodeURIComponent(kv[1] || "");
      });
      raw = raw.slice(0, i);
    }
    var parts = raw.split("/").filter(Boolean);
    return { name: parts[0] || "tests", args: parts.slice(1), q: q };
  }
  var MAIN = null, SIDE = null, cleanup = [];
  A.onLeave = function (fn) { cleanup.push(fn); };

  function render() {
    cleanup.forEach(function (f) { try { f(); } catch (e) {} });
    cleanup = [];
    if (!A.me) return;
    var r = parseHash();
    if (A.isAdmin() && !A.me.settings.org_type && r.name !== "admin") { location.hash = "#/admin"; return; }
    drawSide(r.name);
    MAIN.innerHTML = "";
    MAIN.appendChild(h("button", { class: "menu-btn", onclick: function () { SIDE.classList.toggle("open"); } }, "☰ " + t("Меню")));
    var fn = A.routes[r.name] || A.routes.tests;
    var box = h("div");
    if (A.isArchiveYear() && ["classes", "runs", "psy", "student", "psyres"].indexOf(r.name) >= 0)
      MAIN.appendChild(h("div", { class: "year-arch" }, ST.tf("Просмотр учебного года {0} (архив). Текущий год выбирается в левой панели.", A.year().name || "")));
    if (A.isAdmin() && A.updateInfo && A.updateInfo.newer && r.name === "tests")
      MAIN.appendChild(h("div", { class: "upd-banner" }, ST.tf("Доступна новая версия SchoolTest {0}.", A.updateInfo.latest), " ",
        h("a", { href: A.updateInfo.url, target: "_blank", rel: "noopener" }, t("Скачать на GitHub"))));
    MAIN.appendChild(box);
    SIDE.classList.remove("open");
    try {
      var p = fn(box, r.args, r.q);
      if (p && p.catch) p.catch(function (e) { box.appendChild(A.errorBox(e)); });
    } catch (e) {
      box.appendChild(A.errorBox(e));
      if (window.console) console.error(e);
    }
    window.scrollTo(0, 0);
  }
  A.render = render;
  A.errorBox = function (e) { return h("div", { class: "warnbox" }, (e && e.message) || String(e)); };

  function drawSide(cur) {
    var nav = h("nav", { class: "nav" });
    function link(name, text, hash) {
      nav.appendChild(h("a", { href: hash || "#/" + name, class: cur === name || (name === "tests" && cur === "test") ||
        (name === "runs" && (cur === "run" || cur === "attempt")) || (name === "classes" && cur === "student") ||
        (name === "psy" && (cur === "psyrun" || cur === "psyres" || cur === "psymethod" || cur === "psystudent")) ? "on" : null }, text));
    }
    nav.appendChild(h("div", { class: "grp" }, t("Работа")));
    link("tests", t("Тесты"));
    link("runs", t("Проведение и результаты"));
    link("classes", A.N("classes"));
    if (A.isPsy() && A.isSchool()) {
      nav.appendChild(h("div", { class: "grp" }, t("Психологическая служба")));
      link("psy", t("Психодиагностика"));
    }
    if (A.isAdmin()) {
      nav.appendChild(h("div", { class: "grp" }, t("Администрирование")));
      link("admin", t("Настройки"));
      link("users", t("Пользователи"));
      link("years", t("Учебные годы"));
      link("compilers", t("Компиляторы"));
      link("backup", t("Резервные копии"));
      link("audit", t("Журнал действий"));
    } else link("compilers", t("Компиляторы"));
    if (!A.isAdmin()) link("backup", t("Резервные копии"));
    nav.appendChild(h("div", { class: "grp" }, t("Справка")));
    link("help", t("Как пользоваться"));
    link("about", t("О программе"));
    var lang = h("select", { "aria-label": "Мова / Язык", onchange: function () { ST.setLang(lang.value); render(); } },
      h("option", { value: "ru" }, "Русский"), h("option", { value: "be" }, "Беларуская"));
    lang.value = ST.lang;
    SIDE.innerHTML = "";
    SIDE.appendChild(h("div", { class: "brand" }, h("img", { src: "/icon.svg", alt: "" }),
      h("div", null, h("b", null, "SchoolTest"), h("small", null, A.me.settings.school_name || t("Тестирование в локальной сети")))));
    if (A.me.years.length > 1) {
      var ysel = h("select", { class: "yearsel", "aria-label": t("Учебный год"), onchange: function () {
        try { localStorage.setItem("st_year", ysel.value); } catch (e) {}
        render();
      } }, A.me.years.slice().reverse().map(function (y) {
        return h("option", { value: y.id }, y.name + (y.current ? " (" + t("текущий") + ")" : ""));
      }));
      ysel.value = String(A.yearId());
      SIDE.appendChild(h("div", { class: "yearsel-wrap" }, h("div", { class: "muted small" }, t("Учебный год")), ysel));
    }
    SIDE.appendChild(nav);
    SIDE.appendChild(h("div", { class: "who" },
      h("div", null, A.me.user.full_name || A.me.user.login),
      h("div", null, h("a", { href: "#/password" }, t("Сменить пароль")), " · ",
        h("a", { href: "#", onclick: function (e) { e.preventDefault(); logout(); } }, t("Выйти"))),
      h("div", { style: { marginTop: "6px" } }, lang)));
  }

  /* ---------------- вход ---------------- */
  function logout() {
    api("POST", "/api/logout", {}).then(function () { A.me = null; showLogin(); });
  }
  function showLogin(msg) {
    var app = document.getElementById("app");
    var l = h("input", { type: "text", autocomplete: "username", "aria-label": t("Логин") });
    var p = h("input", { type: "password", autocomplete: "current-password", "aria-label": t("Пароль") });
    var err = h("div", { class: "bad", role: "alert", style: { minHeight: "20px", marginTop: "8px" } }, msg || "");
    var btn = h("button", { class: "pri", type: "submit", style: { width: "100%", marginTop: "12px", padding: "10px" } }, t("Войти"));
    var form = h("form", { class: "card", style: { maxWidth: "360px", margin: "12vh auto 0", padding: "26px" }, onsubmit: function (e) {
      e.preventDefault();
      btn.disabled = true;
      api("POST", "/api/login", { login: l.value, password: p.value }).then(boot).catch(function (e2) {
        err.textContent = e2.message; btn.disabled = false;
      });
    } },
      h("div", { style: { display: "flex", alignItems: "center", gap: "10px", marginBottom: "16px" } },
        h("img", { src: "/icon.svg", alt: "", style: { width: "40px" } }),
        h("div", null, h("h1", { style: { margin: 0 } }, "SchoolTest"), h("div", { class: "muted" }, t("Вход для учителя и администратора")))),
      h("label", { class: "f" }, t("Логин"), l), h("div", { style: { height: "10px" } }),
      h("label", { class: "f" }, t("Пароль"), p), err, btn,
      h("p", { class: "muted small", style: { marginTop: "16px" } }, t("Ученики входят без пароля: по адресу программы без /teacher и коду теста."),
        " ", h("a", { href: "/" }, t("Страница ученика"))));
    app.innerHTML = "";
    app.appendChild(form);
    setTimeout(function () { l.focus(); }, 30);
  }
  function mustChange() {
    var app = document.getElementById("app");
    var o = h("input", { type: "password", autocomplete: "current-password" });
    var n1 = h("input", { type: "password", autocomplete: "new-password" });
    var n2 = h("input", { type: "password", autocomplete: "new-password" });
    var err = h("div", { class: "bad", role: "alert", style: { minHeight: "20px", marginTop: "8px" } });
    var form = h("form", { class: "card", style: { maxWidth: "400px", margin: "10vh auto 0", padding: "26px" }, onsubmit: function (e) {
      e.preventDefault();
      if (n1.value !== n2.value) { err.textContent = t("Пароли не совпадают"); return; }
      api("POST", "/api/me/password", { old: o.value, new: n1.value }).then(boot).catch(function (e2) { err.textContent = e2.message; });
    } },
      h("h1", null, t("Смена пароля")),
      h("p", { class: "muted" }, t("Перед началом работы задайте собственный пароль (не короче 6 символов).")),
      h("label", { class: "f" }, t("Текущий пароль"), o), h("div", { style: { height: "8px" } }),
      h("label", { class: "f" }, t("Новый пароль"), n1), h("div", { style: { height: "8px" } }),
      h("label", { class: "f" }, t("Повторите новый пароль"), n2), err,
      h("button", { class: "pri", type: "submit", style: { marginTop: "12px" } }, t("Сохранить")));
    app.innerHTML = "";
    app.appendChild(form);
  }
  function boot() {
    return api("GET", "/api/me").then(function (me) {
      A.me = me;
      var saved = ST.savedLang();
      ST.setLang(saved || me.settings.lang || "ru");
      if (me.user.must_change) return mustChange();
      var app = document.getElementById("app");
      app.innerHTML = "";
      SIDE = h("aside", { class: "side" });
      MAIN = h("main", { class: "main" });
      app.appendChild(h("div", { class: "shell" }, SIDE, MAIN));
      render();
      if (me.user.role === "admin") api("GET", "/api/update_check", null, { timeout: 15000 }).then(function (u) {
        A.updateInfo = u;
        if (u && u.newer && parseHash().name === "tests") render();
      }).catch(function () {});
    }).catch(function (e) {
      if (e.status === 401) showLogin();
      else if (e.status === 403 && /парол/i.test(e.message)) mustChange();
      else showLogin(e.message);
    });
  }
  A.reloadMe = function () { return api("GET", "/api/me").then(function (me) { A.me = me; }); };
  window.addEventListener("hashchange", render);

  /* ---------------- общие элементы ---------------- */
  A.head = function (box, title, sub, acts) {
    var el = h("div", { class: "pagehead" }, h("div", null, h("h1", null, title), sub ? h("div", { class: "sub" }, sub) : null),
      acts && acts.length ? h("div", { class: "acts" }, acts) : null);
    box.appendChild(el);
    return el;
  };
  A.tabs = function (items, cur) {
    return h("div", { class: "tabs", role: "tablist" }, items.map(function (it) {
      return h("a", { href: it[1], class: it[0] === cur ? "on" : null, role: "tab" }, it[2]);
    }));
  };
  A.field = function (label, input, cls) { return h("label", { class: "f" + (cls ? " " + cls : "") }, label, input); };
  A.check = function (label, checked, onchange, hint) {
    var i = h("input", { type: "checkbox" });
    i.checked = !!checked;
    if (onchange) i.addEventListener("change", function () { onchange(i.checked); });
    return h("label", { class: "chk" }, i, h("span", null, label, hint ? h("div", { class: "muted small" }, hint) : null));
  };
  A.select = function (options, value, onchange) {
    var s = h("select");
    options.forEach(function (o) { s.appendChild(h("option", { value: o[0] }, o[1])); });
    if (value != null) s.value = String(value);
    if (onchange) s.addEventListener("change", function () { onchange(s.value); });
    return s;
  };
  A.table = function (headers, rows, opts) {
    opts = opts || {};
    if (!rows.length) return h("div", { class: "empty" }, opts.empty || t("Нет данных"));
    var tb = h("tbody");
    rows.forEach(function (r) { tb.appendChild(r instanceof Node ? r : h("tr", null, r.map(function (c) { return h("td", null, c); }))); });
    return h("div", { class: "tw" }, h("table", { class: "t" },
      h("thead", null, h("tr", null, headers.map(function (x) { return h("th", { class: x && x.cls || null }, x && x.text != null ? x.text : x); }))), tb));
  };
  A.num = function (v) {
    if (v == null || v === "") return "";
    v = Math.round(Number(v) * 100) / 100;
    return String(v).replace(".", ",");
  };
  A.date = function (ts, withTime) {
    if (!ts) return "";
    var d = typeof ts === "number" ? new Date(ts * 1000) : new Date(String(ts).replace(" ", "T"));
    var p = function (n) { return (n < 10 ? "0" : "") + n; };
    return p(d.getDate()) + "." + p(d.getMonth() + 1) + "." + d.getFullYear() + (withTime ? " " + p(d.getHours()) + ":" + p(d.getMinutes()) : "");
  };
  A.err = function (e) { ST.toast((e && e.message) || String(e), true); };
  A.prompt = function (title, label, value, ok) {
    var inp = h("input", { type: "text", style: { width: "100%" } });
    inp.value = value || "";
    return ST.modal(title, A.field(label, inp), [{ text: t("Отмена"), value: null }, { text: ok || t("Сохранить"), value: 1, cls: "pri" }])
      .then(function (v) { return v ? inp.value.trim() : null; });
  };
  A.showPassword = function (title, login, pw) {
    return ST.modal(title, h("div", null, h("p", null, t("Логин:") + " ", h("b", null, login)),
      h("p", null, t("Временный пароль:") + " ", h("code", { style: { fontSize: "20px", background: "#f2f5f5", padding: "2px 8px" } }, pw)),
      h("p", { class: "muted" }, t("Передайте его пользователю. При первом входе программа попросит сменить пароль."))));
  };

  /* ---------------- печать ---------------- */
  A.printHtml = function (title, html, extraCss) {
    var w = window.open("", "_blank");
    if (!w) { ST.toast(t("Разрешите всплывающие окна для печати"), true); return; }
    w.document.write("<!DOCTYPE html><html><head><meta charset='utf-8'><title>" + ST.esc(title) + "</title>" +
      "<link rel='stylesheet' href='/katex/katex.min.css'><style>" +
      "body{font:13px/1.45 'Times New Roman',serif;color:#000;margin:18mm 14mm}h1{font-size:18px;margin:0 0 4px}h2{font-size:15px}" +
      "table{border-collapse:collapse;width:100%}th,td{border:1px solid #444;padding:3px 6px;text-align:left;vertical-align:top}" +
      "th{background:#eee}.sub{color:#333;margin-bottom:10px}.pb{page-break-after:always}" +
      "@media print{body{margin:0}.noprint{display:none}}" + (extraCss || "") + "</style></head><body>" +
      "<div class='noprint' style='margin-bottom:12px'><button onclick='window.print()'>" + ST.esc(t("Печать")) + "</button></div>" +
      html + "<script src='/katex/katex.min.js'></script><script src='/katex/auto-render.min.js'></script>" +
      "<script>window.onload=function(){try{renderMathInElement(document.body,{delimiters:[{left:'$$',right:'$$',display:true}," +
      "{left:'\\\\[',right:'\\\\]',display:true},{left:'\\\\(',right:'\\\\)',display:false}],throwOnError:false})}catch(e){}}</" + "script></body></html>");
    w.document.close();
  };
  A.printReport = function (rep) {
    var html = "<h1>" + ST.esc(rep.title) + "</h1><div class='sub'>" + ST.esc(rep.subtitle || "") + "</div><table><thead><tr>" +
      rep.headers.map(function (x) { return "<th>" + ST.esc(x) + "</th>"; }).join("") + "</tr></thead><tbody>" +
      rep.rows.map(function (r) { return "<tr>" + r.map(function (c) { return "<td>" + ST.esc(c) + "</td>"; }).join("") + "</tr>"; }).join("") +
      "</tbody></table>";
    A.printHtml(rep.title, html);
  };
  A.reportView = function (rep, xlsxUrl) {
    var box = h("div");
    box.appendChild(h("div", { class: "bar" }, h("div", { class: "muted" }, rep.subtitle || ""), h("div", { class: "sp" }),
      xlsxUrl ? h("button", { onclick: function () { ST.download(xlsxUrl); } }, "⬇ Excel") : null,
      h("button", { onclick: function () { A.printReport(rep); } }, "🖶 " + t("Печать"))));
    box.appendChild(A.table(rep.headers, rep.rows.map(function (r) {
      return h("tr", null, r.map(function (c, i) { return h("td", { class: i === 0 ? "num" : null, html: i === 1 ? ST.fmt(c) : null }, i === 1 ? null : c); }));
    })));
    ST.math(box);
    return box;
  };

  /* ---------------- редактор формул ---------------- */
  var PALETTE = [
    ["Основное", [["a/b", "\\frac{#}{}", "\\frac{a}{b}"], ["√", "\\sqrt{#}", "\\sqrt{x}"], ["ⁿ√", "\\sqrt[n]{#}", "\\sqrt[n]{x}"],
      ["x²", "^{2}", "x^{2}"], ["xⁿ", "^{#}", "x^{n}"], ["xₙ", "_{#}", "x_{n}"], ["( )", "\\left( # \\right)", "\\left(x\\right)"],
      ["|x|", "\\left| # \\right|", "\\left|x\\right|"], ["·", "\\cdot ", "\\cdot"], ["×", "\\times ", "\\times"], ["÷", "\\div ", "\\div"],
      ["±", "\\pm ", "\\pm"], ["°", "^{\\circ}", "90^{\\circ}"]]],
    ["Сравнение", [["≠", "\\neq ", "\\neq"], ["≈", "\\approx ", "\\approx"], ["≤", "\\leq ", "\\leq"], ["≥", "\\geq ", "\\geq"],
      ["<", "< ", "<"], [">", "> ", ">"], ["∞", "\\infty ", "\\infty"], ["→", "\\to ", "\\to"], ["⇒", "\\Rightarrow ", "\\Rightarrow"],
      ["⇔", "\\Leftrightarrow ", "\\Leftrightarrow"]]],
    ["Буквы", [["α", "\\alpha ", "\\alpha"], ["β", "\\beta ", "\\beta"], ["γ", "\\gamma ", "\\gamma"], ["Δ", "\\Delta ", "\\Delta"],
      ["π", "\\pi ", "\\pi"], ["φ", "\\varphi ", "\\varphi"], ["λ", "\\lambda ", "\\lambda"], ["ω", "\\omega ", "\\omega"], ["μ", "\\mu ", "\\mu"],
      ["ρ", "\\rho ", "\\rho"], ["Ω", "\\Omega ", "\\Omega"]]],
    ["Функции", [["sin", "\\sin ", "\\sin x"], ["cos", "\\cos ", "\\cos x"], ["tg", "\\operatorname{tg} ", "\\operatorname{tg} x"],
      ["ctg", "\\operatorname{ctg} ", "\\operatorname{ctg} x"], ["log", "\\log_{#}", "\\log_{a} b"], ["lg", "\\lg ", "\\lg x"], ["ln", "\\ln ", "\\ln x"],
      ["lim", "\\lim_{x \\to #}", "\\lim_{x\\to 0}"], ["Σ", "\\sum_{i=1}^{n} ", "\\sum_{i=1}^{n}"], ["∫", "\\int_{a}^{b} ", "\\int_{a}^{b}"]]],
    ["Геометрия и множества", [["∠", "\\angle ", "\\angle A"], ["△", "\\triangle ", "\\triangle ABC"], ["⊥", "\\perp ", "\\perp"],
      ["∥", "\\parallel ", "\\parallel"], ["вектор", "\\vec{#}", "\\vec{a}"], ["AB̅", "\\overline{#}", "\\overline{AB}"], ["∈", "\\in ", "\\in"],
      ["∉", "\\notin ", "\\notin"], ["∪", "\\cup ", "\\cup"], ["∩", "\\cap ", "\\cap"], ["ℝ", "\\mathbb{R}", "\\mathbb{R}"], ["ℕ", "\\mathbb{N}", "\\mathbb{N}"]]],
    ["Конструкции", [["система", "\\begin{cases} # \\\\  \\end{cases}", "\\begin{cases}x+y=1\\\\x-y=2\\end{cases}"],
      ["матрица", "\\begin{pmatrix} # & \\\\  & \\end{pmatrix}", "\\begin{pmatrix}a&b\\\\c&d\\end{pmatrix}"],
      ["хим. →", "\\xrightarrow{#}", "\\xrightarrow{t}"], ["текст", "\\text{#}", "\\text{м/с}"]]]
  ];
  A.formulaDialog = function (initial) {
    var inp = h("textarea", { rows: 3, spellcheck: "false", style: { fontFamily: "Consolas,monospace", fontSize: "15px" },
                              "aria-label": t("Формула (LaTeX)") });
    inp.value = initial || "";
    var prev = h("div", { class: "fx-prev" });
    var err = h("div", { class: "fx-err" });
    var disp = h("input", { type: "checkbox" });
    function draw() {
      err.textContent = "";
      if (!inp.value.trim()) { prev.textContent = t("Здесь появится формула"); prev.classList.add("muted"); return; }
      prev.classList.remove("muted");
      try {
        window.katex.render(inp.value, prev, { throwOnError: true, displayMode: true });
      } catch (e) {
        err.textContent = t("Ошибка в формуле:") + " " + String(e.message || e).replace(/^KaTeX parse error: /, "");
      }
    }
    function ins(code) {
      var s = inp.selectionStart, e = inp.selectionEnd, v = inp.value, sel = v.slice(s, e);
      var k = code.indexOf("#");
      var text = k >= 0 ? code.slice(0, k) + sel + code.slice(k + 1) : code + sel;
      inp.value = v.slice(0, s) + text + v.slice(e);
      var pos = s + (k >= 0 ? k + sel.length : text.length);
      inp.focus();
      inp.setSelectionRange(pos, pos);
      draw();
    }
    var pal = h("div", { class: "fx-pal" });
    PALETTE.forEach(function (g) {
      pal.appendChild(h("div", { class: "grp" }, t(g[0])));
      g[1].forEach(function (b) {
        var btn = h("button", { type: "button", title: b[1].replace("#", "…"), onclick: function () { ins(b[1]); } });
        try { window.katex.render(b[2], btn, { throwOnError: false }); } catch (e) { btn.textContent = b[0]; }
        pal.appendChild(btn);
      });
    });
    inp.addEventListener("input", draw);
    draw();
    var body = h("div", null,
      h("p", { class: "muted small", style: { marginTop: 0 } }, t("Нажимайте кнопки или пишите формулу в записи LaTeX. Предпросмотр обновляется сразу.")),
      pal, A.field(t("Формула"), inp), h("div", { style: { height: "8px" } }), prev, err,
      h("label", { class: "chk" }, disp, h("span", null, t("Отдельной строкой по центру"))));
    return ST.modal(t("Формула"), body, [{ text: t("Отмена"), value: null },
      { text: t("Вставить"), value: 1, cls: "pri", check: function () { return inp.value.trim(); } }], true).then(function (v) {
      if (!v) return null;
      var code = inp.value.trim();
      return disp.checked ? "\\[" + code + "\\]" : "\\(" + code + "\\)";
    });
  };
  /* Вставка формулы в поле ввода по месту курсора; если курсор внутри формулы — её правка. */
  A.insertFormula = function (field) {
    var v = field.value, s = field.selectionStart || 0, e = field.selectionEnd || s;
    var re = /\\\(([\s\S]+?)\\\)|\\\[([\s\S]+?)\\\]/g, m, found = null;
    while ((m = re.exec(v))) {
      if (s >= m.index && s <= m.index + m[0].length) { found = m; break; }
    }
    var initial = found ? (found[1] || found[2]) : v.slice(s, e);
    return A.formulaDialog(initial).then(function (code) {
      if (!code) return;
      if (found) { s = found.index; e = found.index + found[0].length; }
      field.value = v.slice(0, s) + code + v.slice(e);
      field.dispatchEvent(new Event("input", { bubbles: true }));
      field.focus();
      var p = s + code.length;
      try { field.setSelectionRange(p, p); } catch (er) {}
    });
  };
  /* Поле с кнопкой формулы и предпросмотром (для вариантов ответа и элементов). */
  A.mathInput = function (value, placeholder, oninput) {
    var inp = h("input", { type: "text", placeholder: placeholder || "" });
    inp.value = value || "";
    var prev = h("div", { class: "mprev hidden" });
    function upd() {
      var has = ST.hasMath(inp.value);
      prev.classList.toggle("hidden", !has);
      if (has) { prev.innerHTML = ST.fmt(inp.value); ST.math(prev); }
    }
    inp.addEventListener("input", function () { upd(); if (oninput) oninput(inp.value); });
    upd();
    var wrap = h("div", { class: "mi-wrap", style: { flex: 1, minWidth: 0 } },
      h("div", { class: "mi" }, inp, h("button", { type: "button", class: "sm", title: t("Формула"), "aria-label": t("Формула"),
        onclick: function () { A.insertFormula(inp); } }, "ƒx")), prev);
    wrap.input = inp;
    return wrap;
  };

  boot();
})();
