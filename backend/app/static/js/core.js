/* Exam Monitor Ultimate — front-end core (Phase 5).
   Classic script (no build step). Everything hangs off window.EM.
   SECURITY NOTE: hiding a menu item is a convenience only. Every action below calls an API endpoint that
   enforces the role on the server; a 403 from the server is shown to the user as-is. */
(function () {
  "use strict";
  const EM = (window.EM = { state: { token: "", user: null, config: { college_name: "", show_names: false } }, pages: [], renderId: 0 });
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  EM.$ = $; EM.$$ = $$;

  // ------------------------------------------------------------------ helpers
  const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  EM.esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ESC[c]);
  const esc = EM.esc;
  EM.fmtDate = d => (d ? String(d).slice(0, 10) : "—");
  EM.fmtDT = iso => {
    if (!iso) return "—";
    let s = String(iso); if (/^\d{4}-\d\d-\d\dT[\d:.]+$/.test(s)) s += "Z";
    const d = new Date(s); return isNaN(d) ? esc(iso) : d.toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
  };
  EM.qs = o => Object.entries(o || {}).filter(([, v]) => v !== "" && v != null && v !== false).map(([k, v]) => encodeURIComponent(k) + "=" + encodeURIComponent(v)).join("&");
  EM.num = v => (v === "" || v == null ? null : Number(v));
  EM.badge = (t, cls) => `<span class="badge ${cls || ""}">${esc(t)}</span>`;
  EM.statusBadge = s => EM.badge(String(s).replace(/_/g, " "), ({ published: "ok", active: "ok", approved: "ok", processed: "ok", imported: "ok", completed: "info", draft: "", pending: "warn", processing: "warn", needs_review: "warn", suspended: "bad", failed: "bad", rejected: "bad", stale: "warn", discarded: "" })[s] || "");
  EM.loading = (t) => `<div class="loading" role="status"><span class="spinner" aria-hidden="true"></span>${esc(t || "Loading…")}</div>`;
  EM.empty = (title, text) => `<div class="empty"><b>${esc(title)}</b>${text ? esc(text) : ""}</div>`;
  EM.alert = (msg, kind) => `<div class="alert ${kind || ""}" role="${kind === "bad" ? "alert" : "status"}">${esc(msg)}</div>`;
  EM.role = () => (EM.state.user && EM.state.user.role) || "";
  EM.isAdmin = () => ["admin", "super_admin"].includes(EM.role());
  EM.isStaff = () => ["admin", "super_admin", "staff"].includes(EM.role());
  EM.can = (...roles) => roles.includes(EM.role()) || (roles.includes("admin") && EM.role() === "super_admin");

  // field builder: EM.field({name,label,type,required,hint,value,options:[[v,l]],attrs})
  EM.field = f => {
    let at = f.attrs || "", id = "f_" + f.name + "_" + Math.random().toString(36).slice(2, 7);
    const own = /\bid="([^"]+)"/.exec(at); if (own) { id = own[1]; at = at.replace(own[0], ""); }   // caller-supplied id wins (no duplicate id attributes)
    const req = f.required ? " required" : "", hint = f.hint ? `<span class="hint" id="${id}_h">${esc(f.hint)}</span>` : "";
    const d = f.hint ? ` aria-describedby="${id}_h"` : "";
    let ctl;
    if (f.type === "select") ctl = `<select id="${id}" name="${esc(f.name)}"${req}${d} ${at}>${(f.options || []).map(o => `<option value="${esc(o[0])}"${String(o[0]) === String(f.value ?? "") ? " selected" : ""}>${esc(o[1])}</option>`).join("")}</select>`;
    else if (f.type === "textarea") ctl = `<textarea id="${id}" name="${esc(f.name)}"${req}${d} ${at}>${esc(f.value ?? "")}</textarea>`;
    else if (f.type === "checkbox") return `<div class="field ${f.cls || ""}"><label class="check"><input type="checkbox" name="${esc(f.name)}"${f.value ? " checked" : ""} ${at}> ${esc(f.label)}</label>${hint}</div>`;
    else ctl = `<input id="${id}" name="${esc(f.name)}" type="${f.type || "text"}" value="${esc(f.value ?? "")}"${req}${d} ${f.placeholder ? `placeholder="${esc(f.placeholder)}"` : ""} ${at}>`;
    return `<div class="field ${f.cls || ""}"><label for="${id}" class="${f.required ? "req" : ""}">${esc(f.label)}</label>${ctl}${hint}</div>`;
  };
  EM.formData = form => {
    const o = {};
    for (const el of form.elements) {
      if (!el.name || el.disabled || el.type === "file" || el.type === "submit" || el.type === "button") continue;
      o[el.name] = el.type === "checkbox" ? el.checked : (typeof el.value === "string" ? el.value.trim() : el.value);
    }
    return o;
  };

  // ------------------------------------------------------------------ errors
  class ApiError extends Error { constructor(msg, status, fields) { super(msg); this.status = status; this.fields = fields || {}; } }
  EM.ApiError = ApiError;
  function parseDetail(d, status) {
    const fields = {}; let msg = "";
    if (!d || d.detail == null) return { msg: `Request failed (${status}).`, fields };
    const det = d.detail;
    if (typeof det === "string") msg = det;
    else if (Array.isArray(det)) {
      msg = det.map(e => {
        const loc = Array.isArray(e.loc) ? e.loc.filter(x => x !== "body" && x !== "query" && x !== "path") : [];
        const name = String(loc[loc.length - 1] ?? "");
        const text = String(e.msg || e).replace(/^Value error, /, "");
        if (name) fields[name] = text;
        return (name ? name.replace(/_/g, " ") + ": " : "") + text;
      }).join("; ");
    } else if (typeof det === "object") {
      msg = det.message || det.detail || JSON.stringify(det);
      if (det.duplicate && det.existing_version_id) msg += ` (existing document version #${det.existing_version_id})`;
    }
    return { msg, fields };
  }
  EM.sessionExpired = msg => {
    if (!EM.state.token) return;
    EM.state.token = ""; EM.state.user = null; try { sessionStorage.removeItem("em_token"); } catch (e) { /* ignore */ }
    EM.flash = msg || "Your session has ended. Please sign in again.";
    EM.go("/login", true);
  };
  async function toError(r) {
    let d = null; try { d = await r.json(); } catch (e) { /* not JSON */ }
    if (r.status === 429) { const s = r.headers.get("Retry-After"); return new ApiError("Too many requests. Please wait" + (s ? ` about ${Math.max(1, Math.ceil(s / 60))} minute(s)` : "") + " and try again.", 429); }
    const p = parseDetail(d, r.status);
    return new ApiError(p.msg, r.status, p.fields);
  }

  // ------------------------------------------------------------------ API
  // opts: method, body (JSON), form (FormData), params (query), raw (return Response), auth (default true)
  EM.api = async function (path, opts) {
    const o = opts || {}, headers = {};
    if (EM.state.token && o.auth !== false) headers.Authorization = "Bearer " + EM.state.token;
    let payload;
    if (o.form) payload = o.form; else if (o.body !== undefined) { headers["Content-Type"] = "application/json"; payload = JSON.stringify(o.body); }
    const url = path + (o.params ? (path.includes("?") ? "&" : "?") + EM.qs(o.params) : "");
    let r;
    try { r = await fetch(url, { method: o.method || "GET", headers, body: payload }); }
    catch (e) { throw new ApiError("Cannot reach the server. Check your connection and try again.", 0); }
    if (!r.ok) {
      const err = await toError(r);
      if (r.status === 401 && EM.state.token && o.auth !== false && !o.keepSession) EM.sessionExpired(err.message.includes("timed out") || err.message.includes("ended") ? err.message + "" : "Your session expired. Please sign in again.");
      else if (r.status === 403 && /password change required/i.test(err.message) && EM.state.token) EM.go("/change-password", true);
      throw err;
    }
    if (o.raw) return r;
    if (r.status === 204) return null;
    try { return await r.json(); } catch (e) { return null; }
  };
  // list endpoints that report the total in X-Total-Count
  EM.apiList = async (path, params) => { const r = await EM.api(path, { params, raw: true }); const rows = await r.json(); return { rows, total: Number(r.headers.get("X-Total-Count") || rows.length) }; };
  EM.blob = async path => { const r = await EM.api(path, { raw: true }); return { blob: await r.blob(), name: (/filename="?([^";]+)"?/.exec(r.headers.get("Content-Disposition") || "") || [])[1] }; };
  EM.download = async (path, fallback) => {
    const { blob, name } = await EM.blob(path), a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = name || fallback || "download"; document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 8000);
  };
  EM.dataUrl = blob => new Promise((res, rej) => { const f = new FileReader(); f.onload = () => res(f.result); f.onerror = rej; f.readAsDataURL(blob); }); // data: URLs satisfy the CSP img-src

  // ------------------------------------------------------------------ toasts + dialogs
  EM.toast = (msg, kind) => {
    let box = $("#toasts"); if (!box) { box = document.createElement("div"); box.id = "toasts"; box.setAttribute("aria-live", "polite"); document.body.appendChild(box); }
    const t = document.createElement("div"); t.className = "toast " + (kind || ""); t.textContent = msg; if (kind === "bad") t.setAttribute("role", "alert");
    box.appendChild(t); setTimeout(() => t.remove(), kind === "bad" ? 9000 : 4500);
  };
  EM.fail = e => EM.toast(e && e.message ? e.message : String(e), "bad");

  function dialog(html, onReady) {
    return new Promise(resolve => {
      const opener = document.activeElement, dlg = document.createElement("dialog");
      dlg.setAttribute("aria-modal", "true"); dlg.innerHTML = html; document.body.appendChild(dlg);
      const done = v => { if (dlg.open) dlg.close(); resolve(v); };
      dlg.addEventListener("close", () => { dlg.remove(); if (opener && opener.focus) try { opener.focus(); } catch (e) { /* gone */ } resolve(dlg._value ?? null); });
      dlg.addEventListener("click", e => { if (e.target === dlg) done(null); });
      onReady(dlg, v => { dlg._value = v; done(v); });
      dlg.showModal();
    });
  }
  EM.confirm = o => dialog(`<form method="dialog"><h2 id="dt">${esc(o.title || "Please confirm")}</h2><p>${esc(o.message || "")}</p>${o.detail ? `<p class="small muted">${esc(o.detail)}</p>` : ""}
    <div class="dlg-actions"><button class="btn" value="cancel" data-x="cancel">Cancel</button><button class="btn ${o.danger ? "danger solid" : "primary"}" data-x="ok">${esc(o.confirmText || "Confirm")}</button></div></form>`,
    (dlg, finish) => {
      dlg.setAttribute("aria-labelledby", "dt");
      $("[data-x=cancel]", dlg).onclick = e => { e.preventDefault(); finish(false); };
      $("[data-x=ok]", dlg).onclick = e => { e.preventDefault(); finish(true); };
      $("[data-x=cancel]", dlg).focus();
    }).then(v => v === true);
  // fields: [{name,label,type,required,hint,value,options}] -> resolves to object or null (cancelled)
  EM.ask = o => dialog(`<form novalidate><h2 id="dt">${esc(o.title)}</h2>${o.message ? `<p class="muted">${esc(o.message)}</p>` : ""}<div class="stack">${o.fields.map(EM.field).join("")}</div>
    <div class="dlg-actions"><button type="button" class="btn" data-x="cancel">Cancel</button><button class="btn ${o.danger ? "danger solid" : "primary"}">${esc(o.submitText || "Save")}</button></div></form>`,
    (dlg, finish) => {
      dlg.setAttribute("aria-labelledby", "dt"); const form = $("form", dlg);
      $("[data-x=cancel]", dlg).onclick = () => finish(null);
      form.onsubmit = async e => {
        e.preventDefault();
        if (form.dataset.busy === "1") return;
        EM.clearErrors(form);
        const bad = $$("[required]", form).filter(x => !(x.type === "checkbox" ? x.checked : String(x.value).trim()));
        if (bad.length) { bad.forEach(x => { x.setAttribute("aria-invalid", "true"); }); bad[0].focus(); formMsg(form).innerHTML = EM.alert("Please fill in the required fields.", "bad"); return; }
        const data = EM.formData(form);
        if (!o.submit) { finish(data); return; }
        form.dataset.busy = "1"; const btns = $$("button:not([type=button])", form); setBusy(btns, true);
        try { const r = await o.submit(data); finish(r === undefined ? true : r); }   // o.submit may throw ApiError: the dialog stays open and shows it
        catch (err) { EM.showErrors(form, err.fields ? err : new ApiError(err.message, 0)); }
        finally { delete form.dataset.busy; setBusy(btns, false); }
      };
      const first = $("input,select,textarea", form); if (first) first.focus();
    });
  // read-only dialog with arbitrary (already escaped) HTML
  EM.show = (title, html, ready) => dialog(`<div style="padding:24px"><h2 id="dt">${esc(title)}</h2>${html}<div class="dlg-actions"><button class="btn primary" data-x="ok">Close</button></div></div>`,
    (dlg, finish) => { dlg.setAttribute("aria-labelledby", "dt"); $("[data-x=ok]", dlg).onclick = () => finish(true); $("[data-x=ok]", dlg).focus(); if (ready) ready(dlg); });

  // ------------------------------------------------------------------ safe submit / click (no double submits)
  function setBusy(btns, on) { btns.forEach(b => { if (on) { b.setAttribute("aria-busy", "true"); b.dataset.wasDisabled = b.disabled ? "1" : ""; b.disabled = true; } else { b.removeAttribute("aria-busy"); b.disabled = b.dataset.wasDisabled === "1"; } }); }
  function formMsg(form) { let m = $(".form-msg", form); if (!m) { m = document.createElement("div"); m.className = "form-msg"; m.setAttribute("aria-live", "polite"); form.prepend(m); } return m; }
  EM.clearErrors = form => { $$("[aria-invalid]", form).forEach(x => x.removeAttribute("aria-invalid")); $$(".err", form).forEach(x => x.remove()); const m = $(".form-msg", form); if (m) m.innerHTML = ""; };
  EM.showErrors = (form, e) => {
    const m = formMsg(form); m.innerHTML = EM.alert(e.message, "bad");
    let first = null;
    Object.entries(e.fields || {}).forEach(([k, v]) => { const el = form.elements[k]; if (el && el.setAttribute) { el.setAttribute("aria-invalid", "true"); const s = document.createElement("span"); s.className = "err"; s.textContent = v; el.parentElement.appendChild(s); first = first || el; } });
    if (first) first.focus(); else m.scrollIntoView({ block: "nearest" });
  };
  // handler(data, form, event). Re-entrancy blocked while the request is running.
  EM.onSubmit = (form, handler) => {
    if (!form) return;
    form.noValidate = true;
    form.addEventListener("submit", async ev => {
      ev.preventDefault();
      if (form.dataset.busy === "1") return;
      EM.clearErrors(form);
      const bad = $$("[required]", form).filter(x => !x.disabled && !(x.type === "checkbox" ? x.checked : String(x.value).trim()));
      if (bad.length) {
        bad.forEach(x => { x.setAttribute("aria-invalid", "true"); const s = document.createElement("span"); s.className = "err"; s.textContent = "This field is required."; x.parentElement.appendChild(s); });
        bad[0].focus(); return;
      }
      form.dataset.busy = "1"; const btns = $$("button:not([type=button]),input[type=submit]", form); setBusy(btns, true);
      try { await handler(EM.formData(form), form, ev); }
      catch (e) { if (e instanceof ApiError || e.message) EM.showErrors(form, e.fields ? e : new ApiError(e.message, 0)); }
      finally { delete form.dataset.busy; setBusy(btns, false); }
    });
  };
  // acts: {actionName: async (button, event) => {...}}; buttons use data-act="actionName"
  EM.delegate = (root, acts) => {
    root.addEventListener("click", async ev => {
      const b = ev.target.closest("[data-act]"); if (!b || !root.contains(b) || b.disabled) return;
      const fn = acts[b.dataset.act]; if (!fn) return;
      if (b.getAttribute("aria-busy") === "true") return;
      if (b.tagName === "A") ev.preventDefault();
      setBusy([b], true);
      try { await fn(b, ev); } catch (e) { EM.fail(e); } finally { if (document.body.contains(b)) setBusy([b], false); }
    });
  };

  // ------------------------------------------------------------------ client-side data grid (search, sort, paginate)
  EM.grid = (el, cfg) => {
    const st = { q: "", key: cfg.sortKey || null, dir: cfg.sortDir || 1, page: 0, size: cfg.pageSize || 10, rows: cfg.rows || [] };
    el.innerHTML = `<div class="toolbar">${cfg.search === false ? "" : `<div class="field wide"><label>Search</label><input type="search" data-g="q" placeholder="${esc(cfg.searchPlaceholder || "Type to filter…")}"></div>`}
      <div class="field" style="max-width:130px"><label>Rows per page</label><select data-g="size">${[10, 25, 50, 100].map(n => `<option${n === st.size ? " selected" : ""}>${n}</option>`).join("")}</select></div></div><div data-g="body" aria-live="polite"></div>`;
    const body = $("[data-g=body]", el);
    const val = (r, c) => (c.value ? c.value(r) : r[c.key]);
    function draw() {
      let rows = st.rows;
      if (st.q) { const t = st.q.toLowerCase(); rows = rows.filter(r => (cfg.searchKeys || cfg.columns.map(c => c.key)).some(k => String(typeof k === "function" ? k(r) : r[k] ?? "").toLowerCase().includes(t))); }
      if (st.key) { const c = cfg.columns.find(x => x.key === st.key); rows = rows.slice().sort((a, b) => { const x = val(a, c), y = val(b, c); return (x == null ? 1 : y == null ? -1 : (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y), undefined, { numeric: true }))) * st.dir; }); }
      const pages = Math.max(1, Math.ceil(rows.length / st.size)); st.page = Math.min(st.page, pages - 1);
      const slice = rows.slice(st.page * st.size, (st.page + 1) * st.size);
      if (!rows.length) { body.innerHTML = EM.empty((cfg.empty || {}).title || "Nothing to show", st.q ? "No rows match your search." : (cfg.empty || {}).text || ""); return; }
      body.innerHTML = `<div class="tablewrap"><table class="table stack"><caption class="sr-only">${esc(cfg.caption || "Data table")}</caption><thead><tr>${cfg.columns.map(c => `<th scope="col"${st.key === c.key ? ` aria-sort="${st.dir > 0 ? "ascending" : "descending"}"` : ""}>${c.sort === false ? esc(c.label) : `<button type="button" data-sort="${esc(c.key)}">${esc(c.label)}<span aria-hidden="true">${st.key === c.key ? (st.dir > 0 ? "▲" : "▼") : ""}</span></button>`}</th>`).join("")}${cfg.actions ? `<th scope="col">Actions</th>` : ""}</tr></thead>
        <tbody>${slice.map(r => `<tr>${cfg.columns.map(c => `<td data-label="${esc(c.label)}" class="${c.cls || ""}">${c.render ? c.render(r) : esc(r[c.key] ?? "—")}</td>`).join("")}${cfg.actions ? `<td class="actions" data-label="Actions">${cfg.actions(r)}</td>` : ""}</tr>`).join("")}</tbody></table></div>
        <div class="pager"><span>${rows.length} row${rows.length === 1 ? "" : "s"}${rows.length !== st.rows.length ? ` (filtered from ${st.rows.length})` : ""} · page ${st.page + 1} of ${pages}</span><span class="row"><button type="button" class="btn sm" data-pg="-1"${st.page === 0 ? " disabled" : ""}>Previous</button><button type="button" class="btn sm" data-pg="1"${st.page >= pages - 1 ? " disabled" : ""}>Next</button></span></div>`;
    }
    el.addEventListener("input", e => { if (e.target.dataset.g === "q") { st.q = e.target.value.trim(); st.page = 0; draw(); } });
    el.addEventListener("change", e => { if (e.target.dataset.g === "size") { st.size = Number(e.target.value); st.page = 0; draw(); } });
    el.addEventListener("click", e => {
      const s = e.target.closest("[data-sort]"), p = e.target.closest("[data-pg]");
      if (s) { st.dir = st.key === s.dataset.sort ? -st.dir : 1; st.key = s.dataset.sort; draw(); }
      if (p && !p.disabled) { st.page += Number(p.dataset.pg); draw(); }
    });
    draw();
    return { setRows(r) { st.rows = r; draw(); }, rows: () => st.rows, redraw: draw };
  };
  // server-side pager: EM.pager(el,{total,limit,offset,onPage(offset)})
  EM.pager = (el, o) => {
    const pages = Math.max(1, Math.ceil(o.total / o.limit)), cur = Math.floor(o.offset / o.limit);
    el.innerHTML = `<div class="pager"><span>${o.total} record${o.total === 1 ? "" : "s"} · page ${cur + 1} of ${pages}</span><span class="row"><button type="button" class="btn sm" data-pg="-1"${cur === 0 ? " disabled" : ""}>Previous</button><button type="button" class="btn sm" data-pg="1"${cur >= pages - 1 ? " disabled" : ""}>Next</button></span></div>`;
    el.onclick = e => { const b = e.target.closest("[data-pg]"); if (b && !b.disabled) o.onPage(Math.max(0, o.offset + Number(b.dataset.pg) * o.limit)); };
  };

  // ------------------------------------------------------------------ router
  EM.page = def => { EM.pages.push(def); };
  EM.go = (path, replace) => { const h = "#" + path; if (replace) { history.replaceState(null, "", h); window.dispatchEvent(new Event("hashchange")); } else if (location.hash === h) EM.route(); else location.hash = h; };
  EM.parseHash = () => {
    const raw = location.hash.replace(/^#\/?/, ""), [p, q] = raw.split("?"), seg = p.split("/").filter(Boolean).map(decodeURIComponent);
    return { name: seg[0] || "", args: seg.slice(1), query: Object.fromEntries(new URLSearchParams(q || "")) };
  };
  let cleanup = null;
  EM.route = async () => {
    if (cleanup) { try { cleanup(); } catch (e) { /* ignore */ } cleanup = null; }
    const id = ++EM.renderId, loc = EM.parseHash(), signed = !!EM.state.user;
    const def = EM.pages.find(p => p.name === loc.name) || null;
    const ctx = { args: loc.args, query: loc.query, current: () => id === EM.renderId };
    if (EM.beforeRender) { const redirect = EM.beforeRender(def, loc, signed); if (redirect) return EM.go(redirect, true); }
    const root = EM.root(def); if (!root) return;
    if (!def) { root.innerHTML = `<div class="card"><h2>Page not found</h2><p>The page “${esc(loc.name)}” does not exist.</p><a class="btn primary" href="#/">Go to start</a></div>`; EM.setTitle("Not found"); return; }
    if (def.roles && !def.roles.some(r => EM.can(r))) {
      root.innerHTML = `<div class="card"><h2>Not available for your role</h2><p>Your account (${esc((EM.state.user || {}).role_label || "")}) is not permitted to use this page. The server enforces this independently of what is displayed.</p><a class="btn primary" href="#/">Back to dashboard</a></div>`; EM.setTitle("Not permitted"); return;
    }
    EM.setTitle(def.title); root.innerHTML = EM.loading();
    if (EM.afterNav) EM.afterNav(def);
    try { const r = await def.render(root, ctx); if (typeof r === "function") cleanup = r; }
    catch (e) { if (id === EM.renderId) { root.innerHTML = `<div class="card">${EM.alert(e.message || "This page could not be loaded.", "bad")}<p></p><button class="btn" id="retryBtn">Try again</button></div>`; const rb = $("#retryBtn", root); if (rb) rb.onclick = () => EM.route(); } }
    const h = $("#main h1, #main h2"); if (h && id === EM.renderId) { /* keep focus management light: move to main on navigation */ $("#main").focus({ preventScroll: true }); }
  };
  EM.setTitle = t => { document.title = (t ? t + " · " : "") + "Exam Monitor Ultimate"; const h = $("#pageTitle"); if (h) h.textContent = t || ""; };
  window.addEventListener("hashchange", () => EM.route());
})();
