/* SchoolTest — классы, администрирование, справка */
"use strict";
(function () {
  var h = ST.h, t = ST.t, api = ST.api;

  /* ---------------- классы и ученики ---------------- */
  A.route("classes", function (box, args, q) {
    var admin = A.isAdmin();
    var acts = [];
    if (admin) {
      acts.push(h("button", { class: "pri", onclick: addClass }, "＋ " + A.N("new_class")));
      acts.push(h("button", { onclick: importTable }, "⬆ " + t("Из таблицы")));
      if (A.isSchool()) acts.push(h("button", { onclick: sgFile }, "⬆ " + t("Файл SchoolGrade")));
      if (A.isSchool() && A.me.settings.sg.enabled && A.me.settings.sg.import_classes) acts.push(h("button", { onclick: sgSync }, "⟳ " + t("Обновить из SchoolGrade")));
    }
    A.head(box, A.N("classes"), admin ? null : t("Списки ведёт администратор"), acts);
    var wrap = h("div", { class: "grid-cls", style: { display: "grid", gridTemplateColumns: "minmax(200px,260px) 1fr", gap: "16px" } });
    box.appendChild(wrap);
    return api("GET", A.yearQ("/api/classes")).then(function (classes) {
      var left = h("div", { class: "card", style: { padding: "8px" } });
      var right = h("div");
      wrap.appendChild(left);
      wrap.appendChild(right);
      if (!classes.length) { left.appendChild(h("div", { class: "empty" }, A.N("no_classes"))); return; }
      var cur = +(q.c || classes[0].id);
      classes.forEach(function (c) {
        left.appendChild(h("a", { href: "#/classes?c=" + c.id, style: { display: "flex", justifyContent: "space-between", padding: "6px 10px",
          borderRadius: "6px", background: c.id === cur ? "var(--sel)" : null, fontWeight: c.id === cur ? 600 : null } },
          h("span", null, c.name, c.sg_id ? h("span", { class: "muted small", title: "SchoolGrade" }, " ⟲") : null), h("span", { class: "muted" }, String(c.students))));
      });
      var C = classes.filter(function (c) { return c.id === cur; })[0] || classes[0];
      return showClass(right, C, admin);
    });
  });

  function showClass(box, C, admin) {
    return api("GET", "/api/classes/" + C.id + "/students").then(function (st) {
      var acts = [];
      if (admin) {
        acts.push(h("button", { class: "sm", onclick: function () { addStudent(C); } }, "＋ " + A.N("add_student")));
        acts.push(h("button", { class: "sm", onclick: function () { pasteList(C); } }, t("Вставить список")));
        acts.push(h("button", { class: "sm", onclick: function () {
          A.prompt(t("Переименовать"), t("Название"), C.name).then(function (v) { if (v) api("PUT", "/api/classes/" + C.id, { name: v }).then(A.render).catch(A.err); });
        } }, t("Переименовать")));
        acts.push(h("button", { class: "sm danger", onclick: function () {
          ST.confirm(t("Удалить?"), C.name + ". " + t("Если по списку уже проводились тесты, он будет перенесён в архив."), t("Удалить"), true).then(function (ok) {
            if (ok) api("DELETE", "/api/classes/" + C.id).then(function () { A.go("#/classes"); }).catch(A.err);
          });
        } }, t("Удалить")));
      }
      box.appendChild(h("div", { class: "bar" }, h("h2", { style: { margin: 0 } }, C.name), h("span", { class: "muted" }, ST.tf("{0} чел.", st.length)),
        h("div", { class: "sp" }), acts));
      box.appendChild(A.table(["№", t("Фамилия, имя, отчество"), ""], st.map(function (s, i) {
        return h("tr", null, h("td", { class: "num" }, String(i + 1)), h("td", null, s.name, s.sg_id ? h("span", { class: "muted small" }, " · SchoolGrade") : null),
          h("td", { class: "acts" }, h("a", { class: "btn sm", href: "#/student/" + s.id }, t("История")),
            admin ? h("button", { class: "sm", onclick: function () { editStudent(s); } }, t("Изменить")) : null,
            admin ? h("button", { class: "sm ghost danger", title: t("Удалить"), onclick: function () {
              ST.confirm(t("Удалить?"), s.name, t("Удалить"), true).then(function (ok) { if (ok) api("DELETE", "/api/students/" + s.id).then(A.render).catch(A.err); });
            } }, "✕") : null));
      }), { empty: t("Список пуст") }));
    });
  }
  function addClass() {
    A.prompt(A.N("new_class"), t("Название, например 7«А»"), "", t("Создать")).then(function (v) {
      if (v) api("POST", "/api/classes", { name: v, year_id: A.yearId() }).then(function (r) { A.go("#/classes?c=" + r.id); }).catch(A.err);
    });
  }
  function studentForm(s) {
    var l = h("input", { type: "text" }), f = h("input", { type: "text" }), m = h("input", { type: "text" });
    l.value = s.last_name || ""; f.value = s.first_name || ""; m.value = s.middle_name || "";
    return { el: h("div", { class: "form" }, A.field(t("Фамилия"), l), A.field(t("Имя"), f), A.field(t("Отчество"), m)),
             val: function () { return { last_name: l.value.trim(), first_name: f.value.trim(), middle_name: m.value.trim() }; } };
  }
  function addStudent(C) {
    var fm = studentForm({});
    ST.modal(A.N("add_student"), fm.el, [{ text: t("Отмена"), value: null }, { text: t("Добавить"), value: 1, cls: "pri" }]).then(function (v) {
      if (v) api("POST", "/api/classes/" + C.id + "/students", fm.val()).then(A.render).catch(A.err);
    });
  }
  function editStudent(s) {
    var fm = studentForm(s);
    ST.modal(s.name, fm.el, [{ text: t("Отмена"), value: null }, { text: t("Сохранить"), value: 1, cls: "pri" }]).then(function (v) {
      if (v) api("PUT", "/api/students/" + s.id, fm.val()).then(A.render).catch(A.err);
    });
  }
  function pasteList(C) {
    var ta = h("textarea", { rows: 12, placeholder: "Иванов Иван Иванович\nПетрова Анна Сергеевна" });
    ST.modal(t("Вставить список"), h("div", null, h("p", { class: "muted", style: { marginTop: 0 } },
      t("Один человек на строку: фамилия, имя, отчество. Повторы не добавляются.")), ta),
      [{ text: t("Отмена"), value: null }, { text: t("Добавить"), value: 1, cls: "pri" }]).then(function (v) {
      if (v) api("POST", "/api/classes/" + C.id + "/paste", { text: ta.value }).then(function (r) {
        ST.toast(ST.tf("Добавлено: {0}, уже были в списке: {1}", r.added, r.skipped)); A.render();
      }).catch(A.err);
    });
  }
  function importTable() {
    ST.pickFiles(".xlsx,.xls,.csv,.txt").then(function (fs) {
      if (!fs.length) return;
      return ST.readFile(fs[0]).then(function (d) {
        return api("POST", "/api/import/students/preview", { filename: d.name, data: d.data, year_id: A.yearId() });
      }).then(function (r) {
        var ok = r.rows.filter(function (x) { return !x.error; });
        var body = h("div", null,
          h("p", null, ST.tf("Строк: {0}, к загрузке: {1}", r.rows.length, ok.length) +
            (r.new_classes.length ? " · " + t("будут созданы:") + " " + r.new_classes.join(", ") : "")),
          A.table([A.N("class"), t("Фамилия"), t("Имя"), t("Отчество"), ""], r.rows.map(function (x) {
            return h("tr", { style: { background: x.error ? "var(--bad-soft)" : null } }, h("td", null, x.class), h("td", null, x.last), h("td", null, x.first),
              h("td", null, x.middle), h("td", null, x.error ? h("span", { class: "bad" }, t(x.error)) : x.exists ? h("span", { class: "muted" }, t("уже есть — обновится")) : h("span", { class: "ok" }, t("новый"))));
          })));
        return ST.modal(t("Проверьте данные"), body, [{ text: t("Отмена"), value: null }, { text: t("Загрузить"), value: 1, cls: "pri" }], true).then(function (v) {
          if (!v) return;
          return api("POST", "/api/import/students/commit", { rows: r.rows, year_id: A.yearId() }).then(function (res) {
            ST.toast(ST.tf("Добавлено: {0}, обновлено: {1}", res.added, res.updated)); A.render();
          });
        });
      });
    }).catch(A.err);
  }
  function sgFile() {
    ST.pickFiles(".json,.sgclasses").then(function (fs) {
      if (!fs.length) return;
      return ST.readFile(fs[0]).then(function (d) { return api("POST", "/api/import/schoolgrade_file", { data: d.data }); }).then(sgDone);
    }).catch(A.err);
  }
  function sgSync() { api("POST", "/api/sg/sync_classes", {}, { timeout: 60000 }).then(sgDone).catch(A.err); }
  function sgDone(r) {
    ST.modal(t("Списки обновлены"), h("ul", null, h("li", null, ST.tf("новых списков: {0}, обновлено: {1}", r.classes_new, r.classes_updated)),
      h("li", null, ST.tf("добавлено: {0}, обновлено: {1}, выбыли: {2}", r.added, r.updated, r.deactivated)))).then(A.render);
  }

  /* ---------------- настройки ---------------- */
  A.route("admin", function (box) {
    if (!A.isAdmin()) return A.go("#/tests");
    return api("GET", "/api/settings").then(function (S) {
      var first = !S.org_type;
      A.head(box, first ? t("Первоначальная настройка") : t("Настройки"), first ? t("Выберите тип организации — от него зависят названия и функции программы.") : null);
      var org = A.select([["", "—"]].concat(Object.keys(S.org_types).map(function (k) { return [k, t(S.org_types[k])]; })), S.org_type || "");
      var name = h("input", { type: "text" }); name.value = S.school_name;
      var lang = A.select([["ru", "Русский"], ["be", "Беларуская"]], S.lang);
      var sw = A.check(t("Ученик может переключить язык на своём экране"), S.student_lang_switch);
      var up = h("input", { type: "number", min: 1, max: 50, style: { width: "90px" } }); up.value = S.upload_max_mb;
      var thr = S.default_scale.map(function (x) { return x.slice(); });
      var thrBox = h("div", { style: { display: "flex", gap: "6px", flexWrap: "wrap" } });
      thr.forEach(function (r) {
        var inp = h("input", { type: "number", min: 0, max: 100, step: "0.5", style: { width: "64px" } });
        inp.value = r[0];
        inp.addEventListener("input", function () { r[0] = parseFloat(inp.value.replace(",", ".")) || 0; });
        thrBox.appendChild(h("label", { class: "f", style: { alignItems: "center" } }, h("b", { style: { color: "var(--brand)", fontSize: "15px" } }, String(r[1])), inp));
      });
      box.appendChild(h("div", { class: "card" }, h("h2", { style: { marginTop: 0 } }, t("Организация")),
        h("div", { class: "form" }, A.field(t("Тип организации"), org), A.field(t("Название учреждения"), name, "wide"),
          A.field(t("Язык интерфейса по умолчанию"), lang), A.field(t("Размер файла ответа ученика, МБ"), up)), sw));
      box.appendChild(h("div", { class: "card" }, h("h2", { style: { marginTop: 0 } }, t("Шкала отметок по умолчанию")),
        h("p", { class: "muted", style: { marginTop: 0 } }, t("Процент выполнения, с которого ставится отметка. Учитель может задать в тесте свою шкалу или выбрать нормы оценки.")),
        thrBox, h("button", { class: "sm", style: { marginTop: "8px" }, onclick: function () {
          var d = [[95, 10], [85, 9], [75, 8], [65, 7], [55, 6], [45, 5], [35, 4], [25, 3], [15, 2], [0, 1]];
          thrBox.querySelectorAll("input").forEach(function (i, k) { i.value = d[k][0]; thr[k][0] = d[k][0]; });
        } }, t("Вернуть стандартную"))));
      var sgCard = h("div", { class: "card" });
      var sgf = S.sg_full || {};
      var url = h("input", { type: "text", placeholder: "http://192.168.1.10:8080" }); url.value = sgf.url || "";
      var key = h("input", { type: "text", placeholder: t("ключ из настроек SchoolGrade") }); key.value = sgf.key || "";
      var imp = A.check(t("Импорт классов и учеников из SchoolGrade"), sgf.import_classes);
      var exp = A.check(t("Отправка отметок за тесты в журнал SchoolGrade"), sgf.export_marks);
      var sgStatus = h("span", { class: "small" });
      sgCard.appendChild(h("h2", { style: { marginTop: 0 } }, t("Связь с SchoolGrade")));
      sgCard.appendChild(h("p", { class: "muted", style: { marginTop: 0 } }, t("Адрес программы SchoolGrade в сети и ключ доступа (в SchoolGrade: «Настройки» → «Связь с SchoolTest»). Программа работает и без SchoolGrade.")));
      sgCard.appendChild(h("div", { class: "form" }, A.field(t("Адрес SchoolGrade"), url), A.field(t("Ключ доступа"), key)));
      sgCard.appendChild(imp);
      sgCard.appendChild(exp);
      sgCard.appendChild(h("div", { class: "bar", style: { marginTop: "8px" } }, h("button", { class: "sm", onclick: function () {
        sgStatus.textContent = t("Проверка…");
        sgStatus.className = "small muted";
        api("POST", "/api/sg/ping", { url: url.value, key: key.value }, { timeout: 30000 }).then(function (r) {
          sgStatus.className = "small ok"; sgStatus.textContent = "✓ " + t("Связь есть") + (r.school ? ": " + r.school : "") + (r.version ? " (SchoolGrade " + r.version + ")" : "");
        }).catch(function (e) { sgStatus.className = "small bad"; sgStatus.textContent = e.message; });
      } }, t("Проверить связь")), sgStatus));
      var orgNote = h("div");
      function upd() { sgCard.classList.toggle("hidden", org.value !== "school"); }
      org.addEventListener("change", upd);
      upd();
      box.appendChild(sgCard);
      box.appendChild(orgNote);
      box.appendChild(h("div", { class: "bar" }, h("button", { class: "pri", onclick: function () {
        if (!org.value) { ST.toast(t("Выберите тип организации"), true); return; }
        api("PUT", "/api/settings", { org_type: org.value, school_name: name.value, lang: lang.value,
          student_lang_switch: sw.querySelector("input").checked, upload_max_mb: +up.value || 10, default_scale: thr,
          sg: { url: url.value, key: key.value, import_classes: imp.querySelector("input").checked, export_marks: exp.querySelector("input").checked } })
          .then(function () { return A.reloadMe(); }).then(function () {
            ST.toast(t("Сохранено"));
            if (!ST.savedLang()) ST.setLang(lang.value);
            A.go(first ? "#/classes" : "#/admin");
          }).catch(A.err);
      } }, t("Сохранить"))));
    });
  });

  /* ---------------- пользователи ---------------- */
  A.route("users", function (box) {
    if (!A.isAdmin()) return A.go("#/tests");
    A.head(box, A.N("teachers"), t("Учётные записи для входа в программу"), [h("button", { class: "pri", onclick: addUser }, "＋ " + t("Добавить"))]);
    return api("GET", "/api/users").then(function (us) {
      box.appendChild(A.table([t("ФИО"), t("Логин"), t("Роль"), t("Тестов"), t("Последний вход"), t("Состояние"), ""], us.map(function (u) {
        return h("tr", null, h("td", null, u.full_name), h("td", null, u.login), h("td", null, u.role === "admin" ? t("администратор") :
          u.role === "psychologist" ? t("педагог-психолог") : A.N("teacher").toLowerCase()),
          h("td", { class: "num" }, String(u.tests)), h("td", null, u.last_login ? A.date(u.last_login, true) : ""),
          h("td", null, u.active ? (u.must_change ? h("span", { class: "pill warn" }, t("ждёт смены пароля")) : h("span", { class: "pill ok" }, t("активен"))) :
            h("span", { class: "pill" }, t("отключён"))),
          h("td", { class: "acts" },
            h("button", { class: "sm", onclick: function () { editUser(u); } }, t("Изменить")),
            h("button", { class: "sm", onclick: function () {
              ST.confirm(t("Сбросить пароль?"), u.login, t("Сбросить")).then(function (ok) {
                if (ok) api("POST", "/api/users/" + u.id + "/reset", {}).then(function (r) { A.showPassword(t("Новый пароль"), u.login, r.password); }).catch(A.err);
              });
            } }, t("Сбросить пароль")),
            u.id !== A.me.user.id ? h("button", { class: "sm ghost danger", onclick: function () {
              ST.confirm(t("Удалить пользователя?"), u.login + (u.tests ? ". " + t("Его тесты останутся в программе.") : ""), t("Удалить"), true).then(function (ok) {
                if (ok) api("DELETE", "/api/users/" + u.id).then(A.render).catch(A.err);
              });
            } }, "✕") : null));
      })));
    });
  });
  function userForm(u) {
    var fn = h("input", { type: "text" }); fn.value = u.full_name || "";
    var lg = h("input", { type: "text", disabled: u.id ? true : null }); lg.value = u.login || "";
    var role = A.select([["teacher", A.N("teacher")], ["psychologist", t("Педагог-психолог")], ["admin", t("Администратор")]], u.role || "teacher");
    var act = A.check(t("Может входить"), u.id ? u.active : true);
    return { el: h("div", null, h("div", { class: "form" }, A.field(t("ФИО"), fn, "wide"), A.field(t("Логин"), lg), A.field(t("Роль"), role)), u.id ? act : null),
             val: function () { return { full_name: fn.value.trim(), login: lg.value.trim(), role: role.value, active: act.querySelector("input").checked ? 1 : 0 }; } };
  }
  function addUser() {
    var f = userForm({});
    ST.modal(t("Новый пользователь"), f.el, [{ text: t("Отмена"), value: null }, { text: t("Создать"), value: 1, cls: "pri" }]).then(function (v) {
      if (!v) return;
      var d = f.val();
      api("POST", "/api/users", d).then(function (r) { A.showPassword(t("Пользователь создан"), d.login, r.password).then(A.render); }).catch(A.err);
    });
  }
  function editUser(u) {
    var f = userForm(u);
    ST.modal(u.login, f.el, [{ text: t("Отмена"), value: null }, { text: t("Сохранить"), value: 1, cls: "pri" }]).then(function (v) {
      if (v) api("PUT", "/api/users/" + u.id, f.val()).then(A.render).catch(A.err);
    });
  }

  /* ---------------- резервные копии ---------------- */
  A.route("backup", function (box) {
    if (!A.isAdmin()) {
      A.head(box, t("Резервные копии"), t("Копия создаётся автоматически раз в сутки. Все данные хранятся в одном файле schooltest.db рядом с программой."));
      box.appendChild(h("div", { class: "card" }, h("p", { style: { marginTop: 0 } }, t("Восстановить данные из копии может администратор.")),
        h("button", { class: "pri", onclick: function () { api("POST", "/api/backups", {}).then(function (r) { ST.toast(t("Копия создана") + ": " + r.name); }).catch(A.err); } },
          t("Создать копию сейчас"))));
      return;
    }
    A.head(box, t("Резервные копии"), t("Копия создаётся автоматически раз в сутки. Все данные хранятся в одном файле schooltest.db рядом с программой."), [
      h("button", { class: "pri", onclick: function () { api("POST", "/api/backups", {}).then(function () { ST.toast(t("Копия создана")); A.render(); }).catch(A.err); } }, t("Создать копию сейчас")),
      h("button", { onclick: function () {
        ST.pickFiles(".db").then(function (fs) {
          if (!fs.length) return;
          return ST.confirm(t("Восстановить из файла?"), t("Текущие данные будут заменены данными из копии. Перед этим программа сохранит копию текущего состояния."), t("Восстановить"), true).then(function (ok) {
            if (!ok) return;
            return ST.readFile(fs[0]).then(function (d) { return api("POST", "/api/backups/restore", { data: d.data }, { timeout: 180000 }); })
              .then(function () { ST.toast(t("Данные восстановлены")); setTimeout(function () { location.reload(); }, 800); });
          });
        }).catch(A.err);
      } }, t("Восстановить из файла…"))]);
    return api("GET", "/api/backups").then(function (list) {
      box.appendChild(A.table([t("Файл"), t("Размер"), ""], list.map(function (b) {
        return h("tr", null, h("td", null, b.name), h("td", null, Math.round(b.size / 1024) + " КБ"),
          h("td", { class: "acts" }, h("button", { class: "sm", onclick: function () { ST.download("/api/backups/" + encodeURIComponent(b.name)); } }, "⬇ " + t("Скачать")),
            h("button", { class: "sm danger", onclick: function () {
              ST.confirm(t("Восстановить эту копию?"), b.name + ". " + t("Текущие данные будут заменены. Перед этим программа сохранит копию текущего состояния."), t("Восстановить"), true)
                .then(function (ok) { if (ok) api("POST", "/api/backups/restore", { name: b.name }).then(function () { ST.toast(t("Данные восстановлены")); setTimeout(function () { location.reload(); }, 800); }).catch(A.err); });
            } }, t("Восстановить"))));
      }), { empty: t("Копий пока нет") }));
    });
  });

  A.route("audit", function (box) {
    if (!A.isAdmin()) return A.go("#/tests");
    A.head(box, t("Журнал действий"), t("Последние 500 событий"));
    return api("GET", "/api/audit").then(function (rows) {
      box.appendChild(A.table([t("Время"), t("Пользователь"), "IP", t("Действие"), t("Подробности")], rows.map(function (r) {
        return [A.date(r.created_at, true), r.login || "", r.ip || "", r.action, String(r.details || "").slice(0, 200)];
      })));
    });
  });

  A.route("password", function (box) {
    A.head(box, t("Смена пароля"));
    var o = h("input", { type: "password", autocomplete: "current-password" });
    var n1 = h("input", { type: "password", autocomplete: "new-password" });
    var n2 = h("input", { type: "password", autocomplete: "new-password" });
    box.appendChild(h("div", { class: "card", style: { maxWidth: "420px" } }, A.field(t("Текущий пароль"), o), h("br"), A.field(t("Новый пароль"), n1), h("br"),
      A.field(t("Повторите новый пароль"), n2), h("br"), h("button", { class: "pri", onclick: function () {
        if (n1.value !== n2.value) { ST.toast(t("Пароли не совпадают"), true); return; }
        api("POST", "/api/me/password", { old: o.value, new: n1.value }).then(function () { ST.toast(t("Пароль изменён")); A.go("#/tests"); }).catch(A.err);
      } }, t("Сохранить"))));
  });

  /* ---------------- справка ---------------- */
  A.route("help", function (box) {
    A.head(box, t("Как пользоваться"));
    var steps = [
      [t("Списки"), t("Администратор добавляет списки (вручную, вставкой, из таблицы Excel/CSV или из SchoolGrade) и учётные записи учителей.")],
      [t("Тест"), t("Создайте тест или загрузите готовый. Вопросы объединяются в задания; из задания можно выдавать случайные вопросы. В настройках выберите шкалу: по проценту или по нормам оценки.")],
      [t("Формулы"), t("Кнопка «ƒx» открывает редактор формул: палитра символов, запись LaTeX и предпросмотр. В тексте формула хранится между \\( и \\).")],
      [t("Проведение"), t("Нажмите «Провести», выберите список. Ученики открывают адрес программы (он показан в окне SchoolTest), вводят код и выбирают себя в списке.")],
      [t("Сбой у ученика"), t("Если компьютер ученика завис, он открывает тест на другом устройстве — в наблюдении появится кнопка «Разрешить продолжить». Ответы и таймер сохраняются.")],
      [t("Проверка"), t("Развёрнутые ответы и файлы проверяются на вкладке «Проверка». Итоговая отметка появляется после проверки.")],
      [t("Отчёты"), t("Результаты, анализ вопросов и история ученика выгружаются в Excel и печатаются.")],
      [t("Бумажный тест"), t("Выберите «На бумаге» при запуске: программа напечатает варианты и ключ, а после проверки вы внесёте отметки.")],
      [t("Задачи с кодом"), t("Тип вопроса «Код»: условие, примеры, подзадачи с баллами и тестами (вручную или из ZIP-архива). Ученик пишет программу на разрешённом языке и отправляет её — проверка идёт сразу на компьютере с SchoolTest. Компиляторы — в разделе «Компиляторы».")],
      [t("Учебный год"), t("В конце года администратор переводит учащихся: «Учебные годы» → «Перевести на следующий год…». Прошлые годы выбираются в левой панели — там сохраняются классы, тесты и отметки.")],
      [t("Психодиагностика"), t("Педагог-психолог проводит методики (ДДО, КОС, EPI, карта интересов) по коду, как тест. Подсчёт по ключу, интерпретация, графики и сводка по классу — автоматически; результаты видят только психологи и администратор.")]];
    box.appendChild(h("div", { class: "card" }, h("ol", null, steps.map(function (s) { return h("li", { style: { marginBottom: "10px" } }, h("b", null, s[0] + ". "), s[1]); }))));
    box.appendChild(h("div", { class: "card" }, h("h2", { style: { marginTop: 0 } }, t("Если ученики не могут открыть адрес")),
      h("ul", null, h("li", null, t("Компьютер с SchoolTest и устройства учеников должны быть в одной сети.")),
        h("li", null, t("Откройте порт программы в брандмауэре Windows: запустите firewall_open_port.bat от имени администратора.")),
        h("li", null, t("Адрес вида http://192.168.1.10:8081 показан в окне программы на компьютере учителя.")))));
    ST.math(box);
  });

  A.route("about", function (box) {
    var ab = A.me.about;
    var upd = h("div", { class: "upd" });
    A.head(box, t("О программе"));
    box.appendChild(h("div", { class: "card", style: { maxWidth: "640px" } },
      h("div", { style: { display: "flex", gap: "16px", alignItems: "center" } }, h("img", { src: "/icon.svg", alt: "", style: { width: "64px" } }),
        h("div", null, h("h1", null, ab.name + " " + ab.version), h("div", { class: "muted" }, t("Тестирование в локальной сети")))),
      h("p", null, t(ab.org)), h("p", null, t("Разработчик:") + " " + t(ab.author)), h("p", { class: "muted" }, ab.city),
      h("h2", null, t("Обновления")),
      h("p", null, t("Актуальная версия программы публикуется на GitHub:"), " ",
        h("a", { href: ab.releases.SchoolTest, target: "_blank", rel: "noopener" }, ab.releases.SchoolTest)),
      upd,
      h("p", null, t("Электронный журнал SchoolGrade (связь с SchoolTest: списки классов и отметки):"), " ",
        h("a", { href: ab.releases.SchoolGrade, target: "_blank", rel: "noopener" }, ab.releases.SchoolGrade)),
      h("p", { class: "muted small" }, t("Формулы отображаются библиотекой KaTeX (лицензия MIT)."))));
    upd.textContent = t("Проверка обновлений…");
    api("GET", "/api/update_check", null, { timeout: 15000 }).then(function (u) {
      upd.innerHTML = "";
      if (!u.enabled) upd.appendChild(h("span", { class: "muted" }, t("Автоматическая проверка обновлений выключена.")));
      else if (u.error) upd.appendChild(h("span", { class: "muted" }, t(u.error)));
      else if (u.newer) upd.appendChild(h("b", null, ST.tf("Доступна новая версия {0}", u.latest) + (u.published ? " (" + u.published + ")" : "") + ". ",
        h("a", { href: u.url, target: "_blank", rel: "noopener" }, t("Скачать"))));
      else upd.appendChild(h("span", { class: "ok" }, t("Установлена последняя версия.")));
      if (A.isAdmin()) upd.appendChild(h("div", { style: { marginTop: "6px" } }, A.check(t("Проверять наличие новой версии автоматически (нужен интернет; данные школы не передаются)"),
        u.enabled, function (v) { api("PUT", "/api/update_check", { enabled: v }).then(A.render).catch(A.err); })));
    }).catch(function () { upd.textContent = ""; });
  });
})();
