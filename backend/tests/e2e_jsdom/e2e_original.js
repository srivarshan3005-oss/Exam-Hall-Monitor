// jsdom (NOT a real browser) end-to-end check of the original-data workflow against a live server.
// Covers: admin import panel (dry run changes nothing), unpublished records invisible, publication, the public portal
// lookup for register 992696352326, invalid/unknown registers, staff/student restrictions and chart access.
const { JSDOM } = require("jsdom");
const fs = require("fs");
const BASE = process.env.BASE, PW = process.env.E2E_PW, FILE = process.env.ORIG_JSON;
const REG = "992696352326", SRC_URL = "https://vsbec.edu.in/wp-content/uploads/2026/11/17.11.26-AN-seat.pdf";
let pass = 0; const fails = [];
const ok = (c, m) => { if (c) pass++; else { fails.push(m); console.log("  FAIL:", m); } };
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function until(fn, ms = 8000) { const t = Date.now(); while (Date.now() - t < ms) { try { const v = fn(); if (v) return v; } catch (e) { /* retry */ } await sleep(40); } return null; }
const ENV = { beforeParse(w) {
  w.fetch = (u, o) => fetch(new URL(u, BASE), o); w.FormData = FormData; w.Blob = Blob;
  w.HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  w.HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  w.Element.prototype.scrollIntoView = function () {}; w.HTMLElement.prototype.focus = function () {};
  w.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} }); w.print = () => {};
} };
const api = async (path, token, opts = {}) => fetch(BASE + path, { ...opts, headers: { ...(opts.headers || {}), Authorization: "Bearer " + token } });
async function jsonOf(p) { const r = await p; return { status: r.status, body: await r.json().catch(() => null) }; }
async function login(user) { const r = await jsonOf(fetch(BASE + "/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username: user, password: PW }) })); return r.body.access_token; }
async function setVal(w, el, v) { el.value = v; el.dispatchEvent(new w.Event("input", { bubbles: true })); el.dispatchEvent(new w.Event("change", { bubbles: true })); }
async function signInUi(w, user) {
  await until(() => w.EM && w.document.querySelector("#main"));
  w.location.hash = "#/login"; await sleep(80);
  await until(() => w.document.querySelector("#main form"));
  const f = w.document.querySelector("#main form"); await setVal(w, f.elements.username, user); await setVal(w, f.elements.password, PW);
  f.requestSubmit(); await until(() => w.document.querySelector("#shell") && !w.document.querySelector("#main .loading"), 12000);
  await sleep(100);
}
const portalText = w => w.document.body.textContent;
const visible = (w, id) => { const el = w.document.getElementById(id); return !!el && !el.hidden && el.style.display !== "none"; };

(async () => {
  const admin = await login("e2e-admin"), staff = await login("e2e-staff"), student = await login("e2e-sample");
  const raw = fs.readFileSync(FILE);
  // 1. Administrator: the import panel exists and a DRY RUN changes nothing
  const dom = await JSDOM.fromURL(BASE + "/", { runScripts: "dangerously", resources: "usable", pretendToBeVisual: true, beforeParse: ENV.beforeParse });
  const w = dom.window; await signInUi(w, "e2e-admin");
  w.location.hash = "#/vsb-allocation"; await sleep(80);
  const form = await until(() => w.document.querySelector("#origForm"), 10000);
  ok(!!form, "admin sees the original-data import panel");
  const batchesBefore = (await jsonOf(api("/api/vsb-allocation/batches", admin))).body;
  const file = new (require("buffer").File)([raw], "allotments.json", { type: "application/json" });
  Object.defineProperty(w.document.getElementById("origFile"), "files", { value: [file] });
  // dispatch the submit event directly: jsdom's constraint validation does not see a file set through a property override
  form.dispatchEvent(new w.Event("submit", { cancelable: true, bubbles: true }));
  const msg = await until(() => /rows valid/.test(w.document.getElementById("origMsg").textContent), 30000);
  ok(!!msg, "dry run reports the rows");
  const t1 = w.document.getElementById("origMsg").textContent;
  ok(/3306 rows valid/.test(t1) && /0 rejected/.test(t1) && /would be staged/.test(t1), "dry-run summary is correct: " + t1.slice(0, 120));
  ok(!w.document.getElementById("origApply").disabled, "Stage button enabled after a successful dry run");
  const batchesAfter = (await jsonOf(api("/api/vsb-allocation/batches", admin))).body;
  ok(Array.isArray(batchesBefore) && batchesBefore.length === 0 && Array.isArray(batchesAfter) && batchesAfter.length === 0, "dry run wrote no batches");
  // 2. Staff sees no import panel (administrators only)
  const dom2 = await JSDOM.fromURL(BASE + "/", { runScripts: "dangerously", resources: "usable", pretendToBeVisual: true, beforeParse: ENV.beforeParse });
  await signInUi(dom2.window, "e2e-staff"); dom2.window.location.hash = "#/vsb-allocation"; await sleep(150);
  ok(!dom2.window.document.getElementById("origForm"), "staff does not see the import panel");
  // 3. Apply through the API (the UI stages only after an explicit confirmation); then the record must be invisible
  const applied = await jsonOf(fetch(BASE + "/api/vsb-allocation/import/original?dry_run=false&confirm=true", { method: "POST", headers: { Authorization: "Bearer " + admin }, body: (() => { const f = new FormData(); f.append("file", new (require("buffer").File)([raw], "allotments.json")); return f; })() }));
  ok(applied.status === 200 && applied.body.records_to_stage === 3306, "staging as drafts works: " + applied.status);
  const batches = (await jsonOf(api("/api/vsb-allocation/batches", admin))).body;
  const an = batches.find(b => b.exam_date === "2026-11-17" && b.session === "AN");
  ok(an && an.status === "draft", "17 Nov AN batch exists as a draft");
  const dom3 = await JSDOM.fromURL(BASE + "/portal/?reg=" + REG, { runScripts: "dangerously", resources: "usable", pretendToBeVisual: true, beforeParse: ENV.beforeParse });
  const pw = dom3.window; await until(() => visible(pw, "stateEmpty") || visible(pw, "results"), 12000);
  ok(visible(pw, "stateEmpty") && !visible(pw, "results"), "UNPUBLISHED: draft records are not shown to the student");
  ok(!/23ECT307|MB III A103/.test(portalText(pw)), "UNPUBLISHED: no hall, seat or subject appears before publication");
  // 4. Approve (with the required note and acknowledgement) and publish the batch via the normal endpoints
  const recs = (await jsonOf(api(`/api/vsb-allocation/batches/${an.id}/records?q=${REG}&limit=5`, admin))).body.records;
  const rec = recs.find(r => r.register_number === REG);
  const rv = await jsonOf(fetch(BASE + `/api/vsb-allocation/records/${rec.id}/review`, { method: "POST", headers: { Authorization: "Bearer " + admin, "Content-Type": "application/json" }, body: JSON.stringify({ decision: "approve", note: "Checked seat sheet page 23 and hall list page 4", acknowledge: true }) }));
  ok(rv.status === 200, "administrator approves the sample with a note");
  const pre = (await jsonOf(fetch(BASE + `/api/vsb-allocation/batches/${an.id}/publish/preview`, { method: "POST", headers: { Authorization: "Bearer " + admin } }))).body;
  const pub = await jsonOf(fetch(BASE + `/api/vsb-allocation/batches/${an.id}/publish`, { method: "POST", headers: { Authorization: "Bearer " + admin, "Content-Type": "application/json" }, body: JSON.stringify({ signature: pre.signature, confirm: true, acknowledge_open_issues: pre.open_error_issues > 0 }) }));
  ok(pub.status === 200, "publication succeeds through the preview signature");
  // 5. Student portal: enter the register number and read the result
  const dom4 = await JSDOM.fromURL(BASE + "/portal/", { runScripts: "dangerously", resources: "usable", pretendToBeVisual: true, beforeParse: ENV.beforeParse });
  const p4 = dom4.window;
  // wait for the portal script to start (its notices request completes) before submitting, or the submit listener is not attached
  await until(() => p4.document.getElementById("searchForm") && !/Checking notices/.test(p4.document.getElementById("noticeCount").textContent), 12000);
  const input = p4.document.getElementById("regInput"); input.value = REG;
  p4.document.getElementById("searchForm").requestSubmit();
  await until(() => visible(p4, "results"), 12000);
  const t = portalText(p4);
  ok(visible(p4, "results"), "entering 992696352326 shows the results");
  ok(/23ECT307/.test(t) && /DIGITAL ELECTRONICS/i.test(t), "subject and subject code shown");
  ok(/Tuesday/.test(t) && /17 Nov|November|17/.test(t), "date and day shown");
  ok(/AN · Afternoon/.test(t), "session shown");
  const cells = [...p4.document.querySelectorAll(".allot-grid .cell")].map(c => [c.querySelector("span").textContent, c.querySelector("strong").textContent]);
  ok(cells.some(([k, v]) => k === "Hall" && v === "MB III A103"), "hall MB III A103 shown");
  ok(cells.some(([k, v]) => k === "Seat" && v === "23"), "seat 23 shown");
  const links = [...p4.document.querySelectorAll("a")].map(a => a.href);
  ok(links.includes(SRC_URL), "source link points to the official seat PDF");
  ok(!links.some(h => /sabareesh2008|github/i.test(h)), "no link to the GitHub mirror is offered to students");
  ok(!/1:30|1\.30|4:30|4\.30/.test(t), "no 1:30–4:30 time is displayed (no verified time in the source)");
  ok(/1 EXAM/.test(t), "exactly one published exam is listed");
  // 6. Invalid and unknown registers
  const dom5 = await JSDOM.fromURL(BASE + "/portal/?reg=9225", { runScripts: "dangerously", resources: "usable", pretendToBeVisual: true, beforeParse: ENV.beforeParse });
  await sleep(1500);
  ok(!visible(dom5.window, "results"), "invalid register (9225) shows no result");
  const dom6 = await JSDOM.fromURL(BASE + "/portal/?reg=992696352999", { runScripts: "dangerously", resources: "usable", pretendToBeVisual: true, beforeParse: ENV.beforeParse });
  await until(() => visible(dom6.window, "stateEmpty") || visible(dom6.window, "stateError"), 12000);
  ok(!visible(dom6.window, "results"), "unknown register shows no result");
  // 7. Signed-in student sees only their own published seat; the import and charts stay closed to them
  const my = await jsonOf(api("/api/vsb-allocation/my", student));
  ok(my.status === 200 && my.body.allocations.length === 1 && my.body.allocations[0].seat === "23", "signed-in student sees own seat only");
  ok((await jsonOf(fetch(BASE + "/api/vsb-allocation/import/original", { method: "POST", headers: { Authorization: "Bearer " + student } }))).status === 403, "student cannot import");
  const chartName = "d12cded03485_17.11.26-AN-seat_page_23.png";
  ok((await fetch(BASE + "/api/vsb-allocation/charts/" + chartName, { headers: { Authorization: "Bearer " + student } })).status === 403, "student cannot open seating charts");
  ok((await fetch(BASE + "/api/vsb-allocation/charts/" + chartName, { headers: { Authorization: "Bearer " + staff } })).status === 403, "staff cannot open seating charts");
  const img = await fetch(BASE + "/api/vsb-allocation/charts/" + chartName, { headers: { Authorization: "Bearer " + admin } });
  ok(img.status === 200 && img.headers.get("content-type") === "image/png", "administrator opens the original chart");
  console.log(`E2E original workflow (jsdom): ${pass} checks passed, ${fails.length} failed`);
  process.exit(fails.length ? 1 : 0);
})().catch(e => { console.log("E2E crashed:", e && e.stack || e); process.exit(1); });
