/* Phase 11 — cross-module examination workflow centre. Uses the existing domain APIs; no shadow state. */
(function () {
  "use strict";
  const { $, esc, api } = EM;
  EM.page({ name: "workflow", title: "Workflow centre", roles: ["admin", "staff", "invigilator"],
    nav: { group: "Overview", icon: "🔗", label: "Workflow centre", order: 2 },
    render: async root => {
      root.innerHTML = `<div class="stack"><section class="card"><div class="card-head"><h2>Connected system overview</h2><button class="btn sm" id="refresh">Refresh</button></div><div id="overview">${EM.loading("Loading connected modules…")}</div></section><section class="card"><div class="card-head"><h2>Examination workflow</h2></div><div class="field"><label for="examPick">Select examination</label><select id="examPick"><option value="">Loading examinations…</option></select></div><div id="readiness" style="margin-top:14px">${EM.empty("Choose an examination", "The workflow view joins eligibility, verified hall capacity, seat allocation, timetable publication and result publication.")}</div></section></div>`;
      const overview = async () => {
        const el = $("#overview", root); el.innerHTML = EM.loading();
        try {
          const x = await api("/api/integration/overview");
          const items = [[x.students,"Active students"],[x.examinations,"Examinations"],[x.published_examinations,"Published timetables"],[x.allotments,"Seat allotments"],[x.published_results,"Published results"],[x.verified_halls,"Verified halls"],[x.processed_pdf_versions,"Processed PDF versions"],[x.unread_notifications,"Unread notifications"]];
          el.innerHTML = `<div class="grid g4">${items.map(([v,l])=>`<div class="stat"><span class="n">${Number(v||0).toLocaleString()}</span><span class="l">${esc(l)}</span></div>`).join("")}</div><p class="muted small" style="margin-bottom:0">Access scope: ${esc(x.scope.role)}${x.scope.department ? " · "+esc(x.scope.department) : " · institution-wide"}. Attendance: unavailable — ${esc(x.attendance.reason)}</p>`;
        } catch(e) { el.innerHTML = EM.alert(e.message, "warn"); }
      };
      const renderReadiness = async id => {
        const el = $("#readiness", root); if (!id) { el.innerHTML = EM.empty("Choose an examination"); return; }
        el.innerHTML = EM.loading("Combining examination modules…");
        try {
          const x = await api(`/api/integration/exams/${encodeURIComponent(id)}/readiness`);
          const checks = [
            ["Eligible students", x.audience.eligible_students],
            ["Verified halls / known capacity", `${x.campus.verified_halls} / ${x.campus.known_verified_capacity}`],
            ["Allocated / unallocated", `${x.allocation.allocated} / ${x.allocation.unallocated}`],
            ["Results published / records", `${x.results.published} / ${x.results.records}`],
            ["Timetable status", x.exam.status]
          ];
          el.innerHTML = `<div class="row between"><div><h3 style="margin:0">${esc(x.exam.title)}</h3><p class="muted small">${esc(x.exam.subject_code)} · ${esc(x.exam.date)} · ${esc(x.exam.start_time)}–${esc(x.exam.end_time)}</p></div>${EM.badge(x.workflow.ready_for_exam_day ? "Ready for exam day" : "Action required", x.workflow.ready_for_exam_day ? "ok" : "warn")}</div><div class="grid g2">${checks.map(([l,v])=>`<div class="item"><div class="t">${esc(l)}</div><div class="m">${esc(v)}</div></div>`).join("")}</div><h3 style="margin-top:16px">Next actions</h3>${x.workflow.issues.length ? `<ul>${x.workflow.issues.map(i=>`<li>${esc(i)}</li>`).join("")}</ul>` : EM.alert("No outstanding readiness actions were identified.","ok")}<div class="form-actions">${x.workflow.actions.map(a=>`<a class="btn" href="${esc(a.route)}">${esc(a.label)}</a>`).join("")}</div><p class="muted small">This is a live, read-only summary. Existing module endpoints remain responsible for approvals and changes.</p>`;
        } catch(e) { el.innerHTML = EM.alert(e.message, "bad"); }
      };
      const loadExams = async () => {
        const sel = $("#examPick", root);
        try {
          const r = await api("/api/admin/exams", { params: { limit: 300, offset: 0 } });
          sel.innerHTML = `<option value="">Select an examination…</option>` + r.map(e=>`<option value="${e.id}">#${e.id} · ${esc(e.title)} · ${esc(e.exam_date)} (${esc(e.status)})</option>`).join("");
          if (!r.length) sel.innerHTML = `<option value="">No examinations available</option>`;
        } catch(e) { sel.innerHTML = `<option value="">${esc(e.message)}</option>`; }
      };
      $("#refresh", root).onclick = async () => { await overview(); await loadExams(); if ($("#examPick",root).value) await renderReadiness($("#examPick",root).value); };
      $("#examPick", root).onchange = e => renderReadiness(e.target.value);
      await Promise.all([overview(), loadExams()]);
    }
  });
})();
