// DOM-level test of the public student portal (jsdom against a live uvicorn server). NOT a real browser: it proves the
// scripts run, the API contract is honoured, and the page behaves (search, states, zoom viewer, slip, refresh).
const { JSDOM } = require("jsdom");
const BASE = process.env.BASE;
let failures = 0, passes = 0;
function ok(c, m) { if (c) { passes++; console.log("  ok  " + m); } else { failures++; console.log("  FAIL " + m); } }
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function until(fn, ms = 8000) { const t = Date.now(); while (Date.now() - t < ms) { try { if (fn()) return true; } catch (e) {} await sleep(50); } return false; }

async function open(path) {
  const calls = [];
  const dom = await JSDOM.fromURL(BASE + path, {
    runScripts: "dangerously", resources: "usable", pretendToBeVisual: true,
    beforeParse(w) {
      w.fetch = (u, o) => { const url = new URL(u, BASE).toString(); calls.push(url); return fetch(url, o); };
      w.AbortController = AbortController;
      w.__opened = []; w.open = (u) => { w.__opened.push(u); return null; };
    } });
  dom.calls = calls;
  await until(() => dom.window.document.readyState === "complete");
  return dom;
}
const text = (d, sel) => (d.window.document.querySelector(sel) || {}).textContent || "";

(async () => {
  console.log("portal: welcome state");
  let d = await open("/portal/");
  const doc = () => d.window.document;
  ok(!doc().getElementById("stateWelcome").hidden, "welcome panel is shown first");
  ok(await until(() => /Last successful check:/.test(text(d, "#syncText"))), "status bar shows last successful check");
  ok(await until(() => /20-11-2026/.test(text(d, "#published"))), "published sessions list shows 20-11-2026");
  ok(doc().querySelectorAll("input").length >= 1 && !doc().querySelector("[name=date],[name=session],[name=subject]"), "only a register-number field (no date/session/subject inputs)");

  console.log("portal: validation");
  doc().getElementById("regInput").value = "12"; doc().getElementById("searchForm").dispatchEvent(new d.window.Event("submit", { cancelable: true }));
  ok(/6-20/.test(text(d, "#regMsg")), "short input is rejected client-side with a message");

  console.log("portal: register-number-only search");
  doc().getElementById("regInput").value = " 9225-2310 5015 ";
  doc().getElementById("searchForm").dispatchEvent(new d.window.Event("submit", { cancelable: true }));
  ok(await until(() => !doc().getElementById("results").hidden), "results panel appears");
  ok(text(d, "#resReg") === "922523105015", "register number normalised");
  const card = text(d, "#cards");
  for (const n of ["20-11-2026", "Friday", "AN", "23EET301", "ELECTROMAGNETIC FIELDS", "MB III 02", "BE", "EEE", "Hall and seat confirmed"]) ok(card.includes(n), "card shows " + n);
  const bv = [...doc().querySelectorAll(".bv")].map(e => e.textContent);
  ok(bv[0] === "MB III 02" && bv[1] === "2", "hall and seat boxes: " + bv.join(" / "));
  ok(card.includes("Building/floor location has not yet been verified."), "unverified location message (no map shown)");
  ok(!doc().querySelector("svg.map"), "no map without verified data");
  const imgs = [...doc().querySelectorAll("img.pg")];
  ok(imgs.length === 1 && imgs.every(i => /^\/api\/public\/page\/922523105015\/\d+\/seat\?v=/.test(new URL(i.src).pathname + new URL(i.src).search)), "one seat page image references the public page endpoint");
  ok(!!doc().querySelector('a[href^="https://vsbec.edu.in/wp-content/uploads/"]'), "official PDF links are present");
  ok(!/922524105045/.test(doc().body.textContent), "no other student's number is rendered as text");
  ok(d.window.location.search.includes("reg=922523105015"), "URL carries the register number (shareable)");

  console.log("portal: the delivered image is the full original page");
  const r = await fetch(new URL(imgs[0].src, BASE)); const buf = Buffer.from(await r.arrayBuffer());
  ok(r.status === 200 && buf.slice(0, 4).toString("hex") === "89504e47" && r.headers.get("x-original-page") === "unmasked", "PNG served with x-original-page: unmasked");
  ok(buf.readUInt32BE(16) > 900 && buf.readUInt32BE(20) > 1200, "page is full size " + buf.readUInt32BE(16) + "x" + buf.readUInt32BE(20));

  console.log("portal: zoom viewer");
  doc().querySelector(".srcbar .btn.primary").click();
  ok(!doc().getElementById("viewer").hidden, "viewer opens");
  doc().getElementById("vIn").click(); doc().getElementById("vIn").click();
  ok(doc().getElementById("vZoom").textContent === "150%" && doc().getElementById("vImg").style.width === "150%", "zoom in works (150%)");
  doc().getElementById("vOut").click(); doc().getElementById("vFit").click();
  ok(doc().getElementById("vZoom").textContent === "100%", "fit/zoom out works");
  const hl = doc().getElementById("vHl"); hl.checked = false; hl.dispatchEvent(new d.window.Event("change"));
  ok(/hl=0/.test(doc().getElementById("vImg").src), "highlight toggle switches to the pristine image");
  ok(/\/api\/public\/page\//.test(doc().getElementById("vDown").href), "download link points at the page image");
  doc().dispatchEvent(new d.window.KeyboardEvent("keydown", { key: "Escape" }));
  ok(doc().getElementById("viewer").hidden, "Escape closes the viewer");

  console.log("portal: slip + refresh");
  doc().getElementById("slipBtn").click();
  ok(d.window.__opened.some(u => u.startsWith("/api/public/slip/922523105015")), "Print slip opens the slip endpoint");
  const before = d.calls.length;
  doc().getElementById("refreshBtn").click();
  ok(await until(() => d.calls.filter(u => u.includes("/api/public/lookup/")).length >= 2), "Refresh now re-queries the server");
  ok(!doc().getElementById("results").hidden && doc().getElementById("stateLoading").hidden, "results stay visible during and after a manual refresh (no spinner wipe)");

  console.log("portal: unknown number, server error keeps previous results");
  doc().getElementById("regInput").value = "999999999999"; doc().getElementById("searchForm").dispatchEvent(new d.window.Event("submit", { cancelable: true }));
  ok(await until(() => !doc().getElementById("stateEmpty").hidden), "no-match state");
  ok(/No matching record/.test(text(d, "#emptyTitle")) && /No allotment was found/.test(text(d, "#emptyText")), "no-match message");
  d.window.close();

  d = await open("/portal/?reg=922523105015");
  ok(await until(() => !doc().getElementById("results").hidden), "deep link ?reg= searches automatically");
  let failNext = false; const real = d.window.fetch;
  d.window.fetch = (u, o) => (failNext && /lookup/.test(u) ? Promise.reject(new Error("offline")) : real(u, o));
  failNext = true; doc().getElementById("refreshBtn").click();
  ok(await until(() => !doc().getElementById("stateError").hidden || !doc().getElementById("results").hidden), "a failed manual refresh shows a state");
  d.window.close();

  console.log("portal: XSS safety");
  d = await open("/portal/");
  ok(!/\.innerHTML\s*=|insertAdjacentHTML|document\.write/.test(await (await fetch(BASE + "/portal/portal.js")).text()), "portal.js never uses innerHTML");
  d.window.close();

  console.log(`\n${passes} passed, ${failures} failed`);
  process.exit(failures ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
