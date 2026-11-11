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
      var grid = h("div", { class: "mgrid" });
      ms.forEach(function (m) {
        grid.appendChild(h("div", { class: "mcard" }, h("h3", null, m.name), h("div", { class: "muted small" }, m.author),
          h("div", null, h("span", { class: "pill" }, t(m.block)), " ", h("span", { class: "pill" }, ST.tf("{0} вопр.", m.count))),
          h("div", { class: "small" }, m.purpose), h("div", { class: "muted small" }, m.audience),
          h("div", { class: "acts" }, h("button", { class: "pri sm", onclick: function () { launch(m); } }, "▶ " + t("Провести")),
            h("a", { class: "btn sm", href: "#/psymethod/" + m.id }, t("Описание и ключ")))));
      });
      pane.appendChild(grid);
      pane.appendChild(h("div", { class: "infobox", style: { marginTop: "14px" } },
        t("Проведение — как обычного теста: учащиеся открывают адрес программы, вводят код и выбирают себя в списке. Вопросы идут по одному, после ответа — сразу следующий. Подсчёт по ключу и интерпретация — автоматически.")));
    });
  });

  function launch(m) {
    api("GET", A.yearQ("/api/classes")).then(function (classes) {
      if (!classes.length) { ST.toast(A.N("no_classes"), true); return; }
      var cls = A.select(classes.map(function (c) { return [c.id, c.name + " (" + c.students + ")"]; }));
      var show = A.check(t("Показать учащемуся результат с интерпретацией после завершения"), m.show_default === "profile");
      ST.modal(ST.tf("Провести: {0}", m.short), h("div", null, h("div", { class: "form" }, A.field(A.N("class"), cls)), show,
        m.ask && m.ask.length ? h("p", { class: "muted small" }, t("Перед началом учащийся укажет пол и возраст — они нужны для сравнения с нормативами.")) : null),
        [{ text: t("Отмена"), value: null }, { text: t("Начать"), value: 1, cls: "pri" }]).then(function (v) {
        if (!v) return;
        api("POST", "/api/psy/runs", { method: m.id, class_id: +cls.value, show_result: show.querySelector("input").checked ? "profile" : "none" })
          .then(function (r) { A.go("#/psyrun/" + r.id); }).catch(A.err);
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
  A.route("psymethod", function (box, args) {
    if (!guard()) return;
    return api("GET", "/api/psy/methods/" + args[0]).then(function (m) {
      A.head(box, m.name, m.author, [h("button", { class: "pri", onclick: function () { launch(m); } }, "▶ " + t("Провести")),
        h("button", { onclick: function () { printBlank(m); } }, "🖶 " + t("Бланк вопросов")), h("a", { class: "btn", href: "#/psy" }, "← " + t("Методики"))]);
      box.appendChild(h("div", { class: "card" },
        h("p", null, h("b", null, t("Назначение. ")), m.purpose), h("p", null, h("b", null, t("Для кого. ")), m.audience),
        h("p", null, h("b", null, t("Инструкция. ")), m.instruction), h("p", null, h("b", null, t("Ответы. ")), m.answers),
        m.note ? h("div", { class: "warnbox" }, m.note) : null));
      box.appendChild(h("div", { class: "card" }, h("h2", { style: { marginTop: 0 } }, t("Ключ")),
        A.table([t("Шкала"), t("Вопросы")], m.key.map(function (k) { return [k.name, k.items]; }))));
      box.appendChild(h("details", { class: "card" }, h("summary", null, h("b", null, ST.tf("Вопросы ({0})", m.questions.length))),
        h("ol", null, m.questions.map(function (qq) {
          return h("li", null, m.id === "ddo" ? h("span", null, "а) " + qq.options[0].text + "; б) " + qq.options[1].text) : qq.text.replace(/^Хотелось бы Вам\? Нравится ли Вам\? /, ""));
        }))));
    });
  });
  function printBlank(m) {
    var rows = m.questions.map(function (qq, i) {
      var txt = m.id === "ddo" ? "а) " + qq.options[0].text + "<br>б) " + qq.options[1].text : qq.text.replace(/^Хотелось бы Вам\? Нравится ли Вам\? /, "");
      var ans = qq.options.map(function (o) { return "☐ " + ST.esc(o.text.replace(/\s*\(.*\)$/, "")); }).join("&nbsp;&nbsp; ");
      if (m.id === "ddo") ans = "☐ а &nbsp; ☐ б";
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

  function results(pane, R) {
    var url = "/api/psy/runs/" + R.id + "/results";
    return api("GET", url).then(function (rep) {
      pane.appendChild(h("div", { class: "bar" }, h("div", { class: "muted" }, rep.subtitle), h("div", { class: "sp" }),
        h("button", { onclick: function () { ST.download(url + "?format=xlsx"); } }, "⬇ Excel"),
        h("button", { onclick: function () { A.printReport(rep); } }, "🖶 " + t("Печать")),
        h("button", { onclick: function () { printAll(rep); } }, "🖶 " + t("Все индивидуальные отчёты"))));
      var att = rep.attempts || {};
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
    });
  });

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
