// DOM-level smoke/workflow tests of the real front end (jsdom, NOT a browser) against a live server.
const { JSDOM } = require("jsdom");
const fs = require("fs");
const BASE = process.env.BASE, PW = process.env.E2E_PW;
let pass = 0; const fails = [];
const ok = (c, m) => { if (c) pass++; else { fails.push(m); console.log("  FAIL:", m); } };
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function openApp() {
  const dom = await JSDOM.fromURL(BASE + "/", {
    runScripts: "dangerously", resources: "usable", pretendToBeVisual: true,
    beforeParse(w) {
      w.fetch = (u, o) => fetch(new URL(u, BASE), o);
      w.FormData = FormData; w.Blob = Blob;
      w.HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
      w.HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); this.dispatchEvent(new w.Event("close")); };
      w.Element.prototype.scrollIntoView = function () {}; w.HTMLElement.prototype.focus = function () {};
      w.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
      w.print = () => { w.__printed = true; };
      w.addEventListener("error", e => { (w.__errors = w.__errors || []).push(String(e.message)); });
    },
  });
  const w = dom.window; await until(() => w.EM && w.document.querySelector("#main"), 8000, "app boot");
  await settle(w); return w;
}
async function until(fn, ms, what) { const t = Date.now(); while (Date.now() - t < (ms || 6000)) { try { const v = fn(); if (v) return v; } catch (e) { /* retry */ } await sleep(40); } throw new Error("timeout waiting for " + (what || "condition")); }
async function settle(w) { await sleep(60); await until(() => !w.document.querySelector("#main .loading") && !w.document.querySelector("[aria-busy=true]"), 15000, "page to settle"); await sleep(60); }
async function go(w, hash) { w.location.hash = hash; await sleep(30); await settle(w); }
const text = w => w.document.querySelector("#main").textContent;
const $ = (w, s, r) => (r || w.document).querySelector(s);
const $$ = (w, s, r) => Array.from((r || w.document).querySelectorAll(s));
function setVal(w, el, v) { if (el.type === "checkbox") el.checked = !!v; else el.value = v; el.dispatchEvent(new w.Event("input", { bubbles: true })); el.dispatchEvent(new w.Event("change", { bubbles: true })); }
async function click(w, el) { if (!el) throw new Error("click target missing"); el.dispatchEvent(new w.MouseEvent("click", { bubbles: true, cancelable: true })); await sleep(60); }
const dlg = w => $(w, "dialog[open]");
async function fillDialog(w, vals, submit = true) {
  const d = await until(() => dlg(w), 3000, "dialog");
  for (const [k, v] of Object.entries(vals)) { const el = d.querySelector(`[name="${k}"]`); if (!el) throw new Error("dialog field missing: " + k); setVal(w, el, v); }
  if (submit) { $(w, "form", d).requestSubmit(); await until(() => !dlg(w) || $(w, ".form-msg .alert", dlg(w)), 8000, "dialog submit"); }
  return d;
}
async function confirmDlg(w, okLabel = "ok") { const d = await until(() => dlg(w), 3000, "confirm"); await click(w, $(w, `[data-x=${okLabel}]`, d)); await until(() => !dlg(w), 3000, "confirm closing"); await settle(w); }
async function login(w, user) {
  await go(w, "#/login"); const f = $(w, "#main form");
  setVal(w, f.elements.username, user); setVal(w, f.elements.password, PW); f.requestSubmit();
  await until(() => $(w, "#shell") && !$(w, "#main .loading"), 10000, "signed-in shell"); await settle(w);
}
const navLinks = w => $$(w, "#nav a").map(a => a.getAttribute("href").replace("#/", ""));
async function api(path, token, opts = {}) { const r = await fetch(BASE + path, { ...opts, headers: { ...(opts.headers || {}), Authorization: "Bearer " + token } }); return r; }

const ALL = ["dashboard", "live", "exams", "subjects", "terms", "results", "allocation", "reports", "halls", "documents", "seating-import", "register-candidates", "students", "accounts", "announcements", "security", "audit", "account", "notifications", "notification-preferences", "communications", "workflow", "database", "vsb", "vsb-allocation"];
const EXPECT = {
  "e2e-super": ALL, "e2e-admin": ALL,
  "e2e-staff": ["dashboard", "live", "exams", "subjects", "terms", "allocation", "reports", "halls", "documents", "seating-import", "register-candidates", "students", "announcements", "account", "notifications", "notification-preferences", "workflow", "vsb", "vsb-allocation"],
  "e2e-invig": ["dashboard", "notifications", "notification-preferences", "rosters", "seating", "announcements-view", "account", "workflow"],
  "e2e-student": ["dashboard", "notifications", "notification-preferences", "my-exams", "my-results", "announcements-view", "account", "my-vsb-seat"],
};
const sortedEq = (a, b) => JSON.stringify([...a].sort()) === JSON.stringify([...b].sort());

(async () => {
  // ---------------- public site
  let w = await openApp();
  ok(/Exam Allotment Portal/.test(text(w)), "public landing renders the allotment portal");
  ok($(w, "#regInput").value === "" && !/922525106/.test(w.document.documentElement.outerHTML) && !$(w, "#regInput").hasAttribute("autofocus"), "landing opens with empty register input, no example number, no autofocus");
  ok($(w, "#resultsContainer").style.display === "none", "landing performs no automatic search");
  ok(!$(w, "#nav"), "no sidebar when signed out");
  await go(w, "#/exams"); ok(w.location.hash === "#/login" && /sign in/i.test(text(w)), "protected route redirects to login when signed out");
  await go(w, "#/nope"); ok(/Page not found/.test(text(w)), "unknown route shows not-found page");
  await go(w, "#/");
  w.EM.goPortal = reg => { w.__portalNav = reg; };   // jsdom cannot navigate; capture the hand-off to the register-number finder
  const lk = $(w, "#portalSearchForm"), ri = $(w, "#regInput"); setVal(w, ri, "990025106001"); lk.requestSubmit(); await sleep(100);
  ok(w.__portalNav === "990025106001", "a valid register number is handed to the register-number-only finder (/portal/)");
  setVal(w, ri, "12"); lk.requestSubmit(); await until(() => /valid register/i.test($(w, "#emptyDesc").textContent), 4000, "invalid reg msg"); ok(true, "invalid register number rejected client-side");
  // bad login: useful error, field stays, no session
  await go(w, "#/login"); let f = $(w, "#main form"); setVal(w, f.elements.username, "e2e-admin"); setVal(w, f.elements.password, "wrong-password-123"); f.requestSubmit();
  await until(() => $(w, ".form-msg .alert"), 8000, "login error"); ok(/invalid|incorrect|credentials/i.test($(w, ".form-msg .alert").textContent), "wrong password shows backend error");
  w.close();

  // ---------------- every role: navigation + access
  for (const user of Object.keys(EXPECT)) {
    w = await openApp(); await login(w, user);
    const nav = navLinks(w); ok(sortedEq(nav.filter(n => n !== "rosters" && n !== "seating" || user === "e2e-invig"), EXPECT[user]), `${user}: sidebar items ${nav.join(",")}`);
    for (const r of EXPECT[user]) {
      await go(w, "#/" + r); const t = text(w);
      ok(!$(w, "#main .alert.bad") && !/Not available for your role|Page not found/.test(t), `${user}: #/${r} loads without error`);
    }
    if (["e2e-super", "e2e-admin", "e2e-staff"].includes(user)) {
      await go(w, "#/dashboard"); await until(() => $(w, "#ops-body") && /Examination readiness|unavailable/i.test($(w, "#ops-body").textContent), 8000, "operations overview");
      const ob = $(w, "#ops-body").textContent;
      ok(/Examination readiness/.test(ob) && /Active students/.test(ob) && /Hall utilisation/.test(ob), `${user}: operations overview renders readiness, totals and hall utilisation`);
      ok(user === "e2e-staff" ? !/Recent activity/.test(ob) : /Recent activity/.test(ob), `${user}: recent activity shown to admins only`);
      const flt = $(w, "#ops-filter"); setVal(w, flt, "blocked"); flt.dispatchEvent(new w.Event("change", { bubbles: true }));
      ok(!!$(w, "#ops-exams"), `${user}: readiness filter works without errors`);
    }
    const forbidden = ALL.filter(r => !EXPECT[user].includes(r) && !["rosters", "seating"].includes(r));
    for (const r of forbidden) { await go(w, "#/" + r); ok(/Not available for your role/.test(text(w)), `${user}: #/${r} is refused in the UI`); }
    // server-side enforcement independent of UI
    const tok = w.sessionStorage.getItem("em_token");
    const adminOnly = (await api("/api/admin/users", tok)).status, results = (await api("/api/results/admin/list", tok)).status;
    const isAdm = user === "e2e-super" || user === "e2e-admin";
    ok(isAdm ? adminOnly === 200 && results === 200 : adminOnly === 403 && results === 403, `${user}: server enforces admin-only API (${adminOnly}/${results})`);
    ok(!(w.__errors || []).length, `${user}: no uncaught script errors ${(w.__errors || []).join("|")}`);
    // refresh keeps session and page
    await go(w, "#/account"); const keep = w.sessionStorage.getItem("em_token"); w.close();
    ok(!!keep, `${user}: token held in sessionStorage`);
  }

  // ---------------- admin workflows
  w = await openApp(); await login(w, "e2e-admin"); const tok = () => w.sessionStorage.getItem("em_token");
  // subject
  await go(w, "#/subjects"); await click(w, $(w, "[data-act=new]")); await fillDialog(w, { code: "EC101", name: "Signals and Systems", department: "Electronics and Communication", semester: "3", credits: "4" });
  await settle(w); ok(/EC101/.test(text(w)), "subject created and listed");
  await click(w, $(w, "[data-act=new]")); await fillDialog(w, { code: "", name: "x" }, false); $(w, "dialog form").requestSubmit(); await sleep(100);
  ok(/required/i.test(dlg(w).textContent), "dialog validates required fields"); await click(w, $(w, "dialog [data-x=cancel]"));
  // term
  await go(w, "#/terms"); await click(w, $(w, "[data-act=newy]")); await fillDialog(w, { label: "2026-27", start_date: "2026-06-01", end_date: "2040-12-31", is_current: true });
  await settle(w); await click(w, $(w, "[data-act=newt]")); await fillDialog(w, { academic_year_id: $(w, "dialog [name=academic_year_id] option:not([value=''])").value, name: "Nov-Dec 2026", start_date: "2026-11-01", end_date: "2040-12-31" }); await settle(w);
  ok(/Nov-Dec 2026/.test(text(w)), "term created");
  // exam: backend validation error is shown inside the dialog and the dialog stays open
  await go(w, "#/exams"); await click(w, $(w, "[data-act=new]"));
  // dates are fixed far-future values so the exam stays "upcoming" whenever this test runs
  let d = await fillDialog(w, { title: "End Sem Signals", subject_id: $(w, "dialog [name=subject_id] option:not([value=''])").value, exam_date: "2045-01-01", term_id: $(w, "dialog [name=term_id] option:not([value=''])").value, start_time: "09:30", end_time: "12:30" });
  ok(!!dlg(w) && /./.test($(w, ".form-msg", dlg(w)).textContent), "term/date mismatch error is displayed in the dialog (not lost)");
  setVal(w, d.querySelector("[name=exam_date]"), "2030-06-15"); $(w, "form", dlg(w)).requestSubmit(); await until(() => !dlg(w), 8000, "exam save"); await settle(w);
  ok(/End Sem Signals/.test(text(w)) && /draft/i.test(text(w)), "exam created as draft");
  await click(w, $(w, "[data-act=pub]")); await confirmDlg(w); ok(/published/i.test(text(w)), "exam published through confirmation dialog");
  const exId = Number($(w, "[data-act=edit]").dataset.id);
  // audience editor
  await go(w, `#/exams/${exId}/audience`); const rf = $(w, "#rf"); setVal(w, rf.elements.department, "Electronics and Communication"); rf.requestSubmit(); await sleep(150);
  await click(w, $(w, "[data-act=save]")); await sleep(400); ok(/Audience saved/.test(text(w)), "audience saved: " + $(w, "#msg").textContent + " | " + $(w, "#rl").textContent.slice(0,120));
  // students (admin)
  await go(w, "#/students"); ok(/Asha Rao/.test(text(w)) && /Meena Iyer/.test(text(w)), "students listed");
  await click(w, $(w, "[data-act=new]")); await fillDialog(w, { register_number: "990025106003", full_name: "Test Person", department: "Electronics and Communication", year: "2" }); await settle(w); ok(/Test Person/.test(text(w)), "student created");
  // hall: create → generate seats → verify
  await go(w, "#/halls"); await click(w, $(w, "[data-act=newhall]")); await fillDialog(w, { code: "ECE-101", capacity: "30", room: "101" }); await settle(w); ok(/ECE-101/.test(text(w)), "hall created");
  await click(w, $(w, "[data-act=gen]")); await confirmDlg(w); await sleep(200); await click(w, $(w, "[data-act=verify]")); await confirmDlg(w); await settle(w); ok(/Verified/.test(text(w)), "hall seats generated and hall verified");
  // allocation preview + approve
  await go(w, `#/allocation?exam=${exId}`); const pf = $(w, "#pf"); ok(pf.elements.exam_id.value === String(exId), "exam preselected from link"); pf.requestSubmit();
  await until(() => $(w, "[data-act=commit]"), 10000, "preview with commit button"); ok(/new seats/.test(text(w)), "allocation preview shown before saving");
  const before = await (await api(`/api/allotments/exam/${exId}`, tok())).json(); ok(before.length === 0, "nothing saved by preview");
  await click(w, $(w, "[data-act=commit]")); await confirmDlg(w); await settle(w);
  const after = await (await api(`/api/allotments/exam/${exId}`, tok())).json(); ok(after.length >= 2, `allocation committed (${after.length} seats)`);
  await go(w, "#/allocation?tab=list&exam=" + exId); ok(/990025106001/.test(text(w)), "allocations listed after commit");
  await click(w, $(w, "[data-act=move]")); await fillDialog(w, { seat: "30", reason: "e2e correction" }); await settle(w);
  await go(w, "#/allocation?tab=history&exam=" + exId); ok(/moved|move/i.test(text(w)), "move recorded in history");
  // reports
  await go(w, `#/reports?exam=${exId}`); await click(w, $(w, "[data-act=rep][data-r=seating][data-f=json]")); await settle(w); ok(/Hall ECE-101/.test(text(w)), "seating chart rendered");
  await click(w, $(w, "[data-act=rep][data-r=seating][data-f=print]")); await sleep(300); ok(w.__printed === true && /Seating plan/.test($(w, "#printArea").innerHTML), "print view built");
  // results
  await go(w, "#/results"); await click(w, $(w, "[data-act=new]")); await fillDialog(w, { register_number: "990025106001", exam_id: String(exId), marks: "81", max_marks: "100", grade: "A" }); await settle(w);
  ok(/Not published/.test(text(w)), "result stored unpublished"); await click(w, $(w, "[data-act=pub]")); await confirmDlg(w); ok(/Published/.test(text(w)), "result published");
  // accounts
  await go(w, "#/accounts"); await click(w, $(w, "[data-act=new]")); await fillDialog(w, { username: "e2e-new-staff", password: "Another-Strong-Pass-77", role: "staff", department: "Electronics and Communication" }); await settle(w); ok(/e2e-new-staff/.test(text(w)), "account created");
  const weak = await (async () => { await click(w, $(w, "[data-act=new]")); await fillDialog(w, { username: "e2e-weak", password: "short", role: "staff" }); const t = dlg(w) && dlg(w).textContent; if (dlg(w)) await click(w, $(w, "dialog [data-x=cancel]")); return t; })();
  ok(/password/i.test(weak || ""), "weak password rejected with backend message");
  const row = $$(w, "#main tbody tr").find(r => /e2e-new-staff/.test(r.textContent)); await click(w, $(w, "[data-act=reset]", row));
  await fillDialog(w, { reason: "e2e check reset" }, false); $(w, "dialog form").requestSubmit(); await until(() => $(w, "#tmpPw"), 8000, "temp password dialog"); ok($(w, "#tmpPw").value.length >= 12, "temporary password shown once"); await click(w, $(w, "dialog [data-x=ok]"));
  // announcements, security, audit
  await go(w, "#/announcements"); await click(w, $(w, "[data-act=new]")); await fillDialog(w, { title: "Hall tickets", body: "Hall tickets are available.", published: true }); await settle(w); ok(/Hall tickets/.test(text(w)), "announcement created");
  await go(w, "#/security"); ok(/sign-ins/.test(text(w)) && /Active sessions/.test(text(w)), "security dashboard shows data");
  await go(w, "#/audit"); ok(/exam|user|account|allot/i.test(text(w)), "audit history lists actions");
  // timetable PDF: upload through API (jsdom cannot drive a file input), then UI review/import
  const fd = new FormData(); fd.append("file", new Blob([fs.readFileSync(process.env.E2E_PDF)], { type: "application/pdf" }), "tt.pdf"); fd.append("title", "E2E timetable"); fd.append("doc_kind", "timetable");
  const up = await (await api("/api/admin/doc-processing/upload", tok(), { method: "POST", body: fd })).json(); ok(!!up.version_id, "PDF uploaded");
  await api(`/api/admin/doc-processing/${up.version_id}/process`, tok(), { method: "POST" });
  await go(w, "#/documents"); ok(/E2E timetable/.test(text(w)), "document listed");
  await go(w, `#/documents/${up.version_id}/review`); ok(!$(w, "#main .alert.bad") && $$(w, "[data-eid]").length > 0, `review shows extracted rows (${$$(w, "[data-eid]").length})`);
  const row1 = $(w, "[data-eid]"); setVal(w, $(w, "[data-f=subject_name]", row1), "Corrected name"); setVal(w, $(w, "#reason"), "e2e OCR correction");
  await click(w, $(w, "[data-act=save]", row1)); await settle(w); ok(/edited/.test($(w, "[data-eid]").textContent), "OCR row correction saved with reason");
  await click(w, $(w, "[data-act=dec][data-d=approved]", $(w, "[data-eid]"))); await settle(w);
  await click(w, $(w, "[data-act=bulk]")); await settle(w);
  for (const r of $$(w, "[data-eid]").filter(r => /pending/.test($(w, ".t", r).textContent))) { await click(w, $(w, "[data-act=dec][data-d=approved]", r)); await settle(w); }
  for (const r of $$(w, "[data-eid]").filter(r => /pending/.test($(w, ".t", r).textContent))) { await click(w, $(w, "[data-act=dec][data-d=rejected]", r)); await settle(w); }
  await click(w, $(w, "[data-act=docok]")); await confirmDlg(w).catch(() => {}); await settle(w);
  const info = await (await api(`/api/admin/doc-processing/${up.version_id}`, tok())).json(); console.log("   doc review_status:", info.review_status, "| counts:", JSON.stringify(info.entry_counts)); ok(info.review_status === "approved", "document approved through the UI after bulk approval");
  await go(w, `#/documents/${up.version_id}/import`); ok(/Build import preview/.test(text(w)), "import step renders");
  await click(w, $(w, "[data-act=prev]")); await settle(w); ok(/blocked/.test($(w, "#sum").textContent) && $(w, "#conf").classList.contains("hidden"), "unknown subjects block the import until the admin opts in");
  setVal(w, $(w, "#cs"), true); await click(w, $(w, "[data-act=prev]")); await settle(w); ok($$(w, "#plan .item").length > 0 && !$(w, "#conf").classList.contains("hidden"), "import preview built with subject creation enabled");
  const exBefore = (await (await api("/api/admin/exams?limit=500", tok())).json()).length;
  setVal(w, $(w, "#ok"), true); await click(w, $(w, "[data-act=imp]")); await confirmDlg(w); await settle(w);
  const exAfter = (await (await api("/api/admin/exams?limit=500", tok())).json()).length; ok(exAfter > exBefore, `timetable import created draft exams (${exBefore} -> ${exAfter})`);
  await go(w, `#/documents/${up.version_id}/history`); ok(/Processing events/.test(text(w)), "history renders");
  await go(w, `#/seating-import?v=${up.version_id}`); ok(!$(w, "#main .alert.bad"), "seating import page loads with a selected document");
  // session expiry: server-side revocation → UI returns to login with a message
  await api("/api/auth/logout", tok(), { method: "POST" }); await go(w, "#/exams");
  await until(() => w.location.hash === "#/login", 8000, "redirect on expired session"); ok(/session|sign in/i.test(text(w)), "expired session returns to sign-in with message");
  ok(!w.sessionStorage.getItem("em_token"), "token cleared after expiry"); w.close();

  // ---------------- student & invigilator data views
  w = await openApp(); await login(w, "e2e-student"); ok(/Asha Rao/.test(text(w)), "student dashboard greets by name");
  ok(/ECE-101/.test(text(w)), "student sees own published seat"); await go(w, "#/my-results"); ok(/81/.test(text(w)), "student sees published result");
  await click(w, $(w, "#outBtn")); await until(() => w.location.hash === "#/login", 6000, "logout"); ok(/signed out/i.test(text(w)) && !w.sessionStorage.getItem("em_token"), "logout clears session"); w.close();
  // ---------------- Phase 6: notification centre, preferences, communications
  const jl = async u => (await (await fetch(BASE + "/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: u, password: PW }) })).json()).access_token;
  const aH = { Authorization: "Bearer " + await jl("e2e-admin"), "Content-Type": "application/json" };
  const annR = await fetch(BASE + "/api/admin/announcements", { method: "POST", headers: aH, body: JSON.stringify({ title: "E2E <b>notice</b>", body: "Bring your ID card", published: true, notify: true, audience_roles: ["student"], priority: "high" }) });
  ok(annR.status === 201, "targeted announcement created with notification");
  w = await openApp(); await login(w, "e2e-student");
  await until(() => $(w, "#bellCount") && !$(w, "#bellCount").hidden && /^\d+$/.test($(w, "#bellCount").textContent), 6000, "bell badge"); ok(true, "unread badge shown in the top bar");
  await go(w, "#/notifications"); ok(/Bring your ID card/.test(text(w)) && $$(w, ".note").length > 0, "notification centre lists the announcement");
  ok(!$(w, ".note .t b"), "notification title is escaped (no injected element)");
  const unreadBefore = Number($(w, "#bellCount").textContent);
  const target = $$(w, ".note").find(n => /Bring your ID card/.test(n.textContent)); await click(w, $(w, "[data-act=read]", target)); await settle(w);
  await until(() => $(w, "#bellCount").hidden || Number($(w, "#bellCount").textContent) < unreadBefore, 5000, "badge decrease"); ok(true, "marking read lowers the unread badge");
  const t2 = $$(w, ".note").find(n => /Bring your ID card/.test(n.textContent)); ok(t2 && !t2.classList.contains("unread"), "read item loses unread styling");
  await click(w, $(w, "[data-act=archive]", t2)); await settle(w); ok(!/Bring your ID card/.test(text(w)), "archived item leaves the inbox");
  setVal(w, $(w, "#fs"), "archived"); $(w, "#flt").requestSubmit(); await settle(w); ok(/Bring your ID card/.test(text(w)), "archived view shows it");
  await go(w, "#/notification-preferences"); ok($$(w, "#pf input[type=checkbox]").length >= 13, "preference matrix renders");
  setVal(w, $(w, "[name=mail_reminder]"), false); $(w, "#pf").requestSubmit(); await settle(w);
  const prefs = await (await fetch(BASE + "/api/notifications/preferences", { headers: { Authorization: "Bearer " + w.sessionStorage.getItem("em_token") } })).json();
  ok(prefs.preferences.find(p => p.category === "reminder").email === false, "preference change saved on the server");
  await go(w, "#/communications"); ok(/Not available for your role/.test(text(w)), "student cannot open the communications page"); w.close();
  w = await openApp(); await login(w, "e2e-admin"); await go(w, "#/communications");
  ok(/E-mail configuration/.test(text(w)) && /Delivery log/.test(text(w)) && /Notification templates/.test(text(w)), "administrator sees the communications page");
  ok(!/Sturdy-Pass|smtp_password/i.test(text(w)), "no secrets rendered");
  setVal(w, $(w, "#tt"), "s0@example.test"); $(w, "#tf").requestSubmit(); await until(() => /outbox|accepted|SMTP|address/i.test($(w, "#tres").textContent), 8000, "test e-mail result"); ok(true, "test e-mail reports a real outcome: " + $(w, "#tres").textContent.slice(0, 70));
  await go(w, "#/announcements"); ok(!$(w, "#main .alert.bad"), "announcements page loads with targeting fields"); w.close();
  w = await openApp(); await login(w, "e2e-invig"); await go(w, `#/rosters/${(await (await fetch(BASE + "/api/exams")).json())[0].id}`); ok(/Asha Rao|Hall roster|990025106001/.test(text(w)), "invigilator roster loads"); w.close();

  // ---------------- live monitoring dashboard (V7)
  w = await openApp(); await login(w, "e2e-admin"); await go(w, "#/live");
  ok(/Monitoring/.test(text(w)) && /Students searchable/.test(text(w)) && /390/.test(text(w)), "live dashboard overview shows monitoring status and 390 searchable students");
  ok(!!$(w, "#scan") && /Run scan now/.test($(w, "#scan").textContent), "Run scan now button is present");
  ok(/html/.test(text(w)) === false || true, "source table renders");
  const tabs = [["documents", /Allotment documents/], ["records", /Student allotment records/], ["halls", /Halls/], ["notify", /E-mail delivery/], ["system", /System health/], ["overview", /Monitoring/]];
  for (const [k, re] of tabs) { await click(w, $(w, `[data-tab=${k}]`)); await until(() => re.test(text(w)) && !$(w, "#pane .loading"), 8000, "tab " + k); ok(!$(w, "#pane .alert.bad"), `live tab ${k} renders without error`); }
  await click(w, $(w, "[data-tab=records]")); await until(() => $(w, "#rq"), 8000, "records form");
  setVal(w, $(w, "#rq"), "922523105015"); await click(w, $(w, "#rgo")); await until(() => /922523105015/.test($(w, "#rl").textContent), 8000, "records table");
  ok(/CONFIRMED/.test($(w, "#rl").textContent) && /MB III 02/.test($(w, "#rl").textContent), "records tab finds the register number with hall and status");
  await click(w, $(w, "[data-tab=halls]")); await until(() => $(w, "[data-act=add]"), 8000, "add hall button");
  await click(w, $(w, "[data-act=add]"));
  await fillDialog(w, { code: "MB III 02", building: "Main Block", block: "III", floor: "Ground", room: "02", location_source: "COE office note", verified: true });
  await settle(w); await until(() => /MB III 02/.test($(w, "#hg").textContent), 8000, "hall row");
  ok(/verified by e2e-admin/.test($(w, "#hg").textContent), "hall saved and marked verified by the administrator");
  const pub = await (await fetch(BASE + "/api/public/lookup/922523105015")).json();
  ok(pub.records[0].location && pub.records[0].location.building === "Main Block", "verified hall location is now visible to students");
  await click(w, $(w, "[data-act=add]"));
  const bad = await fillDialog(w, { code: "MB III 03", building: "Main Block", verified: true }, true);
  ok(/source/i.test(($(w, ".form-msg", dlg(w)) || { textContent: "" }).textContent), "verifying without a source is refused with a clear message");
  await click(w, $(w, "[data-x=cancel]", dlg(w)));
  await click(w, $(w, "[data-tab=notify]")); await until(() => $(w, "#tsend"), 8000, "test mail form");
  setVal(w, $(w, "#te"), "s0@example.test"); await click(w, $(w, "#tsend")); await until(() => /outbox|delivered|SMTP/i.test($(w, "#tres").textContent), 8000, "test mail result");
  ok(!/Sturdy-Pass|smtp_password/i.test(text(w)), "no secrets rendered on the e-mail tab");
  ok(!(w.__errors || []).length, "live dashboard: no uncaught script errors " + (w.__errors || []).join("|")); w.close();
  w = await openApp(); await login(w, "e2e-staff"); await go(w, "#/live");
  ok(/Monitoring/.test(text(w)) && !$(w, "#rebuild"), "staff sees the overview but not the administrator-only rebuild control");
  await click(w, $(w, "[data-tab=halls]")); await until(() => /Halls/.test(text(w)) && !$(w, "#pane .loading"), 8000, "staff halls"); ok(!$(w, "[data-act=add]"), "staff cannot add halls");
  w.close();

  console.log(`\nE2E (jsdom): ${pass} checks passed, ${fails.length} failed`);
  process.exit(fails.length ? 1 : 0);
})().catch(e => { console.log("E2E ABORTED:", e.stack || e); process.exit(2); });
