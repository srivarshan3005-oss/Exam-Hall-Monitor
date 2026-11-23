/* Layout (public site / signed-in shell), boot sequence, public pages and authentication pages.
   EXAMINATION INTELLIGENCE PLATFORM — Exam Monitor Ultimate */
(function () {
  "use strict";
  const { $, $$, esc, api } = EM;
  const GROUPS = ["Overview", "Examinations", "Seating", "Documents", "People", "Administration", "Account"];
  let layout = "";   // "public" | "app"
  let store = null;
  try { store = window.sessionStorage; } catch (e) { /* storage blocked */ }
  EM.saveToken = t => { EM.state.token = t; try { t ? store.setItem("em_token", t) : store.removeItem("em_token"); } catch (e) { /* ignore */ } };

  // ------------------------------------------------------------ theme (preference only; never a credential)
  function applyTheme(t) { if (t) document.documentElement.setAttribute("data-theme", t); else document.documentElement.removeAttribute("data-theme"); }
  try { applyTheme(window.localStorage.getItem("em_theme")); } catch (e) { /* ignore */ }
  EM.toggleTheme = () => {
    const dark = (document.documentElement.getAttribute("data-theme") || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")) === "dark";
    const next = dark ? "light" : "dark"; applyTheme(next); try { window.localStorage.setItem("em_theme", next); } catch (e) { /* ignore */ }
  };

  // ------------------------------------------------------------ layouts
  const brand = () => `<span class="logo" aria-hidden="true">EM</span><span><b>${esc(EM.state.config.college_name || "Exam Monitor")}</b><small>EXAM MONITOR ULTIMATE</small></span>`;
  function mount(kind) {
    if (layout === kind && $("#main")) return;
    layout = kind; const app = $("#app");
    if (kind === "public") {
      app.innerHTML = `<header class="pub-top"><a class="brand" href="#/">${brand()}</a><nav class="row" aria-label="Main"><a class="btn" href="#/">Student Allotment Portal</a><a class="btn" href="#/timetable">Timetable</a><a class="btn primary" href="#/login">Staff &amp; student sign in</a><button class="btn" id="themeBtn" type="button" aria-label="Toggle light or dark theme">◐ Theme</button></nav></header><main id="main" tabindex="-1"></main><footer class="foot">© <span id="yr"></span> ${esc(EM.state.config.college_name || "VSB Engineering College")} · Real-Time Examination Allotment Portal · Exam Monitor Ultimate</footer>`;
      $("#yr").textContent = new Date().getFullYear();
    } else {
      app.innerHTML = `<div class="app" id="shell"><aside class="side" id="side" aria-label="Sidebar"><a class="brand" href="#/">${brand()}</a><nav class="nav" id="nav" aria-label="Primary"></nav></aside><div class="scrim" id="scrim"></div>
        <div><header class="topbar"><button class="btn menu-btn" id="menuBtn" type="button" aria-label="Open navigation" aria-expanded="false" aria-controls="side">☰</button><h1 id="pageTitle"></h1>
        <div class="userchip"><a class="btn sm bell" id="bellBtn" href="#/notifications" aria-label="Notifications"><span aria-hidden="true">🔔</span><span class="bell-count" id="bellCount" hidden></span></a><div class="who"><b id="uName"></b><small id="uRole"></small></div><button class="btn sm" id="themeBtn" type="button" aria-label="Toggle light or dark theme">◐</button><button class="btn sm" id="outBtn" type="button">Sign out</button></div></header>
        <main id="main" class="content" tabindex="-1"></main><footer class="foot">© <span id="yr"></span> Exam Monitor Ultimate · Independent software project</footer></div></div>`;
      $("#yr").textContent = new Date().getFullYear();
      $("#uName").textContent = EM.state.user.username; $("#uRole").textContent = EM.state.user.role_label || EM.state.user.role;
      $("#outBtn").onclick = () => EM.logout();
      const shell = $("#shell"), setOpen = o => { const mb = $("#menuBtn"); if (!shell.isConnected || !mb) return; shell.classList.toggle("nav-open", o); mb.setAttribute("aria-expanded", String(o)); };
      $("#menuBtn").onclick = () => setOpen(!shell.classList.contains("nav-open")); $("#scrim").onclick = () => setOpen(false);
      if (!EM.escBound) { EM.escBound = true; document.addEventListener("keydown", e => { const sh = $("#shell"); if (e.key === "Escape" && sh && sh.classList.contains("nav-open")) { sh.classList.remove("nav-open"); const mb = $("#menuBtn"); if (mb) { mb.setAttribute("aria-expanded", "false"); mb.focus(); } } }); }
      EM.closeNav = () => setOpen(false);
      buildNav();
    }
    $("#themeBtn").onclick = EM.toggleTheme;
  }
  function buildNav() {
    const items = EM.pages.filter(p => p.nav && (!p.roles || p.roles.some(r => EM.can(r))) && (!p.nav.only || p.nav.only.includes(EM.role()))).sort((a, b) => GROUPS.indexOf(a.nav.group) - GROUPS.indexOf(b.nav.group) || (a.nav.order || 50) - (b.nav.order || 50));
    let html = "", g = "";
    items.forEach(p => { if (p.nav.group !== g) { g = p.nav.group; html += `<h4>${esc(g)}</h4>`; } html += `<a href="#/${p.name}" data-nav="${p.name}"><span class="ico" aria-hidden="true">${p.nav.icon || "•"}</span>${esc(p.nav.label || p.title)}</a>`; });
    $("#nav").innerHTML = html;
  }
  // Unread badge: refreshed on navigation and when the tab regains focus -- never on a timer, so a background
  // tab cannot keep an idle session alive.
  EM.refreshBell = async () => {
    const c = $("#bellCount"); if (!c || !EM.state.user) return;
    try { const r = await api("/api/notifications/unread-count", { keepSession: true }); const n = r.unread || 0; c.hidden = n === 0; c.textContent = n > 99 ? "99+" : String(n); $("#bellBtn").setAttribute("aria-label", n ? `Notifications, ${n} unread` : "Notifications"); } catch (e) { /* bell is optional */ }
  };
  document.addEventListener("visibilitychange", () => { if (!document.hidden) EM.refreshBell(); });
  EM.afterNav = def => { EM.refreshBell(); const cur = def && (def.name === "" ? "dashboard" : def.name); $$("#nav a").forEach(a => { a.dataset.nav === cur ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"); }); if (EM.closeNav) EM.closeNav(); };
  EM.root = def => {
    mount(EM.state.user ? "app" : "public");
    const main = $("#main"); main.innerHTML = ""; const v = document.createElement("div"); v.className = (layout === "public" && !(def && def.hero) ? "pub-main" : ""); main.appendChild(v); return v;
  };

  // ------------------------------------------------------------ route guards
  const PUBLIC = ["", "login", "register", "forgot", "reset", "activate", "timetable"];
  EM.beforeRender = (def, loc, signed) => {
    if (!signed) { if (!def || PUBLIC.includes(def.name)) return null; EM.after = location.hash; EM.flash = "Please sign in to continue."; return "/login"; }
    if (EM.state.user.pw_change_required && loc.name !== "change-password") return "/change-password";
    if (["login", "register", "forgot", "reset", "activate"].includes(loc.name)) return "/";
    return null;
  };
  EM.logout = async (everywhere) => {
    try { await api(everywhere ? "/api/auth/logout-all" : "/api/auth/logout", { method: "POST", keepSession: true }); } catch (e) { /* offline or already ended: still clear locally */ }
    EM.saveToken(""); EM.state.user = null; layout = ""; EM.flash = everywhere ? "Signed out of every device." : "You have been signed out."; EM.go("/login", true);
  };
  EM.loadUser = async () => { const p = await api("/api/auth/profile", { keepSession: true }); EM.state.user = p; layout = ""; return p; };

  // ------------------------------------------------------------ public: home (lookup, timetable, announcements)
  const regOk = r => /^[A-Za-z0-9]{6,20}$/.test(r);

  function parseCalendarDate(dateStr) {
    if (!dateStr || dateStr === "UNKNOWN") return { month: "EXAM", day: "--", dayName: "Date to be announced", fullDate: dateStr || "Date to be announced" };
    try {
      const parts = String(dateStr).slice(0, 10).split("-");
      if (parts.length === 3) {
        const d = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
        const month = d.toLocaleDateString("en-GB", { month: "short" }).toUpperCase();
        const day = d.toLocaleDateString("en-GB", { day: "2-digit" });
        const dayName = d.toLocaleDateString("en-GB", { weekday: "long" });
        const fullDate = d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
        return { month, day, dayName, fullDate };
      }
    } catch (e) { /* ignore */ }
    return { month: "EXAM", day: "--", dayName: "", fullDate: String(dateStr) };
  }

  function formatExamDate(dateStr) {
    if (!dateStr || dateStr === "UNKNOWN") return { dateText: "Date to be announced", dayText: "" };
    try {
      const parts = String(dateStr).slice(0, 10).split("-");
      if (parts.length === 3) {
        const d = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
        const dateText = d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
        const dayText = d.toLocaleDateString("en-GB", { weekday: "long" });
        return { dateText, dayText };
      }
    } catch (e) { /* ignore */ }
    return { dateText: String(dateStr), dayText: "" };
  }

  async function loadActiveNotices(container, countBadge) {
    if (!container) return;
    try {
      const exams = await api("/api/exams", { auth: false });
      if (!exams || !exams.length) {
        if (countBadge) countBadge.textContent = "Monitoring Live";
        container.innerHTML = `<div class="active-empty-state"><div style="font-weight:700;color:#cbd5e1;margin-bottom:4px">No upcoming examination notices uploaded yet.</div><div>Automated system is monitoring the Controller of Examinations notice board.</div></div>`;
        return;
      }
      const grouped = {};
      exams.forEach(ex => {
        const d = ex.exam_date;
        if (!d || d === "UNKNOWN") return;
        const sess = (ex.session || (ex.start_time && ex.start_time >= "12:00" ? "AN" : "FN")).toUpperCase();
        if (!grouped[d]) grouped[d] = { exam_date: d, sessions: new Set(), exams: [] };
        grouped[d].sessions.add(sess);
        grouped[d].exams.push(ex);
      });
      const dates = Object.keys(grouped).sort();
      if (!dates.length) {
        if (countBadge) countBadge.textContent = "Monitoring Live";
        container.innerHTML = `<div class="active-empty-state"><span>No active examination dates published yet.</span></div>`;
        return;
      }
      if (countBadge) countBadge.textContent = `${dates.length} ${dates.length === 1 ? "Exam Date Active" : "Exam Dates Active"}`;
      container.innerHTML = dates.map(dKey => {
        const group = grouped[dKey];
        const { month, day, dayName, fullDate } = parseCalendarDate(group.exam_date);
        const sessions = Array.from(group.sessions).sort();
        const sessionPills = sessions.map(s => {
          const sLower = s.toLowerCase();
          const sLabel = s === "AN" ? "AN · 01:30 PM" : "FN · 09:30 AM";
          return `<span class="active-session-pill ${sLower}">${esc(sLabel)}</span>`;
        }).join("");
        return `<div class="active-date-card">
          <div class="active-date-info">
            <div class="active-calendar-badge">
              <span class="active-calendar-month">${esc(month)}</span>
              <span class="active-calendar-day">${esc(day)}</span>
            </div>
            <div class="active-date-details">
              <div class="active-date-title">${esc(dayName ? `${dayName}, ${fullDate}` : fullDate)}</div>
              <div class="active-sessions-row">
                ${sessionPills}
                <span style="font-size:11px;color:#94a3b8;margin-left:4px">(${group.exams.length} scheduled)</span>
              </div>
            </div>
          </div>
          <span class="active-status-badge">🟢 ACTIVE NOW</span>
        </div>`;
      }).join("");
    } catch (e) {
      if (countBadge) countBadge.textContent = "Notice Board";
      container.innerHTML = `<div class="active-empty-state"><span>Automated notice watcher is monitoring the Controller of Examinations notice board.</span></div>`;
    }
  }

  function openSeatingModal(imgSrc, hall, seat) {
    const modal = $("#seatingModal");
    const img = $("#modalImg");
    const title = $("#modalTitleSpan");
    const newTab = $("#modalNewTab");
    if (!modal || !img) return;
    img.src = imgSrc;
    if (newTab) newTab.href = imgSrc;
    if (title) title.textContent = `Room Seating Chart · Hall ${hall} (Seat ${seat})`;
    modal.classList.add("active");
    document.body.style.overflow = "hidden";
  }

  function closeSeatingModal() {
    const modal = $("#seatingModal");
    if (modal) {
      modal.classList.remove("active");
      document.body.style.overflow = "";
    }
  }

  function buildPrintSlip(student, items) {
    let printDiv = $("#printArea");
    if (!printDiv) {
      printDiv = document.createElement("div");
      printDiv.id = "printArea";
      document.body.appendChild(printDiv);
    }
    const college = EM.state.config.college_name || "VSB Engineering College, Karur";
    const nowStr = new Date().toLocaleString([], { dateStyle: "long", timeStyle: "short" });
    const sName = student.full_name || "Candidate";
    const sReg = student.register_number || "—";
    const sDept = student.department || "—";
    const sYear = student.year ? `Year ${student.year}` : "—";

    let rowsHtml = items.map(item => {
      const sess = (item.session || (item.time && item.time >= "12:00" ? "AN" : "FN")).toUpperCase();
      const sessTiming = sess === "AN" ? "01:30 PM – 04:30 PM" : "09:30 AM – 12:30 PM";
      const { dateText, dayText } = formatExamDate(item.date);
      const locText = item.location ? Object.values(item.location).filter(Boolean).join(" / ") : "";
      return `<tr>
        <td><b>${esc(dateText)}</b><br><small style="color:#555">${esc(dayText)}</small></td>
        <td><b>${esc(sess)}</b><br><small style="color:#555">${esc(sessTiming)}</small></td>
        <td><span class="mono"><b>${esc(item.subject_code || "—")}</b></span></td>
        <td>${esc(item.subject || item.exam || "Semester Examination")}</td>
        <td style="font-size:11pt"><b>${esc(item.hall || "Notice Board")}</b>${locText ? `<br><small style="color:#555">${esc(locText)}</small>` : ""}</td>
        <td style="font-size:12pt;text-align:center"><b>${esc(item.seat || "Hall Display")}</b></td>
      </tr>`;
    }).join("");

    printDiv.innerHTML = `
      <div class="print-slip">
        <div class="print-slip-header">
          <div class="print-slip-college">${esc(college)}</div>
          <div class="print-slip-title">OFFICE OF THE CONTROLLER OF EXAMINATIONS</div>
          <div class="print-slip-subtitle">STUDENT EXAMINATION SEATING ALLOTMENT SLIP</div>
        </div>
        <table class="print-slip-meta-table">
          <tr>
            <th style="width:20%;background:#f5f5f5">Register Number</th>
            <td style="width:30%" class="mono"><b>${esc(sReg)}</b></td>
            <th style="width:20%;background:#f5f5f5">Student Name</th>
            <td style="width:30%"><b>${esc(sName)}</b></td>
          </tr>
          <tr>
            <th style="background:#f5f5f5">Department</th>
            <td>${esc(sDept)}</td>
            <th style="background:#f5f5f5">Academic Class</th>
            <td>${esc(sYear)}</td>
          </tr>
          <tr>
            <th style="background:#f5f5f5">Examination Centre</th>
            <td colspan="3">${esc(college)} (Autonomous / Affiliated Anna University)</td>
          </tr>
          <tr>
            <th style="background:#f5f5f5">Generated On</th>
            <td colspan="3">${esc(nowStr)} · Verified against examination database</td>
          </tr>
        </table>
        <h4 style="margin:16px 0 8px 0;font-size:11pt;text-transform:uppercase;letter-spacing:0.04em">Allocated Examinations &amp; Seating Plan</h4>
        <table class="print-slip-schedule-table">
          <thead>
            <tr>
              <th style="width:16%">Exam Date</th>
              <th style="width:14%">Session</th>
              <th style="width:14%">Subject Code</th>
              <th style="width:26%">Subject / Examination</th>
              <th style="width:16%">Hall / Room</th>
              <th style="width:14%;text-align:center">Seat No</th>
            </tr>
          </thead>
          <tbody>
            ${rowsHtml}
          </tbody>
        </table>
        <div class="print-slip-instructions">
          <b>IMPORTANT INSTRUCTIONS FOR CANDIDATES:</b>
          <ol>
            <li>Candidates must occupy their allotted seats at least 15 minutes prior to the commencement of the examination (09:15 AM for FN / 01:15 PM for AN).</li>
            <li>Possession of mobile phones, programmable calculators, smart watches, or unauthorized materials is strictly prohibited inside the examination hall.</li>
            <li>Candidates must carry their valid University/College Identity Card and Hall Ticket to all examination sessions.</li>
            <li>This slip reflects verified allotments published by the Controller of Examinations. Cross-check hall display boards on examination day for any last-minute emergency relocations.</li>
          </ol>
        </div>
      </div>
    `;
    window.print();
  }

  EM.lookupHtml = async function (reg, d) {
    const s = d.student, a = d.allotments || [];
    let html = `<dl class="kv">${s.full_name ? `<dt>Name</dt><dd>${esc(s.full_name)}</dd>` : ""}<dt>Register number</dt><dd class="mono">${esc(s.register_number)}</dd><dt>Department</dt><dd>${esc(s.department)} · Year ${esc(s.year)}</dd></dl>`;
    html += `<h3 style="margin-top:16px">Seat allotments</h3>` + (a.length ? `<div class="list">${a.map(x => `<div class="item"><div class="t">${esc(x.exam)} <span class="muted">(${esc(x.subject_code)})</span></div><div class="m">${esc(x.date)} · ${esc(x.time)} · Hall <b>${esc(x.hall)}</b> · Seat <b>${esc(x.seat)}</b>${x.location ? " · " + esc(Object.values(x.location).filter(Boolean).join(" / ")) : ""}</div></div>`).join("")}</div>` : EM.empty("No published seat allotment", "Seats appear here once the examination is published."));
    if (d.vsb_allocations && d.vsb_allocations.length && EM.vsbAllocHtml) html += `<h3 style="margin-top:16px">Confirmed hall and seat (VSB)</h3>` + EM.vsbAllocHtml(d.vsb_allocations);
    if (d.source_documents && d.source_documents.length) html += `<h3 style="margin-top:16px">Approved PDF references</h3><div class="list">${d.source_documents.map(x => `<div class="item m">Original PDF page ${esc(x.page_number)} · Hall ${esc(x.hall || "not specified")} · Seat ${esc(x.seat_number || "not specified")}</div>`).join("")}</div>`;
    html += `<h3 style="margin-top:16px">Published results</h3>` + await EM.resultsHtml(s.register_number, d.results_available_without_signin);
    return html;
  };

  EM.resultsHtml = async function (reg, openToPublic) {
    if (!EM.state.token && !openToPublic) return `<p class="muted">Published results are available after you sign in.</p>`;
    try {
      const rows = await api("/api/results/" + encodeURIComponent(reg));
      return rows.length ? `<div class="tablewrap"><table class="table stack"><thead><tr><th>Examination</th><th>Subject</th><th>Marks</th><th>Grade</th></tr></thead><tbody>${rows.map(x => `<tr><td data-label="Examination">${esc(x.exam)}</td><td data-label="Subject">${esc(x.subject_code)}</td><td data-label="Marks">${esc(x.marks)} / ${esc(x.max_marks)}</td><td data-label="Grade">${esc(x.grade)}</td></tr>`).join("")}</tbody></table></div>` : EM.empty("No published results yet");
    } catch (e) { return `<p class="muted">${e.status === 403 || e.status === 401 ? "Published results are visible only to the signed-in student (or staff)." : esc(e.message)}</p>`; }
  };

  async function publicLists(root) {
    const [ex, an] = await Promise.allSettled([api("/api/exams", { auth: false }), api("/api/announcements", { auth: false })]);
    const exams = ex.status === "fulfilled" ? ex.value : null, anns = an.status === "fulfilled" ? an.value : null;
    const pe = $("#pubExams", root), pa = $("#pubAnn", root);
    if (pe) pe.innerHTML = exams === null ? EM.alert("The timetable is temporarily unavailable.", "warn") : exams.length ? EM.timetableTable(exams) : EM.empty("No published examinations yet");
    if (pa) pa.innerHTML = anns === null ? EM.alert("Announcements are temporarily unavailable.", "warn") : anns.length ? `<div class="list">${anns.map(a => `<div class="item"><div class="t">${esc(a.title)}</div><div class="m" style="white-space:pre-wrap">${esc(a.body)}</div></div>`).join("")}</div>` : EM.empty("No current announcements");
  }

  EM.timetableTable = exams => `<div class="tablewrap"><table class="table stack"><caption class="sr-only">Published examination timetable</caption><thead><tr><th scope="col">Date</th><th scope="col">Time</th><th scope="col">Examination</th><th scope="col">Subject</th><th scope="col">Venue</th></tr></thead><tbody>${exams.map(e => `<tr><td data-label="Date" class="nowrap">${esc(e.exam_date)}</td><td data-label="Time" class="nowrap">${esc(e.start_time)}–${esc(e.end_time)}</td><td data-label="Examination">${esc(e.title)}</td><td data-label="Subject">${esc(e.subject_code)}</td><td data-label="Venue">${esc(e.venue)}</td></tr>`).join("")}</tbody></table></div>`;

  EM.page({ name: "", title: "", hero: true, render: async (root, ctx) => {
    if (EM.state.user) return EM.pageByName("dashboard").render(root, ctx);
    const collegeName = EM.state.config.college_name || "VSB Engineering College";
    EM.setTitle("Exam Allotment Portal · Hall & Seating Arrangement Finder");

    root.innerHTML = `
      <div class="portal-wrapper">
        <header class="portal-header">
          <div class="college-tag">${esc(collegeName.toUpperCase())} · SEMESTER EXAMINATION MONITOR</div>
          <h1 class="portal-title">Exam Allotment Portal</h1>
          <p class="portal-subtitle">Real-Time Examination Hall &amp; Seating Arrangement Finder</p>
        </header>

        <!-- Live Active Examination Allotments Banner -->
        <div class="active-notices-card" id="activeNoticesCard">
          <div class="active-notices-header">
            <div class="active-notices-title-wrap">
              <span class="live-dot-pulse" aria-hidden="true"></span>
              <span class="active-notices-title">Live Published Examination Allotments</span>
            </div>
            <span class="active-notices-count-badge" id="activeCountBadge">Checking notices...</span>
          </div>
          <div class="active-notices-grid" id="activeNoticesList">
            <div class="active-empty-state">
              <span>Loading currently published examination notices...</span>
            </div>
          </div>
          <div class="active-notices-footer">
            <span>⚡ Synchronized with Controller of Examinations notice board</span>
            <span>Enter your register number below to view hall &amp; seat</span>
          </div>
        </div>

        <div class="search-card">
          <form class="search-form" id="portalSearchForm">
            <div class="input-wrap">
              <input 
                type="text" 
                id="regInput" 
                name="reg" 
                placeholder="Enter your register number" 
                autocomplete="off" 
                                required 
                maxlength="24"
                inputmode="numeric"
                aria-label="Student Register Number"
              >
            </div>
            <div class="row" style="gap:8px;flex-wrap:nowrap">
              <button type="submit" class="btn-search" id="searchBtn">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
                <span>Find Allotment</span>
              </button>
              <button type="button" class="btn" id="clearBtn">Clear</button>
            </div>
          </form>
          <p class="search-hint">
            Enter your university register number to view your allocated examination hall &amp; seat arrangement.
          </p>
        </div>

        <div id="loadingView" class="state-box" style="display:none;" aria-live="polite">
          <div class="spinner" aria-hidden="true"></div>
          <div style="font-weight:600;color:#94a3b8;">Searching published examination records...</div>
        </div>

        <div id="emptyView" class="state-box not-allotted" style="display:none;" aria-live="polite">
          <div class="state-icon" aria-hidden="true">📋</div>
          <div class="state-title" id="emptyTitle">Not Allotted / Not Yet Published</div>
          <div class="state-desc" id="emptyDesc">
            No examination allotment record was found for this register number in currently published records.
          </div>
        </div>

        <div id="resultsContainer" style="display:none;" aria-live="polite">
          <div class="results-header">
            <div class="row" style="align-items:center;gap:10px">
              <span class="student-badge" id="displayReg">REG NUMBER</span>
              <span class="count-badge" id="displayCount">0 EXAMS</span>
            </div>
            <button type="button" class="btn-print" id="printSlipBtn">🖨️ Print Slip</button>
          </div>

          <div id="studentDetailsBox" class="student-meta-box" style="display:none;"></div>
          <div class="cards-list" id="cardsList"></div>
          <div id="extraResultsBox" style="margin-top:20px;"></div>
        </div>

        <!-- Modal for viewing full Seating Allotment Page Image -->
        <div id="seatingModal" class="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="modalTitle">
          <div class="modal-content">
            <div class="modal-header">
              <h3 id="modalTitle">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M20.4 14.5L16 10 4 20"/></svg>
                <span id="modalTitleSpan">Room Seating Chart</span>
              </h3>
              <div class="modal-actions">
                <a id="modalNewTab" href="#" target="_blank" rel="noopener" class="modal-btn">Open Full Image ↗</a>
                <button type="button" class="modal-btn modal-btn-close" id="modalCloseBtn">✕ Close</button>
              </div>
            </div>
            <div class="modal-body">
              <img id="modalImg" src="" alt="Seating Allotment Chart">
            </div>
          </div>
        </div>

        <!-- Official Notices & Auxiliary Info -->
        <div class="stack" style="margin-top:36px">
          <section class="card" aria-labelledby="vsbh">
            <div class="card-head">
              <div>
                <h2 id="vsbh">Official Examination Notices</h2>
                <p class="muted small" style="margin:0">Links to the Controller of Examinations timetables, hall and seating allotment PDFs.</p>
              </div>
            </div>
            <div id="pubVsb">${EM.loading()}</div>
          </section>

          <div class="grid g2">
            <section class="card">
              <div class="card-head"><h2>Examination Timetable</h2></div>
              <div id="pubExams">${EM.loading()}</div>
            </section>
            <section class="card">
              <div class="card-head"><h2>Announcements</h2></div>
              <div id="pubAnn">${EM.loading()}</div>
            </section>
          </div>
        </div>
      </div>
    `;

    const form = $("#portalSearchForm", root);
    // V7: one student experience. A valid register number is handed to the register-number-only finder (/portal/), which reads
    // the automatically monitored official PDFs; invalid input still gets the inline message below.
    EM.goPortal = EM.goPortal || (reg => window.location.assign("/portal/?reg=" + encodeURIComponent(reg)));
    form.addEventListener("submit", ev => {
      const reg = String($("#regInput", root).value || "").replace(/[\s\-_.]+/g, "").toUpperCase();
      if (/^[A-Z0-9]{6,20}$/.test(reg)) { ev.preventDefault(); ev.stopImmediatePropagation(); EM.goPortal(reg); }
    }, true);
    const regInput = $("#regInput", root);
    const searchBtn = $("#searchBtn", root);
    const clearBtn = $("#clearBtn", root);
    const loadingView = $("#loadingView", root);
    const emptyView = $("#emptyView", root);
    const emptyTitle = $("#emptyTitle", root);
    const emptyDesc = $("#emptyDesc", root);
    const resultsContainer = $("#resultsContainer", root);
    const displayReg = $("#displayReg", root);
    const displayCount = $("#displayCount", root);
    const studentBox = $("#studentDetailsBox", root);
    const cardsList = $("#cardsList", root);
    const extraBox = $("#extraResultsBox", root);
    const printBtn = $("#printSlipBtn", root);
    const modal = $("#seatingModal", root);
    const modalCloseBtn = $("#modalCloseBtn", root);

    let lastStudent = null;
    let lastItems = [];

    // Modal listeners
    if (modalCloseBtn) modalCloseBtn.addEventListener("click", closeSeatingModal);
    if (modal) {
      modal.addEventListener("click", (e) => {
        if (e.target === modal) closeSeatingModal();
      });
    }

    // Print button listener
    if (printBtn) {
      printBtn.addEventListener("click", () => {
        if (lastStudent && lastItems.length) {
          buildPrintSlip(lastStudent, lastItems);
        }
      });
    }

    // Delegated click handler for zoom buttons in cards list
    if (cardsList) {
      cardsList.addEventListener("click", (e) => {
        const btn = e.target.closest("[data-zoom-img]");
        if (btn) {
          e.preventDefault();
          const img = btn.getAttribute("data-zoom-img");
          const hall = btn.getAttribute("data-zoom-hall") || "";
          const seat = btn.getAttribute("data-zoom-seat") || "";
          openSeatingModal(img, hall, seat);
        }
      });
    }

    async function executeSearch(rawReg) {
      const reg = String(rawReg || "").replace(/[\s-]/g, "").toUpperCase();
      if (!regOk(reg)) {
        resultsContainer.style.display = "none";
        loadingView.style.display = "none";
        emptyTitle.textContent = "Invalid Register Number";
        emptyTitle.className = "state-title";
        emptyDesc.innerHTML = "Please enter a valid register number (6–20 letters or digits). Spaces and hyphens are ignored.";
        emptyView.className = "state-box not-allotted";
        emptyView.style.display = "block";
        searchBtn.disabled = false;
        return;
      }

      // Sync URL parameter ?reg=...
      try {
        const u = new URL(window.location);
        u.searchParams.set("reg", reg);
        window.history.replaceState({}, "", u);
      } catch (e) { /* ignore */ }

      // Set loading state
      searchBtn.disabled = true;
      loadingView.style.display = "block";
      resultsContainer.style.display = "none";
      emptyView.style.display = "none";

      try {
        const d = await api("/api/lookup/" + encodeURIComponent(reg));
        const s = d.student || { register_number: reg };
        const rawAllotments = d.allotments || [];
        const rawVsb = d.vsb_allocations || [];
        const srcDocs = d.source_documents || [];

        // Combine into unified allotment records
        const combined = [];
        rawAllotments.forEach(a => {
          combined.push({
            exam: a.exam,
            subject: a.exam,
            subject_code: a.subject_code,
            date: a.date,
            time: a.time,
            session: a.time && a.time >= "12:00" ? "AN" : "FN",
            hall: a.hall,
            seat: a.seat,
            location: a.location,
            source: null
          });
        });

        rawVsb.forEach(v => {
          const dup = combined.some(c => c.subject_code === v.subject_code && c.date === v.date && c.hall === v.hall && c.seat === v.seat);
          if (!dup) {
            combined.push({
              exam: v.exam,
              subject: v.subject || v.exam,
              subject_code: v.subject_code,
              date: v.date,
              time: v.session === "AN" ? "13:30" : "09:30",
              session: v.session || "FN",
              hall: v.hall,
              seat: v.seat,
              location: null,
              source: v.source,
              verify_note: v.verify_note,
              verification_label: v.verification_label
            });
          }
        });

        lastStudent = s;
        lastItems = combined;

        if (combined.length === 0) {
          emptyTitle.textContent = "Not Allotted / Not Yet Published";
          emptyTitle.className = "state-title";
          emptyDesc.innerHTML = `No currently published examination allotment record was found for Register Number <strong>${esc(reg)}</strong>.<br><br>If today or tomorrow is your examination day, the Controller of Examinations notice may not yet be uploaded. Please verify the official notice board.`;
          emptyView.className = "state-box not-allotted";
          emptyView.style.display = "block";
        } else {
          displayReg.textContent = `REG: ${reg}`;
          displayCount.textContent = `${combined.length} ${combined.length === 1 ? "CURRENT EXAM" : "CURRENT EXAMS"}`;

          // Student details card
          const hasDetails = s.full_name || s.department || s.year;
          if (hasDetails) {
            studentBox.innerHTML = `
              ${s.full_name ? `<div class="student-meta-item"><span>Student Name</span><strong>${esc(s.full_name)}</strong></div>` : ""}
              <div class="student-meta-item"><span>Register Number</span><strong class="mono">${esc(s.register_number || reg)}</strong></div>
              ${s.department ? `<div class="student-meta-item"><span>Department</span><strong>${esc(s.department)}</strong></div>` : ""}
              ${s.year ? `<div class="student-meta-item"><span>Academic Year</span><strong>Year ${esc(s.year)}</strong></div>` : ""}
              <div class="student-meta-item"><span>Examination Centre</span><strong>${esc(collegeName)}</strong></div>
            `;
            studentBox.style.display = "grid";
          } else {
            studentBox.style.display = "none";
          }

          // Build cards list
          cardsList.innerHTML = combined.map(item => {
            const session = (item.session || (item.time && item.time >= "12:00" ? "AN" : "FN")).toUpperCase();
            const sessionClass = session === "AN" ? "session-an" : "session-fn";
            const sessionBadgeClass = session === "AN" ? "an" : "fn";
            const sessionTime = session === "AN" ? "AN · 01:30 PM – 04:30 PM" : "FN · 09:30 AM – 12:30 PM";
            const { dateText, dayText } = formatExamDate(item.date);
            const subjCode = item.subject_code ? item.subject_code : "Theory Exam";
            const subjTitle = item.subject || item.exam || "Semester Theory Examination";
            const hall = item.hall || "Check Notice Board";
            const seat = item.seat && item.seat !== "UNKNOWN" ? item.seat : "Check Hall Display";
            
            let locationHtml = "";
            if (item.location) {
              const locParts = [];
              if (item.location.building) locParts.push(`Building: ${esc(item.location.building)}`);
              if (item.location.block) locParts.push(`Block: ${esc(item.location.block)}`);
              if (item.location.floor) locParts.push(`Floor: ${esc(item.location.floor)}`);
              if (item.location.room) locParts.push(`Room: ${esc(item.location.room)}`);
              if (locParts.length) {
                locationHtml = `<div class="location-desc">${locParts.join(" · ")}</div>`;
              }
            }

            const seatingHtml = item.seating_image ? `
              <div class="seating-evidence-box">
                <div class="evidence-header">
                  <span class="evidence-title">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M20.4 14.5L16 10 4 20"/></svg>
                    Room Seating Chart · Hall ${esc(hall)}
                  </span>
                  <button type="button" class="btn-zoom" data-zoom-img="${esc(item.seating_image)}" data-zoom-hall="${esc(hall)}" data-zoom-seat="${esc(seat)}">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/></svg>
                    View Full Chart
                  </button>
                </div>
                <div class="evidence-preview-wrapper" data-zoom-img="${esc(item.seating_image)}" data-zoom-hall="${esc(hall)}" data-zoom-seat="${esc(seat)}">
                  <img src="${esc(item.seating_image)}" alt="Seating chart for Hall ${esc(hall)} Seat ${esc(seat)}" loading="lazy">
                  <div class="evidence-overlay-hint">🔍 Tap to inspect desk &amp; seat layout</div>
                </div>
              </div>` : "";

            const pdfLink = (item.source && item.source.url) ? `<a href="${esc(item.source.url)}" target="_blank" rel="noopener">View Official PDF ↗</a>` : "";

            return `<div class="exam-card ${sessionClass}">
              <div class="card-top">
                <div class="exam-date-box">
                  <span class="exam-date">${esc(dateText)}</span>
                  ${dayText ? `<span class="exam-day">${esc(dayText)}</span>` : ""}
                </div>
                <span class="session-pill ${sessionBadgeClass}">${esc(sessionTime)}</span>
              </div>

              <div class="subject-info">
                <div class="subject-code">${esc(subjCode)}</div>
                <div class="subject-title">${esc(subjTitle)}</div>
              </div>

              <div class="allotment-grid">
                <div class="grid-cell hall">
                  <span>Exam Hall / Room</span>
                  <strong>${esc(hall)}</strong>
                  ${locationHtml}
                </div>
                <div class="grid-cell seat">
                  <span>Allocated Seat No</span>
                  <strong>${esc(seat)}</strong>
                </div>
              </div>

              ${seatingHtml}

              <div class="card-meta">
                <span>Status: <strong style="color:#22c55e;">Confirmed</strong> · ${esc(collegeName)}</span>
                ${pdfLink}
              </div>
            </div>`;
          }).join("");

          // Additional approved PDF references / results
          let extraHtml = "";
          if (srcDocs.length) {
            extraHtml += `<div class="card" style="margin-top:16px"><div class="card-head"><h3>Approved PDF Extraction References</h3></div><div class="list">${srcDocs.map(x => `<div class="item m">Official PDF Page ${esc(x.page_number)} · Hall <b>${esc(x.hall || "unspecified")}</b> · Seat <b>${esc(x.seat_number || "unspecified")}</b></div>`).join("")}</div></div>`;
          }
          const resHtml = await EM.resultsHtml(reg, d.results_available_without_signin);
          if (resHtml) {
            extraHtml += `<div class="card" style="margin-top:16px"><div class="card-head"><h3>Published Results</h3></div>${resHtml}</div>`;
          }
          extraBox.innerHTML = extraHtml;

          resultsContainer.style.display = "block";
        }
      } catch (err) {
        lastStudent = null;
        lastItems = [];
        if (err.status === 404) {
          emptyTitle.textContent = "Not Allotted / Not Yet Published";
          emptyTitle.className = "state-title";
          emptyDesc.innerHTML = `No examination allotment record was found for Register Number <strong>${esc(reg)}</strong> in currently published records.<br><br>If today or tomorrow is your examination day, the Controller of Examinations notice may not yet be uploaded. Please verify the official notice board.`;
          emptyView.className = "state-box not-allotted";
        } else {
          emptyTitle.textContent = "Notice Board";
          emptyTitle.className = "state-title info-title";
          emptyDesc.innerHTML = `<span style="color:#f87171;font-weight:700;">Could not connect to examination server.</span><br><br>${esc(err.message || "Please check your network connection and try again.")}`;
          emptyView.className = "state-box info-state";
        }
        emptyView.style.display = "block";
      } finally {
        loadingView.style.display = "none";
        searchBtn.disabled = false;
      }
    }

    // Submit handler
    EM.onSubmit(form, async (d) => {
      await executeSearch(d.reg);
    });

    // Clear handler
    if (clearBtn) {
      clearBtn.addEventListener("click", () => {
        regInput.value = "";
        resultsContainer.style.display = "none";
        emptyView.style.display = "none";
        loadingView.style.display = "none";
        try {
          const u = new URL(window.location);
          u.searchParams.delete("reg");
          window.history.replaceState({}, "", u);
        } catch (e) { /* ignore */ }
        regInput.focus();
      });
    }

    // Load active notices & public lists
    loadActiveNotices($("#activeNoticesList", root), $("#activeCountBadge", root));
    publicLists(root);
    if (EM.vsbPublicCard) EM.vsbPublicCard($("#pubVsb", root));

    // Auto-search if ?reg=... is in query string or ctx query
    const urlParams = new URLSearchParams(window.location.search);
    const regParam = (urlParams.get("reg") || (ctx && ctx.query && ctx.query.reg) || "").trim();
    if (regParam) {
      regInput.value = regParam;
      executeSearch(regParam);
    }
  } });
  EM.page({ name: "timetable", title: "Examination timetable", render: async root => {
    root.innerHTML = `<div class="card"><div class="card-head"><h2>Published examination timetable</h2></div><div id="t">${EM.loading()}</div></div>`;
    const exams = await api("/api/exams", { auth: false }); $("#t", root).innerHTML = exams.length ? EM.timetableTable(exams) : EM.empty("No published examinations yet");
  } });
  EM.pageByName = n => EM.pages.find(p => p.name === n);

  // ------------------------------------------------------------ authentication pages
  const authCard = (title, intro, body, foot) => `<section class="card auth-card"><h2>${esc(title)}</h2>${intro ? `<p class="muted small">${intro}</p>` : ""}${body}${foot ? `<p class="small" style="margin-top:16px">${foot}</p>` : ""}</section>`;
  const PW_HINT = "At least 12 characters with letters and digits; not a common password and not containing your username.";
  EM.page({ name: "login", title: "Sign in", render: root => {
    const flash = EM.flash; EM.flash = "";
    root.innerHTML = authCard("Sign in", "Use the account provided by your administrator, or the one you activated after registering.",
      `${flash ? EM.alert(flash, /ended|expired|timed out|sign in/i.test(flash) ? "warn" : "info") : ""}<form id="f" class="stack" style="margin-top:12px">${EM.field({ name: "username", label: "Username", required: true, attrs: 'autocomplete="username" autocapitalize="none" spellcheck="false"' })}${EM.field({ name: "password", label: "Password", type: "password", required: true, attrs: 'autocomplete="current-password"' })}<button class="btn primary" style="width:100%">Sign in</button></form>`,
      `<a href="#/forgot">Forgot password?</a> · <a href="#/register">Student registration</a> · <a href="#/activate">Activate account</a>`);
    EM.onSubmit($("#f", root), async d => {
      const r = await api("/api/auth/login", { method: "POST", body: { username: d.username, password: d.password }, auth: false });
      EM.saveToken(r.access_token); await EM.loadUser();
      const to = EM.after; EM.after = null; EM.go(EM.state.user.pw_change_required ? "/change-password" : (to ? to.replace(/^#/, "") : "/"), true);
    });
    $("#f", root).elements.username.focus();
  } });
  EM.page({ name: "register", title: "Student registration", render: root => {
    root.innerHTML = authCard("Student registration", "Your register number and e-mail must match your student record. An activation link is then sent to that address.",
      `<form id="f" class="stack">${EM.field({ name: "username", label: "Choose a username", required: true, hint: "Letters, digits, dot, dash, underscore (3–40).", attrs: 'autocomplete="username"' })}${EM.field({ name: "register_number", label: "Register number", required: true, attrs: 'inputmode="numeric" autocomplete="off"' })}${EM.field({ name: "email", label: "E-mail on your student record", type: "email", required: true, attrs: 'autocomplete="email"' })}${EM.field({ name: "password", label: "Password", type: "password", required: true, hint: PW_HINT, attrs: 'autocomplete="new-password"' })}<button class="btn primary">Register</button></form><div id="ok"></div>`, `<a href="#/activate">I have an activation token</a> · <a href="#/login">Back to sign in</a>`);
    EM.onSubmit($("#f", root), async (d, f) => { const r = await api("/api/auth/register", { method: "POST", body: d, auth: false }); $("#ok", root).innerHTML = EM.alert(r.detail || "Request received. Check your e-mail for the activation link.", "ok"); f.reset(); });
  } });
  EM.page({ name: "activate", title: "Activate account", render: root => {
    const t = (EM.pending && EM.pending.activate) || ""; EM.pending = null;
    root.innerHTML = authCard("Activate your account", "Paste the activation token from your e-mail (opening the link fills it automatically).", `<form id="f" class="stack">${EM.field({ name: "token", label: "Activation token", required: true, value: t, attrs: 'autocomplete="off"' })}<button class="btn primary">Activate</button></form><div id="ok"></div>`, `<a href="#/login">Back to sign in</a>`);
    EM.onSubmit($("#f", root), async (d, f) => { const r = await api("/api/auth/activate", { method: "POST", body: d, auth: false }); $("#ok", root).innerHTML = EM.alert(r.detail || "Account activated. You can sign in now.", "ok"); f.reset(); });
  } });
  EM.page({ name: "forgot", title: "Forgot password", render: root => {
    root.innerHTML = authCard("Forgot your password?", "Enter your username or e-mail. If an account matches, a reset link is e-mailed. The response is the same either way.", `<form id="f" class="stack">${EM.field({ name: "identifier", label: "Username or e-mail", required: true })}<button class="btn primary">Send reset link</button></form><div id="ok"></div>`, `<a href="#/reset">I have a reset token</a> · <a href="#/login">Back to sign in</a>`);
    EM.onSubmit($("#f", root), async (d, f) => { const r = await api("/api/auth/forgot-password", { method: "POST", body: d, auth: false }); $("#ok", root).innerHTML = EM.alert(r.detail || "Request received.", "ok"); f.reset(); });
  } });
  EM.page({ name: "reset", title: "Reset password", render: root => {
    const t = (EM.pending && EM.pending.reset) || ""; EM.pending = null;
    root.innerHTML = authCard("Choose a new password", "", `<form id="f" class="stack">${EM.field({ name: "token", label: "Reset token", required: true, value: t, attrs: 'autocomplete="off"' })}${EM.field({ name: "new_password", label: "New password", type: "password", required: true, hint: PW_HINT, attrs: 'autocomplete="new-password"' })}<button class="btn primary">Set new password</button></form><div id="ok"></div>`, `<a href="#/login">Back to sign in</a>`);
    EM.onSubmit($("#f", root), async (d, f) => { const r = await api("/api/auth/reset-password", { method: "POST", body: d, auth: false }); $("#ok", root).innerHTML = EM.alert(r.detail || "Password updated. You can sign in now.", "ok"); f.reset(); });
  } });
  EM.page({ name: "change-password", title: "Change password", render: root => {
    const forced = EM.state.user.pw_change_required;
    root.innerHTML = `<section class="card auth-card"><h2>${forced ? "Choose a new password to continue" : "Change password"}</h2>${forced ? EM.alert("Your administrator requires a new password before you can use the system.", "warn") : ""}<p class="muted small">Changing it signs you out of all other devices.</p><form id="f" class="stack">${EM.field({ name: "current_password", label: forced ? "Temporary / current password" : "Current password", type: "password", required: true, attrs: 'autocomplete="current-password"' })}${EM.field({ name: "new_password", label: "New password", type: "password", required: true, hint: PW_HINT, attrs: 'autocomplete="new-password"' })}<button class="btn primary">Change password</button>${forced ? `<button class="btn" type="button" id="so">Sign out instead</button>` : ""}</form></section>`;
    EM.onSubmit($("#f", root), async (d, f) => { const r = await api("/api/auth/change-password", { method: "POST", body: d }); EM.saveToken(r.access_token); await EM.loadUser(); EM.toast(r.detail || "Password changed.", "ok"); EM.go("/", true); });
    const so = $("#so", root); if (so) so.onclick = () => EM.logout();
  } });

  // ------------------------------------------------------------ boot
  async function boot() {
    try { store && (EM.state.token = store.getItem("em_token") || ""); } catch (e) { /* ignore */ }
    const sp = new URLSearchParams(location.search);
    if (sp.get("reset") || sp.get("activate")) {   // tokens from e-mail links: keep them out of history and referrers
      EM.pending = sp.get("reset") ? { reset: sp.get("reset") } : { activate: sp.get("activate") };
      history.replaceState(null, "", location.pathname + (sp.get("reset") ? "#/reset" : "#/activate"));
    }
    try { const c = await fetch("/api/config"); if (c.ok) Object.assign(EM.state.config, await c.json()); } catch (e) { /* offline */ }
    if (EM.state.token) { try { await EM.loadUser(); } catch (e) { EM.saveToken(""); EM.state.user = null; EM.flash = "Your session has ended. Please sign in again."; if (!location.hash || location.hash === "#/") location.hash = "#/login"; } }
    EM.route();
  }
  let booted = false; const once = () => { if (!booted) { booted = true; boot(); } };
  document.addEventListener("DOMContentLoaded", once);
  if (document.readyState !== "loading") once();
})();
