/* VSB hall / seat allocation: build from the official PDFs, review, correct, approve, publish; student "my seat" view.
   Nothing here publishes anything by itself: every step that exposes data to students is an explicit administrator action. */
(function () {
  "use strict";
  const { $, esc, api } = EM;
  const API = "/api/vsb-allocation";
  const FLAG = {
    missing_in_seating_pdf: "Not on any seat sheet", missing_in_hall_pdf: "Not on the hall list", hall_mismatch: "Hall differs between PDFs",
    conflicting_halls: "Several halls on hall list", multiple_subjects: "Several subjects on hall list", subject_mismatch: "Subject differs between PDFs",
    seat_label_missing: "Seat number unreadable", seat_label_ambiguous: "Seat number ambiguous", seat_cell_ambiguous: "Seat cell ambiguous",
    seat_missing: "No seat", seat_from_text_order: "Seat from text order (unconfirmed)", ocr_ambiguous: "OCR-damaged number", ocr_text: "Read from OCR",
    hall_check_failed: "Hall total check failed", group_check_failed: "Subject/hall count check failed", department_total_mismatch: "Programme total mismatch",
    department_inferred: "Department inferred from register number", student_not_in_database: "Not in student database", duplicate_student: "Listed twice",
    nonstandard_register_number: "Non-standard register number", conflicting_seats: "Several seats", hall_capacity_exceeded: "Hall over capacity", duplicate_seat: "Seat used twice",
    hall_missing: "Hall missing", subject_missing: "Subject missing", session_unknown: "Session unknown", hall_label_variant: "Hall label has two spellings in this session", source_not_official: "Source is not the official site", seating_chart_missing: "No seating chart linked", provenance_mismatch: "Differs from the mirror database" };
  const SEV = { error: "bad", warning: "warn", info: "info" };
  const when = d => (d ? esc(String(d).replace("T", " ").slice(0, 16)) + " UTC" : "—");
  const safeUrl = u => (typeof u === "string" && /^https:\/\//i.test(u) ? esc(u) : "#");
  const flagBadges = fl => (fl || []).map(f => EM.badge(FLAG[f] || f, "warn")).join(" ");
  const st = s => EM.statusBadge(s);

  EM.vsbAllocHtml = list => (list && list.length
    ? `<div class="list">${list.map(x => `<div class="item"><div class="t">${esc(x.subject_code || "")} ${esc(x.subject || "")} <span class="muted">${esc(x.exam || "")}</span></div>
      <div class="m">${esc(x.date)} · ${esc(x.session)} · Hall <b>${esc(x.hall)}</b> · Seat <b>${esc(x.seat || "not yet verified")}</b> · ${esc(x.department || "")}</div>
      ${x.source ? `<div class="m muted small">Source: <a href="${safeUrl(x.source.url)}" target="_blank" rel="noopener noreferrer">${esc(x.source.title)} ↗</a></div>` : ""}
      ${x.verification_label ? `<div class="m muted small">${esc(x.verification_label)}</div>` : ""}
      ${x.verify_note ? `<div class="alert warn small">${esc(x.verify_note)}</div>` : ""}</div>`).join("")}</div>`
    : EM.empty("No confirmed VSB hall and seat yet", "It appears here only after the examination office’s allotment has been checked and published."));

  // ------------------------------------------------------------ student page
  EM.page({ name: "my-vsb-seat", title: "My hall & seat (VSB)", roles: ["student"],
    nav: { group: "Overview", icon: "🪑", label: "My hall & seat", order: 2 },
    render: async root => {
      const d = await api(API + "/my");
      root.innerHTML = `<section class="card"><div class="card-head"><h2>My confirmed hall and seat</h2></div>
        <p class="muted small">Register number <b class="mono">${esc(d.register_number)}</b>. ${esc(d.note)}</p>${EM.vsbAllocHtml(d.allocations)}
        <p class="muted small" style="margin-bottom:0">Official notices: <a href="https://vsbec.edu.in/controller-of-examination/" target="_blank" rel="noopener noreferrer">Controller of Examinations ↗</a></p></section>`;
    } });

  // ------------------------------------------------------------ staff page
  EM.page({ name: "vsb-allocation", title: "VSB hall & seat allocation", roles: ["admin", "staff"],
    nav: { group: "Seating", icon: "🏛", label: "VSB hall & seat", order: 5 },
    render: async (root, ctx) => {
      const adm = EM.isAdmin(), bid = ctx.query.b ? Number(ctx.query.b) : null;
      if (bid) return detail(root, bid, adm);
      root.innerHTML = `<div class="stack">
        ${adm ? `<section class="card"><div class="card-head"><h2>Import original portal data (review only)</h2></div>
          <p class="muted small">Upload the original repository's <b>allotments.json</b>. A dry run checks every row and shows what would be staged. Staging creates <b>draft batches only</b>: nothing is approved or shown to students until you review each batch and publish it.</p>
          <form id="origForm" class="toolbar"><div class="field"><label for="origFile">allotments.json</label><input id="origFile" type="file" accept="application/json,.json" required></div>
          <button type="submit" class="btn" id="origDry">Dry run</button><button type="button" class="btn primary" id="origApply" disabled>Stage as drafts…</button></form>
          <div id="origMsg" aria-live="polite"></div></section>` : ""}
        <section class="card"><div class="card-head"><h2>Build a draft from the official PDFs</h2></div>
          <p class="muted small">Choose the stored hall-allotment and seating-allotment PDFs of the same session (download them on <a href="#/vsb">VSB official notices</a>). The PDFs are read by the dedicated VSB parsers and a <b>draft</b> is staged. Nothing becomes visible to students until an administrator approves records and publishes.</p>
          <div class="toolbar"><div class="field"><label for="hv">Hall-allotment PDF</label><select id="hv"></select></div><div class="field"><label for="sv">Seating-allotment PDF</label><select id="sv"></select></div><button class="btn primary" id="build" type="button">Build draft</button></div><div id="bmsg"></div></section>
        <section class="card"><div class="card-head"><h2>Batches</h2></div><div id="batches">${EM.loading()}</div></section></div>`;
      const load = async () => {
        const [cand, bs] = await Promise.all([api(API + "/candidates"), api(API + "/batches")]);
        const opt = (k) => `<option value="">— none —</option>` + cand.filter(c => c.kind === k).map(c => `<option value="${c.version_id}">${esc(c.title)} (v${esc(c.version_no)}${c.exam_date ? ", " + esc(c.exam_date) : ""}${c.session ? " " + esc(c.session) : ""}) · ${esc(c.processing_status)}</option>`).join("");
        $("#hv", root).innerHTML = opt("hall_allotment"); $("#sv", root).innerHTML = opt("seating_allotment");
        $("#batches", root).innerHTML = bs.length ? `<div class="tablewrap"><table class="table stack"><thead><tr><th>Session</th><th>Status</th><th>Records</th><th>Open issues</th><th>Sources</th><th></th></tr></thead><tbody>${bs.map(b => `<tr>
          <td data-label="Session"><b>${esc(b.exam_date)}</b> ${esc(b.session)}<br><span class="muted small">${esc(b.exam_name || "")}</span></td>
          <td data-label="Status">${st(b.status)}${b.source_changed ? "<br>" + EM.badge("PDF replaced since", "warn") : ""}</td>
          <td data-label="Records">${esc(b.records.total)} · approved ${esc(b.records.approved || 0)} · pending ${esc(b.records.pending || 0)} · rejected ${esc(b.records.rejected || 0)}</td>
          <td data-label="Open issues">${esc(b.open_issues.error || 0)} errors · ${esc(b.open_issues.warning || 0)} warnings</td>
          <td data-label="Sources">${["hall_pdf", "seat_pdf"].map(k => b.documents[k] ? `<a href="${safeUrl(b.documents[k].source_url)}" target="_blank" rel="noopener noreferrer">${esc(k === "hall_pdf" ? "Hall" : "Seat")} v${esc(b.documents[k].version_no)} ↗</a>` : `<span class="muted">${k === "hall_pdf" ? "Hall" : "Seat"}: none</span>`).join("<br>")}</td>
          <td class="actions"><a class="btn sm primary" href="#/vsb-allocation?b=${b.id}">Open</a></td></tr>`).join("")}</tbody></table></div>` : EM.empty("No batches yet", "Build a draft from two processed PDFs.");
      };
      $("#build", root).onclick = async ev => {
        const b = ev.currentTarget, h = $("#hv", root).value, s = $("#sv", root).value; if (!h && !s) { EM.toast("Choose at least one PDF.", "bad"); return; }
        b.disabled = true; try { const r = await api(API + "/batches/build", { method: "POST", body: { hall_version_id: h ? Number(h) : null, seat_version_id: s ? Number(s) : null } });
          EM.toast(`${r.length} draft batch(es) staged. Review them before anything is published.`, "ok"); EM.go("/vsb-allocation?b=" + r[0].id); } catch (e) { $("#bmsg", root).innerHTML = EM.alert(e.message, "bad"); } finally { b.disabled = false; } };
      if (adm) {
        const send = dry => {
          const f = $("#origFile", root).files[0];
          if (!f) { EM.toast("Choose allotments.json first.", "bad"); return Promise.resolve(null); }
          const fd = new FormData(); fd.append("file", f);
          return api(API + "/import/original", { method: "POST", form: fd, params: { dry_run: dry ? "true" : "false", confirm: dry ? "false" : "true" } });
        };
        const show = r => {
          $("#origMsg", root).innerHTML = EM.alert(`${r.rows_valid} rows valid, ${r.rows_rejected} rejected, ${r.conflicts_total} conflicting register(s) not staged. ${r.records_to_stage} record(s) ${r.dry_run ? "would be" : "were"} staged${r.dry_run ? "" : " as draft batches"}.${r.dry_run ? "" : " Review each batch before publishing."}`, "")
            + `<div class="tablewrap"><table class="table stack"><thead><tr><th>Date</th><th>Session</th><th>Records</th><th>Flagged</th><th>Blocking</th><th>Linked to students</th><th>Skipped</th></tr></thead><tbody>${r.sessions.map(x => `<tr><td>${esc(x.exam_date)}</td><td>${esc(x.session)}</td><td>${esc(x.records)}</td><td>${esc(x.flagged)}</td><td>${esc(x.blocking)}</td><td>${esc(x.student_linked)}</td><td>${esc(x.skipped_reason || "—")}</td></tr>`).join("")}</tbody></table></div>`;
        };
        $("#origForm", root).onsubmit = async e => {
          e.preventDefault();
          try { const r = await send(true); if (r) { show(r); $("#origApply", root).disabled = r.records_to_stage === 0; } }
          catch (x) { $("#origMsg", root).innerHTML = EM.alert(x.message, "bad"); }
        };
        $("#origApply", root).onclick = async () => {
          const ok = await EM.confirm({ title: "Stage original data as drafts?", message: "Draft batches are created for review. Nothing is approved, published or shown to students.", confirmText: "Stage drafts" });
          if (!ok) return;
          try { const r = await send(false); if (r) { show(r); $("#origApply", root).disabled = true; await load(); } }
          catch (x) { $("#origMsg", root).innerHTML = EM.alert(x.message, "bad"); }
        };
      }
      await load();
    } });

  async function detail(root, bid, adm) {
    let off = 0; const LIM = 100;
    root.innerHTML = `<div class="stack"><div><a class="btn sm" href="#/vsb-allocation">← All batches</a></div><section class="card" id="head">${EM.loading()}</section>
      <section class="card"><div class="card-head"><h2>Issues</h2></div><div id="issues">${EM.loading()}</div></section>
      <section class="card"><div class="card-head"><h2>Records</h2></div>
        <div class="toolbar"><div class="field"><label for="q">Register number</label><input id="q" inputmode="numeric"></div><div class="field"><label for="fh">Hall</label><input id="fh" placeholder="MB III 02"></div>
        <div class="field"><label for="fs">Decision</label><select id="fs"><option value="">All</option><option value="pending">Pending</option><option value="approved">Approved</option><option value="rejected">Rejected</option></select></div>
        <label class="check"><input type="checkbox" id="fu"> Only uncertain</label></div><div id="recs">${EM.loading()}</div><div id="pg"></div></section></div>`;
    let batch = null;
    const head = async () => {
      batch = await api(`${API}/batches/${bid}`);
      const b = batch, s = b.summary || {}, draft = b.status === "draft";
      $("#head", root).innerHTML = `<div class="card-head"><h2>${esc(b.exam_date)} ${esc(b.session)} ${st(b.status)}</h2></div>
        <p class="muted small">${esc(b.exam_name || "")} · parser ${esc(b.parser_version)} · built by ${esc(b.created_by)} ${when(b.created_at)}${b.published_at ? " · published " + when(b.published_at) + " by " + esc(b.published_by) : ""}${b.withdraw_reason ? " · withdrawn: " + esc(b.withdraw_reason) : ""}</p>
        ${b.source_changed ? EM.alert("The official PDF behind this batch has been replaced by a newer version. Rebuild the draft to review the differences.", "warn") : ""}
        <dl class="kv"><dt>Students</dt><dd>${esc(s.students)} (hall list ${esc(s.hall_pdf_students)}, seat sheets ${esc(s.seat_pdf_students)})</dd><dt>Clean / uncertain / blocking</dt><dd>${esc(s.clean)} / ${esc(s.uncertain)} / ${esc(s.blocking)}</dd><dt>Halls</dt><dd>${esc(s.halls)}</dd>
        <dt>Departments</dt><dd>${Object.entries(s.by_department || {}).map(([k, v]) => `${esc(k)}: ${esc(v)}`).join(" · ")}</dd><dt>Subjects</dt><dd>${Object.entries(s.by_subject || {}).map(([k, v]) => `${esc(k)}: ${esc(v)}`).join(" · ")}</dd>
        <dt>Decisions</dt><dd>approved ${esc(b.records.approved || 0)} · pending ${esc(b.records.pending || 0)} · rejected ${esc(b.records.rejected || 0)}</dd></dl>
        ${adm ? `<div class="toolbar">${draft ? `<button class="btn" data-act="conf">Approve clean records</button><button class="btn primary" data-act="pub">Preview &amp; publish…</button>` : ""}${b.status === "published" ? `<button class="btn" data-act="bridge">Bridge to seat allotments…</button><button class="btn danger" data-act="wd">Withdraw</button>` : ""}${b.status === "withdrawn" ? `<button class="btn" data-act="reopen">Reopen as draft</button>` : ""}</div>` : EM.alert("Only administrators can correct, approve or publish.", "info")}`;
    };
    const issues = async () => {
      const rows = await api(`${API}/batches/${bid}/issues`, { params: { status: "open" } });
      $("#issues", root).innerHTML = rows.length ? `<div class="list">${rows.slice(0, 150).map(i => `<div class="item"><div class="t">${EM.badge(i.severity, SEV[i.severity])} ${esc(i.kind)}${i.page ? ` <span class="muted small">PDF page ${esc(i.page)}</span>` : ""}</div><div class="m">${esc(i.message)}</div>${adm ? `<div class="m"><button class="btn sm" data-act="iss" data-id="${i.id}">Resolve / dismiss</button></div>` : ""}</div>`).join("")}</div>${rows.length > 150 ? `<p class="muted small">Showing 150 of ${rows.length}.</p>` : ""}` : EM.empty("No open issues");
    };
    const recs = async () => {
      const r = await api(`${API}/batches/${bid}/records`, { params: { q: $("#q", root).value, hall: $("#fh", root).value, status: $("#fs", root).value, uncertain: $("#fu", root).checked, limit: LIM, offset: off } });
      const draft = batch && batch.status === "draft";
      $("#recs", root).innerHTML = r.records.length ? `<div class="tablewrap"><table class="table stack"><caption class="sr-only">Proposed hall and seat per student</caption><thead><tr><th>Register no.</th><th>Department</th><th>Subject</th><th>Exam / date</th><th>Hall</th><th>Seat</th><th>Flags</th><th>Decision</th><th></th></tr></thead><tbody>${r.records.map(x => `<tr>
        <td data-label="Register no." class="mono">${esc(x.register_number)}${x.student_known ? "" : "<br>" + EM.badge("not in DB", "warn")}</td><td data-label="Department">${esc(x.department || "—")}</td>
        <td data-label="Subject"><b>${esc(x.subject_code || "—")}</b><br><span class="small muted">${esc(x.subject_title || "")}</span></td><td data-label="Exam / date">${esc(x.exam_name || "")}<br>${esc(x.exam_date)} ${esc(x.session)}</td>
        <td data-label="Hall">${esc(x.hall || "—")}${adm && x.seating_chart ? `<br><a href="#" data-act="chart" data-name="${esc(x.seating_chart)}">Original seat chart</a>` : ""}${x.hall_pdf_hall && x.seat_pdf_hall && x.hall_pdf_hall !== x.seat_pdf_hall ? `<br><span class="small">hall PDF: ${esc(x.hall_pdf_hall)}<br>seat PDF: ${esc(x.seat_pdf_hall)}</span>` : ""}</td><td data-label="Seat"><b>${esc(x.seat || "—")}</b></td>
        <td data-label="Flags">${flagBadges(x.flags) || '<span class="muted">none</span>'}${x.edited ? "<br>" + EM.badge("corrected", "info") : ""}${(x.notes || []).map(n => `<br><span class="small">${esc(n)}</span>`).join("")}</td>
        <td data-label="Decision">${st(x.review_status)}${x.review_note ? `<br><span class="small muted">${esc(x.review_note)}</span>` : ""}</td>
        <td class="actions">${adm && draft ? `<button class="btn sm" data-act="edit" data-id="${x.id}">Correct</button><button class="btn sm primary" data-act="ok" data-id="${x.id}">Approve</button><button class="btn sm" data-act="no" data-id="${x.id}">Reject</button>${x.review_status !== "pending" ? `<button class="btn sm" data-act="reset" data-id="${x.id}">Undo</button>` : ""}` : ""}</td></tr>`).join("")}</tbody></table></div>` : EM.empty("No records match");
      EM.pager($("#pg", root), { total: r.total, limit: LIM, offset: off, onPage: o => { off = o; recs().catch(EM.fail); } });
      root._recs = Object.fromEntries(r.records.map(x => [x.id, x]));
    };
    const all = async () => { await head(); await Promise.all([issues(), recs()]); };
    ["q", "fh", "fs", "fu"].forEach(id => { $("#" + id, root).onchange = () => { off = 0; recs().catch(EM.fail); }; });
    const decide = async (id, decision, ask) => {
      const x = root._recs[id]; let body = { decision, note: "", acknowledge: false };
      if (decision === "approve" && x.flags.length) {
        const a = await EM.ask({ title: "This record carries flags", message: (x.flags.map(f => FLAG[f] || f).join("; ")) + ". Confirm you checked it against the official PDF.", fields: [{ name: "note", label: "How did you verify it?", required: true }, ...(x.blocking && !x.edited ? [{ name: "acknowledge", label: "I verified this against the official PDF", type: "checkbox", required: true }] : [])], submitText: "Approve" });
        if (!a) return; body = { decision, note: a.note, acknowledge: !!a.acknowledge };
      } else if (ask) { const a = await EM.ask({ title: "Reject record", fields: [{ name: "note", label: "Reason", required: true }], submitText: "Reject" }); if (!a) return; body.note = a.note; }
      await api(`${API}/records/${id}/review`, { method: "POST", body }); await all();
    };
    EM.delegate(root, {
      edit: async b => { const x = root._recs[b.dataset.id];
        const a = await EM.ask({ title: `Correct ${x.register_number}`, message: "Enter values exactly as printed in the official PDF. Every change is recorded with your reason.", fields: [
          { name: "hall", label: "Hall", value: x.hall || "" }, { name: "seat", label: "Seat", value: x.seat || "" }, { name: "subject_code", label: "Subject code", value: x.subject_code || "" }, { name: "department", label: "Department", value: x.department || "" },
          { name: "reason", label: "Reason / evidence (e.g. PDF page)", required: true }], submitText: "Save correction" });
        if (!a) return; const body = { reason: a.reason }; ["hall", "seat", "subject_code", "department"].forEach(k => { if (a[k] !== (x[k] || "")) body[k] = a[k]; });
        await api(`${API}/records/${x.id}`, { method: "PATCH", body }); EM.toast("Corrected. The record is pending again and needs approval.", "ok"); await all(); },
      chart: async b => {
        const w = window.open("", "_blank");
        try {
          const r = await fetch(`${API}/charts/${encodeURIComponent(b.dataset.name)}`, { headers: { Authorization: "Bearer " + EM.state.token } });
          if (!r.ok) throw new Error("The seating chart is not available.");
          const url = URL.createObjectURL(await r.blob());
          if (w) w.location = url; else EM.toast("Allow pop-ups to view the chart.", "bad");
        } catch (e) { if (w) w.close(); EM.toast(e.message, "bad"); }
      },
      ok: b => decide(b.dataset.id, "approve"), no: b => decide(b.dataset.id, "reject", true), reset: b => decide(b.dataset.id, "reset"),
      conf: async () => { const r = await api(`${API}/batches/${bid}/approve-confident`, { method: "POST" }); EM.toast(`${r.approved} clean record(s) approved. Flagged records were left for review.`, "ok"); await all(); },
      iss: async b => { const a = await EM.ask({ title: "Resolve issue", fields: [{ name: "decision", label: "Outcome", type: "select", options: [["resolved", "Resolved (fixed or verified)"], ["dismissed", "Dismissed (not a real problem)"]] }, { name: "note", label: "Note", required: true }] }); if (!a) return;
        await api(`${API}/issues/${b.dataset.id}/resolve`, { method: "POST", body: a }); await Promise.all([head(), issues()]); },
      pub: async () => { const p = await api(`${API}/batches/${bid}/publish/preview`, { method: "POST" });
        const ok = await EM.confirm({ title: "Publish to students?", message: `${p.will_publish} approved record(s) will become visible to those students. ${p.pending} pending and ${p.rejected} rejected record(s) stay hidden.`,
          detail: `${p.approved_with_flags} approved record(s) carry flags you accepted; ${p.approved_without_student} have no student account match; ${p.open_error_issues} error issue(s) still open.`, confirmText: "Publish" });
        if (!ok) return; await api(`${API}/batches/${bid}/publish`, { method: "POST", body: { signature: p.signature, confirm: true, acknowledge_open_issues: p.open_error_issues > 0 } }); EM.toast("Published.", "ok"); await all(); },
      wd: async () => { const a = await EM.ask({ title: "Withdraw published batch", message: "Students will no longer see these seats.", fields: [{ name: "reason", label: "Reason", required: true }], danger: true, submitText: "Withdraw" }); if (!a) return;
        await api(`${API}/batches/${bid}/withdraw`, { method: "POST", body: a }); await all(); },
      reopen: async () => { await api(`${API}/batches/${bid}/reopen`, { method: "POST" }); await all(); },
      bridge: async () => { const p = await api(`${API}/batches/${bid}/bridge/preview`, { method: "POST" });
        const blocked = p.items.filter(i => i.state === "blocked").slice(0, 8).map(i => `${i.register_number}: ${i.reasons.join(", ")}`).join("\n");
        const ok = await EM.confirm({ title: "Create seat allotments?", message: `${p.summary.ready} record(s) can be written to the seat-allotment system (examination matched by date and subject). ${p.summary.blocked} are blocked.`, detail: blocked, confirmText: "Create allotments" });
        if (!ok) return; const r = await api(`${API}/batches/${bid}/bridge`, { method: "POST", body: { signature: p.signature, confirm: true, skip_blocked: true } }); EM.toast(`${r.created} allotment(s) created.`, "ok"); await all(); } });
    await all();
  }
})();
