/* Examination management: exams, audience (eligibility), subject catalogue, academic years and terms. */
(function () {
  "use strict";
  const { $, esc, api } = EM;
  const opt = (rows, v, l, first) => [["", first]].concat(rows.map(r => [r[v], l(r)]));

  // ------------------------------------------------------------ examinations
  async function examForm(e, subjects, terms) {
    const edit = !!e;
    return EM.ask({ title: edit ? `Edit examination #${e.id}` : "New examination", submitText: edit ? "Save changes" : "Create examination", fields: [
      { name: "title", label: "Examination title", required: true, value: e && e.title },
      { name: "subject_id", label: "Subject (catalogue)", type: "select", options: opt(subjects.filter(s => s.active || (e && s.id === e.subject_id)), "id", s => `${s.code} — ${s.name}`, "— not in catalogue: type a code below —"), value: e && e.subject_id },
      { name: "subject_code", label: "Subject code (only if not in the catalogue)", value: e && !e.subject_id ? e.subject_code : "" },
      { name: "term_id", label: "Examination term", type: "select", options: opt(terms, "id", t => t.name, "No term"), value: e && e.term_id },
      { name: "exam_date", label: "Date", type: "date", required: true, value: e && e.exam_date },
      { name: "start_time", label: "Start time", type: "time", required: true, value: e && e.start_time },
      { name: "end_time", label: "End time", type: "time", required: true, value: e && e.end_time },
      { name: "venue", label: "Venue / block", value: e ? e.venue : "", hint: "Leave blank for “To be announced”." },
      { name: "status", label: "Status", type: "select", options: [["draft", "Draft (hidden from students)"], ["published", "Published"], ["completed", "Completed"]], value: e ? e.status : "draft" },
    ], submit: async d => {
      const body = { title: d.title, exam_date: d.exam_date, start_time: d.start_time, end_time: d.end_time, venue: d.venue || "To be announced", status: d.status, subject_id: EM.num(d.subject_id), term_id: EM.num(d.term_id) };
      if (!body.subject_id) { if (!d.subject_code && !edit) throw new EM.ApiError("Choose a catalogue subject or enter a subject code.", 422, { subject_code: "Required when no catalogue subject is chosen." }); if (d.subject_code) body.subject_code = d.subject_code; }
      await api(edit ? "/api/exams/" + e.id : "/api/exams", { method: edit ? "PATCH" : "POST", body });
      return true;
    } });
  }

  EM.page({ name: "exams", title: "Examinations", roles: ["admin", "staff"], nav: { group: "Examinations", icon: "📝", label: "Examinations", order: 1 }, render: async (root, ctx) => {
    if (ctx.args[1] === "audience") return audience(root, ctx, Number(ctx.args[0]));
    const LIMIT = 25, adm = EM.isAdmin();
    let [subjects, terms] = await Promise.all([api("/api/admin/subjects", { params: { limit: 500 } }), api("/api/admin/terms")]);
    let offset = 0, rows = [];
    root.innerHTML = `<div class="stack"><div class="row between"><p class="muted" style="margin:0">Create, schedule and publish examinations. Students only see <b>published</b> examinations.</p><button class="btn primary" data-act="new">+ New examination</button></div>
      <form id="flt" class="toolbar card flat" style="padding:12px;margin:0">
        <div class="field wide"><label>Search</label><input name="q" placeholder="Title or subject code" value="${esc(ctx.query.q || "")}"></div>
        <div class="field"><label>Status</label><select name="status">${[["", "Any"], ["draft", "Draft"], ["published", "Published"], ["completed", "Completed"]].map(o => `<option value="${o[0]}"${o[0] === (ctx.query.status || "") ? " selected" : ""}>${o[1]}</option>`).join("")}</select></div>
        <div class="field"><label>Term</label><select name="term_id">${opt(terms, "id", t => t.name, "Any").map(o => `<option value="${esc(o[0])}">${esc(o[1])}</option>`).join("")}</select></div>
        <div class="field"><label>Session</label><select name="session"><option value="">FN + AN</option><option>FN</option><option>AN</option></select></div>
        <div class="field"><label>From</label><input type="date" name="date_from"></div><div class="field"><label>To</label><input type="date" name="date_to"></div>
        <button class="btn primary">Filter</button><button class="btn" type="reset" id="rst">Reset</button></form>
      <div id="list"></div><div id="pg"></div></div>`;
    const list = $("#list", root);
    async function load() {
      list.innerHTML = EM.loading();
      const f = EM.formData($("#flt", root)), r = await EM.apiList("/api/admin/exams", { ...f, limit: LIMIT, offset });
      rows = r.rows;
      list.innerHTML = ""; const g = document.createElement("div"); list.appendChild(g);
      EM.grid(g, { rows, caption: "Examinations", search: false, pageSize: 100, empty: { title: "No examinations match", text: "Adjust the filters or create a new examination." }, columns: [
        { key: "exam_date", label: "Date", render: e => `<span class="nowrap">${esc(e.exam_date)}</span>` },
        { key: "start_time", label: "Time", render: e => `<span class="nowrap">${esc(e.start_time)}–${esc(e.end_time)}</span><br><span class="muted small">${esc(e.session)} · ${esc(e.duration_minutes)} min</span>` },
        { key: "title", label: "Examination", render: e => `<b>${esc(e.title)}</b><br><span class="muted small">${esc(e.subject_code)}${e.subject_name ? " · " + esc(e.subject_name) : ""}</span>` },
        { key: "venue", label: "Venue / term", render: e => `${esc(e.venue)}${e.term_name ? `<br><span class="muted small">${esc(e.term_name)}</span>` : ""}` },
        { key: "status", label: "Status", render: e => EM.statusBadge(e.status) },
        { key: "allotment_count", label: "Seats", render: e => `${esc(e.allotment_count)}${e.eligibility_rule_count ? `<br><span class="muted small">${esc(e.eligibility_rule_count)} audience rule(s)</span>` : `<br><span class="muted small">all students</span>`}` },
      ], actions: e => `<button class="btn sm" data-act="edit" data-id="${e.id}">Edit</button><a class="btn sm" href="#/exams/${e.id}/audience">Audience</a><a class="btn sm" href="#/allocation?exam=${e.id}">Seats</a>${e.status === "draft" ? `<button class="btn sm primary" data-act="pub" data-id="${e.id}">Publish</button>` : e.status === "published" ? `<button class="btn sm" data-act="unpub" data-id="${e.id}">Unpublish</button>` : ""}${adm && e.status === "draft" ? `<button class="btn sm danger" data-act="del" data-id="${e.id}">Delete</button>` : ""}` });
      EM.pager($("#pg", root), { total: r.total, limit: LIMIT, offset, onPage: o => { offset = o; load().catch(EM.fail); } });
    }
    EM.onSubmit($("#flt", root), async () => { offset = 0; await load(); });
    $("#rst", root).onclick = () => setTimeout(() => { offset = 0; load().catch(EM.fail); }, 0);
    const byId = id => rows.find(x => x.id === Number(id));
    EM.delegate(root, {
      new: async () => { if (await examForm(null, subjects, terms)) { EM.toast("Examination created.", "ok"); await load(); } },
      edit: async b => { const e = byId(b.dataset.id); if (await examForm(e, subjects, terms)) { EM.toast("Examination updated.", "ok"); await load(); } },
      pub: async b => { const e = byId(b.dataset.id); if (!await EM.confirm({ title: "Publish examination?", message: `“${e.title}” on ${e.exam_date} becomes visible to students, including any seat allotments.`, confirmText: "Publish" })) return; await api(`/api/exams/${e.id}/publish`, { method: "POST" }); EM.toast("Examination published.", "ok"); await load(); },
      unpub: async b => { const e = byId(b.dataset.id); if (!await EM.confirm({ title: "Unpublish examination?", message: `Students will no longer see “${e.title}” or its seats.`, confirmText: "Unpublish" })) return; await api(`/api/exams/${e.id}/unpublish`, { method: "POST" }); EM.toast("Examination unpublished.", "ok"); await load(); },
      del: async b => { const e = byId(b.dataset.id); if (!await EM.confirm({ title: "Delete draft examination?", message: `Permanently delete “${e.title}”. Only drafts without seats or results can be deleted.`, confirmText: "Delete", danger: true })) return; await api("/api/exams/" + e.id, { method: "DELETE" }); EM.toast("Examination deleted.", "ok"); await load(); },
    });
    await load();
    if (ctx.query.new) EM.go("/exams", true);
  } });

  // ------------------------------------------------------------ audience (eligibility)
  async function audience(root, ctx, id) {
    const v = await api(`/api/exams/${id}/eligibility`);
    let rules = v.rules.slice();
    const info = `${v.eligible_count} of ${v.active_students} active students currently eligible.`;
    root.innerHTML = `<div class="stack"><div><a href="#/exams">← Examinations</a><h2 style="margin-top:8px">Audience for examination #${id}</h2><p class="muted">Rules combine as “any match”; a blank field matches anything. With <b>no rules</b>, every active student is eligible. Included students are always eligible; excluded students never are.</p></div>
      <section class="card"><div class="card-head"><h3>Rules</h3><span class="badge info" id="cnt">${esc(info)}</span></div><form id="rf" class="toolbar"><div class="field"><label>Department</label><input name="department" placeholder="blank = any"></div><div class="field"><label>Course</label><input name="course" placeholder="blank = any"></div><div class="field"><label>Year</label><input name="year" type="number" min="1" max="6" placeholder="any"></div><button class="btn">Add rule</button></form><div id="rl"></div></section>
      <section class="card"><div class="grid g2">${EM.field({ name: "include", label: "Always include (register numbers)", type: "textarea", value: v.include.join(" "), hint: "Separate with spaces, commas or new lines." })}${EM.field({ name: "exclude", label: "Always exclude (register numbers)", type: "textarea", value: v.exclude.join(" ") })}</div><div class="form-actions"><button class="btn primary" data-act="save">Save audience</button><a class="btn" href="#/exams">Close</a></div><div id="msg"></div></section></div>`;
    const draw = () => { $("#rl", root).innerHTML = rules.length ? `<div class="list">${rules.map((r, i) => `<div class="item row between"><span>${esc(r.department || "any department")} · ${esc(r.course || "any course")} · ${r.year ? "year " + esc(r.year) : "any year"}</span><button class="btn sm danger" data-act="rm" data-i="${i}">Remove</button></div>`).join("")}</div>` : EM.empty("No rules", "Every active student is eligible.");};
    draw();
    EM.onSubmit($("#rf", root), async (d, f) => { const r = { department: d.department || null, course: d.course || null, year: EM.num(d.year) }; if (!r.department && !r.course && !r.year) throw new Error("Enter a department, course or year."); rules.push(r); f.reset(); draw(); });
    const regs = t => t.split(/[\s,;]+/).map(x => x.trim()).filter(Boolean);
    EM.delegate(root, {
      rm: async b => { rules.splice(Number(b.dataset.i), 1); draw(); },
      save: async () => { try { const r = await api(`/api/exams/${id}/eligibility`, { method: "PUT", body: { rules, include: regs($("[name=include]", root).value), exclude: regs($("[name=exclude]", root).value) } }); rules = r.rules; draw(); $("#cnt", root).textContent = `${r.eligible_count} of ${r.active_students} active students currently eligible.`; $("#msg", root).innerHTML = EM.alert("Audience saved.", "ok"); EM.toast("Audience saved.", "ok"); } catch (e) { $("#msg", root).innerHTML = EM.alert(e.message, "bad"); } },
    });
  }

  // ------------------------------------------------------------ subjects
  EM.page({ name: "subjects", title: "Subject catalogue", roles: ["admin", "staff"], nav: { group: "Examinations", icon: "📚", label: "Subjects", order: 2 }, render: async root => {
    const adm = EM.isAdmin(); let subs = await api("/api/admin/subjects", { params: { limit: 500 } });
    root.innerHTML = `<div class="stack"><div class="row between"><p class="muted" style="margin:0">Subject codes used by examinations and timetable imports.</p><button class="btn primary" data-act="new">+ New subject</button></div><div id="g"></div></div>`;
    const form = s => EM.ask({ title: s ? "Edit subject " + s.code : "New subject", fields: [
      { name: "code", label: "Subject code", required: true, value: s && s.code }, { name: "name", label: "Subject name", required: true, value: s && s.name },
      { name: "department", label: "Department", value: s && s.department }, { name: "semester", label: "Semester", type: "number", attrs: 'min="1" max="12"', value: s && s.semester },
      { name: "credits", label: "Credits", type: "number", attrs: 'min="0" step="0.5"', value: s && s.credits }, { name: "active", label: "Active", type: "checkbox", value: s ? s.active : true }],
      submit: async d => { await api(s ? "/api/admin/subjects/" + s.id : "/api/admin/subjects", { method: s ? "PATCH" : "POST", body: { code: d.code, name: d.name, department: d.department || null, semester: EM.num(d.semester), credits: EM.num(d.credits), active: d.active } }); return true; } });
    const grid = EM.grid($("#g", root), { rows: subs, caption: "Subjects", searchPlaceholder: "Search code, name or department", searchKeys: ["code", "name", "department"], sortKey: "code", empty: { title: "No subjects yet", text: "Add the subjects your examinations use." }, columns: [
      { key: "code", label: "Code", render: s => `<b>${esc(s.code)}</b>` }, { key: "name", label: "Name" }, { key: "department", label: "Department", render: s => esc(s.department || "all") },
      { key: "semester", label: "Sem", render: s => esc(s.semester ?? "—") }, { key: "credits", label: "Credits", render: s => esc(s.credits ?? "—") }, { key: "active", label: "Status", render: s => EM.badge(s.active ? "Active" : "Inactive", s.active ? "ok" : "") }],
      actions: s => `<button class="btn sm" data-act="edit" data-id="${s.id}">Edit</button><button class="btn sm" data-act="tog" data-id="${s.id}">${s.active ? "Deactivate" : "Activate"}</button>${adm ? `<button class="btn sm danger" data-act="del" data-id="${s.id}">Delete</button>` : ""}` });
    const reload = async () => { subs = await api("/api/admin/subjects", { params: { limit: 500 } }); grid.setRows(subs); };
    const by = id => subs.find(x => x.id === Number(id));
    EM.delegate(root, {
      new: async () => { if (await form(null)) { EM.toast("Subject saved.", "ok"); await reload(); } },
      edit: async b => { if (await form(by(b.dataset.id))) { EM.toast("Subject updated.", "ok"); await reload(); } },
      tog: async b => { const s = by(b.dataset.id); await api("/api/admin/subjects/" + s.id, { method: "PATCH", body: { active: !s.active } }); EM.toast(s.active ? "Subject deactivated." : "Subject activated.", "ok"); await reload(); },
      del: async b => { const s = by(b.dataset.id); if (!await EM.confirm({ title: "Delete subject?", message: `Delete ${s.code} — ${s.name}. Subjects used by examinations cannot be deleted.`, confirmText: "Delete", danger: true })) return; await api("/api/admin/subjects/" + s.id, { method: "DELETE" }); EM.toast("Subject deleted.", "ok"); await reload(); },
    });
  } });

  // ------------------------------------------------------------ academic years and terms
  EM.page({ name: "terms", title: "Academic years & terms", roles: ["admin", "staff"], nav: { group: "Examinations", icon: "🗂", label: "Years & terms", order: 3 }, render: async root => {
    const adm = EM.isAdmin();
    let [years, terms] = await Promise.all([api("/api/admin/academic-years"), api("/api/admin/terms")]);
    const yl = id => (years.find(y => y.id === id) || {}).label || "";
    root.innerHTML = `<div class="stack">${adm ? "" : EM.alert("Only administrators can add or change academic years and terms.", "info")}
      <section class="card"><div class="card-head"><h2>Academic years</h2>${adm ? `<button class="btn primary" data-act="newy">+ Academic year</button>` : ""}</div><div id="gy"></div></section>
      <section class="card"><div class="card-head"><h2>Examination terms</h2>${adm ? `<button class="btn primary" data-act="newt">+ Term</button>` : ""}</div><p class="muted small">An examination's date must fall inside its term.</p><div id="gt"></div></section></div>`;
    const yearForm = y => EM.ask({ title: y ? "Edit academic year" : "New academic year", fields: [{ name: "label", label: "Label", required: true, value: y && y.label, hint: "e.g. 2026-27" }, { name: "start_date", label: "Start date", type: "date", required: true, value: y && y.start_date }, { name: "end_date", label: "End date", type: "date", required: true, value: y && y.end_date }, { name: "is_current", label: "Current academic year", type: "checkbox", value: y && y.is_current }],
      submit: async d => { await api(y ? "/api/admin/academic-years/" + y.id : "/api/admin/academic-years", { method: y ? "PATCH" : "POST", body: d }); return true; } });
    const termForm = t => EM.ask({ title: t ? "Edit term" : "New examination term", fields: [{ name: "academic_year_id", label: "Academic year", type: "select", required: true, options: opt(years, "id", y => y.label, "Select…"), value: t && t.academic_year_id }, { name: "name", label: "Term name", required: true, value: t && t.name, hint: "e.g. Nov–Dec End Semester" }, { name: "semester_no", label: "Semester (optional)", type: "number", attrs: 'min="1" max="12"', value: t && t.semester_no }, { name: "start_date", label: "Start date", type: "date", required: true, value: t && t.start_date }, { name: "end_date", label: "End date", type: "date", required: true, value: t && t.end_date }, { name: "active", label: "Active", type: "checkbox", value: t ? t.active : true }],
      submit: async d => { await api(t ? "/api/admin/terms/" + t.id : "/api/admin/terms", { method: t ? "PATCH" : "POST", body: { ...d, academic_year_id: EM.num(d.academic_year_id), semester_no: EM.num(d.semester_no) } }); return true; } });
    const gy = EM.grid($("#gy", root), { rows: years, search: false, caption: "Academic years", empty: { title: "No academic years" }, columns: [{ key: "label", label: "Year", render: y => `<b>${esc(y.label)}</b>` }, { key: "start_date", label: "Starts" }, { key: "end_date", label: "Ends" }, { key: "is_current", label: "Current", render: y => y.is_current ? EM.badge("Current", "ok") : "" }], actions: adm ? y => `<button class="btn sm" data-act="edity" data-id="${y.id}">Edit</button>` : null });
    const gt = EM.grid($("#gt", root), { rows: terms, search: false, caption: "Examination terms", empty: { title: "No terms" }, columns: [{ key: "name", label: "Term", render: t => `<b>${esc(t.name)}</b>` }, { key: "ay", label: "Academic year", value: t => yl(t.academic_year_id), render: t => esc(yl(t.academic_year_id)) }, { key: "semester_no", label: "Sem", render: t => esc(t.semester_no ?? "—") }, { key: "start_date", label: "Starts" }, { key: "end_date", label: "Ends" }, { key: "active", label: "Status", render: t => EM.badge(t.active ? "Active" : "Inactive", t.active ? "ok" : "") }], actions: adm ? t => `<button class="btn sm" data-act="editt" data-id="${t.id}">Edit</button>` : null });
    const reload = async () => { [years, terms] = await Promise.all([api("/api/admin/academic-years"), api("/api/admin/terms")]); gy.setRows(years); gt.setRows(terms); };
    EM.delegate(root, {
      newy: async () => { if (await yearForm(null)) { EM.toast("Academic year added.", "ok"); await reload(); } },
      edity: async b => { if (await yearForm(years.find(y => y.id === Number(b.dataset.id)))) { EM.toast("Academic year updated.", "ok"); await reload(); } },
      newt: async () => { if (!years.length) { EM.toast("Add an academic year first.", "bad"); return; } if (await termForm(null)) { EM.toast("Term added.", "ok"); await reload(); } },
      editt: async b => { if (await termForm(terms.find(t => t.id === Number(b.dataset.id)))) { EM.toast("Term updated.", "ok"); await reload(); } },
    });
  } });
})();
