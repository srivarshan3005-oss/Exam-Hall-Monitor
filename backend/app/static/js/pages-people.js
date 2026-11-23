/* People: student registry, user accounts and permissions, results publication. */
(function () {
  "use strict";
  const { $, esc, api } = EM;
  const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

  // ------------------------------------------------------------ students
  EM.page({ name: "students", title: "Students", roles: ["admin", "staff"], nav: { group: "People", icon: "🧑‍🎓", label: "Students", order: 1 }, render: async root => {
    const adm = EM.isAdmin(), u = EM.state.user; let rows = [];
    root.innerHTML = `<div class="stack">${u.role === "staff" && u.department ? EM.alert(`Your account is limited to the ${u.department} department; the server only returns those students.`, "info") : ""}
      <div class="row between"><div class="field grow" style="max-width:420px"><label for="q">Search register number or name</label><input id="q" type="search" placeholder="Type at least one character"></div>${adm ? `<button class="btn primary" data-act="new">+ New student</button>` : ""}</div>
      <div id="note"></div><div id="g"></div></div>`;
    const grid = EM.grid($("#g", root), { rows, search: false, caption: "Students", empty: { title: "No students found", text: adm ? "Add a student or refine the search." : "Refine the search." }, columns: [
      { key: "register_number", label: "Register number", render: s => `<span class="mono">${esc(s.register_number)}</span>` }, { key: "full_name", label: "Name" }, { key: "department", label: "Department" }, { key: "course", label: "Course", render: s => esc(s.course || "—") }, { key: "year", label: "Year" }, { key: "active", label: "Status", render: s => EM.badge(s.active ? "Active" : "Inactive", s.active ? "ok" : "") }],
      actions: s => `<button class="btn sm" data-act="seats" data-id="${esc(s.register_number)}">Seats</button>${adm ? `<button class="btn sm" data-act="edit" data-id="${esc(s.register_number)}">Edit</button>` : ""}` });
    async function load() {
      rows = await api("/api/students", { params: { q: $("#q", root).value.trim(), limit: 200 } }); grid.setRows(rows);
      $("#note", root).innerHTML = rows.length >= 200 ? EM.alert("Showing the first 200 matches. Use the search box to narrow the list.", "info") : "";
    }
    $("#q", root).addEventListener("input", debounce(() => load().catch(EM.fail), 300));
    const form = s => EM.ask({ title: s ? "Edit student " + s.register_number : "New student", fields: (s ? [] : [{ name: "register_number", label: "Register number", required: true, attrs: 'inputmode="numeric"' }]).concat([
      { name: "full_name", label: "Full name", required: true, value: s && s.full_name }, { name: "department", label: "Department", required: true, value: s && s.department },
      { name: "course", label: "Course", value: s && s.course }, { name: "year", label: "Year (1–6)", type: "number", required: true, attrs: 'min="1" max="6"', value: s && s.year },
      { name: "email", label: "E-mail", type: "email", hint: s ? "Leave blank to keep the current e-mail." : "Optional. Needed for student self-registration." }].concat(s ? [{ name: "active", label: "Active", type: "checkbox", value: s.active }] : [])),
      submit: async d => {
        if (!s) { const b = { ...d, year: Number(d.year) }; ["email", "course"].forEach(k => { if (!b[k]) delete b[k]; }); await api("/api/students", { method: "POST", body: b }); }
        else { const b = { full_name: d.full_name, department: d.department, year: Number(d.year), active: d.active, course: d.course || null }; if (d.email) b.email = d.email; await api("/api/students/" + encodeURIComponent(s.register_number), { method: "PATCH", body: b }); }
        return true;
      } });
    EM.delegate(root, {
      new: async () => { if (await form(null)) { EM.toast("Student record created.", "ok"); await load(); } },
      edit: async b => { if (await form(rows.find(x => x.register_number === b.dataset.id))) { EM.toast("Student updated.", "ok"); await load(); } },
      seats: async b => {
        const r = await api("/api/admin/reports/students/seats", { params: { q: b.dataset.id } }), s = r.find(x => x.register_number === b.dataset.id) || r[0];
        await EM.show("Seats · " + b.dataset.id, s && s.allotments.length ? `<div class="list">${s.allotments.map(a => `<div class="item"><div class="t">${esc(a.exam)} ${EM.statusBadge(a.status)}</div><div class="m">${esc(a.date)} ${esc(a.start_time)} · Hall ${esc(a.hall)} · Seat ${esc(a.seat)}</div></div>`).join("")}</div>` : EM.empty("No seats allotted"));
      },
    });
    await load();
  } });

  // ------------------------------------------------------------ accounts
  const when = s => (s ? EM.fmtDT(s) : "never");
  EM.page({ name: "accounts", title: "User accounts & permissions", roles: ["admin"], nav: { group: "Administration", icon: "👥", label: "Accounts", order: 1 }, render: async root => {
    const roles = (await api("/api/admin/roles")).roles; let users = [];
    root.innerHTML = `<div class="stack"><div class="row between"><p class="muted" style="margin:0">Roles: ${roles.map(r => esc(r.label)).join(" · ")}. ${EM.role() === "super_admin" ? "As super administrator you may also manage administrator accounts." : "Only a super administrator can grant or change administrator roles."}</p><button class="btn primary" data-act="new">+ New account</button></div>
      <form id="flt" class="toolbar card flat" style="padding:12px;margin:0"><div class="field wide"><label>Search</label><input name="q" placeholder="Username or e-mail"></div><div class="field"><label>Role</label><select name="role"><option value="">Any</option>${roles.map(r => `<option value="${r.role}">${esc(r.label)}</option>`).join("")}</select></div>
      <div class="field"><label>Status</label><select name="status"><option value="">Any</option><option>active</option><option>pending</option><option>suspended</option></select></div><div class="field"><label>Department</label><input name="department"></div><button class="btn primary">Filter</button><button class="btn" type="reset" id="rst">Reset</button></form><div id="g"></div></div>`;
    const assignable = roles.filter(r => r.assignable);
    const grid = EM.grid($("#g", root), { rows: users, search: false, caption: "User accounts", empty: { title: "No matching accounts" }, columns: [
      { key: "username", label: "User", render: u => `<b>${esc(u.username)}</b>${u.email ? `<br><span class="muted small">${esc(u.email)}</span>` : ""}` }, { key: "role_label", label: "Role" }, { key: "department", label: "Department", render: u => esc(u.department || "—") },
      { key: "status", label: "Status", render: u => EM.statusBadge(u.status) + (u.locked ? EM.badge("locked", "bad") : "") + (u.pw_change_required ? EM.badge("must change password", "warn") : "") }, { key: "last_login_at", label: "Last sign-in", render: u => esc(when(u.last_login_at)) }],
      actions: u => `${u.status === "active" ? `<button class="btn sm" data-act="suspend" data-id="${esc(u.username)}">Suspend</button>` : `<button class="btn sm primary" data-act="restore" data-id="${esc(u.username)}">${u.status === "pending" ? "Approve" : "Restore"}</button>`}<button class="btn sm" data-act="role" data-id="${esc(u.username)}">Role</button><button class="btn sm" data-act="reset" data-id="${esc(u.username)}">Reset password</button><button class="btn sm" data-act="logout" data-id="${esc(u.username)}">Sign out</button>${u.locked ? `<button class="btn sm" data-act="unlock" data-id="${esc(u.username)}">Unlock</button>` : ""}<button class="btn sm" data-act="activity" data-id="${esc(u.username)}">Activity</button>` });
    async function load() { const r = await EM.apiList("/api/admin/users", { ...EM.formData($("#flt", root)), limit: 500 }); users = r.rows; grid.setRows(users); }
    EM.onSubmit($("#flt", root), load); $("#rst", root).onclick = () => setTimeout(() => load().catch(EM.fail), 0);
    const U = b => users.find(x => x.username === b.dataset.id), base = b => "/api/admin/users/" + encodeURIComponent(b.dataset.id);
    EM.delegate(root, {
      new: async () => { if (await EM.ask({ title: "New account", fields: [
        { name: "username", label: "Username", required: true, hint: "3–40 letters, digits, dot, dash, underscore." }, { name: "password", label: "Initial password", type: "password", required: true, hint: "12+ characters with letters and digits.", attrs: 'autocomplete="new-password"' },
        { name: "role", label: "Role", type: "select", required: true, options: assignable.map(r => [r.role, r.label]) }, { name: "email", label: "E-mail (for password recovery)", type: "email" },
        { name: "department", label: "Department (limits department staff to that department)" }, { name: "student_register_number", label: "Student register number (student role only)", hint: "Links the account to the student's record." },
        { name: "require_password_change", label: "Require a password change at first sign-in", type: "checkbox", value: true }],
        submit: async d => { const b = { ...d }; ["email", "department", "student_register_number"].forEach(k => { if (!b[k]) delete b[k]; }); await api("/api/admin/users", { method: "POST", body: b }); return true; } })) { EM.toast("Account created.", "ok"); await load(); } },
      suspend: async b => { const r = await EM.ask({ title: "Suspend " + b.dataset.id, message: "They are signed out immediately and cannot sign in until restored.", danger: true, submitText: "Suspend", fields: [{ name: "reason", label: "Reason (optional, kept in the audit trail)" }] }); if (!r) return; await api(base(b) + "/suspend", { method: "POST", body: { reason: r.reason || null } }); EM.toast(b.dataset.id + " suspended.", "ok"); await load(); },
      restore: async b => { await api(base(b) + "/restore", { method: "POST", body: {} }); EM.toast(b.dataset.id + " is active.", "ok"); await load(); },
      unlock: async b => { await api(base(b), { method: "PATCH", body: { unlock: true } }); EM.toast(b.dataset.id + " unlocked.", "ok"); await load(); },
      logout: async b => { if (!await EM.confirm({ title: "Force sign-out?", message: `End every active session of ${b.dataset.id}.`, confirmText: "Sign out user" })) return; await api(base(b) + "/force-logout", { method: "POST" }); EM.toast("Sessions ended.", "ok"); },
      role: async b => { const u = U(b), r = await EM.ask({ title: "Change role of " + u.username, message: "They are signed out and must sign in again with the new role.", submitText: "Change role", fields: [{ name: "role", label: "Role", type: "select", options: roles.map(x => [x.role, x.label + (x.assignable || x.role === u.role ? "" : " (not allowed for you)")]), value: u.role }] }); if (!r || r.role === u.role) return; await api(base(b), { method: "PATCH", body: { role: r.role } }); EM.toast(`${u.username} is now ${r.role}.`, "ok"); await load(); },
      reset: async b => { const r = await EM.ask({ title: "Reset password of " + b.dataset.id, message: "A temporary password is generated and shown once. They must change it at next sign-in.", danger: true, submitText: "Reset password", fields: [{ name: "reason", label: "Reason (required, recorded in the audit trail)", required: true, hint: "At least 5 characters." }] }); if (!r) return;
        const res = await api(base(b) + "/reset-password", { method: "POST", body: { reason: r.reason } }); await EM.show("Temporary password", `<p>Copy it now — it is shown only once. Give it to <b>${esc(b.dataset.id)}</b> through a secure channel.</p><input readonly value="${esc(res.temporary_password)}" class="mono" id="tmpPw" aria-label="Temporary password">`, d => { const i = d.querySelector("#tmpPw"); i.focus(); i.select(); }); await load(); },
      activity: async b => { const d = await api(base(b) + "/activity"); await EM.show("Activity · " + b.dataset.id, `<h3>Security events</h3>${d.security_events.length ? `<div class="list scroll">${d.security_events.map(e => `<div class="item ${e.severity === "critical" ? "bad" : e.severity === "warning" ? "warn" : ""}"><div class="t">${esc(e.event_type)}</div><div class="m">${EM.fmtDT(e.created_at)} · ${esc(e.ip || "")} ${esc(e.detail || "")}</div></div>`).join("")}</div>` : EM.empty("No security events")}<h3 style="margin-top:12px">Audit trail</h3>${d.audit.length ? `<div class="list scroll">${d.audit.map(a => `<div class="item"><div class="t">${esc(a.action)}</div><div class="m">${EM.fmtDT(a.created_at)} · ${esc(a.actor)} · ${esc(a.target)}</div></div>`).join("")}</div>` : EM.empty("No audit records")}`); },
    });
    await load();
  } });

  // ------------------------------------------------------------ results (administrator)
  EM.page({ name: "results", title: "Results", roles: ["admin"], nav: { group: "Examinations", icon: "🎓", label: "Results", order: 5 }, render: async root => {
    const exams = (await EM.apiList("/api/admin/exams", { limit: 500 })).rows, LIMIT = 50; let offset = 0, rows = [];
    root.innerHTML = `<div class="stack"><div class="row between"><p class="muted" style="margin:0">Results become visible to the student (and staff) only when <b>published</b>. Marks are never written to the audit log.</p><button class="btn primary" data-act="new">+ Add result</button></div>
      <form id="flt" class="toolbar card flat" style="padding:12px;margin:0"><div class="field wide"><label>Search</label><input name="q" placeholder="Register number or name"></div><div class="field"><label>Examination</label><select name="exam_id"><option value="">Any</option>${exams.map(e => `<option value="${e.id}">#${e.id} ${esc(e.title)}</option>`).join("")}</select></div><div class="field"><label>Publication</label><select name="published"><option value="">Any</option><option value="true">Published</option><option value="false">Not published</option></select></div><button class="btn primary">Filter</button></form><div id="g"></div><div id="pg"></div></div>`;
    const g = $("#g", root);
    async function load() {
      const r = await EM.apiList("/api/results/admin/list", { ...EM.formData($("#flt", root)), limit: LIMIT, offset }); rows = r.rows;
      EM.grid(g, { rows, search: false, pageSize: 100, caption: "Results", empty: { title: "No results recorded", text: "Add results, then publish them." }, columns: [
        { key: "register_number", label: "Register number", render: x => `<span class="mono">${esc(x.register_number)}</span><br><span class="muted small">${esc(x.student_name)}</span>` }, { key: "exam", label: "Examination", render: x => `${esc(x.exam)}<br><span class="muted small">${esc(x.subject_code)}</span>` },
        { key: "marks", label: "Marks", render: x => `${esc(x.marks)} / ${esc(x.max_marks)}` }, { key: "grade", label: "Grade" }, { key: "published", label: "Status", render: x => EM.badge(x.published ? "Published" : "Not published", x.published ? "ok" : "warn") }],
        actions: x => x.published ? `<button class="btn sm" data-act="unpub" data-id="${x.id}">Unpublish</button>` : `<button class="btn sm primary" data-act="pub" data-id="${x.id}">Publish</button>` });
      EM.pager($("#pg", root), { total: r.total, limit: LIMIT, offset, onPage: o => { offset = o; load().catch(EM.fail); } });
    }
    EM.onSubmit($("#flt", root), async () => { offset = 0; await load(); });
    EM.delegate(root, {
      new: async () => { if (await EM.ask({ title: "Add result", fields: [{ name: "register_number", label: "Student register number", required: true, attrs: 'inputmode="numeric"' }, { name: "exam_id", label: "Examination", type: "select", required: true, options: [["", "Select…"]].concat(exams.map(e => [e.id, `#${e.id} ${e.title} · ${e.exam_date}`])) }, { name: "marks", label: "Marks", type: "number", required: true, attrs: 'min="0" step="0.01"' }, { name: "max_marks", label: "Maximum marks", type: "number", required: true, attrs: 'min="0.01" step="0.01"' }, { name: "grade", label: "Grade", value: "—", hint: "Up to 5 characters." }, { name: "published", label: "Publish immediately", type: "checkbox" }],
        submit: async d => { await api("/api/results", { method: "POST", body: { register_number: d.register_number, exam_id: Number(d.exam_id), marks: Number(d.marks), max_marks: Number(d.max_marks), grade: d.grade || "—", published: d.published } }); return true; } })) { EM.toast("Result saved.", "ok"); await load(); } },
      pub: async b => { if (!await EM.confirm({ title: "Publish result?", message: "The student will be able to see this result.", confirmText: "Publish" })) return; await api(`/api/results/${b.dataset.id}/publish`, { method: "POST" }); EM.toast("Result published.", "ok"); await load(); },
      unpub: async b => { if (!await EM.confirm({ title: "Unpublish result?", message: "The student will no longer see this result.", confirmText: "Unpublish" })) return; await api(`/api/results/${b.dataset.id}/unpublish`, { method: "POST" }); EM.toast("Result unpublished.", "ok"); await load(); },
    });
    await load();
  } });
})();
