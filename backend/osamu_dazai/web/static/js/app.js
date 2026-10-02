// AppShell: routing, navigation, language selection, page wiring.

import { $, $$, storage } from "./dom.js";
import { apply, initialLang, lang, setLang, t } from "./i18n.js";
import { ApiError, fetchSample, getConfig, post } from "./api.js";
import { UploadZone } from "./upload-zone.js";
import { renderEmpty, renderError, renderRepair, renderValidation } from "./results.js";
import { renderLibrary } from "./generators.js";

const state = { config: { ai_enabled: false, max_upload_mb: 5, version: "" }, last: { validate: null, repair: null } };
const ROUTES = ["/", "/validate", "/repair", "/generate", "/about"];

// ---------------- routing ----------------
function currentRoute() {
  const path = location.hash.replace(/^#/, "") || "/";
  return ROUTES.includes(path) ? path : "/";
}

function route({ focus = true } = {}) {
  const path = currentRoute();
  for (const page of $$("[data-page]")) {
    const match = page.dataset.page === path;
    if (match && page.hidden) {
      page.hidden = false;
      page.classList.remove("is-entering");
      void page.offsetWidth; // restart the entrance animation
      page.classList.add("is-entering");
    } else if (!match) {
      page.hidden = true;
    }
  }
  for (const a of $$(".nav-link")) {
    if (a.dataset.route === path) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  }
  closeMenu();
  const titleKey = { "/": null, "/validate": "validate.title", "/repair": "repair.title", "/generate": "gen.title",
    "/about": "nav.about" }[path];
  document.title = titleKey ? `${t(titleKey)} — Osamu Dazai` : `Osamu Dazai — ${t("brand.tagline")}`;
  if (path !== "/") storage.set("dazai-last-tool", path.slice(1));
  if (focus) {
    window.scrollTo({ top: 0 });
    $(`[data-page="${path}"] h1`)?.setAttribute("tabindex", "-1");
    $(`[data-page="${path}"] h1`)?.focus({ preventScroll: true });
  }
  markLastUsed();
}

// ---------------- mobile menu ----------------
const toggle = $("#menu-toggle");
const panel = $("#nav-panel");
function setMenu(open) {
  panel.classList.toggle("is-open", open);
  toggle.setAttribute("aria-expanded", String(open));
  const label = toggle.querySelector("[data-i18n]");
  label.dataset.i18n = open ? "nav.close" : "nav.menu";  // keeps the label right across language changes
  label.textContent = t(label.dataset.i18n);
}
function closeMenu() { setMenu(false); }
toggle.addEventListener("click", () => setMenu(!panel.classList.contains("is-open")));
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && panel.classList.contains("is-open")) { closeMenu(); toggle.focus(); } });

// ---------------- language ----------------
for (const input of $$("#lang-selector input")) {
  input.addEventListener("change", () => input.checked && setLang(input.value));
}
document.addEventListener("langchange", () => {
  for (const input of $$("#lang-selector input")) input.checked = input.value === lang();
  greet();
  for (const z of Object.values(zones)) z.translate();
  renderLibrary($("#generator-library"), { aiEnabled: state.config.ai_enabled });
  renderConfig();
  for (const page of ["validate", "repair"]) renderLast(page);
  route({ focus: false });
});

// ---------------- workspace ----------------
function greet() {
  const h = new Date().getHours();
  $("#greeting").textContent = t(h < 12 ? "greeting.morning" : h < 18 ? "greeting.afternoon" : "greeting.evening");
}

function markLastUsed() {
  const last = storage.get("dazai-last-tool");
  for (const a of $$(".tool[data-tool]")) {
    a.querySelector(".badge")?.remove();
    if (a.dataset.tool === last) {
      const b = document.createElement("span");
      b.className = "badge badge--accent";
      b.textContent = t("dash.lastUsed");
      a.querySelector(".tool__title").append(b);
    }
  }
}

// ---------------- tools ----------------
const zones = {};

function renderLast(page) {
  const target = $(`#${page}-results [data-results]`);
  const last = state.last[page];
  if (!last) return renderEmpty(target, page);
  if (last.error) return renderError(target, last.error);
  (page === "validate" ? renderValidation : renderRepair)(target, last.data);
}

function setBusy(form, busy) {
  const btn = form.querySelector("button[type=submit]");
  const label = btn.querySelector("[data-label]");
  btn.disabled = busy;
  btn.classList.toggle("is-busy", busy);
  label.textContent = t(busy ? label.dataset.busy : label.dataset.label);
  label.dataset.i18n = busy ? label.dataset.busy : label.dataset.label;
}

function wireTool(page, endpoint) {
  const form = $(`#${page}-form`);
  const zone = new UploadZone($(`[data-upload="${page}"]`), {
    id: page, maxBytes: state.config.max_upload_mb * 1024 * 1024,
    samples: page === "validate"
      ? [{ name: "broken_reading.docx", label: "upload.sampleBroken" }, { name: "clean_reading.docx", label: "upload.sampleClean" }]
      : [{ name: "broken_reading.docx", label: "upload.sampleBroken" }],
    onSample: async (name) => {
      try { zone.setFile(await fetchSample(name)); run(); }
      catch (e) { zone.showError(e.message); }
    },
  });
  zones[page] = zone;

  async function run() {
    if (!zone.file) { zone.showError(t("upload.required")); zone.input.focus(); return; }
    const fd = new FormData();
    fd.append("file", zone.file, zone.file.name);
    fd.append("kind", form.querySelector("input[name=kind]:checked").value);
    if (page === "repair") fd.append("threshold", $("#r-threshold").value);
    setBusy(form, true);
    zone.setState("loading");
    try {
      const data = await post(endpoint, fd);
      state.last[page] = { data };
      const ok = page === "validate" ? data.passed : data.exported;
      zone.setState(ok ? "success" : "error");
    } catch (e) {
      state.last[page] = { error: e instanceof ApiError ? e.message : t("err.network") };
      zone.setState("error");
    } finally {
      setBusy(form, false);
    }
    renderLast(page);
    const results = $(`#${page}-results`);
    if (results.getBoundingClientRect().top > window.innerHeight * 0.6) results.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  form.addEventListener("submit", (e) => { e.preventDefault(); run(); });
}

// ---------------- repair slider ----------------
const slider = $("#r-threshold");
function paintSlider() {
  const pct = ((slider.value - slider.min) / (slider.max - slider.min)) * 100;
  slider.style.setProperty("--pct", `${pct}%`);
  $("#r-threshold-out").textContent = Number(slider.value).toFixed(2);
}
slider.addEventListener("input", paintSlider);

// ---------------- about: section index ----------------
for (const a of $$(".toc a")) {
  a.addEventListener("click", (e) => {
    e.preventDefault();
    $(`#about-${a.dataset.section}`).scrollIntoView({ behavior: "smooth", block: "start" });
  });
}
if ("IntersectionObserver" in window) {
  const io = new IntersectionObserver((entries) => {
    for (const en of entries) {
      if (!en.isIntersecting) continue;
      const id = en.target.id.replace("about-", "");
      for (const a of $$(".toc a")) a.classList.toggle("is-active", a.dataset.section === id);
    }
  }, { rootMargin: "-30% 0px -60% 0px" });
  for (const s of $$(".article section")) io.observe(s);
}

// ---------------- config ----------------
function renderConfig() {
  const c = state.config;
  const notice = $("#ai-notice");
  notice.classList.toggle("notice--ok", !!c.ai_enabled);
  notice.querySelector("p").textContent = t(c.ai_enabled ? "gen.aiOn" : "gen.aiOff");
  notice.querySelector("p").dataset.i18n = c.ai_enabled ? "gen.aiOn" : "gen.aiOff";
  if (c.version) {
    $("#footer-version").textContent = t("footer.version", { v: c.version });
    $("#version-line").textContent = t("footer.version", { v: c.version });
  }
}

// ---------------- boot ----------------
async function boot() {
  await setLang(initialLang(), { persist: false });
  try { state.config = { ...state.config, ...(await getConfig()) }; } catch { /* informational only */ }
  greet();
  wireTool("validate", "/api/ielts/validate");
  wireTool("repair", "/api/ielts/repair");
  renderLibrary($("#generator-library"), { aiEnabled: state.config.ai_enabled });
  renderConfig();
  renderLast("validate");
  renderLast("repair");
  paintSlider();
  apply();
  route({ focus: false });
  window.addEventListener("hashchange", () => route());
}

boot();
