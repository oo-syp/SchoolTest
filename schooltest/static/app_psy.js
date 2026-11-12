/* SchoolTest — психологическая служба: методики, обследования, результаты */
"use strict";
(function () {
  var h = ST.h, t = ST.t, api = ST.api;

  function guard() {
    if (!A.isPsy()) { A.go("#/tests"); return false; }
    return true;
  }

  A.route("psy", function (box, args, q) {
    if (!guard()) return;
    var tab = q.tab || "methods";
    A.head(box, t("Психодиагностика"), t("Методики для работы педагога-психолога. Результаты видят только педагоги-психологи и администратор."));
    box.appendChild(A.tabs([["methods", "#/psy", t("Методики")], ["runs", "#/psy?tab=runs", t("Обследования")]], tab));
    var pane = h("div");
    box.appendChild(pane);
    if (tab === "runs") return runsList(pane);
    return api("GET", "/api/psy/methods").then(function (ms) {
      var blocks = [];
      ms.forEach(function (m) { if (blocks.indexOf(m.block) < 0) blocks.push(m.block); });
      blocks.forEach(function (bl) {
        pane.appendChild(h("h2", null, t(bl)));
        var grid = h("div", { class: "mgrid" });
        ms.filter(function (m) { return m.block === bl; }).forEach(function (m) {
          grid.appendChild(h("div", { class: "mcard" }, h("h3", null, m.name), h("div", { class: "muted small" }, m.author),
            h("div", null, h("span", { class: "pill" }, ST.tf("{0} вопр.", m.count)),
              m.kind === "group" ? h("span", { class: "pill" }, t("групповая")) : null,
              m.ask && m.ask.length ? h("span", { class: "pill" }, t("пол и возраст")) : null,
              m.timed ? h("span", { class: "pill" }, t("с ограничением времени")) : null),
            h("div", { class: "small" }, m.purpose), h("div", { class: "muted small" }, m.audience),
            h("div", { class: "acts" }, h("button", { class: "pri sm", onclick: function () { launch(m); } }, "▶ " + t("Провести")),
              h("a", { class: "btn sm", href: "#/psymethod/" + m.id }, t("Описание и ключ")))));
        });
        pane.appendChild(grid);
      });
      pane.appendChild(h("div", { class: "infobox", style: { marginTop: "14px" } },
        h("p", { style: { marginTop: 0 } }, t("Проведение — как обычного теста: учащиеся открывают адрес программы, вводят код и выбирают себя в списке. Вопросы идут по одному, после ответа — сразу следующий. Подсчёт по ключу и интерпретация — автоматически.")),
        h("p", { style: { marginBottom: 0 } }, t("Социометрия — групповая методика: учащийся выбирает одноклассников из списка класса и своих результатов не видит, выводы делаются по классу (социоматрица, статусы, социограмма, индексы). ШТУР-2 идёт по субтестам: перед каждым показывается описание с примерами, время каждого субтеста ограничено, вернуться к пройденному нельзя."))));
    });
  });

  function criteriaPicker(m) {
    var box = h("div", { class: "crit" });
    var list = m.criteria || [];
    var def = m.default_criteria || [];
    var boxes = list.map(function (c, i) {
      var inp = h("input", { type: "checkbox", checked: def.indexOf(i) >= 0 || null });
      box.appendChild(h("label", { class: "crit-row" }, inp,
        h("span", null, c.text, " ",
          h("span", { class: "pill " + (c.sign === "neg" ? "bad" : "ok") }, c.sign === "neg" ? t("отрицательный") : t("положительный")),
          c.note ? h("span", { class: "muted small" }, " — " + c.note) : null)));
      return inp;
    });
    var own = h("textarea", { rows: 2, placeholder: t("Свои вопросы — по одному в строке; начните со знака «−», если выбор отрицательный") });
    box.appendChild(h("label", { class: "f" }, t("Свои вопросы"), own));
    return { el: box, value: function () {
      var out = [];
      boxes.forEach(function (inp, i) { if (inp.checked) out.push({ text: list[i].text, sign: list[i].sign }); });
      String(own.value || "").split("\n").forEach(function (line) {
        line = line.trim();
        if (!line) return;
        var neg = /^[-–—−]/.test(line);
        out.push({ text: line.replace(/^[-–—−]\s*/, ""), sign: neg ? "neg" : "pos" });
      });
      return out;
    } };
  }

  function launch(m) {
    api("GET", A.yearQ("/api/classes")).then(function (classes) {
      if (!classes.length) { ST.toast(A.N("no_classes"), true); return; }
      var cls = A.select(classes.map(function (c) { return [c.id, c.name + " (" + c.students + ")"]; }));
      var show = A.check(t("Показать учащемуся результат с интерпретацией после завершения"), m.show_default === "profile");
      var extra = h("div");
      var form = null, timed = null, about = null, picks = null, crit = null;
      if (m.id === "tsr") {
        about = h("input", { type: "text", maxlength: 200, placeholder: t("Фамилия и инициалы учителя или предмет") });
        extra.appendChild(h("div", { class: "form" }, A.field(t("Анкета об учителе"), about)));
        extra.appendChild(h("p", { class: "muted small" }, t("Этот текст увидят учащиеся: анкета заполняется об одном учителе.")));
      }
      if (m.forms) {
        form = A.select((m.forms || []).map(function (f) { return [f, t("Форма") + " " + f]; }));
        extra.appendChild(h("div", { class: "form" }, A.field(t("Форма теста"), form)));
        timed = A.check(t("Ограничивать время каждого субтеста (54 минуты на весь тест)"), true);
        extra.appendChild(timed);
        extra.appendChild(h("p", { class: "muted small" },
          t("Формы А и Б равноценны: вторую удобно использовать при повторном обследовании. Класс для шкалы оценки берётся из названия класса.")));
      }
      if (m.kind === "group") {
        picks = h("input", { type: "number", min: 1, max: 10, value: 3, style: { width: "90px" } });
        extra.appendChild(h("div", { class: "form" }, A.field(t("Сколько одноклассников выбирать на каждый вопрос"), picks)));
        crit = criteriaPicker(m);
        extra.appendChild(h("h3", null, t("Вопросы (критерии)")));
        extra.appendChild(crit.el);
      }
      ST.modal(ST.tf("Провести: {0}", m.short), h("div", null, h("div", { class: "form" }, A.field(A.N("class"), cls)), show, extra,
        m.ask && m.ask.length ? h("p", { class: "muted small" }, t("Перед началом учащийся укажет пол и возраст — они нужны для сравнения с нормативами.")) : null),
        [{ text: t("Отмена"), value: null }, { text: t("Начать"), value: 1, cls: "pri",
          check: function () {
            if (about && !String(about.value).trim()) { ST.toast(t("Укажите, о каком учителе заполняется анкета"), true); return false; }
            if (crit && !crit.value().length) { ST.toast(t("Отметьте хотя бы один вопрос"), true); return false; }
            return true;
          } }]).then(function (v) {
        if (!v) return;
        var body = { method: m.id, class_id: +cls.value, show_result: show.querySelector("input").checked ? "profile" : "none" };
        if (about) body.about = String(about.value).trim();
        if (form) body.form = form.value;
        if (timed) body.timed = !!timed.querySelector("input").checked;
        if (picks) body.picks = Math.max(1, Math.min(10, +picks.value || 3));
        if (crit) body.criteria = crit.value();
        api("POST", "/api/psy/runs", body).then(function (r) { A.go("#/psyrun/" + r.id); }).catch(A.err);
      });
    }).catch(A.err);
  }

  function runsList(pane) {
    return api("GET", A.yearQ("/api/runs?kind=psy")).then(function (runs) {
      pane.appendChild(A.table([t("Дата"), t("Методика"), A.N("class"), t("Прошли"), t("Статус"), ""], runs.map(function (r) {
        return h("tr", null, h("td", null, A.date(r.created_at, true)), h("td", null, h("a", { href: "#/psyrun/" + r.id + "/results" }, r.title)),
          h("td", null, r.class_name), h("td", { class: "num" }, String(r.finished || 0)),
          h("td", null, r.status === "open" ? h("span", { class: "pill ok" }, t("идёт") + " · " + r.code) : h("span", { class: "pill" }, t("завершено"))),
          h("td", { class: "acts" }, h("a", { class: "btn sm", href: "#/psyrun/" + r.id + (r.status === "open" ? "" : "/results") }, t("Открыть"))));
      }), { empty: t("Обследований пока нет") }));
    });
  }

  /* ---------------- описание методики ---------------- */
  function qText(m, qq) {
    if (m.id === "ddo") return "а) " + qq.options[0].text + "; б) " + qq.options[1].text;
    var txt = (qq.text || "").replace(/^Хотелось бы Вам\? Нравится ли Вам\? /, "");
    if (m.id === "shtur" && qq.options && qq.options.length && qq.section !== 7 && qq.section !== 8) {
      txt += (txt ? " " : "") + qq.options.map(function (o, i) { return "абвгд"[i] + ") " + o.text; }).join(" ");
    }
    if (m.id === "shtur" && (qq.section === 7 || qq.section === 8)) txt = t("Задание с рисунком");
    return txt;
  }

  A.route("psymethod", function (box, args, q) {
    if (!guard()) return;
    var form = q.form || "";
    return api("GET", "/api/psy/methods/" + args[0] + (form ? "?form=" + encodeURIComponent(form) : "")).then(function (m) {
      A.head(box, m.name, m.author, [h("button", { class: "pri", onclick: function () { launch(m); } }, "▶ " + t("Провести")),
        h("button", { onclick: function () { printBlank(m); } }, "🖶 " + t("Бланк вопросов")), h("a", { class: "btn", href: "#/psy" }, "← " + t("Методики"))]);
      box.appendChild(h("div", { class: "card" },
        h("p", null, h("b", null, t("Назначение. ")), m.purpose), h("p", null, h("b", null, t("Для кого. ")), m.audience),
        h("p", null, h("b", null, t("Инструкция. ")), m.instruction), h("p", null, h("b", null, t("Ответы. ")), m.answers),
        m.note ? h("div", { class: "warnbox" }, m.note) : null));
      if (m.forms) {
        box.appendChild(h("div", { class: "bar" }, h("span", { class: "muted" }, t("Форма теста")), m.forms.map(function (f) {
          return h("a", { class: "btn sm" + (f === m.form ? " pri" : ""), href: "#/psymethod/" + m.id + "?form=" + encodeURIComponent(f) }, f);
        })));
      }
      if (m.sections) {
        box.appendChild(h("div", { class: "card" }, h("h2", { style: { marginTop: 0 } }, t("Субтесты")),
          A.table(["№", t("Субтест"), t("Задания"), t("Время, мин")], m.sections.map(function (s) {
            return [s.num, s.title.replace(/^Субтест \d+\. /, ""), s["from"] + "–" + s.to, s.minutes];
          }))));
      }
      if (m.criteria) {
        box.appendChild(h("div", { class: "card" }, h("h2", { style: { marginTop: 0 } }, t("Готовые вопросы (критерии)")),
          A.table([t("Вопрос"), t("Знак")], m.criteria.map(function (c) {
            return [c.text + (c.note ? " — " + c.note : ""), c.sign === "neg" ? t("отрицательный") : t("положительный")];
          }))));
      }
      box.appendChild(h("div", { class: "card" }, h("h2", { style: { marginTop: 0 } }, t("Ключ")),
        A.table([t("Шкала"), t("Вопросы")], m.key.map(function (k) { return [k.name, k.items]; }))));
      box.appendChild(h("details", { class: "card" }, h("summary", null, h("b", null, ST.tf("Вопросы ({0})", m.questions.length))),
        h("ol", null, m.questions.map(function (qq) { return h("li", null, qText(m, qq)); }))));
    });
  });
  function printBlank(m) {
    var rows = m.questions.map(function (qq, i) {
      var txt = qText(m, qq);
      var ans = (qq.options || []).map(function (o) { return "☐ " + ST.esc(o.text.replace(/\s*\(.*\)$/, "")); }).join("&nbsp;&nbsp; ");
      if (m.id === "ddo") ans = "☐ а &nbsp; ☐ б";
      if (m.id === "shtur" && qq.options && qq.options.length) ans = qq.options.map(function (o, k) { return "☐ " + "абвгд"[k]; }).join("&nbsp; ");
      if (!qq.options || !qq.options.length) ans = "____________________";
      if (m.kind === "group") ans = "1. __________ 2. __________ 3. __________";
      return "<tr><td>" + (i + 1) + "</td><td>" + (m.id === "ddo" ? txt : ST.esc(txt)) + "</td><td style='white-space:nowrap'>" + ans + "</td></tr>";
    }).join("");
    A.printHtml(m.name, "<h1>" + ST.esc(m.name) + "</h1><div class='sub'>" + ST.esc(m.author) + "</div>" +
      "<p>" + t("Фамилия, имя") + " ______________________________ " + A.N("class") + " ________ " + t("Дата") + " ___________</p>" +
      "<p><i>" + ST.esc(m.instruction) + "</i></p><table><tbody>" + rows + "</tbody></table>");
  }

  /* ---------------- обследование: наблюдение и результаты ---------------- */
  A.route("psyrun", function (box, args) {
    if (!guard()) return;
    var id = +args[0], tab = args[1] || "monitor";
    return api("GET", "/api/runs/" + id).then(function (R) {
      var acts = [];
      if (R.status === "open") acts.push(h("button", { class: "danger", onclick: function () { A.closeRun(R); } }, "■ " + t("Завершить")));
      else acts.push(h("button", { onclick: function () {
        api("POST", "/api/runs/" + R.id + "/reopen", {}).then(A.render).catch(A.err);
      } }, t("Открыть снова")));
      acts.push(h("button", { class: "danger ghost", onclick: function () {
        ST.confirm(t("Удалить обследование?"), t("Будут удалены все ответы и результаты учащихся."), t("Удалить"), true).then(function (ok) {
          if (ok) api("DELETE", "/api/runs/" + R.id).then(function () { A.go("#/psy?tab=runs"); }).catch(A.err);
        });
      } }, t("Удалить")));
      A.head(box, R.title, R.class_name + " · " + A.date(R.created_at, true), acts);
      box.appendChild(A.tabs([["monitor", "#/psyrun/" + id, t("Наблюдение")], ["results", "#/psyrun/" + id + "/results", t("Результаты")]], tab));
      var pane = h("div");
      box.appendChild(pane);
      if (tab === "monitor") A.runMonitor(pane, R);
      else return results(pane, R);
    });
  });

  /* ---------------- социометрия: матрица, индексы, социограмма ---------------- */
  var NS = "http://www.w3.org/2000/svg";
  function sv(tag, attrs, text) {
    var e = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    if (text != null) e.textContent = text;
    return e;
  }

  function sociogram(so) {
    var ring = { star: 0, pref: 1, acc: 2, half: 3, rej: 3 };
    var byRing = [[], [], [], []];
    so.people.forEach(function (p, i) { byRing[ring[p.status]].push(i); });
    var S = 640, c = S / 2, R = [0, 92, 175, 258];
    var svg = sv("svg", { viewBox: "0 0 " + S + " " + S, width: "100%", style: "max-width:640px;font-family:inherit",
                          role: "img", "aria-label": t("Социограмма") });
    [92, 175, 258].forEach(function (r) {
      svg.appendChild(sv("circle", { cx: c, cy: c, r: r, fill: "none", stroke: "#dfe6e8", "stroke-dasharray": "4 4" }));
    });
    var pos = {};
    byRing.forEach(function (list, k) {
      var n = list.length;
      list.forEach(function (idx, j) {
        if (k === 0 && n === 1) { pos[idx] = [c, c]; return; }
        var a = -Math.PI / 2 + 2 * Math.PI * j / Math.max(1, n) + (k % 2 ? Math.PI / Math.max(2, n * 2) : 0);
        var r = k === 0 ? 42 : R[k];
        pos[idx] = [c + r * Math.cos(a), c + r * Math.sin(a)];
      });
    });
    (so.pairs_pos || []).forEach(function (pr) {
      var a = pos[pr[0]], b = pos[pr[1]];
      if (a && b) svg.appendChild(sv("line", { x1: a[0], y1: a[1], x2: b[0], y2: b[1], stroke: "#1f7a6d", "stroke-width": 2 }));
    });
    (so.pairs_neg || []).forEach(function (pr) {
      var a = pos[pr[0]], b = pos[pr[1]];
      if (a && b) svg.appendChild(sv("line", { x1: a[0], y1: a[1], x2: b[0], y2: b[1], stroke: "#c0563f",
                                               "stroke-width": 2, "stroke-dasharray": "5 4" }));
    });
    so.people.forEach(function (p, i) {
      var pt = pos[i];
      if (!pt) return;
      var fill = p.status === "star" ? "#1f7a6d" : p.status === "pref" ? "#5aa89c" :
                 p.status === "acc" ? "#c9dcd8" : p.status === "half" ? "#f0e0b8" : "#f0c9c0";
      var dark = p.status === "star" || p.status === "pref";
      svg.appendChild(sv("circle", { cx: pt[0], cy: pt[1], r: 16, fill: fill, stroke: "#4b5560", "stroke-width": 1 }));
      svg.appendChild(sv("text", { x: pt[0], y: pt[1] + 4, "text-anchor": "middle", "font-size": 12,
                                   "font-weight": 600, fill: dark ? "#fff" : "#1d2a33" }, String(p.num)));
    });
    return svg;
  }

  function socioView(pane, so) {
    var ix = so.indices;
    var g = h("div", { class: "card" }, h("h2", { style: { marginTop: 0 } }, t("Показатели класса")),
      A.table([t("Показатель"), t("Значение")], [
        [t("Учащихся в классе"), String(ix.N)],
        [t("Прошли опрос"), ix.done + " " + t("из") + " " + ix.N],
        [t("Положительных выборов"), ix.pos + " (" + String(ix.pct_pos).replace(".", ",") + " %)"],
        [t("Отрицательных выборов"), ix.neg + " (" + String(ix.pct_neg).replace(".", ",") + " %)"],
        [t("Безразличных"), ix.zero + " (" + String(ix.pct_zero).replace(".", ",") + " %)"],
        [t("Взаимных пар «+» / «–»"), ix.pairs_pos + " / " + ix.pairs_neg],
        [t("Индекс сплочённости группы (ИС)"), String(ix.cohesion).replace(".", ",") + " %"],
        [t("Индекс групповой взаимности (ИГВ)"), String(ix.mutuality).replace(".", ",")],
        [t("Имеют взаимный выбор"), String(ix.satisfaction).replace(".", ",") + " %"]]));
    g.appendChild(h("p", { class: "muted small" },
      ST.tf("Сплочённость класса — {0}: доля положительных выборов {1} %.", t(so.cohesion_level), String(ix.pct_pos).replace(".", ","))));
    pane.appendChild(g);

    var st = h("div", { class: "card" }, h("h2", { style: { marginTop: 0 } }, t("Статусные группы")));
    st.appendChild(A.table([t("Статус"), t("Учащихся"), t("Кто"), ""], so.status_order.map(function (s) {
      var who = so.people.filter(function (p) { return p.status === s; });
      return [so.status_names[s] + " — " + so.status_help[s], String(so.counts[s]),
              who.map(function (p) { return p.name; }).join(", "), ""];
    })));
    pane.appendChild(st);

    var sg = h("div", { class: "card" }, h("h2", { style: { marginTop: 0 } }, t("Социограмма")));
    sg.appendChild(sociogram(so));
    sg.appendChild(h("p", { class: "muted small" },
      t("В центре — «звёзды», дальше от центра — предпочитаемые, принятые и отвергнутые. Сплошная линия — взаимная симпатия, пунктир — взаимная антипатия. Номер в кружке — номер учащегося в таблице.")));
    if (so.groups && so.groups.length) {
      sg.appendChild(h("h3", null, t("Микрогруппы")));
      sg.appendChild(h("ul", null, so.groups.map(function (grp) {
        return h("li", null, grp.map(function (i) { return so.people[i].name; }).join(" — "));
      })));
    }
    pane.appendChild(sg);

    var mt = h("div", { class: "card" }, h("h2", { style: { marginTop: 0 } }, t("Социоматрица")));
    var head = ["№", t("Кто выбирает")].concat(so.people.map(function (p) { return String(p.num); }))
      .concat([t("Отдано +"), t("Отдано –"), t("Получено +"), t("Получено –"), t("Взаимных +"), t("Статус")]);
    mt.appendChild(h("div", { class: "tw" }, A.table(head, so.people.map(function (p, i) {
      return h("tr", null, [h("td", { class: "num" }, String(p.num)), h("td", null, p.name + (p.done ? "" : " ⚠"))]
        .concat(so.matrix[i].map(function (v, j) {
          var cls = "num" + (v === "+" ? " ok" : v === "-" ? " bad" : "") + (so.mutual[i][j] ? " mut" : "");
          return h("td", { class: cls, title: so.mutual[i][j] ? t("взаимный выбор") : null }, v === "x" ? "·" : v);
        }))
        .concat([h("td", { class: "num" }, String(p.made_pos)), h("td", { class: "num" }, String(p.made_neg)),
                 h("td", { class: "num" }, String(p.got_pos)), h("td", { class: "num" }, String(p.got_neg)),
                 h("td", { class: "num" }, String(p.mutual_pos)), h("td", null, p.status_name)]));
    }))));
    pane.appendChild(mt);

    var pi = h("div", { class: "card" }, h("h2", { style: { marginTop: 0 } }, t("Персональные индексы")));
    pi.appendChild(h("div", { class: "tw" }, A.table(["№", t("Учащийся"), "ИСС", "ИСС+", "ИСС–", "ИПЭ", "ИПЭ+", "ИПЭ–", "ИВ", "ИП"],
      so.people.map(function (p) {
        return [p.num, p.name].concat([p.iss, p.iss_pos, p.iss_neg, p.ipe, p.ipe_pos, p.ipe_neg, p.iv, p.ip]
          .map(function (x) { return String(x).replace(".", ","); }));
      }))));
    pi.appendChild(h("p", { class: "muted small" },
      t("ИСС — социометрический статус (полученные выборы), ИПЭ — психологическая экспансивность (отданные выборы), ИВ — авторитетность, ИП — отношение к другим членам класса.")));
    pane.appendChild(pi);

    (so.notes || []).forEach(function (n) { pane.appendChild(h("div", { class: "warnbox" }, n)); });
  }

  function results(pane, R) {
    var url = "/api/psy/runs/" + R.id + "/results";
    return api("GET", url).then(function (rep) {
      pane.appendChild(h("div", { class: "bar" }, h("div", { class: "muted" }, rep.subtitle), h("div", { class: "sp" }),
        h("button", { onclick: function () { ST.download(url + "?format=xlsx"); } }, "⬇ Excel"),
        h("button", { onclick: function () { A.printReport(rep); } }, "🖶 " + t("Печать")),
        h("button", { onclick: function () { printAll(rep); } }, "🖶 " + t("Все индивидуальные отчёты"))));
      var att = rep.attempts || {};
      if (rep.socio) { socioView(pane, rep.socio); return; }
      pane.appendChild(A.table(rep.headers.concat([""]), rep.rows.map(function (r, i) {
        var aid = att[String(rep.sids[i])];
        return h("tr", null, r.map(function (c, k) { return h("td", { class: k === 0 || k > 3 && k < r.length - 1 ? "num" : null }, c === "" || c == null ? "" : String(c)); })
          .concat([h("td", null, aid ? h("a", { class: "btn sm", href: "#/psyres/" + aid }, t("Отчёт")) : null)]));
      })));
      if (rep.summary && rep.summary.length) {
        var card = h("div", { class: "card" }, h("h2", { style: { marginTop: 0 } }, t("Сводка по группе")));
        var maxCount = Math.max.apply(null, rep.summary.map(function (x) { return x.count || 0; }).concat([1]));
        card.appendChild(A.table([t("Показатель"), t("Учащихся"), "", t("Среднее")], rep.summary.map(function (x) {
          return h("tr", null, h("td", null, x.name), h("td", { class: "num" }, x.count != null ? String(x.count) : ""),
            h("td", { style: { width: "40%" } }, x.count != null ? h("div", { class: "bar-mini" }, h("i", { style: { width: (100 * x.count / maxCount) + "%" } })) :
              x.levels ? h("span", { class: "small" }, x.levels.map(function (l) { return l.name + ": " + l.count; }).join(" · ")) : ""),
            h("td", { class: "num" }, x.avg != null ? String(x.avg).replace(".", ",") : ""));
        })));
        pane.appendChild(card);
      }
    });
  }

  function printAll(rep) {
    var att = rep.attempts || {};
    var ids = rep.sids.map(function (sid) { return att[String(sid)]; }).filter(Boolean);
    if (!ids.length) { ST.toast(t("Нет завершённых результатов"), true); return; }
    Promise.all(ids.map(function (aid) { return api("GET", "/api/psy/attempts/" + aid); })).then(function (list) {
      A.printHtml(rep.title, list.map(function (D, i) { return reportHtml(D) + (i < list.length - 1 ? "<div class='pb'></div>" : ""); }).join(""), PRINT_CSS);
    }).catch(A.err);
  }
  var PRINT_CSS = ".psy-sum{font-size:16px;font-weight:bold;margin:6px 0}.psy-chart{margin:8px 0}.psy-txt h3{font-size:14px;margin:10px 0 2px}" +
    ".psy-txt p{margin:0}.warnbox{border:1px solid #c90;padding:6px 10px;margin:6px 0}.muted{color:#555}.tw{overflow:visible}svg text{font-family:Arial}";
  function reportHtml(D) {
    var ex = D.extra || {};
    var who = ST.esc(D.student) + " · " + ST.esc(D.class) + " · " + A.date(D.date) +
      (ex.age ? " · " + ex.age + " " + t("лет") : "") + (ex.gender ? " · " + (ex.gender === "m" ? t("муж.") : t("жен.")) : "");
    return "<h1>" + ST.esc(D.method_name) + "</h1><div class='sub'>" + who + "</div>" + ST.psyResultHtml(D.result);
  }

  A.route("psyres", function (box, args) {
    if (!guard()) return;
    return api("GET", "/api/psy/attempts/" + args[0]).then(function (D) {
      A.head(box, D.student, D.method_name + " · " + D.class + " · " + A.date(D.date, true), [
        h("button", { class: "pri", onclick: function () { A.printHtml(D.student, reportHtml(D), PRINT_CSS); } }, "🖶 " + t("Печать")),
        D.student_id ? h("a", { class: "btn", href: "#/psystudent/" + D.student_id }, t("Все обследования учащегося")) : null]);
      var ex = D.extra || {};
      if (ex.age || ex.gender) box.appendChild(h("div", { class: "muted", style: { marginBottom: "8px" } },
        (ex.gender ? (ex.gender === "m" ? t("Пол: мужской") : t("Пол: женский")) : "") + (ex.age ? " · " + ST.tf("Возраст: {0}", ex.age) : "")));
      box.appendChild(h("div", { class: "card" }, ST.psyResult(D.result)));
      if (D.result && D.result.details5) box.appendChild(genCheck(D));
      if (D.result && D.result.cycles) box.appendChild(h("div", { class: "card" }, h("h2", { style: { marginTop: 0 } }, t("Циклы знаний")),
        A.table([t("Цикл"), t("Баллы"), "%"], D.result.cycles.map(function (c) {
          return [c.name, c.value + " " + t("из") + " " + c.max, String(c.percent).replace(".", ",")];
        }))));
    });
  });

  /* проверка субтеста «Обобщения» ШТУР-2: психолог ставит 0, 1 или 2 балла */
  function genCheck(D) {
    var card = h("div", { class: "card" }, h("h2", { style: { marginTop: 0 } }, t("Субтест «Обобщения»: проверка")));
    card.appendChild(h("p", { class: "muted small" },
      t("2 балла — обобщение по родовому признаку с указанием видового отличия, 1 балл — только родовое или только видовое обобщение, 0 — неправильный ответ. Оценку, подставленную программой, можно изменить.")));
    var changed = {};
    var rows = D.result.details5.map(function (x) {
      var cell = h("td", { class: "gen-btns" });
      [0, 1, 2].forEach(function (v) {
        var b = h("button", { type: "button", class: "sm" + (x.value === v ? " pri" : "") }, String(v));
        b.addEventListener("click", function () {
          x.value = v; x.manual = v; changed[x.num] = v;
          cell.querySelectorAll("button").forEach(function (o) { o.classList.remove("pri"); });
          b.classList.add("pri");
        });
        cell.appendChild(b);
      });
      return h("tr", { class: x.sure ? null : "warn-row" }, h("td", { class: "num" }, String(x.num)),
        h("td", null, x.task), h("td", null, h("b", null, x.answer || "—")),
        h("td", { class: "small muted" }, "2: " + (x.ref["2"] || []).join(", ") + "; 1: " + (x.ref["1"] || []).join(", ")),
        h("td", { class: "num" }, x.manual != null ? t("вручную") : (x.sure ? t("по таблице") : t("не найдено"))), cell);
    });
    card.appendChild(h("div", { class: "tw" }, A.table(["№", t("Задание"), t("Ответ"), t("Возможные ответы"), t("Оценка"), t("Балл")], rows)));
    card.appendChild(h("div", { class: "bar" }, h("div", { class: "sp" }),
      h("button", { class: "pri", onclick: function () {
        if (!Object.keys(changed).length) { ST.toast(t("Изменений нет")); return; }
        api("PUT", "/api/psy/attempts/" + D.attempt_id + "/gen", { scores: changed })
          .then(function () { ST.toast(t("Сохранено")); A.render(); }).catch(A.err);
      } }, t("Сохранить оценки"))));
    return card;
  }

  A.route("psystudent", function (box, args) {
    if (!guard()) return;
    return api("GET", "/api/psy/students/" + args[0]).then(function (D) {
      A.head(box, D.student, t("Обследования за все учебные годы"));
      box.appendChild(A.table([t("Дата"), t("Учебный год"), A.N("class"), t("Методика"), t("Итог"), ""], D.items.map(function (x) {
        return h("tr", null, h("td", null, A.date(x.date)), h("td", null, x.year || ""), h("td", null, x.class || ""), h("td", null, x.title),
          h("td", null, x.summary), h("td", null, h("a", { class: "btn sm", href: "#/psyres/" + x.attempt_id }, t("Отчёт"))));
      }), { empty: t("Обследований нет") }));
    });
  });
})();
