/* Seating: allocation (preview → approve → commit), corrections and history, reports and seating plans,
   invigilator rosters, halls & campus directory, announcements. */
(function () {
  "use strict";
  const { $, esc, api } = EM;
  const stat = (n, label) => `<div class="stat"><span class="n">${esc(n)}</span><span class="l">${esc(label)}</span></div>`;
  const REASON = { insufficient_capacity: "not enough seats", rules_prevent_placement: "spacing/separation rules leave no seat", not_eligible: "not eligible", simultaneous_exam: "has a simultaneous exam" };
  const examLabel = e => `#${e.id} ${e.title} · ${e.exam_date} ${e.start_time}`;
  const examOpts = (exams, first) => [["", first || "Select examination…"]].concat(exams.map(e => [e.id, examLabel(e)]));
  const loadExams = () => EM.apiList("/api/admin/exams", { limit: 500 }).then(r => r.rows);

  // ------------------------------------------------------------ seat allocation
  EM.page({ name: "allocation", title: "Seat allocation", roles: ["admin", "staff"], nav: { group: "Seating", icon: "💺", label: "Seat allocation", order: 1 }, render: async (root, ctx) => {
    const adm = EM.isAdmin(), tab = ctx.query.tab || "plan";
    const [exams, halls] = await Promise.all([loadExams(), api("/api/admin/halls")]);
    const vHalls = halls.filter(h => h.verified), open = exams.filter(e => e.status !== "completed"), pre = ctx.query.exam || "";
    const tabs = [["plan", "1 · Build & approve"], ["list", "2 · Allocations & corrections"], ["history", "3 · Change history"]];
    root.innerHTML = `<div class="stack"><nav class="tabs" aria-label="Allocation sections">${tabs.map(t => `<a href="#/allocation?tab=${t[0]}${pre ? "&exam=" + esc(pre) : ""}" ${tab === t[0] ? 'aria-current="page" class="active"' : ""}>${t[1]}</a>`).join("")}</nav><div id="body"></div></div>`;
    const body = $("#body", root);
    if (tab === "plan") return planTab(body, open, vHalls, adm, pre);
    if (tab === "list") return listTab(body, exams, vHalls, pre);
    return historyTab(body, exams, pre);
  } });

  function planTab(body, exams, halls, adm, pre) {
    let plan = null;
    body.innerHTML = `<div class="grid g2"><section class="card"><h3>Configure and preview</h3><p class="muted small">Nothing is saved until an administrator approves the preview. Existing seats are never moved.</p>
      <form id="pf" class="stack">${EM.field({ name: "exam_id", label: "Examination", type: "select", required: true, options: examOpts(exams), value: pre })}
      <div class="field"><span class="lbl">Halls (verified, with seat inventory) — none ticked = all</span><div class="checks" id="hl">${halls.map(h => `<label class="check"><input type="checkbox" value="${h.id}"> ${esc(h.code)}${h.capacity ? ` (${esc(h.capacity)})` : ""}</label>`).join("") || `<span class="muted small">No verified halls yet. Create a hall, generate its seat inventory and verify it on the Halls page.</span>`}</div></div>
      <div class="form-grid">${EM.field({ name: "strategy", label: "Strategy", type: "select", options: [["balanced", "Balanced across halls"], ["sequential", "Fill halls in order"]] })}${EM.field({ name: "department_separation", label: "Department separation", type: "select", options: [["preferred", "Preferred"], ["strict", "Strict"], ["off", "Off"]] })}${EM.field({ name: "seat_gap", label: "Empty seats between students", type: "number", value: 0, attrs: 'min="0" max="5"', hint: "0 = none. Neighbours are consecutive seat numbers." })}</div>
      <button class="btn primary">Build allocation preview</button></form></section>
      <section class="card"><h3>Review and approve</h3><div id="pv">${EM.empty("No preview yet", "Build a preview to review it here.")}</div></section></div>`;
    const pv = $("#pv", body);
    const draw = () => {
      const p = plan, s = p.summary; let h = `<div class="item"><div class="t">${esc(p.exam_title || "Plan")} — plan #${esc(p.id)}</div><div class="m">${esc(s.new_allocations)} new seats · ${esc(s.already_allocated)} already allocated (kept) · ${esc(s.unallocated_count)} unallocated · ${esc(s.free_seats_before)} free seats before</div></div>`;
      if (!s.capacity_sufficient) h += `<div class="alert warn" style="margin-top:8px"><b>Insufficient capacity or rules too strict.</b> Some students cannot be seated. Add halls/seats, relax spacing, or approve a partial allocation.</div>`;
      (s.warnings || []).forEach(w => { h += `<div class="alert info" style="margin-top:8px">${esc(w)}</div>`; });
      if (p.invalid_existing && p.invalid_existing.length) h += `<div class="alert warn" style="margin-top:8px"><b>${p.invalid_existing.length} existing allotment(s) need attention (not changed)</b><br>${p.invalid_existing.slice(0, 15).map(x => esc(x.register_number) + " " + esc(x.hall) + "/" + esc(x.seat) + ": " + esc(x.problem)).join("<br>")}</div>`;
      h += (s.hall_stats || []).length ? `<h4 style="margin-top:12px">Halls</h4><div class="list">${s.hall_stats.map(x => `<div class="item"><b>${esc(x.hall)}</b> <span class="muted small">${esc(x.newly_placed)} new + ${esc(x.already_occupied)} occupied of ${esc(x.usable_seats)} seats</span></div>`).join("")}</div>` : "";
      if (p.unallocated.length) h += `<h4 style="margin-top:12px">Unallocated (${p.unallocated.length}${p.unallocated.length >= 500 ? "+" : ""})</h4><div class="pre">${p.unallocated.slice(0, 80).map(u => esc(u.register_number) + " — " + esc(REASON[u.reason] || u.reason)).join("\n")}</div>`;
      h += `<h4 style="margin-top:12px">Proposed seats (${p.assignment_count})</h4><div class="pre">${p.assignments.slice(0, 150).map(a => esc(a.register_number) + " → " + esc(a.hall) + " / " + esc(a.seat)).join("\n")}${p.assignments_truncated || p.assignments.length > 150 ? "\n…" : ""}</div>`;
      const can = p.can_commit || (p.assignment_count && !s.capacity_sufficient);
      h += `<div class="stack" style="margin-top:12px">${can ? (adm ? `${!s.capacity_sufficient ? `<label class="check"><input type="checkbox" id="part"> Approve partial allocation (some students stay unallocated)</label>` : ""}<div class="form-actions"><button class="btn primary" data-act="commit">Approve and save allocation</button><button class="btn" data-act="discard">Discard preview</button></div>` : `${EM.alert("An examination administrator must approve and save this preview. You can discard it.", "info")}<div class="form-actions"><button class="btn" data-act="discard">Discard preview</button></div>`) : `<div class="form-actions"><button class="btn" data-act="discard">Discard preview</button></div>`}</div>`;
      pv.innerHTML = h;
    };
    EM.onSubmit($("#pf", body), async d => {
      const b = { exam_id: Number(d.exam_id), strategy: d.strategy, department_separation: d.department_separation, seat_gap: Number(d.seat_gap || 0) };
      const ids = [...body.querySelectorAll("#hl input:checked")].map(i => Number(i.value)); if (ids.length) b.hall_ids = ids;
      pv.innerHTML = EM.loading("Building preview…"); plan = null;
      try { plan = await api("/api/allotments/plans", { method: "POST", body: b }); } catch (e) { pv.innerHTML = EM.empty("No preview yet", "Build a preview to review it here."); throw e; }
      draw(); EM.toast("Preview built — nothing has been saved yet.");
    });
    EM.delegate(body, {
      commit: async () => {
        const part = $("#part", body) && $("#part", body).checked;
        if (!await EM.confirm({ title: "Approve and save allocation?", message: "This creates seat records for the examination.", detail: part ? "Partial allocation: unallocated students will have no seat." : "", confirmText: "Approve and save" })) return;
        const r = await api(`/api/allotments/plans/${plan.id}/commit`, { method: "POST", body: { allow_partial: !!part } });
        EM.toast(`Saved ${r.created} allocations (${r.unallocated} students remain unallocated).`, "ok"); plan = null; pv.innerHTML = EM.alert(`Saved ${r.created} allocations. ${r.unallocated} students remain unallocated.`, "ok");
      },
      discard: async () => { await api(`/api/allotments/plans/${plan.id}/discard`, { method: "POST" }); plan = null; pv.innerHTML = EM.empty("Preview discarded"); },
    });
  }

  async function listTab(body, exams, halls, pre) {
    let rows = [], examId = pre || "", grid = null;
    body.innerHTML = `<section class="card"><div class="toolbar"><div class="field wide"><label>Examination</label><select id="ex">${examOpts(exams).map(o => `<option value="${esc(o[0])}"${String(o[0]) === String(examId) ? " selected" : ""}>${esc(o[1])}</option>`).join("")}</select></div><div class="field"><label>Register number or name</label><input id="q" type="search"></div><button class="btn primary" data-act="load">Load</button><button class="btn" data-act="manual">+ Manual allocation</button></div><div id="g">${EM.empty("Select an examination", "Choose one and press Load.")}</div></section>`;
    const load = async () => {
      examId = $("#ex", body).value; if (!examId) { EM.toast("Select an examination first.", "bad"); return; }
      rows = await api(`/api/allotments/exam/${examId}`, { params: { q: $("#q", body).value.trim(), limit: 1000 } });
      grid = EM.grid($("#g", body), { rows, caption: "Allocations", search: true, searchKeys: ["register_number", "student_name", "hall", "seat"], empty: { title: "No allotments", text: "No seats have been allocated for this examination." }, columns: [
        { key: "register_number", label: "Register number", render: a => `<span class="mono">${esc(a.register_number)}</span>` }, { key: "student_name", label: "Name" }, { key: "department", label: "Department" }, { key: "hall", label: "Hall" }, { key: "seat", label: "Seat" }, { key: "source", label: "Source", render: a => EM.badge(a.source) }],
        actions: a => `<button class="btn sm" data-act="move" data-id="${a.id}">Move</button><button class="btn sm danger" data-act="rm" data-id="${a.id}">Remove</button>` });
    };
    const hallField = (v) => halls.length ? { name: "hall", label: "Hall (verified)", type: "select", required: true, options: [["", "Select hall…"]].concat(halls.map(h => [h.code, h.code])), value: v } : { name: "hall", label: "Hall code", required: true, value: v };
    EM.delegate(body, {
      load,
      manual: async () => { const id = $("#ex", body).value; if (!id) { EM.toast("Select an examination first.", "bad"); return; }
        if (await EM.ask({ title: "Manual seat allocation", fields: [{ name: "register_number", label: "Student register number", required: true, attrs: 'inputmode="numeric"' }, hallField(""), { name: "seat", label: "Seat label", required: true }], submit: async d => { await api("/api/allotments", { method: "POST", body: { register_number: d.register_number, exam_id: Number(id), hall: d.hall, seat: d.seat } }); return true; } })) { EM.toast("Seat allocated.", "ok"); await load(); } },
      move: async b => { const a = rows.find(x => x.id === Number(b.dataset.id));
        if (await EM.ask({ title: `Move ${a.register_number}`, message: "The change is recorded in the allocation history.", fields: [hallField(a.hall), { name: "seat", label: "New seat", required: true, value: a.seat }, { name: "reason", label: "Reason (required)", required: true, hint: "At least 3 characters." }], submitText: "Move", submit: async d => { await api("/api/allotments/" + a.id, { method: "PATCH", body: d }); return true; } })) { EM.toast("Allotment moved and recorded in history.", "ok"); await load(); } },
      rm: async b => { const a = rows.find(x => x.id === Number(b.dataset.id)); const r = await EM.ask({ title: `Remove seat of ${a.register_number}?`, message: `Hall ${a.hall}, seat ${a.seat} will be freed.`, danger: true, submitText: "Remove", fields: [{ name: "reason", label: "Reason (optional)" }] }); if (!r) return;
        await api("/api/allotments/" + a.id, { method: "DELETE", params: { reason: r.reason } }); EM.toast("Allotment removed and recorded in history.", "ok"); await load(); },
    });
    $("#q", body).addEventListener("keydown", e => { if (e.key === "Enter") load().catch(EM.fail); });
    if (examId) await load();
  }

  async function historyTab(body, exams, pre) {
    body.innerHTML = `<section class="card"><div class="toolbar"><div class="field wide"><label>Examination</label><select id="ex">${examOpts(exams, "All examinations").map(o => `<option value="${esc(o[0])}"${String(o[0]) === String(pre) ? " selected" : ""}>${esc(o[1])}</option>`).join("")}</select></div><button class="btn primary" data-act="load">Show history</button></div><div id="g"></div></section>`;
    const load = async () => { const rows = await api("/api/allotments/history", { params: { exam_id: $("#ex", body).value, limit: 200 } });
      EM.grid($("#g", body), { rows, caption: "Allocation history", searchKeys: ["register_number", "actor", "action", "reason"], empty: { title: "No history yet" }, columns: [{ key: "created_at", label: "When", render: h => esc(EM.fmtDT(h.created_at)) }, { key: "action", label: "Action", render: h => EM.badge(h.action) }, { key: "register_number", label: "Student", render: h => esc(h.register_number || "") }, { key: "actor", label: "By" }, { key: "from", label: "From", render: h => esc(h.from || "") }, { key: "to", label: "To", render: h => esc(h.to || "") }, { key: "reason", label: "Reason", render: h => esc(h.reason || "") }] }); };
    EM.delegate(body, { load }); await load();
  }

  // ------------------------------------------------------------ reports
  const REPORTS = [
    { id: "allocations-register", label: "Register-number-wise list", path: "allocations", extra: { order: "register" } },
    { id: "allocations-hall", label: "Hall-wise list", path: "allocations", extra: { order: "hall" } },
    { id: "unallocated", label: "Unallocated students", path: "unallocated" },
    { id: "halls", label: "Hall occupancy & capacity", path: "halls", extra: { include_unused: "true" } },
    { id: "seating", label: "Seating chart", path: "seating", seating: true },
  ];
  function seatCharts(charts) { return charts.length ? charts.map(c => `<div class="hall"><h4>Hall ${esc(c.hall)} — ${esc(c.allocated)} allocated, ${esc(c.free)} free (capacity ${esc(c.capacity)})</h4><div class="seats">${c.seats.map(s => `<div class="seat ${esc(s.state)}" title="${esc(s.student_name || s.state)}"><b>${esc(s.seat)}</b>${esc(s.register_number || (s.state === "free" ? "" : String(s.state).replace("_", " ")))}${s.department ? `<br><span class="muted">${esc(s.department)}</span>` : ""}</div>`).join("")}</div></div>`).join("") : EM.empty("No seating data", "No seats are allocated for this selection."); }
  EM.printCharts = (charts, title) => {
    let a = $("#printArea"); if (!a) { a = document.createElement("div"); a.id = "printArea"; document.body.appendChild(a); }
    a.innerHTML = `<h2>${esc(title)}</h2>` + seatCharts(charts);
    const clear = () => { a.innerHTML = ""; window.removeEventListener("afterprint", clear); }; window.addEventListener("afterprint", clear); window.print();
  };
  function dynTable(el, rows) {
    if (!rows.length) { el.innerHTML = EM.empty("No rows"); return; }
    EM.grid(el, { rows, caption: "Report", pageSize: 25, columns: Object.keys(rows[0]).map(k => ({ key: k, label: k.replace(/_/g, " "), render: r => esc(r[k] && typeof r[k] === "object" ? JSON.stringify(r[k]) : (r[k] ?? "")) })) });
  }
  EM.page({ name: "reports", title: "Reports & seating plans", roles: ["admin", "staff"], nav: { group: "Seating", icon: "📊", label: "Reports & plans", order: 2 }, render: async (root, ctx) => {
    const exams = await loadExams(); let last = null;
    root.innerHTML = `<div class="stack"><section class="card"><div class="card-head"><h2>Phase 10 · Analytics & intelligence</h2></div>
      <div class="grid g4">
        <div class="field"><label for="an-from">From date</label><input id="an-from" type="date"></div>
        <div class="field"><label for="an-to">To date</label><input id="an-to" type="date"></div>
        <div class="field"><label for="an-dept">Department</label><input id="an-dept" maxlength="100" value="${esc(EM.state.user.department || "")}"></div>
        <div class="field"><label for="an-sem">Semester</label><input id="an-sem" type="number" min="1" max="12"></div>
        <div class="field"><label for="an-sub">Subject ID</label><input id="an-sub" type="number" min="1"></div>
        <div class="field"><label for="an-pass">Pass threshold (%)</label><input id="an-pass" type="number" min="0" max="100" value="40"></div>
      </div>
      <div class="row"><button class="btn primary" id="an-dashboard">Performance dashboard</button><button class="btn" id="an-comparisons">Semester/year comparison</button><button class="btn" id="an-insights">Trend insights</button><button class="btn" id="an-allocation">Hall utilization</button><button class="btn" id="an-risk">At-risk screening</button></div>
      <div class="row"><span class="muted">Export filtered published performance:</span>${["csv","xlsx","pdf"].map(f=>`<button class="btn sm" data-an-export="${f}">${f.toUpperCase()}</button>`).join("")}</div>
      <div id="an-out" aria-live="polite" style="margin-top:12px">${EM.empty("Choose an analytics view", "All values are calculated from persisted records.")}</div>
      </section><section class="card"><div class="toolbar"><div class="field wide"><label for="ex">Examination</label><select id="ex">${examOpts(exams).map(o => `<option value="${esc(o[0])}"${String(o[0]) === String(ctx.query.exam || "") ? " selected" : ""}>${esc(o[1])}</option>`).join("")}</select></div><div class="field"><label for="hall">Hall code (optional filter)</label><input id="hall"></div></div>
      <div class="grid gauto">${REPORTS.concat([{ id: "overview", label: "Examination summary (all exams)" }]).map(r => `<div class="item"><div class="t">${esc(r.label)}</div><div class="row" style="margin-top:8px"><button class="btn sm primary" data-act="rep" data-r="${r.id}" data-f="json">View</button>${["csv", "xlsx", "pdf"].map(f => `<button class="btn sm" data-act="rep" data-r="${r.id}" data-f="${f}">${f.toUpperCase()}</button>`).join("")}${r.seating ? `<button class="btn sm" data-act="rep" data-r="${r.id}" data-f="print">Print</button>` : ""}</div></div>`).join("")}</div></section>
      <section class="card" aria-live="polite"><div id="out">${EM.empty("Choose an examination and a report", "Results appear here. CSV, Excel and PDF are downloaded.")}</div></section></div>`;
    EM.delegate(root, { rep: async b => {
      const exam = $("#ex", root).value, hall = $("#hall", root).value.trim(), isOv = b.dataset.r === "overview", def = REPORTS.find(x => x.id === b.dataset.r) || {};
      if (!exam && !isOv) { EM.toast("Select an examination first.", "bad"); return; }
      const base = isOv ? "/api/admin/reports/exams" : `/api/admin/reports/exams/${exam}/${def.path}`, f = b.dataset.f;
      const extra = { ...(def.extra || {}), ...(def.path === "allocations" || def.seating ? { hall } : {}) };
      if (f === "print") { EM.printCharts(await api(base, { params: { hall, format: "json" } }), "Seating plan"); return; }
      if (f !== "json") { await EM.download(base + "?" + EM.qs({ ...extra, format: f }), "report." + f); EM.toast("Download started."); return; }
      const out = $("#out", root); out.innerHTML = EM.loading();
      const data = await api(base, { params: { ...extra, format: "json" } });
      if (def.seating) out.innerHTML = seatCharts(data); else dynTable(out, data);
    } });
    const anOut = $("#an-out", root);
    const anFilters = () => ({ date_from: $("#an-from", root).value, date_to: $("#an-to", root).value,
      department: $("#an-dept", root).value.trim(), semester: $("#an-sem", root).value,
      subject_id: $("#an-sub", root).value, pass_percent: $("#an-pass", root).value });
    const runAnalytics = async kind => {
      anOut.innerHTML = EM.loading("Calculating from stored records…");
      try {
        const f = anFilters(); let data;
        if (kind === "dashboard") {
          data = await api("/api/analytics/dashboard", { params: f });
          anOut.innerHTML = `<div class="grid g4">${stat(data.performance.result_records, "Published result records")}${stat(data.performance.average_percent == null ? "—" : data.performance.average_percent + "%", "Average")}${stat(data.performance.pass_rate_percent == null ? "—" : data.performance.pass_rate_percent + "%", "Pass rate")}${stat(data.allocation.allocation_rate_percent == null ? "—" : data.allocation.allocation_rate_percent + "%", "Allocation rate")}</div>
            <div class="grid g2"><div><h4>By subject</h4><div id="an-subjects"></div></div><div><h4>By department</h4><div id="an-depts"></div></div></div>
            <p class="muted">Attendance ${data.attendance.available ? "available" : "unavailable"}: ${esc(data.attendance.reason || "")}. No estimates or missing scores are added.</p>`;
          dynTable($("#an-subjects", anOut), data.by_subject); dynTable($("#an-depts", anOut), data.by_department);
        } else if (kind === "comparisons") {
          data = await api("/api/analytics/comparisons", { params: f }); dynTable(anOut, data.comparisons);
        } else if (kind === "insights") {
          data = await api("/api/analytics/insights", { params: { ...f, change_threshold: 15, minimum_records: 5 } }); dynTable(anOut, data.findings);
          if (!data.finding_count) anOut.innerHTML = EM.empty("No unusual changes detected", "No consecutive subject exams met the configured cohort and change thresholds.");
        } else if (kind === "allocation") {
          data = await api("/api/analytics/allocation", { params: { department: f.department } });
          anOut.innerHTML = `<h4>Hall utilization</h4><div id="an-halls"></div><h4>Examination allocation</h4><div id="an-exams"></div><p class="muted">${esc(data.capacity_note)}</p>`;
          dynTable($("#an-halls", anOut), data.by_hall); dynTable($("#an-exams", anOut), data.examinations);
        } else {
          data = await api("/api/analytics/students/at-risk", { params: { department: f.department, threshold: 45, recent_drop: 15, minimum_results: 2, limit: 100 } });
          dynTable(anOut, data.items);
          if (!data.total) anOut.innerHTML = EM.empty("No students currently meet the screening rules.");
          else anOut.insertAdjacentHTML("afterbegin", `<p class="muted">${esc(data.total)} student(s) flagged. Rules: average below 45% or latest result drop of at least 15 percentage points. Review before taking action.</p>`);
        }
      } catch (e) { anOut.innerHTML = EM.alert(e.message || "Analytics request failed.", "warn"); }
    };
    [["an-dashboard","dashboard"],["an-comparisons","comparisons"],["an-insights","insights"],["an-allocation","allocation"],["an-risk","risk"]]
      .forEach(([id, kind]) => $("#"+id, root).addEventListener("click", () => runAnalytics(kind)));
    root.querySelectorAll("[data-an-export]").forEach(btn => btn.addEventListener("click", () => {
      const f = anFilters(); f.format = btn.dataset.anExport;
      EM.download("/api/analytics/reports/performance?" + EM.qs(f), "performance_analytics." + btn.dataset.anExport).catch(EM.fail);
    }));
  } });

  // ------------------------------------------------------------ invigilator + shared read-only views
  async function examPicker(root, ctx, title, render) {
    const exams = (await loadExams()).filter(e => e.status !== "draft" || !EM.can("invigilator") || EM.isStaff());
    const id = ctx.args[0] || "";
    root.innerHTML = `<div class="stack"><section class="card"><div class="card-head"><h2>${esc(title)}</h2></div><div class="toolbar"><div class="field wide"><label for="ex">Examination</label><select id="ex">${examOpts(exams).map(o => `<option value="${esc(o[0])}"${String(o[0]) === id ? " selected" : ""}>${esc(o[1])}</option>`).join("")}</select></div><div class="field"><label for="hall">Hall code (optional)</label><input id="hall"></div><button class="btn primary" data-act="go">Show</button></div></section><section class="card" aria-live="polite"><div id="out">${EM.empty("Select an examination")}</div></section></div>`;
    EM.delegate(root, { go: async () => { const ex = $("#ex", root).value; if (!ex) { EM.toast("Select an examination first.", "bad"); return; } const out = $("#out", root); out.innerHTML = EM.loading(); await render(out, ex, $("#hall", root).value.trim()); } });
    if (id) $("[data-act=go]", root).click();
  }
  EM.page({ name: "rosters", title: "Hall rosters", roles: ["admin", "staff", "invigilator"], nav: { group: "Seating", icon: "📋", label: "Hall rosters", order: 3, only: ["invigilator"] }, render: (root, ctx) => examPicker(root, ctx, "Hall rosters (read-only)", async (out, ex, hall) => {
    const [rows, occ] = await Promise.all([api(`/api/allotments/exam/${ex}`, { params: { hall, limit: 1000 } }), api(`/api/admin/reports/exams/${ex}/halls`, { params: { format: "json", include_unused: "false" } }).catch(() => [])]);
    out.innerHTML = (occ.length ? `<div class="grid gauto" style="margin-bottom:16px">${occ.map(h => `<div class="stat"><span class="n">${esc(h.allocated ?? h.occupied ?? "")}</span><span class="l">Hall ${esc(h.hall)}${h.capacity != null ? " · capacity " + esc(h.capacity) : ""}</span></div>`).join("")}</div>` : "") + `<div id="rg"></div>`;
    EM.grid($("#rg", out), { rows, caption: "Hall roster", searchKeys: ["register_number", "student_name", "hall", "seat"], sortKey: "hall", empty: { title: "No allotments", text: "No students are seated for this selection." }, columns: [{ key: "hall", label: "Hall" }, { key: "seat", label: "Seat" }, { key: "register_number", label: "Register number", render: a => `<span class="mono">${esc(a.register_number)}</span>` }, { key: "student_name", label: "Name" }, { key: "department", label: "Department" }] });
  }) });
  EM.page({ name: "seating", title: "Seating charts", roles: ["admin", "staff", "invigilator"], nav: { group: "Seating", icon: "🪑", label: "Seating charts", order: 4, only: ["invigilator"] }, render: (root, ctx) => examPicker(root, ctx, "Seating charts (read-only)", async (out, ex, hall) => {
    const charts = await api(`/api/admin/reports/exams/${ex}/seating`, { params: { hall, format: "json" } });
    out.innerHTML = `<div class="row end" style="margin-bottom:12px"><button class="btn" id="pr">Print</button></div>${seatCharts(charts)}`; $("#pr", out).onclick = () => EM.printCharts(charts, "Seating plan");
  }) });

  // ------------------------------------------------------------ halls & campus directory
  const toLocalInput = iso => { if (!iso) return ""; const d = new Date(iso); if (isNaN(d)) return ""; d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 16); };
  EM.page({ name: "halls", title: "Halls & campus", roles: ["admin", "staff"], nav: { group: "Seating", icon: "🏛", label: "Halls & campus", order: 5 }, render: async root => {
    const adm = EM.isAdmin(); let halls = await api("/api/admin/halls"), dir = [];
    async function loadDir() {
      const bs = await api("/api/admin/buildings"); dir = [];
      for (const b of bs) { const blocks = await api(`/api/admin/buildings/${b.id}/blocks`); dir.push({ b, blocks: [] }); for (const bl of blocks) { const floors = await api(`/api/admin/blocks/${bl.id}/floors`); dir[dir.length - 1].blocks.push({ bl, floors }); } }
    }
    await loadDir();
    root.innerHTML = `<div class="stack">${adm ? "" : EM.alert("Only administrators can create, verify and edit halls and the campus directory.", "info")}
      <section class="card"><div class="card-head"><h2>Halls</h2>${adm ? `<button class="btn primary" data-act="newhall">+ New hall</button>` : ""}</div><p class="muted small">A hall must have a seat inventory and be <b>verified</b> before it can be used for allocation or shown to students.</p><div id="gh"></div></section>
      <section class="card"><div class="card-head"><h2>Building / block / floor directory</h2>${adm ? `<div class="row"><button class="btn" data-act="newb">+ Building</button><button class="btn" data-act="newbl">+ Block</button><button class="btn" data-act="newfl">+ Floor</button></div>` : ""}</div><div id="dir"></div></section></div>`;
    const paintDir = () => { $("#dir", root).innerHTML = dir.length ? `<div class="list">${dir.map(x => `<div class="item"><div class="t">${esc(x.b.code)} · ${esc(x.b.name)}</div>${x.blocks.length ? `<div class="m">${x.blocks.map(y => `Block ${esc(y.bl.code)} (${esc(y.bl.name)})${y.floors.length ? ": floors " + y.floors.map(f => esc(f.code)).join(", ") : ""}`).join("<br>")}</div>` : `<div class="m">No blocks yet</div>`}</div>`).join("")}</div>` : EM.empty("No buildings yet", "Buildings are optional; halls can also use free-text locations."); };
    const locOpts = () => { const o = [["", "No directory location"]]; dir.forEach(x => { if (!x.blocks.length) o.push([`${x.b.id},,`, x.b.name]); x.blocks.forEach(y => { if (!y.floors.length) o.push([`${x.b.id},${y.bl.id},`, `${x.b.name} › ${y.bl.name}`]); y.floors.forEach(f => o.push([`${x.b.id},${y.bl.id},${f.id}`, `${x.b.name} › ${y.bl.name} › ${f.name}`])); }); }); return o; };
    const hallForm = h => EM.ask({ title: h ? "Edit hall " + h.code : "New hall", fields: [
      { name: "code", label: "Hall code", required: true, value: h && h.code, hint: "e.g. ECE-101 (stored upper-case)" }, { name: "display_name", label: "Display name", value: h && h.display_name }, { name: "capacity", label: "Capacity (seats)", type: "number", attrs: 'min="1"', value: h && h.capacity },
      { name: "loc", label: "Directory location", type: "select", options: locOpts(), value: h ? [h.building_id, h.block_id, h.floor_id].map(v => v || "").join(",") : "" },
      { name: "building", label: "Building (free text, if not in directory)", value: h && h.building }, { name: "block", label: "Block (free text)", value: h && h.block }, { name: "floor", label: "Floor label (free text)", value: h && h.floor }, { name: "room", label: "Room", value: h && h.room }, { name: "notes", label: "Notes", type: "textarea", value: h && h.notes }],
      submit: async d => { const [bi, bl, fl] = (d.loc || ",,").split(","); const b = { code: d.code, display_name: d.display_name || null, capacity: EM.num(d.capacity), building_id: bi ? Number(bi) : null, block_id: bl ? Number(bl) : null, floor_id: fl ? Number(fl) : null, building: d.building || null, block: d.block || null, floor: d.floor || null, room: d.room || null, notes: d.notes || null };
        await api(h ? "/api/admin/halls/" + h.id : "/api/admin/halls", { method: h ? "PATCH" : "POST", body: b }); return true; } });
    const grid = EM.grid($("#gh", root), { rows: halls, caption: "Halls", searchKeys: ["code", "display_name", "building", "block", "floor", "room"], sortKey: "code", empty: { title: "No halls yet", text: adm ? "Create a hall to begin." : "" }, columns: [
      { key: "code", label: "Code", render: h => `<b>${esc(h.code)}</b>${h.display_name ? `<br><span class="muted small">${esc(h.display_name)}</span>` : ""}` }, { key: "building", label: "Location", render: h => esc([h.building, h.block, h.floor, h.room].filter(Boolean).join(" / ") || "not set") }, { key: "capacity", label: "Capacity", render: h => esc(h.capacity ?? "—") }, { key: "verified", label: "Status", render: h => EM.badge(h.verified ? "Verified" : "Pending verification", h.verified ? "ok" : "warn") }],
      actions: h => `<button class="btn sm" data-act="seats" data-id="${h.id}">Seats</button>${adm ? `<button class="btn sm" data-act="edit" data-id="${h.id}">Edit</button><button class="btn sm" data-act="gen" data-id="${h.id}">Generate seats</button>${h.verified ? "" : `<button class="btn sm primary" data-act="verify" data-id="${h.id}">Verify</button>`}` : ""}` });
    const reload = async () => { halls = await api("/api/admin/halls"); grid.setRows(halls); };
    const H = b => halls.find(x => x.id === Number(b.dataset.id));
    const parentSel = (name, label, opts) => ({ name, label, type: "select", required: true, options: [["", "Select…"]].concat(opts) });
    EM.delegate(root, {
      newhall: async () => { if (await hallForm(null)) { EM.toast("Hall saved. Generate its seats and verify it before use.", "ok"); await reload(); } },
      edit: async b => { if (await hallForm(H(b))) { EM.toast("Hall updated.", "ok"); await reload(); } },
      verify: async b => { const h = H(b); if (!await EM.confirm({ title: "Verify hall " + h.code + "?", message: "Verified halls become usable for allocation and their location is shown to students.", confirmText: "Verify" })) return; await api(`/api/admin/halls/${h.id}/verify`, { method: "POST" }); EM.toast("Hall verified.", "ok"); await reload(); },
      gen: async b => { const h = H(b); if (!await EM.confirm({ title: "Generate seat inventory?", message: `Creates seats 1–${h.capacity || "?"} for ${h.code}. An existing inventory is never overwritten.`, confirmText: "Generate" })) return; const r = await api(`/api/admin/halls/${h.id}/seats/generate`, { method: "POST" }); EM.toast(`Created ${r.seats_created} seats.`, "ok"); },
      seats: async b => { const h = H(b), s = await api(`/api/admin/halls/${h.id}/seats`); await EM.show("Seat inventory · " + h.code, s.length ? `<p class="muted small">${s.length} seats (${s.filter(x => x.active).length} active)</p><div class="seats scroll">${s.map(x => `<div class="seat ${x.active ? "" : "unavailable"}"><b>${esc(x.seat_label)}</b>${x.active ? "" : "inactive"}</div>`).join("")}</div>` : EM.empty("No seat inventory yet", adm ? "Use “Generate seats”." : "")); },
      newb: async () => { if (await EM.ask({ title: "New building", fields: [{ name: "code", label: "Code", required: true }, { name: "name", label: "Name", required: true }, { name: "address", label: "Address" }], submit: async d => { await api("/api/admin/buildings", { method: "POST", body: d }); return true; } })) { EM.toast("Building created.", "ok"); await loadDir(); paintDir(); } },
      newbl: async () => { if (!dir.length) { EM.toast("Create a building first.", "bad"); return; } if (await EM.ask({ title: "New block", fields: [parentSel("building_id", "Building", dir.map(x => [x.b.id, `${x.b.code} · ${x.b.name}`])), { name: "code", label: "Block code", required: true }, { name: "name", label: "Block name", required: true }], submit: async d => { await api(`/api/admin/buildings/${d.building_id}/blocks`, { method: "POST", body: { code: d.code, name: d.name } }); return true; } })) { EM.toast("Block created.", "ok"); await loadDir(); paintDir(); } },
      newfl: async () => { const bl = dir.flatMap(x => x.blocks.map(y => [y.bl.id, `${x.b.name} › ${y.bl.code} · ${y.bl.name}`])); if (!bl.length) { EM.toast("Create a block first.", "bad"); return; } if (await EM.ask({ title: "New floor", fields: [parentSel("block_id", "Block", bl), { name: "code", label: "Floor code (e.g. G, 1)", required: true }, { name: "name", label: "Floor name", required: true }], submit: async d => { await api(`/api/admin/blocks/${d.block_id}/floors`, { method: "POST", body: { code: d.code, name: d.name } }); return true; } })) { EM.toast("Floor created.", "ok"); await loadDir(); paintDir(); } },
    });
    paintDir();
  } });

  // ------------------------------------------------------------ announcements
  EM.page({ name: "announcements", title: "Announcements", roles: ["admin", "staff"], nav: { group: "Administration", icon: "📣", label: "Announcements", order: 2 }, render: async root => {
    const adm = EM.isAdmin(); let rows = await api("/api/admin/announcements");
    root.innerHTML = `<div class="stack"><div class="row between"><p class="muted" style="margin:0">Untargeted published announcements appear on the public home page. Notifications go only to the chosen audience, once.</p><button class="btn primary" data-act="new">+ New announcement</button></div><div id="g"></div></div>`;
    const form = a => EM.ask({ title: a ? "Edit announcement" : "New announcement", fields: [{ name: "title", label: "Title", required: true, value: a && a.title, hint: "3–180 characters." }, { name: "body", label: "Details", type: "textarea", required: true, value: a && a.body }, { name: "publish_at", label: "Publish at (optional)", type: "datetime-local", value: a && toLocalInput(a.publish_at) }, { name: "expires_at", label: "Expires at (optional)", type: "datetime-local", value: a && toLocalInput(a.expires_at) }, { name: "published", label: "Published (visible at the scheduled time)", type: "checkbox", value: a && a.published },
      { name: "priority", label: "Priority", type: "select", options: [["normal", "Normal"], ["low", "Low"], ["high", "High"], ["urgent", "Urgent"]], value: (a && a.priority) || "normal" },
      { name: "notify", label: adm ? "Also send as a notification (in-app and e-mail) — once" : "Also notify my department's students — once", type: "checkbox", value: a && a.notify },
      ...(adm ? [{ name: "audience_roles", label: "Audience roles (blank = everyone; comma separated: student, staff, invigilator, admin)", value: a && (a.audience_roles || []).join(", ") }, { name: "audience_department", label: "Audience department (optional; students and staff)", value: a && a.audience_department }, { name: "audience_year", label: "Audience year (optional; students)", type: "number", value: a && a.audience_year }] : []),
      { name: "remind_at", label: "Send a reminder at (optional)", type: "datetime-local", value: a && toLocalInput(a.remind_at) }],
      submit: async d => { await api(a ? "/api/admin/announcements/" + a.id : "/api/admin/announcements", { method: a ? "PATCH" : "POST", body: { title: d.title, body: d.body, published: d.published, publish_at: d.publish_at ? new Date(d.publish_at).toISOString() : null, expires_at: d.expires_at ? new Date(d.expires_at).toISOString() : null,
        priority: d.priority, notify: !!d.notify, remind_at: d.remind_at ? new Date(d.remind_at).toISOString() : null,
        ...(adm ? { audience_roles: d.audience_roles ? d.audience_roles.split(",").map(x => x.trim()).filter(Boolean) : null, audience_department: d.audience_department || null, audience_year: d.audience_year ? Number(d.audience_year) : null } : {}) } }); return true; } });
    const grid = EM.grid($("#g", root), { rows, caption: "Announcements", searchKeys: ["title", "body"], empty: { title: "No announcements yet" }, columns: [{ key: "title", label: "Title", render: a => `<b>${esc(a.title)}</b><br><span class="muted small">${esc(String(a.body).slice(0, 90))}${a.body.length > 90 ? "…" : ""}</span>` }, { key: "published", label: "Status", render: a => EM.badge(a.published ? "Published" : "Draft", a.published ? "ok" : "") }, { key: "notify", label: "Delivery", render: a => (a.notify ? EM.badge(a.notified_at ? "Notified" : "Notify pending", a.notified_at ? "ok" : "warn") : EM.badge("Public list only")) + (a.audience_roles.length || a.audience_department || a.audience_year ? `<br><span class="muted small">${esc([a.audience_roles.join("/"), a.audience_department, a.audience_year ? "year " + a.audience_year : ""].filter(Boolean).join(" · "))}</span>` : "") }, { key: "publish_at", label: "Schedule", render: a => `${a.publish_at ? esc(EM.fmtDT(a.publish_at)) : "now"} → ${a.expires_at ? esc(EM.fmtDT(a.expires_at)) : "no expiry"}` }],
      actions: a => `<button class="btn sm" data-act="edit" data-id="${a.id}">Edit</button>${adm ? `<button class="btn sm danger" data-act="del" data-id="${a.id}">Delete</button>` : ""}` });
    const reload = async () => { rows = await api("/api/admin/announcements"); grid.setRows(rows); };
    EM.delegate(root, {
      new: async () => { if (await form(null)) { EM.toast("Announcement saved.", "ok"); await reload(); } },
      edit: async b => { if (await form(rows.find(x => x.id === Number(b.dataset.id)))) { EM.toast("Announcement updated.", "ok"); await reload(); } },
      del: async b => { if (!await EM.confirm({ title: "Delete announcement?", message: "This cannot be undone.", confirmText: "Delete", danger: true })) return; await api("/api/admin/announcements/" + b.dataset.id, { method: "DELETE" }); EM.toast("Announcement deleted.", "ok"); await reload(); },
    });
  } });
})();
