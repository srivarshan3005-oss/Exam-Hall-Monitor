/* Live monitoring dashboard (V7): overview + scan, sources, documents/queue/failures, student records, hall locations,
   e-mail watch + notifications, cloud sync, health and logs. Every control calls a real /api/live endpoint. */
(function () {
  "use strict";
  const { $, esc, api } = EM;
  const when = d => (d ? esc(String(d).replace("T", " ").slice(0, 16)) + " UTC" : "—");
  const cls = s => ({ ok: "ok", sent: "ok", outbox: "info", CONFIRMED: "ok", HALL_ONLY: "info", SEAT_ONLY: "info", pending: "warn", processing: "warn",
    MANUAL_REVIEW: "warn", failed: "bad", CONFLICT: "bad", partial: "warn", skipped: "" })[s] || "";
  const bd = s => EM.badge(String(s).replace(/_/g, " "), cls(s));
  const TABS = [["overview", "Overview"], ["documents", "Documents & queue"], ["records", "Student records"], ["halls", "Hall locations"],
    ["notify", "E-mail"], ["system", "System & logs"]];

  EM.page({ name: "live", title: "Live monitoring", roles: ["admin", "staff"],
    nav: { group: "Documents", icon: "📡", label: "Live monitoring", order: 1 },
    render: async (root, ctx) => {
      const admin = EM.isAdmin();
      let tab = ctx.query.tab || "overview", timer = null;
      root.innerHTML = `<div class="stack"><nav class="toolbar" role="tablist" aria-label="Live monitoring sections">${TABS.map(([k, v]) =>
        `<button class="btn${k === tab ? " primary" : ""}" role="tab" data-tab="${k}" aria-selected="${k === tab}">${esc(v)}</button>`).join("")}</nav><div id="pane">${EM.loading()}</div></div>`;
      const pane = $("#pane", root);
      const views = { overview, documents, records, halls, notify, system };
      const show = async k => {
        tab = k; if (timer) { clearInterval(timer); timer = null; }
        root.querySelectorAll("[data-tab]").forEach(b => { const on = b.dataset.tab === k; b.classList.toggle("primary", on); b.setAttribute("aria-selected", on); });
        // Each render gets its own container: a slow earlier tab that finishes late writes into a detached element and can
        // never overwrite the tab the user switched to (race found by the jsdom E2E: "timeout waiting for tab notify").
        const view = document.createElement("div");
        view.innerHTML = EM.loading();
        pane.replaceChildren(view);
        try { await views[k](view); } catch (e) { view.innerHTML = EM.alert(e.message, "bad"); }
      };
      root.addEventListener("click", ev => { const b = ev.target.closest("[data-tab]"); if (b) show(b.dataset.tab); });

      // ------------------------------------------------------------------ overview
      async function overview(el) {
        const draw = async () => {
          const o = await api("/api/live/overview"), src = await api("/api/live/sources"), st = await api("/api/live/scan/state");
          const n = (m, k) => (m && m[k]) || 0;
          el.innerHTML = `<div class="stack">
            <section class="card"><div class="card-head"><h2>Monitoring</h2></div>
              <div class="grid cols-4">
                <div class="stat"><b>${when(o.last_success_at)}</b><span>Last successful scan</span></div>
                <div class="stat"><b>${when(o.last_scan_at)} ${o.last_scan_status ? bd(o.last_scan_status) : ""}</b><span>Latest scan</span></div>
                <div class="stat"><b>${esc(o.poll_minutes)} min</b><span>Polling interval (${esc(o.poll_range_minutes.join("–"))} allowed) · ${o.auto_enabled ? "automatic scanning ON" : "automatic scanning OFF"}</span></div>
                <div class="stat"><b>${esc(o.students_indexed)}</b><span>Students searchable</span></div></div>
              ${o.last_scan_status === "failed" ? EM.alert("The latest scan FAILED. Previously verified data is still being served; the scheduler retries with back-off.", "bad") : ""}
              <div class="toolbar" style="margin-top:12px"><button class="btn primary" id="scan" type="button"${st.running ? " disabled" : ""}>${st.running ? "Scan running…" : "Run scan now"}</button>
                ${admin ? `<button class="btn" id="rebuild" type="button">Re-parse &amp; rebuild index</button>` : ""}
                <button class="btn" id="reload" type="button">Refresh</button></div>
              <div id="scanmsg" class="small muted"></div></section>
            <section class="card"><div class="card-head"><h2>Pipeline</h2></div><div class="grid cols-4">
              <div class="stat"><b>${esc(Object.values(o.links).reduce((a, b) => a + b, 0))}</b><span>PDF links discovered (${esc(n(o.links, "downloaded"))} downloaded, ${esc(n(o.links, "failed") + n(o.links, "blocked"))} failed)</span></div>
              <div class="stat"><b>${esc(o.documents)}</b><span>Allotment documents stored</span></div>
              <div class="stat"><b>${esc(n(o.queue, "ok"))} ok · ${esc(n(o.queue, "pending") + n(o.queue, "processing"))} queued · ${esc(n(o.queue, "failed"))} failed</b><span>Processing queue</span></div>
              <div class="stat"><b>${Object.entries(o.allotments).map(([k, v]) => `${esc(v)} ${esc(k.toLowerCase().replace("_", " "))}`).join(" · ") || "none"}</b><span>Current records by status</span></div></div></section>
            <section class="card"><div class="card-head"><h2>Source status</h2></div>${src.length ? `<div class="tablewrap"><table class="table"><thead><tr><th>Method</th><th>Address</th><th>Status</th><th>Last success</th><th>Items</th><th>Failures</th></tr></thead><tbody>${src.map(s => `<tr><td>${esc(s.method)}</td><td class="small">${esc(s.url)}</td><td>${bd(s.status)}${s.error ? `<br><span class="small">${esc(s.error)}</span>` : ""}</td><td>${when(s.last_success_at)}</td><td>${esc(s.items_found)}</td><td>${esc(s.consecutive_failures)}</td></tr>`).join("")}</tbody></table></div>` : EM.empty("No scan has run yet", "Press “Run scan now”.")}</section>
            <section class="card"><div class="card-head"><h2>Recent scans</h2></div>${o.runs.length ? `<div class="list">${o.runs.map(r => `<div class="item"><div class="t">#${esc(r.id)} · ${when(r.started_at)} · ${esc(r.trigger)} ${bd(r.status)}</div><div class="m">${esc(r.links_found)} found · ${esc(r.new_links)} new · ${esc(r.downloaded)} downloaded · ${esc(r.duplicates)} duplicate · ${esc(r.failed)} failed${r.message ? "<br>" + esc(r.message) : ""}</div></div>`).join("")}</div>` : EM.empty("No scans yet")}</section></div>`;
          const scan = $("#scan", el);
          if (scan) scan.onclick = async () => { scan.disabled = true; scan.textContent = "Scan started…";
            try { await api("/api/live/scan", { method: "POST" }); EM.toast("Scan started. This page refreshes automatically.", "ok"); poll(); } catch (e) { EM.fail(e); scan.disabled = false; scan.textContent = "Run scan now"; } };
          const rb = $("#rebuild", el); if (rb) rb.onclick = async () => { rb.disabled = true; try { const r = await api("/api/live/rebuild", { method: "POST" }); EM.toast(`Index rebuilt: ${r.index.records} records, ${r.index.revised} revised.`, "ok"); await draw(); } catch (e) { EM.fail(e); rb.disabled = false; } };
          $("#reload", el).onclick = draw;
        };
        const poll = () => { if (timer) clearInterval(timer); timer = setInterval(async () => { const s = await api("/api/live/scan/state").catch(() => null); if (s && !s.running) { clearInterval(timer); timer = null; draw(); } }, 3000); };
        await draw();
      }

      // ------------------------------------------------------------------ documents, queue, failures, duplicates
      async function documents(el) {
        const [docs, q, f, d] = await Promise.all([api("/api/live/documents"), api("/api/live/queue"), api("/api/live/failures"), api("/api/live/duplicates")]);
        el.innerHTML = `<div class="stack">
          <section class="card"><div class="card-head"><h2>Allotment documents</h2></div>${docs.length ? `<div class="tablewrap"><table class="table"><thead><tr><th>Document</th><th>Date / session</th><th>Versions</th><th>Pages</th><th>Processing</th><th>Records</th></tr></thead><tbody>${docs.map(x => `<tr><td>${esc(x.filename || x.title)}<br><span class="small muted">${esc(x.kind.replace("_", " "))}</span><br><span class="small mono">${esc((x.sha256 || "").slice(0, 16))}</span></td><td>${esc(x.exam_date || "—")} ${esc(x.session || "")}</td><td>${esc(x.versions)}</td><td>${esc(x.pages)}${x.ocr_pages ? ` (${esc(x.ocr_pages)} OCR)` : ""}</td><td>${bd(x.ingest_status)}${x.ingest_error ? `<br><span class="small">${esc(x.ingest_error)}</span>` : ""}</td><td>${esc(x.records)}</td></tr>`).join("")}</tbody></table></div>` : EM.empty("No allotment document yet")}</section>
          <section class="card"><div class="card-head"><h2>Processing queue</h2></div>${q.length ? `<div class="tablewrap"><table class="table"><thead><tr><th>#</th><th>Version</th><th>Status</th><th>Attempts</th><th>Records</th><th>Processed</th><th></th></tr></thead><tbody>${q.map(r => `<tr><td>${esc(r.id)}</td><td>${esc(r.version_id)}</td><td>${bd(r.status)}${r.error ? `<br><span class="small">${esc(r.error)}</span>` : ""}</td><td>${esc(r.attempts)}</td><td>${esc(r.records)}</td><td>${when(r.processed_at)}</td><td>${admin && r.status === "failed" ? `<button class="btn sm" data-act="retry" data-id="${r.id}">Retry</button>` : ""}</td></tr>`).join("")}</tbody></table></div>` : EM.empty("Queue is empty")}</section>
          <section class="card"><div class="card-head"><h2>Failed documents</h2></div>${f.downloads.length + f.processing.length ? `<div class="list">${f.downloads.map(x => `<div class="item"><div class="t">${esc(x.url)} ${bd(x.status)}</div><div class="m">${x.http ? "HTTP " + esc(x.http) + " · " : ""}${esc(x.error || "")} · ${esc(x.failures)} failure(s) · ${when(x.last_attempt_at)}</div></div>`).join("")}${f.processing.map(x => `<div class="item"><div class="t">Processing of version ${esc(x.version_id)} failed</div><div class="m">${esc(x.error || "")}</div></div>`).join("")}</div>` : EM.empty("No failures")}</section>
          <section class="card"><div class="card-head"><h2>Duplicate documents</h2></div>${d.length ? `<div class="list">${d.map(x => `<div class="item"><div class="t">${esc(x.title)}</div><div class="m">${esc(x.url)}<br>${esc(x.note || "Identical content to a stored PDF")}</div></div>`).join("")}</div>` : EM.empty("No duplicates")}</section></div>`;
        EM.delegate(el, { retry: async b => { await api(`/api/live/queue/${b.dataset.id}/retry`, { method: "POST" }); EM.toast("Queued for retry. Run a scan to process it.", "ok"); await documents(el); } });
      }

      // ------------------------------------------------------------------ student records (search, filter, review)
      async function records(el) {
        el.innerHTML = `<section class="card"><div class="card-head"><h2>Student allotment records</h2></div>
          <div class="toolbar"><div class="field wide"><label for="rq">Register number, subject code or hall</label><input id="rq" type="search" maxlength="40"></div>
          <div class="field"><label for="rs">Status</label><select id="rs"><option value="">All</option>${["CONFIRMED", "HALL_ONLY", "SEAT_ONLY", "CONFLICT", "MANUAL_REVIEW"].map(s => `<option>${s}</option>`).join("")}</select></div>
          <button class="btn primary" id="rgo" type="button">Search</button></div><p class="small muted">Conflicts and manual-verification records are not hidden: students see them with a warning and both source pages. Correct them by publishing a corrected PDF, then run a scan.</p><div id="rl"></div></section>`;
        let loadSeq = 0;            // latest request wins: an older, slower response must never overwrite a newer search
        const load = async () => {
          const mine = ++loadSeq;
          const d = await api("/api/live/allotments", { params: { q: $("#rq", el).value.trim(), status: $("#rs", el).value, limit: 100 } });
          if (mine !== loadSeq) return;
          $("#rl", el).innerHTML = d.items.length ? `<p class="small muted">${esc(d.total)} record(s), showing ${esc(d.items.length)}</p><div class="tablewrap"><table class="table"><thead><tr><th>Register no.</th><th>Date / session</th><th>Subject</th><th>Hall</th><th>Seat</th><th>Status</th><th>Sources</th></tr></thead><tbody>${d.items.map(r => `<tr><td class="mono">${esc(r.register_number)}</td><td>${esc(r.date)} ${esc(r.session)}</td><td>${esc(r.subject_code || "")}<br><span class="small">${esc(r.subject_name || "")}</span></td><td>${esc(r.hall || "—")}</td><td>${esc(r.seat || "—")}</td><td>${bd(r.status)}${r.revised ? " " + EM.badge("revised", "info") : ""}${r.notes.length ? `<br><span class="small">${esc(r.notes.join(" · ").slice(0, 160))}</span>` : ""}</td><td>${r.sources.map(s => `<a href="${esc(s.image_url)}" target="_blank" rel="noopener">${esc(s.kind)} p.${esc(s.page)}</a>`).join(" · ")}<br><a class="small" href="/portal/?reg=${encodeURIComponent(r.register_number)}" target="_blank" rel="noopener">student view</a></td></tr>`).join("")}</tbody></table></div>` : EM.empty("No records", "Nothing matches, or no PDF has been processed yet.");
        };
        $("#rgo", el).onclick = load; $("#rq", el).onkeydown = e => { if (e.key === "Enter") load(); }; $("#rs", el).onchange = load;
        await load();
      }

      // ------------------------------------------------------------------ hall locations
      async function halls(el) {
        const [h, pts] = await Promise.all([api("/api/live/halls"), api("/api/live/campus-points")]);
        const fields = (v = {}) => [
          { name: "display_name", label: "Display name", value: v.display_name || "" }, { name: "building", label: "Building", value: v.building || "" },
          { name: "block", label: "Block", value: v.block || "" }, { name: "floor", label: "Floor", value: v.floor || "" }, { name: "room", label: "Room", value: v.room || "" },
          { name: "latitude", label: "Latitude (verified)", value: v.latitude ?? "", hint: "Leave blank unless verified. Never estimate." }, { name: "longitude", label: "Longitude (verified)", value: v.longitude ?? "" },
          { name: "entrance_id", label: "Campus entrance", type: "select", value: v.entrance_id || "", options: [["", "None"]].concat(pts.filter(p => p.verified).map(p => [p.id, p.name])) },
          { name: "directions", label: "Directions from the entrance", type: "textarea", value: v.directions || "" },
          { name: "location_source", label: "Source of this information", value: v.location_source || "", hint: "Required to verify (official notice, site plan, or who confirmed it)." },
          { name: "verified", type: "checkbox", label: "Verified – show to students", value: v.verified }];
        const body = d => ({ display_name: d.display_name || null, building: d.building || null, block: d.block || null, floor: d.floor || null, room: d.room || null,
          latitude: d.latitude === "" ? null : Number(d.latitude), longitude: d.longitude === "" ? null : Number(d.longitude), entrance_id: d.entrance_id ? Number(d.entrance_id) : null,
          directions: d.directions || null, location_source: d.location_source || null, verified: !!d.verified });
        el.innerHTML = `<div class="stack"><section class="card"><div class="card-head"><h2>Halls</h2>${admin ? `<button class="btn primary" data-act="add" type="button">Add hall</button>` : ""}</div>
          <p class="small muted">Students see building, floor, room, directions and a map <b>only</b> for halls marked verified, and only the values entered here. Otherwise they see “Building/floor location has not yet been verified.”</p>
          ${h.halls_in_documents_without_record.length ? EM.alert("Halls used in current allotments without a record: " + h.halls_in_documents_without_record.join(", "), "warn") : ""}
          <div id="hg"></div></section>
          <section class="card"><div class="card-head"><h2>Campus entrances / landmarks</h2>${admin ? `<button class="btn" data-act="addpt" type="button">Add point</button>` : ""}</div>
          ${pts.length ? `<div class="list">${pts.map(p => `<div class="item"><div class="t">${esc(p.name)} ${p.verified ? EM.badge("verified", "ok") : EM.badge("unverified", "warn")}</div><div class="m">${p.latitude != null ? esc(p.latitude) + ", " + esc(p.longitude) : "no coordinates"} · ${esc(p.source || "no source")}${admin ? ` <button class="btn sm danger" data-act="delpt" data-id="${p.id}">Delete</button>` : ""}</div></div>`).join("")}</div>` : EM.empty("No campus points", "Add the verified main entrance to enable directions.")}</section></div>`;
        EM.grid($("#hg", el), { rows: h.halls, caption: "Halls", searchKeys: ["code", "building", "block"], columns: [
          { key: "code", label: "Hall", render: r => `<b>${esc(r.code)}</b>${r.in_use ? "<br>" + EM.badge("in current allotments", "info") : ""}` },
          { key: "building", label: "Building / block", render: r => esc([r.building, r.block].filter(Boolean).join(" · ") || "—") },
          { key: "floor", label: "Floor / room", render: r => esc([r.floor, r.room].filter(Boolean).join(" · ") || "—") },
          { key: "latitude", label: "Map", render: r => r.latitude != null ? esc(r.latitude + ", " + r.longitude) : "—" },
          { key: "verified", label: "Verified", render: r => r.verified ? EM.badge("verified by " + (r.verified_by || "?"), "ok") : EM.badge("not verified", "warn") }],
          actions: r => admin ? `<button class="btn sm" data-act="edit" data-id="${r.id}">Edit</button><button class="btn sm" data-act="hist" data-id="${r.id}">History</button>` : `<button class="btn sm" data-act="hist" data-id="${r.id}">History</button>` });
        EM.delegate(el, {
          add: async () => { const r = await EM.ask({ title: "Add hall", fields: [{ name: "code", label: "Hall code (as printed in the PDFs)", required: true }].concat(fields()),
            submit: d => api("/api/live/halls", { method: "POST", body: Object.assign({ code: d.code }, body(d)) }) }); if (r) { EM.toast("Hall added", "ok"); halls(el); } },
          edit: async b => { const v = h.halls.find(x => String(x.id) === b.dataset.id); const r = await EM.ask({ title: "Edit " + v.code, fields: fields(v),
            submit: d => api(`/api/live/halls/${v.id}/location`, { method: "PUT", body: body(d) }) }); if (r) { EM.toast("Saved", "ok"); halls(el); } },
          hist: async b => { const x = await api(`/api/live/halls/${b.dataset.id}/history`); EM.show("Change history", x.length ? `<div class="list">${x.map(i => `<div class="item"><div class="t">${esc(i.action)} · ${esc(i.actor)} · ${when(i.at)}</div><div class="m">Source: ${esc(i.source || "—")}</div></div>`).join("")}</div>` : EM.empty("No changes recorded")); },
          addpt: async () => { const r = await EM.ask({ title: "Add campus point", fields: [{ name: "name", label: "Name", required: true }, { name: "latitude", label: "Latitude" }, { name: "longitude", label: "Longitude" },
            { name: "source", label: "Source" }, { name: "verified", type: "checkbox", label: "Verified" }],
            submit: d => api("/api/live/campus-points", { method: "POST", body: { name: d.name, latitude: d.latitude === "" ? null : Number(d.latitude), longitude: d.longitude === "" ? null : Number(d.longitude), source: d.source || null, verified: !!d.verified } }) }); if (r) halls(el); },
          delpt: async b => { if (await EM.confirm({ title: "Delete point?", message: "Halls using it lose their entrance." })) { await api(`/api/live/campus-points/${b.dataset.id}`, { method: "DELETE" }); halls(el); } } });
      }

      // ------------------------------------------------------------------ e-mail
      async function notify(el) {
        const n = await api("/api/live/notifications"), w = admin ? await api("/api/live/watches") : [];
        const m = n.mail;
        el.innerHTML = `<div class="stack">
          <section class="card"><div class="card-head"><h2>E-mail delivery</h2></div>
            <p>Mode: ${bd(m.mode)} ${m.smtp_configured ? `· ${esc(m.host)}:${esc(m.port)} (${esc(m.security)}) · password ${m.password_set ? "set" : "NOT set"}` : "· SMTP not configured (set SMTP_HOST and the other SMTP_* variables)"}</p>
            <p class="small muted">Credentials come from environment variables only and are never shown. A failure never affects student lookups.</p>
            ${admin ? `<div class="toolbar"><div class="field wide"><label for="te">Send a test e-mail to</label><input id="te" type="email" maxlength="200" autocomplete="off"></div><button class="btn primary" id="tsend" type="button">Send test</button></div><div id="tres"></div>` : ""}</section>
          ${admin ? `<section class="card"><div class="card-head"><h2>Register-number watch list</h2></div>
            <p class="small muted">Notify an address when the watched register number gets a new or revised allotment (original PDF and unmasked page attached). Each event is sent once.</p>
            <div class="toolbar"><div class="field"><label for="wr">Register number</label><input id="wr" maxlength="20"></div><div class="field wide"><label for="we">E-mail</label><input id="we" type="email" maxlength="200"></div><button class="btn primary" id="wadd" type="button">Add watch</button></div>
            ${w.length ? `<div class="list">${w.map(x => `<div class="item"><div class="t mono">${esc(x.register_number)} → ${esc(x.email)}</div><div class="m">by ${esc(x.created_by)} <button class="btn sm danger" data-act="delw" data-id="${x.id}">Remove</button></div></div>`).join("")}</div>` : EM.empty("No watches")}</section>` : ""}
          <section class="card"><div class="card-head"><h2>Notification history</h2>${admin ? `<button class="btn" data-act="proc" type="button">Process due now</button>` : ""}</div>
            ${n.items.length ? `<div class="tablewrap"><table class="table"><thead><tr><th>When</th><th>Register no.</th><th>To</th><th>Event</th><th>Status</th><th>Attempts</th></tr></thead><tbody>${n.items.map(i => `<tr><td>${when(i.created_at)}</td><td class="mono">${esc(i.register_number)}</td><td>${esc(i.to)}</td><td>${esc(i.event)}<br><span class="small">${esc(i.subject)}</span></td><td>${bd(i.status)}${i.error ? `<br><span class="small">${esc(i.error)}</span>` : ""}</td><td>${esc(i.attempts)}</td></tr>`).join("")}</tbody></table></div>` : EM.empty("No notifications yet")}</section></div>`;
        const ts = $("#tsend", el);
        if (ts) ts.onclick = async () => { ts.disabled = true; try { const r = await api("/api/live/notifications/test-email", { method: "POST", body: { to: $("#te", el).value.trim() } }); $("#tres", el).innerHTML = EM.alert(r.message, r.status === "sent" ? "ok" : "bad"); } catch (e) { $("#tres", el).innerHTML = EM.alert(e.message, "bad"); } finally { ts.disabled = false; } };
        const wa = $("#wadd", el);
        if (wa) wa.onclick = async () => { try { await api("/api/live/watches", { method: "POST", body: { register_number: $("#wr", el).value.trim(), email: $("#we", el).value.trim() } }); EM.toast("Watch added", "ok"); notify(el); } catch (e) { EM.fail(e); } };
        EM.delegate(el, { delw: async b => { await api(`/api/live/watches/${b.dataset.id}`, { method: "DELETE" }); notify(el); },
          proc: async () => { const r = await api("/api/live/notifications/process", { method: "POST" }); EM.toast(`${r.sent} sent, ${r.failed} failed, ${r.retry_scheduled} retry scheduled`, "ok"); notify(el); } });
      }

      // ------------------------------------------------------------------ system, sync, logs
      async function system(el) {
        const [h, s, lg] = await Promise.all([api("/api/live/health"), api("/api/live/sync/log"), api("/api/live/logs")]);
        const yes = (v, t) => EM.badge(t || (v ? "OK" : "Problem"), v ? "ok" : "bad");
        el.innerHTML = `<div class="stack">
          <section class="card"><div class="card-head"><h2>System health</h2></div><dl class="kv">
            <dt>Database</dt><dd>${yes(h.database.ok)} ${esc(h.database.engine || "")} · revision ${esc(h.database.revision)}</dd>
            <dt>Document storage</dt><dd>${yes(h.storage_writable, h.storage_writable ? "writable" : "NOT writable")}</dd>
            <dt>OCR (Tesseract)</dt><dd>${h.ocr_available ? EM.badge("available", "ok") : EM.badge("not installed – text PDFs only", "warn")}</dd>
            <dt>Background scheduler</dt><dd>${yes(h.scheduler_running, h.scheduler_running ? "running" : "not running")}</dd>
            <dt>E-mail</dt><dd>${bd(h.mail)}</dd><dt>Page-image cache</dt><dd>${esc(h.preview_cache_version)}</dd>
            <dt>Last successful scan</dt><dd>${when(h.last_success_at)}</dd></dl></section>
          <section class="card"><div class="card-head"><h2>Cloud mirror (Supabase, optional)</h2>${admin && s.enabled ? `<button class="btn" data-act="sync" type="button">Sync now</button>` : ""}</div>
            <p>${s.enabled ? EM.badge("configured", "ok") : EM.badge("off", "")} ${s.enabled ? "" : "Set SUPABASE_URL and SUPABASE_SERVICE_KEY on the server to enable. Local SQLite works without it."}</p>
            ${s.items.length ? `<div class="list">${s.items.map(i => `<div class="item"><div class="t">${when(i.started_at)} ${bd(i.status)}</div><div class="m">${esc(i.records)} records${i.error ? " · " + esc(i.error) : ""}</div></div>`).join("")}</div>` : ""}</section>
          <section class="card"><div class="card-head"><h2>Activity log</h2></div>${lg.length ? `<div class="list">${lg.map(l => `<div class="item"><div class="t small">${when(l.at)} · ${esc(l.type)} ${l.level === "error" ? EM.badge("error", "bad") : ""}</div><div class="m">${esc(l.text)}</div></div>`).join("")}</div>` : EM.empty("No activity yet")}</section></div>`;
        EM.delegate(el, { sync: async () => { const r = await api("/api/live/sync/supabase", { method: "POST" }); EM.toast(`Sync ${r.status}: ${r.records} records${r.message ? " – " + r.message : ""}`, r.status === "ok" ? "ok" : "bad"); system(el); } });
      }
      await show(tab);
      return () => { if (timer) clearInterval(timer); };
    } });
})();
