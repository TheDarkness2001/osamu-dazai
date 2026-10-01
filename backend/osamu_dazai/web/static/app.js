// Osamu Dazai website. No framework; every server value is inserted with textContent (never innerHTML).
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const el = (tag, attrs = {}, ...children) => {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else node.setAttribute(k, v);
  }
  for (const c of children) if (c != null) node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return node;
};

let password = sessionStorageGet("dazai-password");
function sessionStorageGet(k) { try { return sessionStorage.getItem(k) || ""; } catch { return ""; } }
function sessionStorageSet(k, v) { try { sessionStorage.setItem(k, v); } catch { /* private mode */ } }

// ---- routing ---------------------------------------------------------------
function route() {
  const path = (location.hash.replace(/^#/, "") || "/");
  let shown = false;
  for (const page of document.querySelectorAll("[data-page]")) {
    const match = page.dataset.page === path;
    page.hidden = !match;
    shown ||= match;
  }
  if (!shown) $("[data-page='/']").hidden = false;
  for (const a of document.querySelectorAll("nav a")) {
    if (a.dataset.route === path) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  }
  $("#nav").classList.remove("open");
  $("#menu-toggle").setAttribute("aria-expanded", "false");
  $("#app").focus({ preventScroll: true });
}
window.addEventListener("hashchange", route);
$("#menu-toggle").addEventListener("click", () => {
  const open = $("#nav").classList.toggle("open");
  $("#menu-toggle").setAttribute("aria-expanded", String(open));
});

// ---- API ---------------------------------------------------------------------
async function api(path, form) {
  const headers = password ? { "X-Dazai-Password": password } : {};
  const res = await fetch(path, { method: "POST", body: form, headers });
  if (res.status === 401) {
    const p = window.prompt("This site is password-protected. Password:");
    if (p) { password = p; sessionStorageSet("dazai-password", p); return api(path, form); }
  }
  let body = null;
  try { body = await res.json(); } catch { /* non-JSON error */ }
  if (!res.ok) throw new Error((body && (typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail)))
    || `Request failed (${res.status})`);
  return body;
}

function busy(form, on) {
  for (const b of form.querySelectorAll("button")) b.disabled = on;
  const submit = form.querySelector("button[type=submit]");
  if (on) { submit.dataset.label = submit.textContent; submit.textContent = "Working…"; }
  else if (submit.dataset.label) submit.textContent = submit.dataset.label;
}

function showError(target, err) {
  target.replaceChildren(el("div", { class: "error-box", role: "alert", text: err.message || String(err) }));
}

// ---- rendering ---------------------------------------------------------------------
function issueCard(i) {
  const dl = el("dl");
  const row = (k, v, cls) => { if (v) dl.append(el("dt", { text: k }), el("dd", cls ? { class: cls, text: v } : { text: v })); };
  row("Problem", i.problem);
  row("Text", i.excerpt, "excerpt");
  row("Expected", i.expected);
  row("Suggested fix", i.suggestion);
  return el("article", { class: `issue ${i.severity}` },
    el("div", { class: "head" },
      el("span", { class: `pill ${i.severity === "error" ? "err" : "warn"}`, text: i.severity.toUpperCase() }),
      el("span", { class: "loc", text: i.location }),
      el("span", { class: "code", text: i.code })),
    dl);
}

function summaryBar(passed, errors, warnings, extra) {
  return el("div", { class: "summary" },
    el("span", { class: `pill ${passed ? "ok" : "err"}`, text: passed ? "PASSED" : "FAILED" }),
    el("span", { text: `${errors} error(s), ${warnings} warning(s)` }),
    extra ?? null);
}

function renderValidation(target, r) {
  const nodes = [summaryBar(r.passed, r.errors, r.warnings, el("span", { class: "muted", text: `${r.file} · ${r.lines} lines · ${r.kind}` }))];
  if (r.issues.length === 0) nodes.push(el("p", { class: "notice ok", text: "No issues: the document follows the import contract." }));
  for (const i of r.issues) nodes.push(issueCard(i));
  target.replaceChildren(...nodes);
}

function downloadBase64(b64, name) {
  const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], {
    type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" }));
  const a = el("a", { href: url, download: name });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

function renderRepair(target, r) {
  const nodes = [];
  const v = r.validation;
  if (!r.preserved) {
    nodes.push(el("div", { class: "error-box", role: "alert",
      text: "Repair was rejected because it would have changed the document's wording. Nothing was exported." }));
  } else if (r.exported) {
    const btn = el("button", { class: "primary", type: "button", text: `Download ${r.download_name}` });
    btn.addEventListener("click", () => downloadBase64(r.docx_base64, r.download_name));
    nodes.push(el("div", { class: "summary" },
      el("span", { class: "pill ok", text: "FIXED" }),
      el("span", { text: `${r.ops.filter(o => o.kind === "split").length} line break(s) inserted · text preserved · validation passed` }),
      btn));
  } else {
    nodes.push(summaryBar(false, v ? v.errors : 0, v ? v.warnings : 0,
      el("span", { class: "muted", text: "Not exported — see the remaining problems and review items below." })));
  }
  if (r.groups.length) {
    nodes.push(el("details", {}, el("summary", { text: `Detected question groups (${r.groups.length})` }),
      el("ul", {}, ...r.groups.map(g => el("li", { text: g })))));
  }
  if (r.ops.length) {
    const list = el("div", { class: "result" });
    for (const o of r.ops) {
      const dl = el("dl");
      if (o.before) dl.append(el("dt", { text: "Before" }), el("dd", { class: "excerpt", text: o.before }));
      if (o.after.length) dl.append(el("dt", { text: "After" }), el("dd", { class: "excerpt", text: o.after.join("\n⏎ ") }));
      list.append(el("article", { class: "issue op" },
        el("div", { class: "head" },
          el("span", { class: "pill ok", text: o.kind.replace(/_/g, " ") }),
          el("span", { class: "loc", text: o.line ? `Line ${o.line}` : "Whole document" }),
          el("span", { class: "code", text: `confidence ${o.confidence}` })),
        el("p", { text: o.reason }), dl));
    }
    nodes.push(el("details", { open: "" }, el("summary", { text: `Repairs applied (${r.ops.length})` }), list));
  }
  if (r.flags.length) {
    const list = el("div", { class: "result" });
    for (const f of r.flags) {
      list.append(el("article", { class: "issue warning" },
        el("div", { class: "head" }, el("span", { class: "pill warn", text: "REVIEW" }),
          el("span", { class: "loc", text: `Line ${f.line}` })),
        el("p", { text: `${f.problem} — ${f.proposal}` }),
        el("p", { class: "excerpt", text: f.excerpt })));
    }
    nodes.push(el("details", { open: "" }, el("summary", { text: `Needs your review (${r.flags.length})` }), list));
  }
  if (v && v.issues.length) {
    nodes.push(el("details", { open: "" }, el("summary", { text: `Validation of the result (${v.issues.length})` }),
      el("div", { class: "result" }, ...v.issues.map(issueCard))));
  }
  target.replaceChildren(...nodes);
}

// ---- forms ----------------------------------------------------------------------------
function wire(formId, endpoint, resultId, render) {
  const form = $(formId);
  const target = $(resultId);
  const run = async (fd) => {
    busy(form, true);
    target.replaceChildren(el("p", { class: "muted", text: "Checking…" }));
    try { render(target, await api(endpoint, fd)); }
    catch (err) { showError(target, err); }
    finally { busy(form, false); }
  };
  form.addEventListener("submit", (e) => { e.preventDefault(); run(new FormData(form)); });
  return run;
}

const runners = {
  validate: wire("#validate-form", "/api/ielts/validate", "#validate-result", renderValidation),
  repair: wire("#repair-form", "/api/ielts/repair", "#repair-result", renderRepair),
};

for (const btn of document.querySelectorAll("[data-sample]")) {
  btn.addEventListener("click", async () => {
    const form = btn.closest("form");
    try {
      const res = await fetch(`/api/samples/${btn.dataset.sample}`);
      if (!res.ok) throw new Error("Could not load the sample file.");
      const fd = new FormData(form);
      fd.set("file", new File([await res.blob()], btn.dataset.sample));
      runners[btn.dataset.target](fd);
    } catch (err) { showError($(`#${btn.dataset.target}-result`), err); }
  });
}

const slider = $("#r-threshold");
slider.addEventListener("input", () => { $("#r-threshold-out").textContent = Number(slider.value).toFixed(2); });

// ---- config ---------------------------------------------------------------------------
fetch("/api/config").then(r => r.json()).then(cfg => {
  $("#version-line").textContent = `Version ${cfg.version} · uploads up to ${cfg.max_upload_mb} MB`;
  const notice = $("#ai-notice");
  if (cfg.ai_enabled) {
    notice.className = "notice ok";
    notice.textContent = "An AI provider is configured on this server.";
    $("#ai-status-inline").textContent = "AI provider configured.";
  } else {
    notice.textContent = "AI generation is not enabled on this website yet (no AI provider key is configured).";
  }
}).catch(() => { /* config is informational */ });

route();
