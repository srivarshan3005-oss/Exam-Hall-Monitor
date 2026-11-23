/* Security dashboard, audit history, and "My account" (all roles). */
(function () {
  "use strict";
  const { $, esc, api } = EM;
  const SEV = { critical: "bad", warning: "warn", info: "" };

  EM.page({ name: "security", title: "Security dashboard", roles: ["admin"], nav: { group: "Administration", icon: "🛡", label: "Security", order: 3 }, render: async root => {
    const LIMIT = 50; let offset = 0, hours = 24;
    root.innerHTML = `<div class="stack"><div class="toolbar"><div class="field" style="max-width:200px"><label for="hrs">Summary window</label><select id="hrs"><option value="24">Last 24 hours</option><option value="168">Last 7 days</option><option value="720">Last 30 days</option></select></div></div><div id="sum">${EM.loading()}</div>
      <section class="card"><div class="card-head"><h3>Security events</h3></div><form id="flt" class="toolbar"><div class="field"><label>Event type</label><select name="type"><option value="">Any</option><option value="auth.login">Sign-ins (incl. failures)</option><option value="auth.login_failed">Failed sign-ins</option><option value="auth.account_locked">Lockouts</option><option value="authz.denied">Permission denied</option><option value="auth.reset">Password reset</option><option value="account.">Account changes</option></select></div>
      <div class="field"><label>Severity</label><select name="severity"><option value="">Any</option><option>info</option><option>warning</option><option>critical</option></select></div><div class="field"><label>Username</label><input name="username"></div><div class="field"><label>IP address</label><input name="ip"></div><div class="field"><label>Search</label><input name="q"></div><div class="field"><label>From</label><input type="date" name="since"></div><div class="field"><label>To</label><input type="date" name="until"></div><button class="btn primary">Filter</button></form><div id="ev"></div><div id="pg"></div></section>
      <section class="card"><div class="card-head"><h3>Active sessions</h3></div><div id="ses">${EM.loading()}</div></section></div>`;
    const stat = (n, l) => `<div class="stat"><span class="n">${esc(n)}</span><span class="l">${esc(l)}</span></div>`;
    async function summary() {
      const s = await api("/api/admin/security/summary", { params: { hours } });
      $("#sum", root).innerHTML = `<div class="grid g4">${stat(s.successful_logins, "sign-ins")}${stat(s.failed_logins, "failed sign-ins")}${stat(s.lockouts, "lockouts")}${stat(s.permission_denials, "permission denials")}${stat(s.rate_limited, "rate-limited")}${stat(s.password_resets, "password resets")}${stat(s.role_changes, "role changes")}${stat(s.critical_events, "critical events")}</div>
        <div class="grid g2" style="margin-top:16px"><div class="card flat"><h4>Accounts</h4><p class="small">${Object.entries(s.accounts_by_status).map(([k, v]) => esc(k) + ": <b>" + esc(v) + "</b>").join(" · ") || "—"}<br>${Object.entries(s.accounts_by_role).map(([k, v]) => esc(k) + ": " + esc(v)).join(" · ")}</p><p class="small">Locked accounts: ${s.locked_accounts.map(esc).join(", ") || "none"}<br>Active sessions: <b>${esc(s.active_sessions)}</b></p></div><div class="card flat"><h4>Top failing IP addresses</h4>${s.top_failed_login_ips.length ? `<div class="list">${s.top_failed_login_ips.map(i => `<div class="item row between"><span class="mono">${esc(i.ip)}</span><b>${esc(i.count)}</b></div>`).join("")}</div>` : EM.empty("None")}</div></div>`;
    }
    async function events() {
      const r = await EM.apiList("/api/admin/security/events", { ...EM.formData($("#flt", root)), limit: LIMIT, offset });
      EM.grid($("#ev", root), { rows: r.rows, search: false, pageSize: 100, caption: "Security events", empty: { title: "No events match" }, columns: [{ key: "created_at", label: "When", render: e => esc(EM.fmtDT(e.created_at)) }, { key: "severity", label: "Severity", render: e => EM.badge(e.severity, SEV[e.severity]) }, { key: "event_type", label: "Event", render: e => `<b>${esc(e.event_type)}</b>` }, { key: "username", label: "User", render: e => esc(e.username || "—") }, { key: "ip", label: "IP", render: e => esc(e.ip || e.ip_address || "") }, { key: "detail", label: "Detail", render: e => esc(e.detail || "") }] });
      EM.pager($("#pg", root), { total: r.total, limit: LIMIT, offset, onPage: o => { offset = o; events().catch(EM.fail); } });
    }
    $("#hrs", root).onchange = e => { hours = Number(e.target.value); summary().catch(EM.fail); };
    EM.onSubmit($("#flt", root), async () => { offset = 0; await events(); });
    await Promise.all([summary(), events()]);
    const ss = await api("/api/admin/security/sessions");
    EM.grid($("#ses", root), { rows: ss, search: false, caption: "Active sessions", empty: { title: "No active sessions" }, columns: [{ key: "username", label: "User", render: x => `<b>${esc(x.username)}</b> <span class="muted small">${esc(x.role)}</span>` }, { key: "created_at", label: "Since", render: x => esc(EM.fmtDT(x.created_at)) }, { key: "last_seen_at", label: "Last seen", render: x => esc(EM.fmtDT(x.last_seen_at)) }, { key: "ip", label: "IP", render: x => esc(x.ip || "") }] });
  } });

  EM.page({ name: "audit", title: "Audit history", roles: ["admin"], nav: { group: "Administration", icon: "🧾", label: "Audit history", order: 4 }, render: async root => {
    const LIMIT = 50; let offset = 0;
    root.innerHTML = `<div class="stack"><p class="muted" style="margin:0">A tamper-evident record of administrative actions. Passwords, tokens and marks are never stored here.</p><form id="flt" class="toolbar card flat" style="padding:12px;margin:0"><div class="field wide"><label>Search</label><input name="q"></div><div class="field"><label>Actor</label><input name="actor"></div><div class="field"><label>Action prefix</label><input name="action" placeholder="e.g. user."></div><div class="field"><label>From</label><input type="date" name="since"></div><div class="field"><label>To</label><input type="date" name="until"></div><button class="btn primary">Filter</button><button class="btn" type="reset" id="rst">Reset</button></form><div id="g"></div><div id="pg"></div></div>`;
    async function load() {
      const r = await EM.apiList("/api/admin/audit", { ...EM.formData($("#flt", root)), limit: LIMIT, offset });
      EM.grid($("#g", root), { rows: r.rows, search: false, pageSize: 100, caption: "Audit history", empty: { title: "No audit records match" }, columns: [{ key: "created_at", label: "When", render: a => esc(EM.fmtDT(a.created_at)) }, { key: "actor", label: "Actor", render: a => `${esc(a.actor)}<br><span class="muted small">${esc(a.role || "")}</span>` }, { key: "action", label: "Action", render: a => `<b>${esc(a.action)}</b>` }, { key: "target", label: "Target" }, { key: "details", label: "Details", render: a => esc(a.details || "") }, { key: "ip", label: "IP", render: a => esc(a.ip || "") }] });
      EM.pager($("#pg", root), { total: r.total, limit: LIMIT, offset, onPage: o => { offset = o; load().catch(EM.fail); } });
    }
    EM.onSubmit($("#flt", root), async () => { offset = 0; await load(); }); $("#rst", root).onclick = () => setTimeout(() => { offset = 0; load().catch(EM.fail); }, 0);
    await load();
  } });

  EM.page({ name: "account", title: "My account", nav: { group: "Account", icon: "👤", label: "My account", order: 1 }, roles: ["admin", "staff", "invigilator", "student"], render: async root => {
    const [pf, ss] = await Promise.all([api("/api/auth/profile"), api("/api/auth/sessions")]);
    root.innerHTML = `<div class="grid g2"><div class="stack"><section class="card"><h3>Signed in</h3><dl class="kv"><dt>Username</dt><dd>${esc(pf.username)}</dd><dt>Role</dt><dd>${esc(pf.role_label)}</dd>${pf.department ? `<dt>Department</dt><dd>${esc(pf.department)}</dd>` : ""}${pf.email ? `<dt>E-mail</dt><dd>${esc(pf.email)}</dd>` : ""}${pf.register_number ? `<dt>Register number</dt><dd class="mono">${esc(pf.register_number)}</dd>` : ""}</dl></section>
      <section class="card"><h3>Change password</h3><p class="muted small">You will be signed out of other devices.</p><form id="pw" class="stack">${EM.field({ name: "current_password", label: "Current password", type: "password", required: true, attrs: 'autocomplete="current-password"' })}${EM.field({ name: "new_password", label: "New password", type: "password", required: true, hint: "At least 12 characters with letters and digits.", attrs: 'autocomplete="new-password"' })}<button class="btn primary">Change password</button></form></section></div>
      <section class="card"><div class="card-head"><h3>My active sessions</h3><button class="btn danger" data-act="all">Sign out everywhere</button></div><div class="list">${ss.map(s => `<div class="item row between"><div><div class="t">${s.current ? "This device (current)" : "Session #" + esc(s.id)}</div><div class="m">Started ${esc(EM.fmtDT(s.created_at))} · last used ${esc(EM.fmtDT(s.last_seen_at))}${s.ip ? " · " + esc(s.ip) : ""}</div></div>${s.current ? "" : `<button class="btn sm" data-act="end" data-id="${esc(s.id)}">End</button>`}</div>`).join("") || EM.empty("No sessions")}</div></section></div>`;
    EM.onSubmit($("#pw", root), async (d, f) => { const r = await api("/api/auth/change-password", { method: "POST", body: d }); EM.saveToken(r.access_token); f.reset(); EM.toast(r.detail || "Password changed.", "ok"); EM.route(); });
    EM.delegate(root, {
      all: async () => { if (await EM.confirm({ title: "Sign out of every device?", message: "You will need to sign in again everywhere, including here.", confirmText: "Sign out everywhere" })) await EM.logout(true); },
      end: async b => { await api("/api/auth/sessions/" + encodeURIComponent(b.dataset.id), { method: "DELETE" }); EM.toast("Session ended.", "ok"); EM.route(); },
    });
  } });


  EM.page({ name: "database", title: "Database administration", roles: ["admin"], nav: { group: "Administration", icon: "🗄", label: "Database", order: 5 }, render: async root => {
    root.innerHTML = `<div class="stack">
      <section class="card"><div class="card-head"><h3>Database health</h3><button class="btn" id="db-refresh">Refresh</button></div><div id="db-status">${EM.loading()}</div></section>
      <div class="grid g2"><section class="card"><div class="card-head"><h3>Backups</h3><button class="btn primary" id="db-backup">Create backup</button></div><p class="muted small">Verified archives include a consistent database snapshot and uploaded documents. Restore remains an offline CLI operation.</p><div id="db-backups"></div></section>
      <section class="card"><h3>Integrity report</h3><div id="db-integrity">${EM.loading()}</div></section></div>
      <section class="card"><h3>Migration history</h3><div id="db-migrations"></div></section>
      <section class="card"><h3>Data export</h3><div class="toolbar"><label>Dataset <select id="db-dataset"><option>students</option><option>exams</option><option>allotments</option><option>results</option></select></label><label>Format <select id="db-format"><option>csv</option><option>xlsx</option><option>json</option><option>pdf</option></select></label><button class="btn" id="db-export">Export</button></div></section>
      <section class="card"><h3>Student import</h3><p class="muted small">Upload CSV, XLSX or JSON. Preview validation before committing.</p><form id="db-import" class="toolbar"><input type="file" name="file" accept=".csv,.xlsx,.xlsm,.json" required><button class="btn" type="submit">Preview import</button><button class="btn primary" type="button" id="db-commit" disabled>Commit preview</button></form><pre id="db-import-result" class="small"></pre></section>
    </div>`;
    let previewReady = false;
    async function load() {
      const [st, backups, integrity, migrations] = await Promise.all([
        api("/api/admin/data/status"), api("/api/admin/data/backups"),
        api("/api/admin/data/integrity"), api("/api/admin/data/migrations")
      ]);
      $("#db-status", root).innerHTML = `<div class="grid g3"><div><b>${esc(st.database_type)}</b><div class="muted small">Database engine</div></div><div><b>${esc(st.tables)}</b><div class="muted small">Tables</div></div><div><b>${esc(st.migration_revision || "none")} / ${esc(st.migration_head)}</b><div class="muted small">Migration revision</div></div></div><p>${st.migration_revision === st.migration_head ? EM.badge("Up to date", "ok") : EM.badge("Migration pending", "warn")}</p>`;
      $("#db-backups", root).innerHTML = backups.backups.length ? `<div class="list">${backups.backups.map(b => `<div class="item"><div class="row between"><b>${esc(b.filename)}</b>${EM.badge(b.verified ? "Verified" : "Invalid", b.verified ? "ok" : "bad")}</div><div class="muted small">${esc(EM.fmtDT(b.created_at))} · ${esc(Math.round(b.size_bytes/1024))} KB</div>${b.verified ? `<div class="row"><button class="btn sm" data-verify="${esc(b.filename)}">Verify</button><button class="btn sm" data-download="${esc(b.filename)}">Download</button></div>` : `<p class="small">${esc(b.error || "")}</p>`}</div>`).join("")}</div>` : EM.empty("No backups yet");
      $("#db-integrity", root).innerHTML = `<p>${(integrity.healthy ?? integrity.ok) ? EM.badge("Integrity OK", "ok") : EM.badge("Attention required", "bad")}</p><pre class="pre small">${esc(JSON.stringify(integrity, null, 2))}</pre>`;
      $("#db-migrations", root).innerHTML = `<p>${migrations.up_to_date ? EM.badge("Schema current", "ok") : EM.badge("Upgrade required", "warn")}</p><div class="list">${migrations.history.map(m => `<div class="item"><b>${esc(m.revision)}</b> · ${esc(m.description || "")}</div>`).join("")}</div>`;
    }
    $("#db-refresh", root).onclick = () => load().catch(EM.fail);
    $("#db-backup", root).onclick = async () => { if (!await EM.confirm({title:"Create database backup?", message:"A verified snapshot will be created."})) return; await api("/api/admin/data/backups", {method:"POST"}); EM.toast("Backup created.", "ok"); await load(); };
    root.addEventListener("click", async e => {
      const v = e.target.closest("[data-verify]"); const d = e.target.closest("[data-download]");
      if (v) { const r = await api("/api/admin/data/backups/" + encodeURIComponent(v.dataset.verify) + "/verify"); EM.toast(r.verified ? "Backup verified." : "Backup verification failed.", r.verified ? "ok" : "error"); }
      if (d) { const url = "/api/admin/data/backups/" + encodeURIComponent(d.dataset.download) + "/download"; await EM.download(url, d.dataset.download); }
    });
    $("#db-export", root).onclick = () => { const ds=$("#db-dataset",root).value, fmt=$("#db-format",root).value; EM.download("/api/admin/data/export/"+encodeURIComponent(ds)+"?format="+encodeURIComponent(fmt), "exam_monitor_"+ds+"."+fmt).catch(EM.fail); };
    $("#db-import", root).onsubmit = async e => { e.preventDefault(); const file=e.currentTarget.querySelector('input[type=file]').files[0]; if(!file) return; const fd=new FormData(); fd.append("file",file); const r=await fetch("/api/admin/data/import/students?mode=preview", {method:"POST",headers:{Authorization:"Bearer "+EM.state.token},body:fd}); const data=await r.json(); if(!r.ok) throw new Error(data.detail || "Import preview failed"); $("#db-import-result",root).textContent=JSON.stringify(data,null,2); previewReady=data.invalid_rows===0 && data.valid_rows>0; $("#db-commit",root).disabled=!previewReady; };
    $("#db-commit", root).onclick = async () => { if(!previewReady || !await EM.confirm({title:"Commit student import?",message:"This will insert the validated preview rows."})) return; const file=$("#db-import input[type=file]",root).files[0]; const fd=new FormData(); fd.append("file",file); const r=await fetch("/api/admin/data/import/students?mode=commit&confirm=true",{method:"POST",headers:{Authorization:"Bearer "+EM.state.token},body:fd}); const data=await r.json(); if(!r.ok) throw new Error(data.detail || "Import failed"); $("#db-import-result",root).textContent=JSON.stringify(data,null,2); previewReady=false; $("#db-commit",root).disabled=true; await load(); };
    await load();
  } });

})();
