/* VSB Engineering College, Karur - examination hall & seat finder (register number only).
   External file on purpose (the Content-Security-Policy blocks inline scripts). All dynamic text is inserted with
   textContent / createElement, never innerHTML, so nothing from the server can inject markup. */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var REFRESH_MS = 60000, FAST_MS = 5000;
  var lastReg = "", lastSig = "", lastVer = null, fastTimer = null, lastOk = null, inflight = null, timer = null, current = null, showEarlier = false;

  function el(tag, cls, text) { var e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; }
  function show(id, on) { $(id).hidden = !on; }
  function view(name) { ["stateWelcome", "stateLoading", "stateError", "stateEmpty", "results"].forEach(function (i) { show(i, i === name); }); }
  function normalise(raw) { return String(raw || "").replace(/[\s\-_.]+/g, "").toUpperCase(); }
  function fmtDate(iso) { var p = String(iso).split("-"); return p.length === 3 ? p[2] + "-" + p[1] + "-" + p[0] : iso; }
  function fmtTime(iso) {
    if (!iso) return "never";
    var d = new Date(iso); if (isNaN(d)) return iso;
    return d.toLocaleString(undefined, { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
  }
  var STATIC = !!window.STATIC_SITE;     /* GitHub Pages copy: data comes from data/*.json instead of the server API */
  function istToday() { try { return new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" }); } catch (e) { return new Date().toISOString().slice(0, 10); } }
  function staticApi(path, signal) {
    var m = path.match(/^\/api\/public\/lookup\/(.+)$/), url;
    if (path === "/api/public/status") url = "data/status.json";
    else if (path === "/api/public/published") url = "data/published.json";
    else if (m) url = "data/lookup/" + m[1].toUpperCase() + ".json";
    else return Promise.resolve({});                       /* version polling etc.: not needed for a static copy */
    return fetch(url + "?t=" + Math.floor(Date.now() / 60000), { signal: signal }).then(function (r) {
      if (r.status === 404 && m) {
        return { version: null, register_number: decodeURIComponent(m[1]).toUpperCase(), today: istToday(), records: [], warnings: [], status: "no_match",
                 message: "No allotment was found for this register number in the documents published so far. It may not have been published yet; check again later or ask the Controller of Examinations." };
      }
      if (!r.ok) { var err = new Error("HTTP " + r.status); err.status = r.status; throw err; }
      return r.json().then(function (j) { if (m || path === "/api/public/published") j.today = istToday(); return j; });
    });
  }
  function api(path, signal) {
    if (STATIC) return staticApi(path, signal);
    return fetch(path, { headers: { Accept: "application/json" }, signal: signal }).then(function (r) {
      return r.text().then(function (t) {
        var j = null; try { j = JSON.parse(t); } catch (e) { /* not JSON */ }
        if (!r.ok) { var err = new Error((j && j.detail) || ("HTTP " + r.status)); err.status = r.status; err.retry = r.headers.get("Retry-After"); throw err; }
        return j;
      });
    });
  }

  /* ---------- status bar & published sessions ---------- */
  function loadStatus() {
    return api("/api/public/status").then(function (s) {
      var t = STATIC ? "Allotments last updated: " + fmtTime(s.last_success_at) + ". Reload the page to see newer data." : "Official sources checked every " + s.poll_minutes + " min. Last successful check: " + fmtTime(s.last_success_at) + ".";
      if (s.last_scan_status === "failed") t += " The latest check FAILED; showing the last verified data.";
      $("syncText").textContent = t;
      $("syncText").className = s.last_scan_status === "failed" ? "warn" : "";
    }).catch(function () { $("syncText").textContent = "The status service is not reachable right now."; $("syncText").className = "warn"; });
  }
  var MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
  var MONTH_LONG = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function t12(hhmm) {
    var p = String(hhmm).split(":"), h = parseInt(p[0], 10), m = (p[1] || "00").slice(0, 2);
    if (isNaN(h)) return hhmm;
    var hh = h % 12 === 0 ? 12 : h % 12;
    return (hh < 10 ? "0" : "") + hh + ":" + m + (h >= 12 ? " PM" : " AM");
  }
  function timeRange(t) { return t ? String(t).split("-").map(function (x) { return t12(x.trim()); }).join(" \u2013 ") : ""; }
  function timeStart(t) { return t ? t12(String(t).split("-")[0].trim()) : ""; }
  function loadPublished() {
    return api("/api/public/published").then(function (d) {
      var box = $("published"); box.textContent = "";
      var today = d.today || new Date().toISOString().slice(0, 10), days = {}, order = [];
      d.sessions.forEach(function (s) { if (!days[s.date]) { days[s.date] = { date: s.date, weekday: s.weekday, sessions: [], students: 0 }; order.push(s.date); } days[s.date].sessions.push(s); days[s.date].students += s.students; });
      if (!order.length) { box.hidden = false; box.appendChild(el("p", "muted", "No allotment has been published yet. This page checks automatically.")); return; }
      order.sort(); var totalDates = order.length;
      /* show only 2 boxes: today and the next exam day first; if fewer than 2 are current, fill with the most recent past days */
      var soon = order.filter(function (k) { return k >= today; }).slice(0, 2);
      var past = order.filter(function (k) { return k < today; });
      order = past.slice(Math.max(0, past.length - (2 - soon.length))).concat(soon);
      box.hidden = false;
      var head = el("div", "pubhead");
      var ttl = el("div", "pubttl"); ttl.appendChild(el("i", "dot")); ttl.appendChild(document.createTextNode("Live Published Examination Allotments")); head.appendChild(ttl);
      var active = order.filter(function (k) { return k >= today; }).length;
      head.appendChild(el("span", "pill ok", totalDates + " Exam Date" + (totalDates === 1 ? "" : "s") + " Published" + (active ? " \u00b7 " + active + " Active" : ""))); box.appendChild(head);
      var grid = el("div", "pubgrid");
      order.forEach(function (k) {
        var g = days[k], p = k.split("-"), c = el("div", "pubday");
        var cal = el("div", "cal"); cal.appendChild(el("span", "mon", MON[+p[1] - 1])); cal.appendChild(el("b", null, p[2])); c.appendChild(cal);
        var info = el("div", "pubinfo");
        info.appendChild(el("div", "pubdate", g.weekday + ", " + (+p[2]) + " " + MONTH_LONG[+p[1] - 1] + " " + p[0]));
        var pills = el("div", "pills");
        g.sessions.slice().sort(function (a, b) { return a.session < b.session ? 1 : -1; }).forEach(function (s) {
          pills.appendChild(el("span", "pill " + s.session.toLowerCase(), s.session + (s.session_time ? " \u00b7 " + timeStart(s.session_time) : "")));
        });
        var st = k === today ? ["now", "\u25cf Active now"] : k > today ? ["soon", "Upcoming"] : ["done", "Completed"];
        pills.appendChild(el("span", "stat " + st[0], st[1]));
        info.appendChild(pills);
        info.appendChild(el("div", "fine", "(" + g.students.toLocaleString() + " allotments)"));
        c.appendChild(info); grid.appendChild(c);
      });
      box.appendChild(grid);
      var foot = el("div", "pubfoot"); foot.appendChild(el("span", null, "\u26a1 Synchronized with Controller of Examinations notice board")); foot.appendChild(el("span", null, "Enter your register number below to view hall & seat")); box.appendChild(foot);
    }).catch(function () { /* the panel is optional */ });
  }

  /* ---------- search ---------- */
  function setUrl(reg, push) { try { var u = new URL(location.href); u.searchParams.set("reg", reg); history[push ? "pushState" : "replaceState"](null, "", u.toString()); } catch (e) { /* ignore */ } }
  function banner(kind, text) { var b = $("banner"); if (!text) { b.hidden = true; return; } b.hidden = false; b.className = "banner " + kind; b.textContent = text; }

  function search(raw, opts) {
    opts = opts || {};
    var reg = normalise(raw);
    $("regMsg").textContent = "";
    if (!/^[A-Z0-9]{6,20}$/.test(reg)) { $("regMsg").textContent = "Enter your register number (6-20 letters or digits)."; $("regInput").setAttribute("aria-invalid", "true"); return; }
    $("regInput").value = reg; if (reg !== lastReg) showEarlier = false; lastReg = reg;
    if (!opts.silent) { view("stateLoading"); banner(null); }
    if (inflight) inflight.abort();
    var ctl = (typeof AbortController === "function") ? new AbortController() : null; inflight = ctl;
    $("searchBtn").disabled = true;
    api("/api/public/lookup/" + encodeURIComponent(reg), ctl && ctl.signal).then(function (d) {
      lastOk = new Date().toISOString(); lastVer = d.version || null;
      if (!opts.noUrl) setUrl(reg, opts.push);
      apply(d, opts.silent);
      $("refreshBtn").hidden = false;
      schedule();
    }).catch(function (e) {
      if (e && e.name === "AbortError") return;
      if (opts.silent && current) { banner("warn", "Could not refresh at " + fmtTime(new Date().toISOString()) + ". Showing the last verified results."); return; }
      if (e.status === 422) { view("stateWelcome"); $("regMsg").textContent = "That does not look like a valid register number."; return; }
      if (e.status === 429) { fail("Too many searches", "Please wait a moment" + (e.retry ? " (" + e.retry + " s)" : "") + " and try again."); return; }
      fail("Could not reach the server", "Check your connection and try again.");
    }).then(function () { $("searchBtn").disabled = false; if (inflight === ctl) inflight = null; });
  }
  function fail(t, m) { $("errTitle").textContent = t; $("errText").textContent = m; view("stateError"); }

  function signature(d) { return (d.today || "") + "|" + d.status + "|" + d.records.map(function (r) { return [r.id, r.revision, r.status, r.hall, r.seat, r.last_verified_at].join(","); }).join(";"); }

  function apply(d, silent) {
    var sig = signature(d), changed = sig !== lastSig;
    var hadRevised = current && d.records.some(function (r) { return r.revised && !current.records.some(function (o) { return o.id === r.id; }); });
    current = d; lastSig = sig;
    loadStatus();
    if (silent && !changed) { banner(d.warnings.length ? "warn" : null, d.warnings[0]); return; }   // nothing new: do not touch the page
    if (!d.records.length) {
      var titles = { no_match: "No matching record", not_yet_published: "Not yet published", processing: "Processing in progress", source_unavailable: "Official website temporarily unavailable" };
      $("emptyTitle").textContent = titles[d.status] || "No record";
      $("emptyText").textContent = d.message;
      view("stateEmpty"); banner(null); return;
    }
    $("resReg").textContent = d.register_number;
    var vis = render(d);
    $("resCount").textContent = vis.length + " CURRENT EXAM" + (vis.length === 1 ? "" : "S");
    view("results");
    var st = vis.some(function (r) { return r.status === "CONFLICT"; }) ? "conflict" : vis.some(function (r) { return r.status === "MANUAL_REVIEW"; }) ? "manual_verification" : "found";
    var msg = { found: vis.length + " examination record(s) shown.",
                conflict: "A record has conflicting information in the official documents. Check the original pages shown below.",
                manual_verification: "A record needs manual verification. Use the original page shown below." }[st];
    var text = msg + (d.warnings.length ? " " + d.warnings.join(" ") : "") + (hadRevised ? " A revised allotment was detected." : "");
    banner(d.warnings.length && st === "found" ? "warn" : { found: "ok", conflict: "bad", manual_verification: "warn" }[st], text);
  }

  /* ---------- which exams to show ----------
     Upcoming (today or later)  -> show those only.
     Nothing upcoming           -> show only the latest previous exam day, with a button for anything earlier. */
  function sortRecs(a, b) { return a.date < b.date ? -1 : a.date > b.date ? 1 : (a.session < b.session ? -1 : a.session > b.session ? 1 : 0); }
  function addDays(iso, n) { var p = iso.split("-"), t = new Date(Date.UTC(+p[0], +p[1] - 1, +p[2] + n)); return t.toISOString().slice(0, 10); }
  function render(d) {
    var today = d.today || new Date().toISOString().slice(0, 10);
    var all = d.records.slice().sort(sortRecs);
    var upcoming = all.filter(function (r) { return r.date >= today; });
    var past = all.filter(function (r) { return r.date < today; });
    var shown, note = "", earlierBtn = 0;
    if (upcoming.length) { shown = upcoming; }
    else {
      var latest = past[past.length - 1].date;
      var latestRecs = past.filter(function (r) { return r.date === latest; });
      var older = past.filter(function (r) { return r.date !== latest; });
      note = "No upcoming exam is published for you right now. Showing your latest previous exam (" + fmtDate(latest) + ").";
      shown = showEarlier ? latestRecs.concat(older.slice().reverse()) : latestRecs;
      earlierBtn = older.length;
    }
    var cards = $("cards"); cards.textContent = ""; clearInterval(cdTimer);
    if (upcoming.length) cards.appendChild(countdownBox(upcoming[0], today));
    if (note) cards.appendChild(el("p", "note pastnote", note));
    var lastDay = null, isPast = !upcoming.length;
    shown.forEach(function (r) {
      if (r.date !== lastDay) {
        lastDay = r.date;
        var h = el("h3", "dayhead", fmtDate(r.date) + " \u00b7 " + r.weekday);
        var tag = r.date === today ? "Today" : r.date === addDays(today, 1) ? "Tomorrow" : r.date < today ? "Completed" : "";
        if (tag) h.appendChild(el("span", "daytag " + tag.toLowerCase(), tag));
        cards.appendChild(h);
      }
      var c = card(r); if (r.date < today) c.classList.add("past"); cards.appendChild(c);
    });
    if (earlierBtn) {
      var b = el("button", "btn", showEarlier ? "Hide earlier exams" : "Show earlier exams (" + earlierBtn + ")"); b.type = "button";
      b.addEventListener("click", function () { showEarlier = !showEarlier; render(current); });
      cards.appendChild(b);
    }
    return shown;
  }

  /* ---------- cards ---------- */
  function field(label, value, cls) { var d = el("div", "f " + (cls || "")); d.appendChild(el("span", "k", label)); d.appendChild(el("span", "v", value)); return d; }

  /* ---------- themes ---------- */
  var THEMES = [["aurora", "Aurora", "linear-gradient(135deg,#7c5cff,#13c7b4)"], ["danger", "Danger red", "linear-gradient(135deg,#ff1f3d,#ff7a18)"], ["neon", "Neon", "linear-gradient(135deg,#00e5ff,#ff2bd6)"], ["emerald", "Emerald", "linear-gradient(135deg,#19d38a,#d9ff3d)"], ["sunset", "Sunset", "linear-gradient(135deg,#ff6a3d,#e0307b)"]];
  function setTheme(name, save) {
    document.documentElement.setAttribute("data-theme", name);
    [].forEach.call(document.querySelectorAll(".sw"), function (b) { b.setAttribute("aria-pressed", String(b.dataset.t === name)); });
    if (save) { try { localStorage.setItem("examTheme", name); } catch (e) { /* storage may be blocked */ } }
  }
  function initThemes() {
    var box = $("themes"); if (!box) return;
    THEMES.forEach(function (t) {
      var b = el("button", "sw"); b.type = "button"; b.dataset.t = t[0]; b.title = t[1]; b.setAttribute("aria-label", t[1] + " theme"); b.style.background = t[2];
      b.addEventListener("click", function () { setTheme(t[0], true); }); box.appendChild(b);
    });
    var saved = null; try { saved = localStorage.getItem("examTheme"); } catch (e) { /* ignore */ }
    setTheme(THEMES.some(function (t) { return t[0] === saved; }) ? saved : "aurora", false);
  }
  function toast(msg) { var t = el("div", "toast", msg); t.setAttribute("role", "status"); document.body.appendChild(t); setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 2200); }
  function copyText(txt, ok) {
    function fb() { var a = el("textarea"); a.value = txt; a.style.position = "fixed"; a.style.opacity = "0"; document.body.appendChild(a); a.select(); try { document.execCommand("copy"); toast(ok); } catch (e) { toast("Could not copy"); } document.body.removeChild(a); }
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(txt).then(function () { toast(ok); }, fb); else fb();
  }

  /* ---------- countdown ---------- */
  var cdTimer = null;
  function startOf(r) {
    var p = r.date.split("-"), t = r.session_time ? String(r.session_time).split("-")[0].trim().split(":") : null;
    return t ? new Date(+p[0], +p[1] - 1, +p[2], +t[0], +(t[1] || 0)) : null;
  }
  function countdownBox(r, today) {
    var box = el("div", "countdown"), left = el("div");
    left.appendChild(el("div", "cdk", "Next exam"));
    left.appendChild(el("div", "cdn", (r.subject_code ? r.subject_code + " \u00b7 " : "") + fmtDate(r.date) + " " + r.session));
    box.appendChild(left);
    var start = startOf(r), grid = el("div", "cdt"); box.appendChild(grid);
    function tick() {
      var ms, label;
      if (start) { ms = start - new Date(); }
      else { var p = r.date.split("-"); ms = new Date(+p[0], +p[1] - 1, +p[2]) - new Date(); }
      if (r.date === today && (!start || ms <= 0)) { grid.textContent = ""; grid.appendChild(el("b", "cdn", start ? "Exam in progress / started" : "EXAM TODAY")); box.className = "countdown urgent"; return; }
      if (ms < 0) ms = 0;
      var d = Math.floor(ms / 864e5), h = Math.floor(ms % 864e5 / 36e5), m = Math.floor(ms % 36e5 / 6e4), sc = Math.floor(ms % 6e4 / 1e3);
      box.className = "countdown" + (ms < 864e5 ? " urgent" : ms < 3 * 864e5 ? " soon" : "");
      grid.textContent = "";
      (start ? [[d, "days"], [h, "hrs"], [m, "min"], [sc, "sec"]] : [[d, "days"]]).forEach(function (x) { var c = el("div"); c.appendChild(el("b", null, String(x[0]).padStart(2, "0"))); c.appendChild(el("span", null, x[1])); grid.appendChild(c); });
    }
    tick(); if (start) { clearInterval(cdTimer); cdTimer = setInterval(tick, 1000); }
    return box;
  }

  /* ---------- per-card actions ---------- */
  function ymd(iso) { return iso.replace(/-/g, ""); }
  function icsFor(r) {
    var st = r.session_time ? String(r.session_time).split("-") : null, L = [], uid = "exam-" + r.register_number + "-" + r.date + r.session + "@exam-monitor";
    var title = "Exam: " + (r.subject_code ? r.subject_code + " " : "") + (r.subject_name || "");
    var desc = "Hall: " + (r.hall || "not confirmed") + "\\nSeat: " + (r.seat || "not confirmed") + "\\nCheck the official notice before travelling.";
    L.push("BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Exam Monitor//EN", "BEGIN:VEVENT", "UID:" + uid, "DTSTAMP:" + new Date().toISOString().replace(/[-:]/g, "").slice(0, 15) + "Z");
    if (st) { var a = st[0].trim().replace(":", "") + "00", b = (st[1] ? st[1].trim().replace(":", "") : String(+st[0].split(":")[0] + 3) + st[0].split(":")[1]) + "00"; L.push("DTSTART:" + ymd(r.date) + "T" + a.padStart(6, "0"), "DTEND:" + ymd(r.date) + "T" + b.padStart(6, "0")); }
    else { var p = r.date.split("-"), n = new Date(Date.UTC(+p[0], +p[1] - 1, +p[2] + 1)).toISOString().slice(0, 10); L.push("DTSTART;VALUE=DATE:" + ymd(r.date), "DTEND;VALUE=DATE:" + ymd(n)); }
    L.push("SUMMARY:" + title.replace(/[,;]/g, " "), "LOCATION:" + (r.hall || ""), "DESCRIPTION:" + desc, "END:VEVENT", "END:VCALENDAR");
    return L.join("\r\n");
  }
  function actions(r) {
    var row = el("div", "cactions");
    var cal = el("button", "btn small", "\ud83d\udcc5 Add to calendar"); cal.type = "button";
    cal.addEventListener("click", function () {
      var blob = new Blob([icsFor(r)], { type: "text/calendar" }), a = el("a"); a.href = URL.createObjectURL(blob); a.download = "exam-" + r.date + "-" + r.session + ".ics";
      document.body.appendChild(a); a.click(); document.body.removeChild(a); setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
    });
    row.appendChild(cal);
    if (r.hall && r.seat) {
      var cp = el("button", "btn small", "\ud83d\udccb Copy hall & seat"); cp.type = "button";
      cp.addEventListener("click", function () { copyText(fmtDate(r.date) + " " + r.session + " - Hall " + r.hall + ", Seat " + r.seat, "Hall and seat copied"); }); row.appendChild(cp);
    }
    var sh = el("button", "btn small", "\ud83d\udd17 Share link"); sh.type = "button";
    sh.addEventListener("click", function () {
      var url = location.origin + location.pathname + "?reg=" + encodeURIComponent(r.register_number);
      if (navigator.share) navigator.share({ title: "Exam Allotment Portal", url: url }).catch(function () {}); else copyText(url, "Link copied");
    }); row.appendChild(sh);
    return row;
  }

  function card(r) {
    var c = el("article", "card rec s-" + r.status.toLowerCase());
    var head = el("header", "rhead");
    var left = el("div");
    left.appendChild(el("div", "date", fmtDate(r.date) + " \u00b7 " + r.weekday));
    var pills = el("div", "pills");
    pills.appendChild(el("span", "pill " + r.session.toLowerCase(), r.session === "AN" ? "AN \u00b7 Afternoon" : "FN \u00b7 Forenoon"));
    if (r.session_time) { var t = el("span", "pill ghost", timeRange(r.session_time)); t.title = r.session_time_note || ""; pills.appendChild(t); }
    pills.appendChild(el("span", "badge b-" + r.status.toLowerCase(), r.status_label));
    if (r.revised) pills.appendChild(el("span", "badge b-revised", "Revised allotment"));
    left.appendChild(pills);
    head.appendChild(left); c.appendChild(head);

    c.appendChild(el("div", "subject", (r.subject_code ? r.subject_code + " \u2014 " : "") + (r.subject_name || "Subject not read from the PDF")));
    var meta = [r.programme && ("Programme: " + r.programme), r.department && ("Department: " + r.department)].filter(Boolean).join("   \u00b7   ");
    if (meta) c.appendChild(el("div", "meta", meta));

    var big = el("div", "big");
    var hallBox = el("div", "bigbox"); hallBox.appendChild(el("span", "k", "Hall"));
    hallBox.appendChild(el("span", "bv" + (r.hall ? "" : " na"), r.hall || (r.unverified ? "Needs verification" : "\u2014")));
    var seatBox = el("div", "bigbox"); seatBox.appendChild(el("span", "k", "Seat"));
    seatBox.appendChild(el("span", "bv" + (r.seat ? "" : " na"), r.seat || (r.status === "HALL_ONLY" ? "Not published yet" : (r.unverified ? "Needs verification" : "\u2014"))));
    big.appendChild(hallBox); big.appendChild(seatBox); c.appendChild(big);
    if (r.seat_note) c.appendChild(el("p", "note", r.seat_note + " Individual seating has not been verified, so no seat is shown."));

    if (r.unverified) {
      var u = el("div", "unv"); u.appendChild(el("b", null, "Unverified reading of the PDF text (do not rely on it): "));
      u.appendChild(document.createTextNode(Object.keys(r.unverified).filter(function (k) { return r.unverified[k]; }).map(function (k) { return k.replace(/_/g, " ") + " = " + r.unverified[k]; }).join(", ") || "nothing readable"));
      u.appendChild(document.createTextNode(". Check the original page below."));
      c.appendChild(u);
      (r.review_reasons || []).forEach(function (t) { c.appendChild(el("p", "note", "Why: " + t)); });
    }
    (r.notes || []).forEach(function (n) { c.appendChild(el("p", "note", n)); });

    c.appendChild(locationBlock(r));
    c.appendChild(evidence(r));
    c.appendChild(actions(r));
    var foot = el("p", "fine", "Last verified " + fmtTime(r.last_verified_at) + (r.revision > 1 ? " \u00b7 revision " + r.revision : ""));
    c.appendChild(foot);
    return c;
  }

  function locationBlock(r) {
    var box = el("div", "loc");
    box.appendChild(el("h4", null, "Where is my hall?"));
    var l = r.location;
    if (!l) { box.appendChild(el("p", "muted", r.location_message || (r.hall ? "Building/floor location has not yet been verified." : "The hall is not confirmed yet."))); return box; }
    var grid = el("div", "fgrid");
    [["building", "Building"], ["block", "Block"], ["floor", "Floor"], ["room", "Room"]].forEach(function (k) { if (l[k[0]]) grid.appendChild(field(k[1], l[k[0]])); });
    box.appendChild(grid);
    if (l.directions) box.appendChild(el("p", "dir", l.directions));
    if (l.map) box.appendChild(mapSvg(l.map));
    if (l.source) box.appendChild(el("p", "fine", "Source: " + l.source));
    return box;
  }
  function mapSvg(m) {
    var NS = "http://www.w3.org/2000/svg", W = 320, H = 170, P = 26;
    var pts = [{ lat: m.latitude, lon: m.longitude, label: m.label || "Hall", dest: true }];
    if (m.entrance) pts.unshift({ lat: m.entrance.latitude, lon: m.entrance.longitude, label: m.entrance.name, dest: false });
    var lats = pts.map(function (p) { return p.lat; }), lons = pts.map(function (p) { return p.lon; });
    var minLa = Math.min.apply(null, lats), maxLa = Math.max.apply(null, lats), minLo = Math.min.apply(null, lons), maxLo = Math.max.apply(null, lons);
    var coslat = Math.cos(minLa * Math.PI / 180), dx = Math.max((maxLo - minLo) * coslat, 1e-9), dy = Math.max(maxLa - minLa, 1e-9);
    var sc = pts.length > 1 ? Math.min((W - 2 * P) / dx, (H - 2 * P) / dy) : 1;
    function pos(p) { return pts.length > 1 ? [P + ((p.lon - minLo) * coslat) * sc, H - P - (p.lat - minLa) * sc] : [W / 2, H / 2]; }
    var s = document.createElementNS(NS, "svg"); s.setAttribute("viewBox", "0 0 " + W + " " + H); s.setAttribute("class", "map"); s.setAttribute("role", "img");
    s.setAttribute("aria-label", "Schematic campus position of the hall" + (m.entrance ? " relative to " + m.entrance.name : ""));
    var bg = document.createElementNS(NS, "rect"); bg.setAttribute("width", W); bg.setAttribute("height", H); bg.setAttribute("rx", 10); bg.setAttribute("class", "mbg"); s.appendChild(bg);
    if (pts.length > 1) { var a = pos(pts[0]), b = pos(pts[1]); var ln = document.createElementNS(NS, "line"); ln.setAttribute("x1", a[0]); ln.setAttribute("y1", a[1]); ln.setAttribute("x2", b[0]); ln.setAttribute("y2", b[1]); ln.setAttribute("class", "mline"); s.appendChild(ln); }
    pts.forEach(function (p) {
      var q = pos(p), c = document.createElementNS(NS, "circle"); c.setAttribute("cx", q[0]); c.setAttribute("cy", q[1]); c.setAttribute("r", p.dest ? 9 : 6); c.setAttribute("class", p.dest ? "mdest" : "ment"); s.appendChild(c);
      var t = document.createElementNS(NS, "text"); t.setAttribute("x", Math.min(Math.max(q[0], 40), W - 40)); t.setAttribute("y", q[1] + (p.dest ? -14 : 20)); t.setAttribute("text-anchor", "middle"); t.setAttribute("class", "mtxt"); t.textContent = (p.dest ? "Hall " : "") + p.label; s.appendChild(t);
    });
    var w = el("div", "mapwrap"); w.appendChild(s);
    w.appendChild(el("p", "fine", "Schematic position from administrator-verified coordinates (not to scale)."));
    var link = el("a", null, "Open in OpenStreetMap"); link.href = m.osm_url; link.target = "_blank"; link.rel = "noopener noreferrer"; w.appendChild(link);
    return w;
  }

  /* The static copy ships one plain image per page; the searched number is highlighted here, in the browser. */
  function hlLayer(s) {
    var layer = el("div", "hlbox"); layer.setAttribute("aria-hidden", "true");
    (s.highlights || []).forEach(function (b) { var d = el("div", "hl"); d.style.left = b[0] * 100 + "%"; d.style.top = b[1] * 100 + "%"; d.style.width = b[2] * 100 + "%"; d.style.height = b[3] * 100 + "%"; layer.appendChild(d); });
    return layer;
  }
  function evidence(r) {
    var box = el("div", "evid");
    var all = r.sources || [];
    var seatOnly = all.filter(function (s) { return s.kind === "seat"; });
    var list;
    if (r.status === "CONFLICT") list = all;                       /* documents disagree: show both pages, each labelled for what it is */
    else list = seatOnly.length ? seatOnly : all.slice(0, 1);      /* hall-list pages are hidden; used only when no seat page exists */
    var kinds = list.map(function (s) { return s.kind; });
    var title = kinds.length === 1 ? (kinds[0] === "seat" ? "Seat allotment page" : "Hall allotment page (seat sheet not available)") : "Source pages";
    box.appendChild(el("h4", null, title));
    if (!list.length) { box.appendChild(el("p", "muted", "No source page is available for this record.")); return box; }
    list.forEach(function (s) {
      var what = s.kind === "seat" ? "Seat allotment" : "Hall allotment";
      var sec = el("div", "src");
      var bar = el("div", "srcbar");
      bar.appendChild(el("b", null, (list.length > 1 ? what + " \u00b7 " : "") + "Page " + s.page + (s.page_count ? " of " + s.page_count : "")));
      var zoom = el("button", "btn small primary", "Zoom"); zoom.type = "button"; zoom.addEventListener("click", function () { openViewer(r, s); });
      bar.appendChild(zoom);
      if (s.official_url) { var a = el("a", "btn small", "Official PDF"); a.href = s.official_url; a.target = "_blank"; a.rel = "noopener noreferrer"; bar.appendChild(a); }
      sec.appendChild(bar);
      var img = el("img", "pg"); img.loading = "lazy"; img.alt = what + " page " + s.page + " with your register number highlighted";
      img.src = s.image_url;
      img.addEventListener("click", function () { openViewer(r, s); });
      img.addEventListener("error", function () { var m = el("p", "muted", "The page image could not be loaded. Use the official PDF link."); if (img.parentNode) img.parentNode.replaceChild(m, img); });
      var wrapEl = el("div", "pgwrap"); wrapEl.appendChild(img); wrapEl.appendChild(hlLayer(s)); sec.appendChild(wrapEl);
      box.appendChild(sec);
    });
    return box;
  }

  /* ---------- full-page viewer with zoom ---------- */
  var zoom = 100, vSrc = null;
  function setZoom(z) { zoom = Math.max(25, Math.min(400, z)); $("vWrap").style.width = zoom + "%"; $("vZoom").textContent = zoom + "%"; }
  function vUrl() { return $("vHl").checked ? vSrc.image_url : vSrc.plain_image_url; }
  function openViewer(r, s) {
    vSrc = s; var oldL = $("vWrap").querySelector(".hlbox"); if (oldL) oldL.parentNode.replaceChild(hlLayer(s), oldL); else $("vWrap").appendChild(hlLayer(s));
    $("vTitle").textContent = s.label + " \u00b7 page " + s.page; $("vHl").checked = true;
    $("vImg").src = vUrl(); $("vDown").href = vUrl(); $("vDown").download = "page-" + s.kind + "-" + s.page + (STATIC ? ".jpg" : ".png");
    var p = $("vPdf"); if (s.official_url) { p.href = s.official_url; p.hidden = false; } else { p.hidden = true; }
    setZoom(100); $("viewer").hidden = false; document.body.classList.add("noscroll"); $("vClose").focus();
  }
  function closeViewer() { $("viewer").hidden = true; document.body.classList.remove("noscroll"); }
  $("vClose").addEventListener("click", closeViewer);
  $("vIn").addEventListener("click", function () { setZoom(zoom + 25); });
  $("vOut").addEventListener("click", function () { setZoom(zoom - 25); });
  $("vFit").addEventListener("click", function () { setZoom(100); });
  $("vHl").addEventListener("change", function () { $("vImg").src = vUrl(); $("vDown").href = vUrl(); var L = $("vWrap").querySelector(".hlbox"); if (L) L.style.display = $("vHl").checked ? "" : "none"; });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !$("viewer").hidden) closeViewer(); });

  /* ---------- automatic refresh (never overlapping, never while hidden, never wipes good results on error) ---------- */
  function schedule() { if (timer) clearTimeout(timer); timer = setTimeout(tick, REFRESH_MS); }
  function tick() {
    if (!lastReg) return;
    if (document.hidden || inflight) { schedule(); return; }
    search(lastReg, { silent: true, noUrl: true });
  }
  /* light change check every FAST_MS: only a tiny version token is fetched; the full lookup runs when it changes */
  function fastTick() {
    fastTimer = setTimeout(fastTick, FAST_MS);
    if (!lastReg || !lastVer || document.hidden || inflight) return;
    api("/api/public/version/" + encodeURIComponent(lastReg)).then(function (v) {
      if (v && v.version && v.version !== lastVer && lastReg && !inflight) search(lastReg, { silent: true, noUrl: true });
    }).catch(function () { /* ignore: the 60 s full refresh still runs */ });
  }
  fastTimer = setTimeout(fastTick, FAST_MS);
  document.addEventListener("visibilitychange", function () { if (!document.hidden && lastReg && lastOk && Date.now() - new Date(lastOk).getTime() > REFRESH_MS) tick(); });

  /* ---------- wiring ---------- */
  $("searchForm").addEventListener("submit", function (e) { e.preventDefault(); lastSig = ""; search($("regInput").value, { push: true }); });
  /* Search by itself: no button press needed. Fires ~0.35 s after typing/pasting stops once the number is complete (12+ characters). */
  var autoTimer = null, AUTO_LEN = 12;
  $("regInput").addEventListener("input", function () {
    $("regMsg").textContent = ""; this.removeAttribute("aria-invalid");
    if (autoTimer) clearTimeout(autoTimer);
    var reg = normalise(this.value);
    if (!reg) { lastReg = ""; lastSig = ""; current = null; view("stateWelcome"); banner(null); return; }
    if (reg.length < AUTO_LEN || reg === lastReg) return;
    autoTimer = setTimeout(function () { lastSig = ""; search(reg, { push: false }); }, 350);
  });
  $("retryBtn").addEventListener("click", function () { search(lastReg || $("regInput").value, { noUrl: true }); });
  $("refreshBtn").addEventListener("click", function () { lastSig = ""; search(lastReg, { silent: true, noUrl: true }); loadPublished(); });
  $("slipBtn").addEventListener("click", function () { if (!lastReg) return; if (STATIC) window.print(); else window.open("/api/public/slip/" + encodeURIComponent(lastReg) + "?print=1", "_blank", "noopener"); });
  window.addEventListener("popstate", function () { var q = new URL(location.href).searchParams.get("reg"); if (q) search(q, { noUrl: true }); else { view("stateWelcome"); banner(null); } });

  initThemes(); loadStatus(); loadPublished();
  var initial = new URL(location.href).searchParams.get("reg");
  if (initial) search(initial, { noUrl: true });
  setInterval(function () { loadPublished(); if (!lastReg) loadStatus(); }, REFRESH_MS * 2);
})();
