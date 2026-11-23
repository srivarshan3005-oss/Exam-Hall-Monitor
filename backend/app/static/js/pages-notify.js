/* Phase 6: notification centre, preferences, and the administrators' communication controls. */
(function () {
  "use strict";
  const { $, esc, api } = EM;
  const PRIO = { urgent: "bad", high: "warn", normal: "", low: "" };
  const DSTATUS = { sent: "ok", outbox: "info", queued: "", sending: "", retrying: "warn", failed: "bad", not_configured: "warn" };

  // ------------------------------------------------------------ notification centre (every signed-in role)
  EM.page({ name: "notifications", title: "Notifications", nav: { group: "Overview", icon: "🔔", label: "Notifications", order: 2.5 }, render: async root => {
    const LIMIT = 15; let offset = 0;
    root.innerHTML = `<div class="stack"><section class="card"><form id="flt" class="toolbar" role="search" aria-label="Filter notifications">
      <div class="field"><label for="fs">Show</label><select id="fs" name="status"><option value="inbox">Inbox</option><option value="unread">Unread</option><option value="read">Read</option><option value="archived">Archived</option><option value="all">Everything</option></select></div>
      <div class="field"><label for="fc">Category</label><select id="fc" name="category"><option value="">All</option><option value="exam">Examinations</option><option value="timetable">Timetable changes</option><option value="seating">Hall &amp; seat</option><option value="result">Results</option><option value="announcement">Announcements</option><option value="reminder">Reminders</option><option value="account">Account &amp; security</option></select></div>
      <div class="field"><label for="fp">Priority</label><select id="fp" name="priority"><option value="">Any</option><option>urgent</option><option>high</option><option>normal</option><option>low</option></select></div>
      <div class="field wide"><label for="fq">Search</label><input id="fq" type="search" name="q" maxlength="80" placeholder="Words in the title or text"></div>
      <button class="btn primary">Apply</button><button class="btn" type="button" data-act="readall">Mark all as read</button><a class="btn" href="#/notification-preferences">Preferences</a></form>
      <div id="list" aria-live="polite">${EM.loading()}</div><div id="pg"></div></section></div>`;
    const load = async () => {
      const f = EM.formData($("#flt", root));
      const r = await EM.apiList("/api/notifications", { ...f, limit: LIMIT, offset });
      $("#list", root).innerHTML = r.rows.length ? `<div class="list">${r.rows.map(n => `<article class="item note ${n.read ? "" : "unread"}" aria-label="${esc(n.title)}">
        <div class="t">${n.read ? "" : '<span class="sr-only">Unread: </span>'}${esc(n.title)} ${EM.badge(n.category_label)} ${n.priority === "normal" || n.priority === "low" ? "" : EM.badge(n.priority, PRIO[n.priority])}</div>
        <p class="body">${esc(n.body)}</p><div class="m">${esc(EM.fmtDT(n.created_at))}</div>
        <div class="actions">${n.link ? `<a class="btn sm" href="${esc(n.link)}">Open</a>` : ""}<button class="btn sm" data-act="${n.read ? "unread" : "read"}" data-id="${n.id}">${n.read ? "Mark unread" : "Mark read"}</button><button class="btn sm" data-act="${n.archived ? "unarchive" : "archive"}" data-id="${n.id}">${n.archived ? "Restore" : "Archive"}</button><button class="btn sm danger" data-act="del" data-id="${n.id}">Delete</button></div></article>`).join("")}</div>`
        : EM.empty("No notifications", f.q || f.category || f.priority || f.status !== "inbox" ? "Nothing matches these filters." : "You are all caught up.");
      EM.pager($("#pg", root), { total: r.total, limit: LIMIT, offset, onPage: o => { offset = o; load().catch(EM.fail); } });
      EM.refreshBell();
    };
    $("#flt", root).addEventListener("submit", e => { e.preventDefault(); offset = 0; load().catch(EM.fail); });
    const act = (path, method) => async b => { await api(`/api/notifications/${b.dataset.id}${path}`, { method: method || "POST" }); await load(); };
    EM.delegate(root, { read: act("/read"), unread: act("/unread"), archive: act("/archive"), unarchive: act("/unarchive"),
      del: async b => { if (!await EM.confirm({ title: "Delete this notification?", message: "It is removed from your list.", confirmText: "Delete", danger: true })) return; await api(`/api/notifications/${b.dataset.id}`, { method: "DELETE" }); EM.toast("Notification deleted.", "ok"); await load(); },
      readall: async () => { const r = await api("/api/notifications/read-all", { method: "POST", params: { category: $("#fc", root).value } }); EM.toast(`${r.marked_read} notification(s) marked as read.`, "ok"); await load(); } });
    await load();
  } });

  // ------------------------------------------------------------ preferences
  EM.page({ name: "notification-preferences", title: "Notification preferences", nav: { group: "Account", icon: "⚙", label: "Notification preferences", order: 2 }, render: async root => {
    const d = await api("/api/notifications/preferences");
    root.innerHTML = `<section class="card"><div class="card-head"><h2>Notification preferences</h2></div>
      <p class="muted">Choose how you are told about each kind of event. E-mail goes to the address on your account or student record${d.has_email ? "" : " (your account has none, so only in-app notices can reach you)"}. Account and security notices always appear in the application.</p>
      <form id="pf"><div class="tablewrap"><table class="table pref-table"><caption class="sr-only">Notification preferences</caption><thead><tr><th scope="col">Category</th><th scope="col">In the application</th><th scope="col">By e-mail</th></tr></thead><tbody>
      ${d.preferences.map(p => `<tr><th scope="row">${esc(p.label)}</th><td><label class="check"><input type="checkbox" name="in_${esc(p.category)}"${p.in_app ? " checked" : ""}${p.in_app_locked ? " disabled" : ""}> <span class="sr-only">${esc(p.label)} in the application</span>On</label></td><td><label class="check"><input type="checkbox" name="mail_${esc(p.category)}"${p.email ? " checked" : ""}> <span class="sr-only">${esc(p.label)} by e-mail</span>On</label></td></tr>`).join("")}</tbody></table></div>
      <p><button class="btn primary">Save preferences</button> <a class="btn" href="#/notifications">Back to notifications</a></p></form></section>`;
    EM.onSubmit($("#pf", root), async (_d, form) => {
      const g = n => { const el = form.elements[n]; return !!(el && el.checked); };
      await api("/api/notifications/preferences", { method: "PUT", body: { preferences: d.preferences.map(p => ({ category: p.category, in_app: p.in_app_locked ? true : g("in_" + p.category), email: g("mail_" + p.category) })) } });
      EM.toast("Preferences saved.", "ok");
    });
  } });

  // ------------------------------------------------------------ communications (administrators only)
  EM.page({ name: "communications", title: "Communications", roles: ["admin"], nav: { group: "Administration", icon: "✉", label: "Communications", order: 2.5 }, render: async root => {
    const LIMIT = 15; let offset = 0;
    root.innerHTML = `<div class="stack"><section class="card"><div class="card-head"><h3>E-mail configuration</h3></div><div id="cfg">${EM.loading()}</div>
      <form id="tf" class="toolbar" style="margin-top:12px"><div class="field wide"><label for="tt">Send a test e-mail to</label><input id="tt" name="to" type="email" placeholder="Leave blank for your own account address"></div><button class="btn primary">Send test e-mail</button></form><div id="tres" aria-live="polite"></div></section>
      <section class="card"><div class="card-head"><h3>Delivery statistics</h3><button class="btn sm" data-act="runsched">Run reminders &amp; queue now</button></div><div id="st">${EM.loading()}</div></section>
      <section class="card"><div class="card-head"><h3>Delivery log</h3></div><form id="df" class="toolbar"><div class="field"><label for="ds">Status</label><select id="ds" name="status"><option value="">Any</option><option>sent</option><option>outbox</option><option>queued</option><option>retrying</option><option>failed</option><option>not_configured</option></select></div>
        <div class="field"><label for="dk">Type</label><select id="dk" name="kind"><option value="">Any</option><option>notification</option><option>account</option><option>test</option></select></div><div class="field wide"><label for="dq">Search subject</label><input id="dq" name="q" type="search"></div><button class="btn primary">Filter</button></form><div id="dl">${EM.loading()}</div><div id="dp"></div></section>
      <section class="card"><div class="card-head"><h3>Notification templates</h3></div><div id="tp">${EM.loading()}</div></section></div>`;
    const stat = (n, l) => `<div class="stat"><span class="n">${esc(n)}</span><span class="l">${esc(l)}</span></div>`;
    async function config() {
      const c = await api("/api/admin/communications/email-status");
      $("#cfg", root).innerHTML = `${EM.alert(c.note, c.mode === "smtp" ? "ok" : "warn")}<dl class="kv" style="margin-top:8px"><dt>Mode</dt><dd>${esc(c.mode)}</dd><dt>SMTP server</dt><dd>${c.smtp_configured ? esc(c.host) + ":" + esc(c.port) + " · " + esc(c.security) : "not set"}</dd><dt>Credentials</dt><dd>user ${c.username_set ? "set" : "not set"} · password ${c.password_set ? "set" : "not set"} <span class="muted small">(values are never shown)</span></dd><dt>Sender</dt><dd>${esc(c.from_name)} &lt;${esc(c.from_address)}&gt;</dd><dt>Retries</dt><dd>${esc(c.max_attempts)} attempts, back-off from ${esc(c.retry_backoff_seconds)} s · timeout ${esc(c.timeout_seconds)} s</dd><dt>Scheduler</dt><dd>${c.scheduler.enabled ? "on" : "off"} · every ${esc(c.scheduler.interval_seconds)} s · time zone ${esc(c.scheduler.timezone)} · exam reminders ${c.scheduler.reminders_enabled ? esc(c.scheduler.exam_reminder_hours_before.join(", ") + " h before") : "off"}</dd></dl>`;
    }
    async function stats() {
      const s = await api("/api/admin/communications/stats");
      $("#st", root).innerHTML = `<div class="grid g4">${stat(s.emails_total, "e-mails (7 days)")}${stat(s.emails_by_status.sent || 0, "accepted by SMTP server")}${stat((s.emails_by_status.failed || 0) + (s.emails_by_status.not_configured || 0), "failed / not configured")}${stat(s.pending, "waiting or retrying")}${stat(s.notifications_total, "in-app notifications")}${stat(s.unread_notifications, "unread now")}${stat(s.success_rate == null ? "—" : Math.round(s.success_rate * 100) + "%", "delivery success")}${stat(s.emails_by_status.outbox || 0, "development outbox only")}</div>`;
    }
    async function log() {
      const r = await EM.apiList("/api/admin/communications/deliveries", { ...EM.formData($("#df", root)), limit: LIMIT, offset });
      $("#dl", root).innerHTML = r.rows.length ? `<div class="tablewrap"><table class="table stack"><caption class="sr-only">E-mail delivery log</caption><thead><tr><th scope="col">When</th><th scope="col">Type</th><th scope="col">To</th><th scope="col">Subject</th><th scope="col">Status</th><th scope="col">Detail</th><th scope="col"></th></tr></thead><tbody>${r.rows.map(x => `<tr><td data-label="When">${esc(EM.fmtDT(x.created_at))}</td><td data-label="Type">${esc(x.kind)}</td><td data-label="To" class="mono">${esc(x.recipient)}</td><td data-label="Subject">${esc(x.subject)}</td><td data-label="Status">${EM.badge(x.status.replace("_", " "), DSTATUS[x.status])}</td><td data-label="Detail" class="small">${x.status === "sent" ? esc(EM.fmtDT(x.sent_at)) : esc(x.last_error || "")}${x.attempts ? ` <span class="muted">(attempt ${esc(x.attempts)}/${esc(x.max_attempts)})</span>` : ""}${x.status === "retrying" ? ` <span class="muted">next ${esc(EM.fmtDT(x.next_attempt_at))}</span>` : ""}</td><td>${x.retryable ? `<button class="btn sm" data-act="retry" data-id="${x.id}">Retry</button>` : ""}</td></tr>`).join("")}</tbody></table></div>` : EM.empty("No deliveries", "Nothing matches the filter.");
      EM.pager($("#dp", root), { total: r.total, limit: LIMIT, offset, onPage: o => { offset = o; log().catch(EM.fail); } });
    }
    let tpls = [];
    async function templates() {
      tpls = await api("/api/admin/communications/templates");
      $("#tp", root).innerHTML = `<div class="list">${tpls.map(t => `<div class="item"><div class="t">${esc(t.label)} ${EM.badge(t.category_label)} ${t.customized ? EM.badge("customised", "info") : ""}</div><div class="m">${esc(t.subject)}</div><div class="actions" style="margin-top:6px"><button class="btn sm" data-act="tedit" data-key="${esc(t.key)}">Edit</button>${t.customized ? `<button class="btn sm" data-act="treset" data-key="${esc(t.key)}">Reset to default</button>` : ""}</div></div>`).join("")}</div>`;
    }
    EM.onSubmit($("#tf", root), async d => {
      const r = await api("/api/admin/communications/test-email", { method: "POST", body: d.to ? { to: d.to } : {} });
      $("#tres", root).innerHTML = EM.alert(r.detail, r.status === "sent" ? "ok" : r.status === "outbox" ? "info" : "bad"); await Promise.all([log(), stats(), config()]);
    });
    $("#df", root).addEventListener("submit", e => { e.preventDefault(); offset = 0; log().catch(EM.fail); });
    EM.delegate(root, {
      retry: async b => { const r = await api(`/api/admin/communications/deliveries/${b.dataset.id}/retry`, { method: "POST" }); EM.toast(r.status === "sent" ? "The SMTP server accepted the message." : "Retry did not succeed: " + (r.last_error || r.status), r.status === "sent" ? "ok" : "bad"); await Promise.all([log(), stats()]); },
      runsched: async () => { const r = await api("/api/admin/communications/run-scheduler", { method: "POST" }); EM.toast(`Done: ${r.exam_reminders} exam reminder(s), ${r.announcements_sent} announcement(s), ${r.email.attempted} e-mail(s) attempted.`, "ok"); await Promise.all([log(), stats()]); },
      treset: async b => { if (!await EM.confirm({ title: "Reset template?", message: "The built-in text is restored.", confirmText: "Reset" })) return; await api(`/api/admin/communications/templates/${b.dataset.key}`, { method: "DELETE" }); await templates(); },
      tedit: async b => {
        const t = tpls.find(x => x.key === b.dataset.key);
        const r = await EM.ask({ title: "Edit template: " + t.label, message: "Allowed placeholders: " + t.placeholders.map(p => "{" + p + "}").join(" "), fields: [{ name: "subject", label: "Subject", required: true, value: t.subject }, { name: "body", label: "Body (plain text)", type: "textarea", required: true, value: t.body }], submitText: "Save template",
          submit: async d => { await api(`/api/admin/communications/templates/${t.key}`, { method: "PUT", body: { subject: d.subject, body: d.body } }); return true; } });
        if (r) { EM.toast("Template saved.", "ok"); await templates(); }
      } });
    await Promise.all([config(), stats(), log(), templates()]);
  } });
})();
