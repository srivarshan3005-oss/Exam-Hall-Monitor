/* Official V.S.B. Engineering College sources: confirmed links, PDF discovery/download, status and history.
   Every address shown here comes from the server (confirmed official pages or links found on the official page). */
(function () {
  "use strict";
  const { $, esc, api } = EM;
  const KIND = { hall_allotment: "Hall allotment", seating_allotment: "Seating allotment", timetable: "Timetable", notice: "Notice", other: "Other (manual)" };
  const STATUS_CLS = { downloaded: "ok", unchanged: "ok", duplicate: "info", discovered: "warn", skipped: "", unavailable: "bad", failed: "bad", blocked: "bad" };
  const STATUS_TXT = { downloaded: "Downloaded", unchanged: "Up to date", duplicate: "Duplicate", discovered: "Not downloaded yet", skipped: "Not auto-downloaded", unavailable: "Unavailable", failed: "Failed – will retry", blocked: "Blocked" };
  const safeUrl = u => (typeof u === "string" && /^https:\/\//i.test(u) ? esc(u) : "#");
  const ext = (u, t) => `<a href="${safeUrl(u)}" target="_blank" rel="noopener noreferrer">${esc(t)} ↗</a>`;
  const when = d => (d ? esc(String(d).replace("T", " ").slice(0, 16)) + " UTC" : "—");
  const sess = l => [l.exam_date ? esc(l.exam_date) : "", l.session ? esc(l.session) : ""].filter(Boolean).join(" · ") || '<span class="muted">not stated</span>';
  const pub = l => l.published_at ? `${when(l.published_at)}<br><span class="muted small">server Last-Modified</span>` : l.upload_month ? `${esc(l.upload_month)}<br><span class="muted small">month uploaded to site</span>` : '<span class="muted">not stated</span>';

  // ------------------------------------------------------------ public card used on the home page
  EM.vsbPublicCard = async function (el) {
    try {
      const d = await api("/api/vsb/official-links", { auth: false });
      const docs = d.documents.slice(0, 12);
      el.innerHTML = `<div class="row" style="flex-wrap:wrap;gap:8px">${d.sources.map(s => `<a class="btn sm" href="${safeUrl(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)} ↗</a>`).join("")}</div>` +
        (docs.length ? `<div class="list" style="margin-top:12px">${docs.map(x => `<div class="item"><div class="t">${ext(x.url, x.title)}</div><div class="m">${esc(KIND[x.kind] || x.kind)}${x.exam_date ? " · " + esc(x.exam_date) : ""}${x.session ? " · " + esc(x.session) : ""}</div></div>`).join("")}</div>` : `<p class="muted small" style="margin-top:12px">No notices have been fetched into this system yet. Use the official links above for the latest PDFs.</p>`) +
        `<p class="muted small" style="margin-bottom:0">${esc(d.note)}</p>`;
    } catch (e) { el.innerHTML = EM.alert("Official links are temporarily unavailable here. Visit https://vsbec.edu.in/controller-of-examination/ directly.", "warn"); }
  };

  // ------------------------------------------------------------ staff page
  EM.page({ name: "vsb", title: "VSB official notices", roles: ["admin", "staff"],
    nav: { group: "Documents", icon: "🏛", label: "VSB official notices", order: 0 },
    render: async (root, ctx) => {
      root.innerHTML = `<div class="stack">
        <section class="card"><div class="card-head"><h2>Official sources</h2></div><div id="src">${EM.loading()}</div></section>
        <section class="card"><div class="card-head"><h2>Discover &amp; download</h2></div>
          <p class="muted small">Reads the college’s Controller of Examinations page, records every PDF link it lists and downloads new or changed hall allotments, seating allotments, timetables and notices. Downloads respect the site’s robots.txt and are spaced out. Nothing is published to students automatically.</p>
          <div class="toolbar"><label class="check"><input type="checkbox" id="dl" checked> Download relevant PDFs</label><label class="check"><input type="checkbox" id="ap" checked> Run PDF processing/OCR on new downloads</label><label class="check"><input type="checkbox" id="sd" checked> Stage hall/seat PDFs as <b>draft</b> allocations (never published)</label><button class="btn primary" id="run" type="button">Check official page now</button></div>
          <div id="last" style="margin-top:10px"></div></section>
        <section class="card"><div class="card-head"><h2>Discovered PDFs</h2></div>
          <div class="toolbar"><div class="field"><label for="fk">Type</label><select id="fk"><option value="">All</option>${Object.entries(KIND).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select></div>
          <div class="field"><label for="fs">Status</label><select id="fs"><option value="">All</option>${Object.entries(STATUS_TXT).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select></div>
          <div class="field"><label for="fl">Listing</label><select id="fl"><option value="">All</option><option value="yes">Still on official page</option><option value="no">No longer listed</option></select></div></div>
          <div id="grid">${EM.loading()}</div></section>
        <section class="card"><div class="card-head"><h2>Document history</h2></div><div id="hist">${EM.empty("Select “History” on a PDF", "Source address, versions, downloads and processing events appear here.")}</div></section>
        <section class="card"><div class="card-head"><h2>Discovery runs</h2></div><div id="runs">${EM.loading()}</div></section></div>`;
      let grid = null;
      const loadSources = async () => {
        try {
          const s = await api("/api/vsb/sources");
          $("#src", root).innerHTML = `<div class="list">${s.sources.map(x => `<div class="item"><div class="t">${ext(x.url, x.title)}</div><div class="m">${esc(x.purpose)} · ${x.crawl ? "read by Discover" : "link only"}</div><div class="m muted small">${esc(x.confirmed)}</div></div>`).join("")}</div><p class="muted small" style="margin-bottom:0">Allowed hosts: ${s.allowed_hosts.map(esc).join(", ")} · Scheduled checks: ${s.auto_discover_enabled ? "on, every " + esc(s.auto_discover_interval_minutes) + " min" : "off (set VSB_AUTO_DISCOVER_ENABLED=true)"}</p>`;
          showRun(s.last_run);
        } catch (e) { $("#src", root).innerHTML = EM.alert(e.message, "bad"); }
      };
      const showRun = r => {
        $("#last", root).innerHTML = r ? `<div class="alert ${r.status === "ok" ? "ok" : r.status === "failed" ? "bad" : "warn"}" role="status"><b>Last run #${esc(r.id)} (${esc(r.trigger)}): ${esc(r.status)}</b> · ${when(r.started_at)} · ${esc(r.links_found)} links found, ${esc(r.new_links)} new, ${esc(r.downloaded)} downloaded, ${esc(r.duplicates)} duplicate, ${esc(r.unavailable)} unavailable, ${esc(r.failed)} failed.${r.message ? "<br>" + esc(r.message) : ""}${(r.staging || []).map(n => "<br>" + esc(n)).join("")}</div>` : EM.empty("No discovery run yet", "Press “Check official page now”.");
      };
      const loadLinks = async () => {
        const g = $("#grid", root);
        try {
          const rows = await api("/api/vsb/links", { params: { kind: $("#fk", root).value, status: $("#fs", root).value, listed: $("#fl", root).value, limit: 500 } });
          const cfg = { rows, caption: "PDFs found on the official college page", pageSize: 10, searchKeys: ["title", "url", "kind", "status"],
            empty: { title: "No PDFs recorded yet", text: "Run “Check official page now” to read the official page." },
            columns: [
              { key: "title", label: "Document", render: l => `${ext(l.url, l.title)}<br><span class="muted small">${esc(KIND[l.kind] || l.kind)}${l.still_listed ? "" : " · no longer listed"}</span>${l.note ? `<br><span class="small">${esc(l.note)}</span>` : ""}` },
              { key: "exam_date", label: "Exam date / session", render: sess },
              { key: "published_at", label: "Published", sort: false, render: pub },
              { key: "status", label: "Download status", render: l => `${EM.badge(STATUS_TXT[l.status] || l.status, STATUS_CLS[l.status] || "")}${l.http_status ? `<br><span class="muted small">HTTP ${esc(l.http_status)}</span>` : ""}${l.error ? `<br><span class="small">${esc(l.error)}</span>` : ""}${l.last_downloaded_at ? `<br><span class="muted small">downloaded ${when(l.last_downloaded_at)}</span>` : ""}` },
              { key: "version", label: "Stored copy", sort: false, render: l => l.version ? `v${esc(l.version.version_no)} · ${esc(l.version.pages)} pp<br>${EM.statusBadge(l.version.processing_status)} ${EM.statusBadge(l.version.review_status)}<br><span class="muted small mono">${esc(l.version.sha256)}…</span>` : '<span class="muted">none</span>' }],
            actions: l => `<button class="btn sm" data-act="dl" data-id="${l.id}">${l.document_id ? "Re-check" : "Download"}</button><button class="btn sm" data-act="hist" data-id="${l.id}">History</button>${l.version && l.version.processing_status === "pending" ? `<button class="btn sm" data-act="proc" data-v="${l.version.version_id}">Process</button>` : ""}${l.version && l.version.processing_status !== "pending" ? ((l.kind === "seating_allotment" || l.kind === "hall_allotment") ? `<a class="btn sm primary" href="#/vsb-allocation">Build allocation</a>` : `<a class="btn sm" href="#/documents">Review PDF</a>`) : ""}` };
          if (grid && g.querySelector("[data-g=body]")) grid.setRows(rows); else grid = EM.grid(g, cfg);
        } catch (e) { g.innerHTML = EM.alert(e.message, "bad"); }
      };
      const loadRuns = async () => {
        try {
          const rs = await api("/api/vsb/runs", { params: { limit: 15 } });
          $("#runs", root).innerHTML = rs.length ? `<div class="list">${rs.map(r => `<div class="item"><div class="t">#${esc(r.id)} · ${when(r.started_at)} · ${esc(r.trigger)} by ${esc(r.actor)} ${EM.badge(r.status, r.status === "ok" ? "ok" : r.status === "failed" ? "bad" : "warn")}</div><div class="m">${esc(r.links_found)} found · ${esc(r.new_links)} new · ${esc(r.downloaded)} downloaded · ${esc(r.duplicates)} duplicate · ${esc(r.unavailable)} unavailable · ${esc(r.failed)} failed${r.message ? "<br>" + esc(r.message) : ""}</div></div>`).join("")}</div>` : EM.empty("No runs yet");
        } catch (e) { $("#runs", root).innerHTML = EM.alert(e.message, "bad"); }
      };
      const refreshAll = async () => { await Promise.all([loadSources(), loadLinks(), loadRuns()]); };
      ["fk", "fs", "fl"].forEach(id => { $("#" + id, root).onchange = loadLinks; });
      EM.delegate(root, {
        dl: async b => { const r = await api(`/api/vsb/links/${b.dataset.id}/download`, { method: "POST", params: { process: true } });
          const m = { downloaded: "Downloaded and stored.", unchanged: "Already up to date.", duplicate: "Identical to a PDF already stored.", unavailable: "The official site no longer serves this file.", failed: "Could not download (network or server problem). It will be retried.", blocked: "Download blocked by the site rules or PDF safety checks." };
          EM.toast((m[r.outcome] || r.outcome) + (r.process_note ? " " + r.process_note : ""), ["downloaded", "unchanged", "duplicate"].includes(r.outcome) ? "ok" : "bad"); await Promise.all([loadLinks(), loadSources()]); },
        proc: async b => { const r = await api(`/api/admin/doc-processing/${b.dataset.v}/process`, { method: "POST" }); EM.toast(`Processed ${r.pages} pages; ${r.entries} rows need review.`, "ok"); await loadLinks(); },
        hist: async b => { const h = $("#hist", root); h.innerHTML = EM.loading(); const d = await api(`/api/vsb/links/${b.dataset.id}/history`), l = d.link;
          h.innerHTML = `<dl class="kv"><dt>Title</dt><dd>${esc(l.title)}</dd><dt>Source URL</dt><dd>${ext(l.url, l.url)}</dd><dt>Found on</dt><dd>${l.listing_url ? ext(l.listing_url, l.listing_url) : "—"}</dd><dt>First / last seen</dt><dd>${when(l.first_seen_at)} / ${when(l.last_seen_at)}</dd><dt>Published</dt><dd>${pub(l)}</dd><dt>Status</dt><dd>${esc(STATUS_TXT[l.status] || l.status)}${l.note ? " — " + esc(l.note) : ""}</dd></dl>
            <h3 style="margin-top:12px">Versions</h3>${d.versions.length ? `<div class="list">${d.versions.map(v => `<div class="item"><div class="t">Version ${esc(v.version_no)}${v.is_current ? " (current)" : ""} · ${esc(v.pages)} pages · ${esc(v.size_bytes)} bytes</div><div class="m">Downloaded ${when(v.downloaded_at)} · ${EM.statusBadge(v.processing_status)} ${EM.statusBadge(v.review_status)}<br><span class="mono small">${esc(v.sha256)}</span></div></div>`).join("")}</div>` : EM.empty("No copy stored", "Nothing has been downloaded for this link yet.")}
            <h3 style="margin-top:12px">Events</h3>${d.events.length ? `<div class="list">${d.events.map(e => `<div class="item"><div class="t">${esc(e.event)} <span class="muted small">v${esc(e.version_id)} · ${when(e.at)} · ${esc(e.actor)}</span></div>${e.detail ? `<div class="m small">${esc(e.detail)}</div>` : ""}</div>`).join("")}</div>` : EM.empty("No events")}`; h.scrollIntoView({ block: "nearest" }); } });
      $("#run", root).onclick = async ev => {
        const btn = ev.currentTarget; btn.disabled = true; btn.textContent = "Checking official page…";
        try {
          const r = await api("/api/vsb/discover", { method: "POST", body: { download: $("#dl", root).checked, auto_process: $("#ap", root).checked, stage_drafts: $("#sd", root).checked } });
          showRun(r); EM.toast(r.status === "failed" ? "The official page could not be read. Nothing was changed." : `Done: ${r.new_links} new link(s), ${r.downloaded} downloaded.`, r.status === "failed" ? "bad" : "ok"); await Promise.all([loadLinks(), loadRuns(), loadSources()]);
        } catch (e) { EM.fail(e); } finally { btn.disabled = false; btn.textContent = "Check official page now"; }
      };
      await refreshAll();
    } });
})();
