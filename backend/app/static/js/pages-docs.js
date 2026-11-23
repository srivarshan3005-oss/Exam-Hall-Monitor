/* Official PDFs: upload, extraction/OCR, review & correction, timetable import preview/confirmation, history,
   seating-allotment PDF import, and the Phase 1 seating-register candidate queue. */
(function () {
  "use strict";
  const { $, esc, api } = EM;
  const B = "/api/admin/doc-processing";
  const kinds = [["timetable", "Timetable"], ["hall_allotment", "Hall allotment"], ["seating_allotment", "Seating allotment"], ["notice", "Notice"], ["other", "Other"]];
  const KIND = Object.fromEntries(kinds);
  const examOpts = exams => [["", "Select examination…"]].concat(exams.map(e => [e.id, `#${e.id} ${e.title} · ${e.exam_date} ${e.start_time}`]));
  const bar = (vid, cur) => `<nav class="tabs" aria-label="Document steps"><a href="#/documents">← All documents</a>${[["review", "Review & correct"], ["import", "Import timetable"], ["history", "History"]].map(t => `<a href="#/documents/${vid}/${t[0]}" ${cur === t[0] ? 'aria-current="page" class="active"' : ""}>${t[1]}</a>`).join("")}</nav>`;
  async function process(vid, force) {
    EM.toast("Extracting text" + (force ? " with OCR" : "") + "… this can take a minute for scanned PDFs.");
    const r = await api(`${B}/${vid}/process`, { method: "POST", params: force ? { force_ocr: "true" } : {} });
    EM.toast(`Done: ${r.entries} row(s) on ${r.pages} page(s); ${r.ocr_pages} read with OCR.`, "ok");
    if (r.issues && r.issues.length) await EM.show("Extraction notes", `<ul>${r.issues.map(i => `<li>${esc(i)}</li>`).join("")}</ul>`);
    return r;
  }

  EM.page({ name: "documents", title: "Timetable PDFs", roles: ["admin", "staff"], nav: { group: "Documents", icon: "📄", label: "Timetable PDFs", order: 1 }, render: async (root, ctx) => {
    if (ctx.args[0]) { const v = Number(ctx.args[0]), s = ctx.args[1] || "review"; return s === "import" ? importView(root, v) : s === "history" ? historyView(root, v) : reviewView(root, v, ctx); }
    const [caps, terms] = await Promise.all([api(B + "/capabilities"), api("/api/admin/terms").catch(() => [])]);
    let rows = await api(B, { params: { limit: 300 } });
    root.innerHTML = `<div class="stack"><div class="alert info">PDF limit ${esc(caps.max_upload_mb)} MB · up to ${esc(caps.max_pages)} pages · OCR ${caps.ocr_available ? "available (" + esc(caps.ocr_languages.join(", ")) + ")" : "<b>NOT available on this server</b> — scanned PDFs cannot be read"}.${caps.can_review ? "" : " Editing, approval and import need an examination administrator."}</div>
      <section class="card"><div class="card-head"><h2>Upload official PDF</h2></div><form id="uf" class="form-grid">${EM.field({ name: "title", label: "Document title", required: true, attrs: 'maxlength="300"' })}${EM.field({ name: "doc_kind", label: "Type", type: "select", options: kinds })}${EM.field({ name: "source_label", label: "Source", placeholder: "e.g. Controller of Examinations" })}${EM.field({ name: "exam_name", label: "Examination name (optional)" })}${EM.field({ name: "term_id", label: "Examination term (optional)", type: "select", options: [["", "None"]].concat(terms.map(t => [t.id, t.name])) })}<div class="field"><label for="pdf" class="req">PDF file</label><input id="pdf" name="file" type="file" accept="application/pdf,.pdf" required></div><div class="full form-actions"><button class="btn primary">Upload and extract</button></div></form></section>
      <section class="card"><div class="card-head"><h2>Documents</h2></div><div id="g"></div></section></div>`;
    const grid = EM.grid($("#g", root), { rows, caption: "Official documents", searchKeys: ["title", "source", "kind", "uploaded_by"], empty: { title: "No documents uploaded yet", text: "Upload a timetable or allotment PDF above." }, columns: [
      { key: "title", label: "Document", render: d => `<b>${esc(d.title)}</b><br><span class="muted small">#${d.version_id} · ${esc(KIND[d.kind] || d.kind)} · ${esc(d.source || "source not stated")} · ${Math.round(d.size_bytes / 1024)} KB · ${esc(d.pages ?? "?")} page(s)</span>` },
      { key: "processing_status", label: "Status", render: d => EM.statusBadge(d.processing_status) + EM.badge("review: " + d.review_status, d.review_status === "approved" ? "ok" : d.review_status === "rejected" ? "bad" : "warn") + (d.ocr_used ? EM.badge("OCR", "warn") : "") + (d.imported_at ? EM.badge("imported", "ok") : "") + (d.processing_error ? `<br><span class="small" style="color:var(--bad)">${esc(d.processing_error)}</span>` : "") },
      { key: "uploaded_at", label: "Uploaded", render: d => `${esc(EM.fmtDate(d.uploaded_at))}<br><span class="muted small">${esc(d.uploaded_by || "")}</span>` }, { key: "rows", label: "Rows", sort: false, render: d => esc(Object.entries(d.entry_counts).map(([k, v]) => v + " " + k).join(" · ") || "—") }],
      actions: d => `<button class="btn sm" data-act="proc" data-id="${d.version_id}">${d.processing_status === "pending" ? "Extract" : "Re-extract"}</button><a class="btn sm primary" href="#/documents/${d.version_id}/review">Review</a><a class="btn sm" href="#/documents/${d.version_id}/import">Import</a><a class="btn sm" href="#/documents/${d.version_id}/history">History</a><button class="btn sm" data-act="dl" data-id="${d.version_id}">Download</button>` });
    const reload = async () => { rows = await api(B, { params: { limit: 300 } }); grid.setRows(rows); };
    EM.onSubmit($("#uf", root), async (d, f) => {
      const fd = new FormData(f); if (!fd.get("term_id")) fd.delete("term_id");
      EM.toast("Uploading…"); const up = await api(B + "/upload", { method: "POST", form: fd }); f.reset(); await reload();
      try { await process(up.version_id, false); } finally { await reload(); }
      EM.go(`/documents/${up.version_id}/review`);
    });
    EM.delegate(root, {
      proc: async b => { const d = rows.find(x => x.version_id === Number(b.dataset.id)); if (d.processing_status !== "pending" && !await EM.confirm({ title: "Re-run extraction?", message: "Machine-extracted rows are replaced (your edit history is kept).", confirmText: "Re-extract" })) return; await process(b.dataset.id, false); await reload(); },
      dl: async b => { await EM.download(`${B}/${b.dataset.id}/download`, "document.pdf"); },
    });
  } });

  // ------------------------------------------------------------ review & correction
  const COLS = [["exam_date", "Date", "date"], ["start_time", "Start", "time"], ["end_time", "End", "time"], ["subject_code", "Code", "text"], ["subject_name", "Subject name", "text"], ["department", "Department", "text"], ["year", "Year", "number"], ["semester", "Sem", "number"]];
  async function reviewView(root, vid) {
    const adm = EM.isAdmin();
    let [info, rev, subjects] = await Promise.all([api(`${B}/${vid}`), api(`${B}/${vid}/review`), api("/api/admin/subjects", { params: { limit: 500 } })]);
    let entries = rev.entries, only = false; const h0 = () => rev.header;
    root.innerHTML = `<div class="stack">${bar(vid, "review")}<div id="head"></div><div class="grid g2"><section class="card"><div class="card-head"><h3>Original PDF</h3></div><div class="toolbar"><div class="field"><label for="pg">Page</label><select id="pg">${info.page_info.map(p => `<option value="${p.page_number}">Page ${p.page_number} — ${esc(p.method || "?")}${p.ocr_confidence != null ? " " + Math.round(p.ocr_confidence * 100) + "%" : ""}${p.warning ? " ⚠" : ""}</option>`).join("")}</select></div><button class="btn" data-act="txt">Show extracted text</button><button class="btn" data-act="dl">Download original</button></div><div id="pinfo" class="small muted"></div><img id="pimg" alt="Preview of the selected PDF page" style="max-width:100%;border:1px solid var(--line);border-radius:10px;background:#fff;margin-top:8px"><pre id="ptxt" class="pre hidden"></pre></section>
      <section class="card"><div class="card-head"><h3>Extracted document details</h3></div><form id="hf" class="stack">${EM.field({ name: "exam_name", label: "Examination name" })}<div class="form-grid">${EM.field({ name: "session_label", label: "Session", type: "select", options: [["", "None"], ["FN", "FN"], ["AN", "AN"]] })}${EM.field({ name: "academic_year", label: "Academic year" })}${EM.field({ name: "department", label: "Department" })}${EM.field({ name: "semester", label: "Semester", type: "number", attrs: 'min="1" max="12"' })}</div>${adm ? `<button class="btn primary">Save details</button>` : ""}</form><div id="hinfo" class="small" style="margin-top:8px"></div><h4 style="margin-top:12px">Instructions found</h4><ol id="instr" class="small"></ol></section></div>
      <section class="card"><div class="card-head"><h3>Timetable rows <span class="muted small" id="cnt"></span></h3></div><div class="toolbar">${EM.field({ name: "reason", label: "Reason for corrections (saved in the audit trail)", attrs: 'id="reason" maxlength="300"', cls: "wide" })}<label class="check"><input type="checkbox" id="unc"> Uncertain rows only</label>${adm ? `<button class="btn" data-act="bulk">Approve all complete &amp; confident</button><button class="btn" data-act="reproc">Re-run extraction</button><button class="btn" data-act="ocr">Re-run with OCR</button>` : ""}</div><div id="rows" class="list"></div>
      ${adm ? `<h4 style="margin-top:16px">Add a missing row</h4><form id="af" class="form-grid">${EM.field({ name: "subject_code", label: "Code", required: true })}${EM.field({ name: "subject_name", label: "Subject name" })}${EM.field({ name: "exam_date", label: "Date", type: "date", required: true })}${EM.field({ name: "start_time", label: "Start", type: "time", required: true })}${EM.field({ name: "end_time", label: "End", type: "time", required: true })}${EM.field({ name: "department", label: "Department" })}${EM.field({ name: "year", label: "Year", type: "number", attrs: 'min="1" max="6"' })}<div class="full"><button class="btn">Add row</button></div></form>
      <div class="form-actions" style="margin-top:16px"><button class="btn primary" data-act="docok">Approve document</button><button class="btn danger" data-act="docno">Reject document</button><a class="btn" href="#/documents/${vid}/import">Continue to import →</a></div>` : `<p class="muted small" style="margin-top:12px">Only an examination administrator can edit, approve and import.</p>`}</section></div>`;
    const paintHead = () => { $("#head", root).innerHTML = `<div class="row"><h2 style="margin:0">${esc(info.title)}</h2>${EM.statusBadge(info.processing_status)}${EM.badge("review: " + info.review_status, info.review_status === "approved" ? "ok" : info.review_status === "rejected" ? "bad" : "warn")}<span class="muted small">version #${info.version_id}</span></div>`; };
    const paintHeader = () => { const h = h0(), f = $("#hf", root); if (h) for (const k of ["exam_name", "session_label", "academic_year", "department", "semester"]) f.elements[k].value = h[k] ?? "";
      f.querySelectorAll("input,select,button").forEach(x => { x.disabled = !adm || !h; });
      $("#hinfo", root).innerHTML = h ? h.flags.map(x => EM.badge(x.replace(/_/g, " "), "warn")).join(" ") + h.issues.map(x => `<div class="alert warn" style="margin-top:6px">${esc(x)}</div>`).join("") + `<div class="muted" style="margin-top:6px">${esc(h.register_numbers_found)} register number(s) detected in the text (kept private; not imported here).</div>` : EM.alert("Not extracted yet — go back and press Extract.", "warn");
      $("#instr", root).innerHTML = h && h.instructions.length ? h.instructions.map(x => `<li>${esc(x)}</li>`).join("") : "<li class='muted'>None found.</li>"; };
    const paintRows = () => {
      const list = entries.filter(e => !only || e.uncertain_fields.length || e.low_confidence), c = {}; entries.forEach(e => { c[e.review_status] = (c[e.review_status] || 0) + 1; });
      $("#cnt", root).textContent = Object.entries(c).map(([k, v]) => v + " " + k).join(" · ");
      $("#rows", root).innerHTML = list.map(e => { const lock = e.review_status === "imported" || !adm;
        return `<div class="item ${e.low_confidence || e.uncertain_fields.length ? "warn" : ""}" data-eid="${e.id}"><div class="t">Row ${e.row_no} · page ${e.page_number} ${EM.statusBadge(e.review_status)}${EM.badge(e.source)}${EM.badge(Math.round((e.confidence ?? 0) * 100) + "% confidence", e.low_confidence ? "warn" : "ok")}${e.edited ? EM.badge("edited", "info") : ""}</div>
        <div class="m">Source text: ${esc(e.raw_text || "—")}</div>${e.flags.length ? `<div>${e.flags.map(f => EM.badge(f.replace(/_/g, " "), "warn")).join(" ")}</div>` : ""}
        <div class="entry-grid">${COLS.map(([k, l, t]) => `<div><label>${l}</label><input data-f="${k}" type="${t}" value="${esc(e[k] ?? "")}" class="${e.uncertain_fields.includes(k) ? "uncertain" : ""}" ${lock ? "disabled" : ""}></div>`).join("")}<div><label>Session</label><select data-f="session" ${lock ? "disabled" : ""}><option value=""></option>${["FN", "AN"].map(s => `<option ${e.session === s ? "selected" : ""}>${s}</option>`).join("")}</select></div><div><label>Catalogue subject</label><select data-f="subject_id" ${lock ? "disabled" : ""}><option value="">${e.catalogue_match ? "auto: " + esc(e.catalogue_match.name) : "— not mapped —"}</option>${subjects.map(s => `<option value="${s.id}" ${e.subject_id === s.id ? "selected" : ""}>${esc(s.code)} · ${esc(s.name)}</option>`).join("")}</select></div></div>
        ${lock ? "" : `<div class="row"><button class="btn sm primary" data-act="save">Save corrections</button><button class="btn sm" data-act="dec" data-d="approved">Approve</button><button class="btn sm danger" data-act="dec" data-d="rejected">Reject</button><button class="btn sm" data-act="dec" data-d="pending">Mark pending</button></div>`}</div>`; }).join("") || EM.empty("No rows to show", only ? "No uncertain rows." : "Nothing was extracted. Try “Re-run with OCR”, or add rows manually.");
    };
    const refresh = async () => { [info, rev] = await Promise.all([api(`${B}/${vid}`), api(`${B}/${vid}/review`)]); entries = rev.entries; paintHead(); paintHeader(); paintRows(); };
    async function showPage() {
      const n = $("#pg", root).value || 1, p = info.page_info.find(x => x.page_number == n);
      $("#pinfo", root).innerHTML = p ? `${esc(p.method)} · ${esc(p.chars)} characters${p.ocr_confidence != null ? " · OCR confidence " + Math.round(p.ocr_confidence * 100) + "%" : ""}${p.warning ? `<div class="alert warn">${esc(p.warning)}</div>` : ""}` : "";
      try { const { blob } = await EM.blob(`${B}/${vid}/pages/${n}/preview`); $("#pimg", root).src = await EM.dataUrl(blob); } catch (e) { $("#pinfo", root).insertAdjacentHTML("beforeend", `<div class="alert warn">Preview unavailable: ${esc(e.message)}</div>`); }
      if (!$("#ptxt", root).classList.contains("hidden")) loadText();
    }
    async function loadText() { try { $("#ptxt", root).textContent = (await api(`${B}/${vid}/pages/${$("#pg", root).value || 1}/text`)).text || "(no text)"; } catch (e) { $("#ptxt", root).textContent = e.message; } }
    $("#pg", root).onchange = () => showPage().catch(EM.fail); $("#unc", root).onchange = e => { only = e.target.checked; paintRows(); };
    const reason = () => $("#reason", root).value.trim() || undefined;
    EM.onSubmit($("#hf", root), async d => { const b = { exam_name: d.exam_name || null, session_label: d.session_label || null, academic_year: d.academic_year || null, department: d.department || null, semester: EM.num(d.semester), reason: reason() }; await api(`${B}/${vid}/header`, { method: "PATCH", body: b }); EM.toast("Details saved.", "ok"); await refresh(); });
    if ($("#af", root)) EM.onSubmit($("#af", root), async (d, f) => { const b = {}; Object.entries(d).forEach(([k, v]) => { if (v !== "") b[k] = k === "year" ? Number(v) : v; }); b.reason = reason(); await api(`${B}/${vid}/entries`, { method: "POST", body: b }); f.reset(); EM.toast("Row added (pending approval).", "ok"); await refresh(); });
    EM.delegate(root, {
      txt: async () => { $("#ptxt", root).classList.toggle("hidden"); if (!$("#ptxt", root).classList.contains("hidden")) await loadText(); },
      dl: async () => EM.download(`${B}/${vid}/download`, "document.pdf"),
      save: async b => { const box = b.closest("[data-eid]"), id = box.dataset.eid, cur = entries.find(x => x.id == id), body = {};
        box.querySelectorAll("[data-f]").forEach(el => { const k = el.dataset.f; let v = el.value.trim(); if (["year", "semester", "subject_id"].includes(k)) v = v === "" ? null : Number(v); else if (v === "") v = null; if ((cur[k] ?? null) !== v) body[k] = v; });
        if (!Object.keys(body).length) { EM.toast("No changes to save."); return; } body.reason = reason(); await api(`${B}/entries/${id}`, { method: "PATCH", body }); EM.toast("Corrections saved; the row needs approval again.", "ok"); await refresh(); },
      dec: async b => { const id = b.closest("[data-eid]").dataset.eid; await api(`${B}/entries/${id}/decision`, { method: "POST", body: { decision: b.dataset.d } }); EM.toast("Row " + b.dataset.d + ".", "ok"); await refresh(); },
      bulk: async () => { const r = await api(`${B}/${vid}/entries/bulk-decision`, { method: "POST", body: { decision: "approved", only_confident: true } }); EM.toast(`${r.changed} row(s) approved. ${r.skipped_ids.length} need individual review.`, "ok"); await refresh(); },
      reproc: async () => { if (!await EM.confirm({ title: "Re-run extraction?", message: "Machine-extracted rows are replaced; your edit history is kept.", confirmText: "Re-run" })) return; await process(vid, false); await refresh(); await showPage(); },
      ocr: async () => { if (!await EM.confirm({ title: "Force OCR on every page?", message: "Existing extracted rows will be replaced.", confirmText: "Run OCR" })) return; await process(vid, true); await refresh(); await showPage(); },
      docok: async () => { if (!await EM.confirm({ title: "Approve this document?", message: "All rows must be approved or rejected first. You can then import it.", confirmText: "Approve document" })) return; await api(`${B}/${vid}/decision`, { method: "POST", body: { decision: "approved" } }); EM.toast("Document approved. You can now import it.", "ok"); await refresh(); },
      docno: async () => { const r = await EM.ask({ title: "Reject this document?", danger: true, submitText: "Reject", fields: [{ name: "note", label: "Reason (optional)" }] }); if (!r) return; await api(`${B}/${vid}/decision`, { method: "POST", body: { decision: "rejected", note: r.note || undefined } }); EM.toast("Document rejected.", "ok"); await refresh(); },
    });
    paintHead(); paintHeader(); paintRows(); await showPage();
  }

  // ------------------------------------------------------------ timetable import
  const ACT = { create: "Create new draft exam", create_with_new_subject: "Create subject + draft exam", update_existing: "Reschedule existing exam", skip_existing: "Skip (already exists)", skip_duplicate_in_document: "Skip (duplicate row)", conflict_existing: "Needs decision (exists with different time)", blocked: "Blocked" };
  async function importView(root, vid) {
    const adm = EM.isAdmin(); const [info, terms] = await Promise.all([api(`${B}/${vid}`), api("/api/admin/terms").catch(() => [])]); let plan = null, opts = null;
    root.innerHTML = `<div class="stack">${bar(vid, "import")}<div class="row"><h2 style="margin:0">${esc(info.title)}</h2>${EM.badge("review: " + info.review_status, info.review_status === "approved" ? "ok" : "warn")}</div>${info.review_status !== "approved" ? EM.alert("Approve the document in the Review step before importing.", "warn") : ""}
      <section class="card"><div class="toolbar"><label class="check"><input type="checkbox" id="cs"> Create missing subjects in the catalogue</label><div class="field"><label for="tm">Term</label><select id="tm"><option value="">No term</option>${terms.map(t => `<option value="${t.id}">${esc(t.name)}</option>`).join("")}</select></div><button class="btn primary" data-act="prev">Build import preview</button></div><div id="sum" class="small muted"></div><div id="plan" class="list"></div>
      <div id="conf" class="stack hidden" style="margin-top:12px"><label class="check hidden" id="skw"><input type="checkbox" id="skip"> Import the rest and skip blocked rows</label><label class="check"><input type="checkbox" id="ok"> I confirm these changes to the examination records</label><div><button class="btn primary" data-act="imp">Import approved timetable</button></div></div>
      <p class="muted small">Imported examinations are created as <b>drafts</b>. Existing examinations are never changed unless “update existing” is ticked for that row.${adm ? "" : " Only an examination administrator can run the import."}</p></section></div>`;
    const build = async () => {
      const upd = [...root.querySelectorAll("[data-upd]:checked")].map(x => Number(x.dataset.upd));
      opts = { create_missing_subjects: $("#cs", root).checked, term_id: EM.num($("#tm", root).value), update_existing_entry_ids: upd };
      const p = plan = await api(`${B}/${vid}/import/preview`, { method: "POST", body: opts });
      $("#sum", root).innerHTML = `${p.will_create} to create · ${p.will_update} to reschedule · ${p.blocked} blocked / need a decision · ${p.items.length} approved row(s). ${p.document_approved ? "" : "<b>Document not approved yet.</b>"}`;
      $("#plan", root).innerHTML = p.items.map(i => { const bad = i.action === "blocked" || i.action === "conflict_existing";
        return `<div class="item ${bad ? "bad" : i.warnings.length ? "warn" : ""}"><div class="t">Row ${i.row_no} · ${esc(i.subject_code || "?")} · ${esc(i.exam_date || "no date")} ${esc(i.start_time || "")}–${esc(i.end_time || "")} ${EM.badge(ACT[i.action] || i.action, bad ? "bad" : i.action.startsWith("skip") ? "" : "ok")}</div><div class="m">${i.subject ? "Catalogue: " + esc(i.subject.code) + " · " + esc(i.subject.name) : "No catalogue subject"}${i.existing_exam_id ? " · existing exam #" + esc(i.existing_exam_id) : ""}</div>${i.errors.map(x => `<div class="small" style="color:var(--bad)">✖ ${esc(x)}</div>`).join("")}${i.warnings.map(x => `<div class="small">⚠ ${esc(x)}</div>`).join("")}${i.suggestions.length ? `<div class="small">Did you mean: ${i.suggestions.map(esc).join(", ")}? Correct the code in the Review step.</div>` : ""}${i.existing_exam_id && (i.action === "conflict_existing" || i.action === "update_existing") ? `<label class="check"><input type="checkbox" data-upd="${i.entry_id}" ${i.action === "update_existing" ? "checked" : ""}> Update existing examination #${esc(i.existing_exam_id)} to this time</label>` : ""}</div>`; }).join("") || EM.empty("No approved rows to import");
      root.querySelectorAll("[data-upd]").forEach(x => { x.onchange = () => build().catch(EM.fail); });
      const can = adm && p.document_approved && (p.will_create + p.will_update) > 0;
      $("#conf", root).classList.toggle("hidden", !can); $("#skw", root).classList.toggle("hidden", !p.blocked); $("#ok", root).checked = false; $("#skip", root).checked = false;
    };
    EM.delegate(root, {
      prev: build,
      imp: async () => { if (!plan) return; if (!$("#ok", root).checked) { EM.toast("Tick the confirmation box first.", "bad"); return; }
        if (!await EM.confirm({ title: "Import timetable?", message: `${plan.will_create} draft exam(s) will be created and ${plan.will_update} rescheduled.`, confirmText: "Import" })) return;
        const r = await api(`${B}/${vid}/import`, { method: "POST", body: { ...opts, confirm: true, signature: plan.signature, skip_blocked: $("#skip", root).checked } });
        EM.toast(`Imported: ${r.created_exam_ids.length} draft exam(s) created, ${r.updated_exam_ids.length} rescheduled, ${r.skipped} skipped.`, "ok"); plan = null; $("#plan", root).innerHTML = EM.alert(r.note || "Import complete. Review the new draft examinations and publish them.", "ok") + `<p><a class="btn primary" href="#/exams?status=draft">Open draft examinations</a></p>`; $("#conf", root).classList.add("hidden"); },
    });
  }

  async function historyView(root, vid) {
    const h = await api(`${B}/${vid}/history`);
    root.innerHTML = `<div class="stack">${bar(vid, "history")}<section class="card"><h3>Processing events</h3>${h.events.length ? `<div class="list">${h.events.map(e => `<div class="item"><div class="t">${esc(e.event)}</div><div class="m">${esc(EM.fmtDT(e.at))} · ${esc(e.actor)}${e.detail ? " · " + esc(e.detail) : ""}</div></div>`).join("")}</div>` : EM.empty("None")}<h3 style="margin-top:16px">Corrections</h3>${h.edits.length ? `<div class="list">${h.edits.map(e => `<div class="item"><div class="t">${esc(e.field)}${e.entry_id ? " (row id " + e.entry_id + ")" : " (document)"}</div><div class="m">${esc(e.old ?? "∅")} → ${esc(e.new ?? "∅")} · ${esc(e.by)} · ${esc(EM.fmtDT(e.at))}${e.reason ? " · " + esc(e.reason) : ""}</div></div>`).join("")}</div>` : EM.empty("No corrections")}</section></div>`;
  }

  // ------------------------------------------------------------ seating-allotment PDF import
  EM.page({ name: "seating-import", title: "Seating PDF import", roles: ["admin", "staff"], nav: { group: "Documents", icon: "🪑", label: "Seating PDF import", order: 2 }, render: async (root, ctx) => {
    const adm = EM.isAdmin(); let docs = (await api(B, { params: { limit: 300 } })).filter(d => d.processing_status !== "pending"), exams = (await EM.apiList("/api/admin/exams", { limit: 500 })).rows, sig = null;
    const vid0 = ctx.query.v || "";
    root.innerHTML = `<div class="stack">${EM.alert("Process the PDF first on the Timetable PDFs page (OCR is used for scans). Rows here are candidates only: nothing reaches seat allocations until an administrator approves rows and confirms the import. Halls must already be verified.", "info")}
      <section class="card"><div class="toolbar"><div class="field wide"><label for="dv">Processed document</label><select id="dv"><option value="">Select…</option>${docs.map(d => `<option value="${d.version_id}"${String(d.version_id) === vid0 ? " selected" : ""}>#${d.version_id} ${esc(d.title)} (${esc(d.kind)})</option>`).join("")}</select></div><button class="btn primary" data-act="ext">Extract rows</button><button class="btn" data-act="load">Reload</button><label class="check"><input type="checkbox" id="unc"> Uncertain only</label>${adm ? `<button class="btn" data-act="bulk">Approve confident rows</button>` : ""}</div><div id="sum" class="small muted"></div><div id="g"></div></section>
      <section class="card"><h3>Import into an examination</h3><div class="toolbar"><div class="field wide"><label for="ie">Examination</label><select id="ie">${examOpts(exams).map(o => `<option value="${esc(o[0])}">${esc(o[1])}</option>`).join("")}</select></div><button class="btn" data-act="prev">Preview import</button></div><div id="plan"></div>
      ${adm ? `<div id="conf" class="stack hidden"><label class="check"><input type="checkbox" id="ok"> I reviewed this preview and confirm the import</label><label class="check"><input type="checkbox" id="skip"> Skip blocked rows</label><div><button class="btn primary" data-act="imp">Import approved rows</button></div></div>` : `<p class="muted small">Only an examination administrator can approve and import.</p>`}</section></div>`;
    const ver = () => $("#dv", root).value, base = () => "/api/admin/seating-import/" + ver();
    const need = () => { if (!ver()) throw new Error("Select a processed document first."); };
    async function load() {
      need(); const d = await api(base(), { params: { only_uncertain: $("#unc", root).checked } });
      $("#sum", root).textContent = `${d.total} rows · ${d.uncertain} uncertain · ` + Object.entries(d.counts).map(([k, v]) => k + " " + v).join(", ");
      EM.grid($("#g", root), { rows: d.entries, caption: "Extracted seating rows", searchKeys: ["register_number", "hall", "seat"], empty: { title: "No rows", text: "Press “Extract rows”." }, columns: [
        { key: "register_number", label: "Register", render: e => `<span class="mono">${esc(e.register_number)}</span><br><span class="muted small">p.${esc(e.page_number)}</span>` },
        { key: "hall", label: "Hall", render: e => adm ? `<input data-h="${e.id}" value="${esc(e.hall || "")}" aria-label="Hall for ${esc(e.register_number)}" style="min-width:90px">` : esc(e.hall || "?") }, { key: "seat", label: "Seat", render: e => adm ? `<input data-s="${e.id}" value="${esc(e.seat || "")}" aria-label="Seat for ${esc(e.register_number)}" style="min-width:60px">` : esc(e.seat || "?") },
        { key: "review_status", label: "Status", render: e => EM.statusBadge(e.review_status) + `<br><span class="muted small">conf ${esc(e.confidence)}</span>` }, { key: "flags", label: "Flags", sort: false, render: e => e.flags.map(f => EM.badge(f, "warn")).join(" ") + e.conflicts.map(c => EM.badge("⚠ " + c, "bad")).join(" ") }],
        actions: adm ? e => `<button class="btn sm" data-act="fix" data-id="${e.id}">Save correction</button><button class="btn sm primary" data-act="dec" data-d="approve" data-id="${e.id}">Approve</button><button class="btn sm danger" data-act="dec" data-d="reject" data-id="${e.id}">Reject</button>` : null });
    }
    EM.delegate(root, {
      ext: async () => { need(); const r = await api(base() + "/extract", { method: "POST" }); EM.toast(`${r.rows} rows read, ${r.needing_attention} need attention.`, "ok"); await load(); },
      load, bulk: async () => { need(); const r = await api(base() + "/approve-confident", { method: "POST" }); EM.toast(r.approved + " confident rows approved.", "ok"); await load(); },
      dec: async b => { await api(`/api/admin/seating-import/entries/${b.dataset.id}/review`, { method: "POST", body: { decision: b.dataset.d } }); await load(); },
      fix: async b => { const r = await EM.ask({ title: "Save correction", message: "The reason is kept in the audit trail.", fields: [{ name: "reason", label: "Reason", required: true }] }); if (!r) return; const id = b.dataset.id;
        await api(`/api/admin/seating-import/entries/${id}`, { method: "PATCH", body: { hall: root.querySelector(`[data-h="${id}"]`).value || null, seat: root.querySelector(`[data-s="${id}"]`).value || null, reason: r.reason } }); EM.toast("Correction saved.", "ok"); await load(); },
      prev: async () => { need(); const ex = $("#ie", root).value; if (!ex) throw new Error("Select an examination."); const p = await api(base() + "/preview", { method: "POST", body: { exam_id: Number(ex) } }); sig = p.signature;
        $("#plan", root).innerHTML = `<p class="small">${Object.entries(p.summary).map(([k, v]) => esc(k) + " " + esc(v)).join(" · ")}</p><div class="list scroll">${p.items.filter(i => i.state !== "ready").slice(0, 200).map(i => `<div class="item ${i.state === "blocked" ? "bad" : ""}"><div class="t">${esc(i.register_number)} · ${esc(i.state)}</div><div class="m">${i.reasons.map(esc).join("; ") || "waiting for approval"}</div></div>`).join("") || EM.empty("Everything shown is ready")}</div>`;
        if ($("#conf", root)) $("#conf", root).classList.toggle("hidden", !(p.summary.ready || p.summary.blocked)); },
      imp: async () => { if (!$("#ok", root).checked) throw new Error("Tick the confirmation first."); if (!sig) throw new Error("Build a preview first.");
        if (!await EM.confirm({ title: "Create seat allotments?", message: "Approved, conflict-free rows become real seat allotments for the chosen examination.", confirmText: "Import" })) return;
        const r = await api(base() + "/import", { method: "POST", body: { exam_id: Number($("#ie", root).value), signature: sig, confirm: true, skip_blocked: $("#skip", root).checked } }); EM.toast(`${r.created} allotments created, ${r.skipped_blocked} blocked rows skipped.`, "ok"); sig = null; await load(); },
    });
    if (vid0) await load();
  } });

  // ------------------------------------------------------------ Phase 1 seating-register candidates (feeds the public lookup's "approved PDF references")
  EM.page({ name: "register-candidates", title: "Seating-register candidates", roles: ["admin", "staff"], nav: { group: "Documents", icon: "🔎", label: "Register candidates", order: 3 }, render: async root => {
    const adm = EM.isAdmin(); let docs = await api("/api/admin/documents");
    root.innerHTML = `<div class="stack">${EM.alert("Earlier-phase workflow: register numbers found in uploaded seating PDFs are reviewed here. Approved entries appear as “Approved PDF references” in the public lookup. Prefer the Seating PDF import for creating real allotments.", "info")}
      <section class="card"><div class="card-head"><h2>Documents</h2></div>${docs.length ? `<div class="list">${docs.map(d => `<div class="item"><div class="t">${esc(d.title)} <span class="muted small">#${d.id}</span></div>${d.versions.map(v => `<div class="row" style="margin-top:6px"><span class="small">Version ${esc(v.version)} (ID ${v.id}) · ${esc(v.processing_status)} / ${esc(v.review_status)}</span>${v.processing_status === "pending" ? `<button class="btn sm" data-act="proc" data-id="${v.id}">Process</button>` : `<button class="btn sm" data-act="cand" data-id="${v.id}">Candidates</button>`}${adm && v.review_status !== "approved" ? `<button class="btn sm primary" data-act="appr" data-id="${v.id}">Approve version</button>` : ""}</div>`).join("")}</div>`).join("")}</div>` : EM.empty("No documents", "Upload PDFs on the Timetable PDFs page.")}</section><section class="card"><div id="out">${EM.empty("Choose “Candidates” on a version")}</div></section></div>`;
    const cand = async id => { const rows = await api(`/api/admin/documents/${id}/review`); $("#out", root).innerHTML = rows.length ? `<div class="list">${rows.map(x => `<div class="item"><div class="t mono">${esc(x.register_number)} <span class="muted small">PDF page ${esc(x.page_number)}</span></div><div class="m">${esc(x.source_text || "No source text")}</div>${adm ? `<div class="row" style="margin-top:6px"><button class="btn sm primary" data-act="ok" data-id="${x.id}" data-v="${id}">Approve</button><button class="btn sm danger" data-act="no" data-id="${x.id}" data-v="${id}">Reject</button></div>` : ""}</div>`).join("")}</div>` : EM.empty("No extraction candidates"); };
    const rv = async b => { const f = new FormData(); f.append("decision", b.dataset.act === "ok" ? "approved" : "rejected"); await api(`/api/admin/documents/entries/${b.dataset.id}/review`, { method: "POST", form: f }); await cand(b.dataset.v); };
    EM.delegate(root, { cand: b => cand(b.dataset.id), ok: rv, no: rv,
      proc: async b => { const d = await api(`/api/admin/documents/${b.dataset.id}/process`, { method: "POST" }); EM.toast(`Processed ${d.pages} pages; ${d.candidate_registers} candidates await review.`, "ok"); EM.route(); },
      appr: async b => { if (!await EM.confirm({ title: "Approve this version?", message: "Approved entries become visible as references in the public lookup.", confirmText: "Approve" })) return; await api(`/api/admin/documents/${b.dataset.id}/approve`, { method: "POST" }); EM.toast("Version approved.", "ok"); EM.route(); } });
  } });
})();
