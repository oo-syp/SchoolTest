/* SchoolTest — учебные годы и перевод учащихся на следующий год */
"use strict";
(function () {
  var h = ST.h, t = ST.t, api = ST.api;
  var ACT = [["promote", "перевести"], ["keep", "перенести без изменения названия"], ["graduate", "выпуск (не переносить)"]];

  A.route("years", function (box) {
    if (!A.isAdmin()) return A.go("#/tests");
    A.head(box, t("Учебные годы"), t("Классы и ученики принадлежат учебному году. Результаты тестов прошлых лет сохраняются: выберите год в левой панели, чтобы их посмотреть."), [
      h("button", { onclick: addYear }, "＋ " + t("Учебный год"))]);
    return api("GET", "/api/years").then(function (years) {
      box.appendChild(A.table([t("Учебный год"), t("Период"), A.N("classes"), A.N("students"), t("Проведений"), ""], years.slice().reverse().map(function (y) {
        return h("tr", null, h("td", null, h("b", null, y.name), y.current ? h("span", { class: "pill ok", style: { marginLeft: "8px" } }, t("текущий")) : null),
          h("td", null, (y.start_date ? A.date(y.start_date) : "") + " — " + (y.end_date ? A.date(y.end_date) : "")),
          h("td", { class: "num" }, String(y.classes)), h("td", { class: "num" }, String(y.students)), h("td", { class: "num" }, String(y.runs)),
          h("td", { class: "acts" },
            y.classes ? h("button", { class: "sm pri", onclick: function () { promote(y); } }, t("Перевести на следующий год…")) : null,
            !y.current ? h("button", { class: "sm", onclick: function () {
              api("PUT", "/api/years/" + y.id, { current: true }).then(function () { return A.reloadMe(); }).then(function () {
                try { localStorage.removeItem("st_year"); } catch (e) {}
                ST.toast(t("Текущий учебный год изменён")); A.render();
              }).catch(A.err);
            } }, t("Сделать текущим")) : null,
            h("button", { class: "sm", onclick: function () {
              A.prompt(t("Название учебного года"), t("Название"), y.name).then(function (v) {
                if (v) api("PUT", "/api/years/" + y.id, { name: v }).then(function () { return A.reloadMe(); }).then(A.render).catch(A.err);
              });
            } }, t("Переименовать")),
            !y.current && !y.classes ? h("button", { class: "sm ghost danger", onclick: function () {
              api("DELETE", "/api/years/" + y.id).then(function () { return A.reloadMe(); }).then(A.render).catch(A.err);
            } }, "✕") : null));
      })));
      box.appendChild(h("div", { class: "card" }, h("h2", { style: { marginTop: 0 } }, t("Как перевести учащихся")),
        h("ol", null,
          h("li", null, t("В конце учебного года нажмите «Перевести на следующий год…» у текущего года.")),
          h("li", null, t("Проверьте новые названия классов (5А → 6А), выпускные классы и выбывших учеников.")),
          h("li", null, t("Программа создаст классы нового года и перенесёт в них учеников. Классы, тесты и отметки прошлого года остаются в архиве — история ученика показывает все годы.")),
          h("li", null, t("Если списки ведутся в SchoolGrade, после перевода там обновите списки кнопкой «Обновить из SchoolGrade»: ученики сопоставятся автоматически.")))));
    });
  });

  function addYear() {
    var y = A.me.years[A.me.years.length - 1];
    var m = /^(\d{4})/.exec(y ? y.name : "");
    var next = m ? (+m[1] + 1) + "/" + (+m[1] + 2) : "";
    A.prompt(t("Новый учебный год"), t("Название, например 2027/2028"), next, t("Создать")).then(function (v) {
      if (v) api("POST", "/api/years", { name: v }).then(function () { return A.reloadMe(); }).then(A.render).catch(A.err);
    });
  }

  function promote(y) {
    api("GET", "/api/years/" + y.id + "/promote").then(function (P) {
      var toName = h("input", { type: "text", style: { width: "140px" } });
      toName.value = P.to.name;
      var makeCur = A.check(t("Сделать новый год текущим"), true);
      var rows = P.classes.map(function (c) {
        var act = A.select(ACT.map(function (a) { return [a[0], t(a[1])]; }), c.action);
        var nm = h("input", { type: "text" });
        nm.value = c.new_name;
        var excl = {};
        var exBtn = h("button", { type: "button", class: "sm" }, t("Выбывшие…"));
        var exInfo = h("span", { class: "muted small" });
        exBtn.addEventListener("click", function () {
          var list = h("div", { class: "chk-list" }, c.students.map(function (s) {
            return A.check(s.name, !!excl[s.id], function (v) { if (v) excl[s.id] = 1; else delete excl[s.id]; });
          }));
          ST.modal(ST.tf("{0}: кого не переводить", c.name), h("div", null, h("p", { class: "muted", style: { marginTop: 0 } },
            t("Отметьте учеников, которые выбыли или остаются в этом году. Их результаты сохранятся в архиве.")), list)).then(function () {
            var n = Object.keys(excl).length;
            exInfo.textContent = n ? ST.tf("не переводятся: {0}", n) : "";
          });
        });
        function sync() { nm.disabled = act.value === "graduate"; exBtn.disabled = act.value === "graduate"; }
        act.addEventListener("change", function () {
          if (act.value === "keep") nm.value = c.name;
          if (act.value === "promote") nm.value = c.new_name !== c.name ? c.new_name : nm.value;
          sync();
        });
        sync();
        c._ui = { act: act, nm: nm, excl: excl };
        return h("tr", null, h("td", null, h("b", null, c.name)), h("td", { class: "num" }, String(c.students.length)), h("td", null, act),
          h("td", null, nm), h("td", null, exBtn, " ", exInfo));
      });
      var body = h("div", { class: "promo" },
        h("div", { class: "form" }, A.field(t("Новый учебный год"), toName), makeCur),
        P.to.id ? h("div", { class: "muted small" }, t("Учебный год уже создан: классы с совпадающими названиями будут дополнены, а не продублированы.")) : null,
        A.table([A.N("class"), A.N("students"), t("Действие"), t("Название в новом году"), ""], rows));
      ST.modal(ST.tf("Перевод: {0} → новый учебный год", P.from.name), body, [{ text: t("Отмена"), value: null },
        { text: t("Перевести"), value: 1, cls: "pri" }], true).then(function (v) {
        if (!v) return;
        var payload = { to: P.to.id ? { id: P.to.id } : { name: toName.value.trim(), start_date: P.to.start_date, end_date: P.to.end_date },
          make_current: makeCur.querySelector("input").checked,
          classes: P.classes.map(function (c) {
            return { class_id: c.class_id, action: c._ui.act.value, new_name: c._ui.nm.value.trim(), exclude: Object.keys(c._ui.excl).map(Number) };
          }) };
        api("POST", "/api/years/" + y.id + "/promote", payload).then(function (r) {
          try { localStorage.removeItem("st_year"); } catch (e) {}
          return A.reloadMe().then(function () {
            ST.modal(t("Перевод выполнен"), h("ul", null,
              h("li", null, ST.tf("создано классов: {0}", r.classes)), h("li", null, ST.tf("переведено учащихся: {0}", r.students)),
              h("li", null, ST.tf("выпускников: {0}", r.graduated)), h("li", null, ST.tf("не переведено (выбывшие): {0}", r.excluded)))).then(A.render);
          });
        }).catch(A.err);
      });
    }).catch(A.err);
  }
})();
