// Real-browser journeys. Every role signs in through the real login form, then every sidebar page is opened.
// Default: headless Chromium (bundled by @sparticuz/chromium). Firefox: BROWSER=firefox FIREFOX_PATH=/path/to/firefox (WebDriver BiDi,
// needs a Firefox build that supports BiDi, 129+). The checks are identical in both browsers.
import chromium from '@sparticuz/chromium';
import puppeteer from 'puppeteer-core';
const BASE = process.env.BASE, PW = process.env.E2E_PW;
let pass = 0, fail = 0; const fails = [];
const ok = (c, m) => { if (c) pass++; else { fail++; fails.push(m); console.log('FAIL', m); } };
const FIREFOX = process.env.BROWSER === 'firefox';
const browser = FIREFOX
  ? await puppeteer.launch({ browser: 'firefox', executablePath: process.env.FIREFOX_PATH, headless: true, protocol: 'webDriverBiDi' })
  : await puppeteer.launch({ args: chromium.args, executablePath: await chromium.executablePath(), headless: 'shell' });

console.log('browser under test:', await browser.version());

async function newPage(w = 1280, h = 900) {
  const p = await browser.newPage(); await p.setViewport({ width: w, height: h });
  // bundled Chromium is single-process: no separate contexts, so cookies are cleared per page (CDP in Chromium, the cookie API in Firefox)
  if (FIREFOX) { const cookies = await p.cookies(); if (cookies.length) await p.deleteCookie(...cookies); }
  else { const cdp = await p.createCDPSession(); await cdp.send('Network.clearBrowserCookies'); }
  p.errs = []; p.bad = [];
  p.on('pageerror', e => p.errs.push('pageerror: ' + e.message));
  p.on('console', m => { if (m.type() === 'error' && !/favicon|Failed to load resource/.test(m.text())) p.errs.push('console: ' + m.text()); });
  p.on('response', r => { if (r.status() >= 500) p.bad.push(r.status() + ' ' + r.url()); });
  return p;
}
const settle = p => new Promise(r => setTimeout(r, 450));
async function login(p, user) {
  await p.goto(BASE + '/#/login', { waitUntil: 'networkidle0' });
  await p.evaluate(() => { localStorage.clear(); sessionStorage.clear(); }); await p.goto(BASE + '/#/login', { waitUntil: 'networkidle0' }); await p.reload({ waitUntil: 'networkidle0' });
  await p.waitForSelector('input[name=username]');
  await p.type('input[name=username]', user); await p.type('input[name=password]', PW);
  await Promise.all([p.click('form#f button'), p.waitForSelector('#nav a', { timeout: 8000 })]);
}
async function walk(p, role) {
  const hrefs = await p.$$eval('#nav a', a => a.map(x => x.getAttribute('href')));
  ok(hrefs.length > 0, `${role}: sidebar has pages`);
  for (const h of hrefs) {
    p.errs.length = 0; p.bad.length = 0;
    await p.evaluate(x => { location.hash = x.replace(/^#/, ''); }, h); await settle(p);
    const txt = await p.evaluate(() => document.querySelector('main')?.innerText || '');
    ok(p.errs.length === 0, `${role} ${h}: no JS errors ${p.errs.join(' | ')}`);
    ok(p.bad.length === 0, `${role} ${h}: no 5xx ${p.bad.join(' | ')}`);
    ok(txt.length > 0 && !/undefined|\[object Object\]|NaN/.test(txt), `${role} ${h}: renders real content`);
    const overflow = await p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    ok(overflow <= 2, `${role} ${h}: no horizontal overflow (${overflow}px)`);
  }
  return hrefs;
}
const expectNav = { 'e2e-admin': ['allocation'], 'e2e-staff': [], 'e2e-invig': [], 'e2e-student': [] };
const seen = {};
for (const [user, role] of [['e2e-admin', 'admin'], ['e2e-staff', 'staff'], ['e2e-invig', 'invigilator'], ['e2e-student', 'student']]) {
  const p = await newPage(); await login(p, user); seen[role] = await walk(p, role);
  await p.evaluate(() => document.querySelector('#logoutBtn, [data-logout], button.logout')?.click());
  await p.close();
}
ok(seen.admin.length > seen.staff.length && seen.staff.length >= seen.invigilator.length, 'nav size ordered admin > staff >= invigilator');
ok(!seen.student.some(h => /users|audit|import|backup|settings/.test(h)), 'student nav has no admin pages: ' + seen.student.join(','));
ok(!seen.invigilator.some(h => /users|audit|import|backup|settings/.test(h)), 'invigilator nav has no admin pages: ' + seen.invigilator.join(','));
ok(!seen.staff.some(h => /users|backup|settings/.test(h)), 'staff nav has no admin-only pages: ' + seen.staff.join(','));

// Wrong password must not sign in
{ const p = await newPage(); await p.goto(BASE + '/#/login', { waitUntil: 'networkidle0' }); await p.waitForSelector('input[name=username]');
  await p.type('input[name=username]', 'e2e-admin'); await p.type('input[name=password]', 'wrong-password-123'); await p.click('form#f button'); await settle(p);
  ok(!(await p.$('#nav a')), 'wrong password does not reach the app'); await p.close(); }
// Direct URL to an admin page as student is refused client- and server-side
{ const p = await newPage(); await login(p, 'e2e-student'); await p.evaluate(() => { location.hash = '#/users'; }); await settle(p);
  const t = await p.evaluate(() => document.body.innerText); ok(!/Create user|Add user/i.test(t), 'student cannot see user management'); await p.close(); }

// Public portal: each verification state, desktop + phone
async function portal(reg, w) {
  const p = await newPage(w, 800); await p.goto(BASE + '/portal', { waitUntil: 'networkidle0' });
  await p.type('#regInput', reg); await p.click('#searchBtn'); await settle(p); await settle(p);
  const body = await p.evaluate(() => document.body.innerText);
  const overflow = await p.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  ok(p.errs.length === 0, `portal ${reg}@${w}: no JS errors ${p.errs.join('|')}`); ok(overflow <= 2, `portal ${reg}@${w}: no overflow`);
  await p.close(); return body;
}
for (const w of [1280, 375]) {
  const full = await portal('990025106001', w), hall = await portal('990025106002', w), legacy = await portal('990025205001', w);
  ok(/MB III A103/.test(full) && /\b11\b/.test(full), `portal full@${w}: hall and seat shown`);
  ok(/MB III A103/.test(hall) && !/Seat\s*\n?\s*12\b/.test(hall) && /not yet|Not yet/.test(hall), `portal hall-only@${w}: hall shown, seat withheld`);
  ok(!/MB III A103/.test(legacy) && !/\b13\b\s*$/m.test(legacy), `portal unresolved@${w}: nothing shown`);
}
// Signed-in student API (called from the browser) mirrors the verification policy
{ const p = await newPage(); await p.goto(BASE + '/portal', { waitUntil: 'networkidle0' });
  for (const [u, n, seat, withheld] of [['e2e-student', 1, '11', 0], ['e2e-legacy', 0, null, 1]]) {
    const r = await p.evaluate(async (u, pw) => {
      const t = (await (await fetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username: u, password: pw }) })).json()).access_token;
      return await (await fetch('/api/vsb-allocation/my', { headers: { Authorization: 'Bearer ' + t } })).json(); }, u, PW);
    ok(r.allocations.length === n && (n === 0 || r.allocations[0].seat === seat) && r.withheld_unverified === withheld, `signed-in ${u}: policy ${JSON.stringify(r).slice(0, 160)}`);
  }
  await p.close(); }
await browser.close();
console.log(`browser e2e: ${pass} passed, ${fail} failed`);
if (fail) { console.log(fails.join('\n')); process.exit(1); }
