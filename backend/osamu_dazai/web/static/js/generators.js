// Generator library. Data-driven: one entry per generator, three visual treatments by category.

import { el, icon } from "./dom.js";
import { t } from "./i18n.js";

const CFG = "--config config/providers.toml";
export const CATEGORIES = [
  { id: "course", style: "list", items: [
    { id: "curriculum", icon: "graduation-cap", cmd: `python -m osamu_dazai.pipeline plan "…" ${CFG} --out brief.json\npython -m osamu_dazai.pipeline design brief.json ${CFG} --out-dir course/` },
    { id: "graph", icon: "network", cmd: `python -m osamu_dazai.pipeline design brief.json ${CFG} --out-dir course/` },
    { id: "studentBook", icon: "book-open", cmd: `python -m osamu_dazai.pipeline write course/ ${CFG}` },
    { id: "teacherGuide", icon: "clipboard-list", cmd: `python -m osamu_dazai.pipeline teach course/ ${CFG}` },
  ] },
  { id: "assessment", style: "tiles", items: [
    { id: "ieltsReading", icon: "book-text", cmd: `python -m osamu_dazai.ielts generate test.docx ${CFG} --topics "…" "…" "…"` },
    { id: "ieltsListening", icon: "headphones", cmd: `python -m osamu_dazai.ielts listening out/ ${CFG} --topics "…" "…" "…" "…"` },
    { id: "ieltsWriting", icon: "pen-line", cmd: `python -m osamu_dazai.ielts writing out/ ${CFG} --module academic --task1 "…" --task2 "…"` },
    { id: "ieltsSpeaking", icon: "mic", cmd: `python -m osamu_dazai.ielts speaking out/ ${CFG} --theme "…"` },
  ] },
  { id: "content", style: "chips", items: [
    { id: "visuals", icon: "image", cmd: `python -m osamu_dazai.pipeline visuals course/ ${CFG}` },
    { id: "exercises", icon: "list-checks", cmd: `python -m osamu_dazai.pipeline write course/ ${CFG}` },
    { id: "vocabulary", icon: "spell-check", cmd: `python -m osamu_dazai.pipeline term kb.json variables uz "oʻzgaruvchi"` },
    { id: "tests", icon: "file-question", cmd: `python -m osamu_dazai.pipeline assess course/ ${CFG} --versions 4` },
  ] },
];

const HEADS = { course: "catCourse", assessment: "catAssessment", content: "catContent" };

function statusBadge(aiEnabled) {
  return aiEnabled ? el("span", { class: "badge badge--success", text: t("gen.statusReady") })
    : el("span", { class: "badge badge--neutral", text: t("gen.statusCli") });
}

function commandToggle(item, host) {
  const btn = el("button", { type: "button", class: "btn btn--quiet", "aria-expanded": "false" },
    icon("terminal", "icon-sm"), el("span", { text: t("gen.showCmd") }));
  let block = null;
  btn.addEventListener("click", () => {
    const open = btn.getAttribute("aria-expanded") === "true";
    btn.setAttribute("aria-expanded", String(!open));
    btn.lastChild.textContent = t(open ? "gen.showCmd" : "gen.hideCmd");
    if (open) { block?.remove(); block = null; return; }
    const copy = el("button", { type: "button", class: "btn" }, icon("copy", "icon-sm"), el("span", { text: t("gen.copy") }));
    copy.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(item.cmd); copy.lastChild.textContent = t("gen.copied"); }
      catch { /* clipboard unavailable — the text stays selectable */ }
      setTimeout(() => { copy.lastChild.textContent = t("gen.copy"); }, 1600);
    });
    block = el("div", { class: "cmd" }, el("code", { text: item.cmd }), copy);
    host.append(block);
  });
  return btn;
}

function listItem(item, ai) {
  const row = el("li", { class: "gen-row" },
    el("span", { class: "gen-row__icon" }, icon(item.icon)),
    el("div", {}, el("div", { class: "gen-row__title", text: t(`gen.${item.id}`) }),
      el("p", { class: "gen-row__desc", text: t(`gen.${item.id}Desc`) })));
  row.append(el("div", { class: "gen-row__aside" }, statusBadge(ai), commandToggle(item, row)));
  return row;
}

function tile(item, ai) {
  const node = el("li", { class: "ielts-tile" },
    el("div", { class: "ielts-tile__top" }, el("span", { class: "t-label", text: "IELTS" }), icon(item.icon)),
    el("div", { class: "ielts-tile__name", text: t(`gen.${item.id}`) }),
    el("p", { text: t(`gen.${item.id}Desc`) }));
  node.append(el("div", { class: "ielts-tile__foot" }, statusBadge(ai), commandToggle(item, node)));
  return node;
}

function chip(item, ai) {
  const node = el("li", { class: "chip" }, icon(item.icon),
    el("h3", { text: t(`gen.${item.id}`) }), el("p", { text: t(`gen.${item.id}Desc`) }));
  node.append(el("div", { class: "chip__foot" }, statusBadge(ai), commandToggle(item, node)));
  return node;
}

export function renderLibrary(target, { aiEnabled = false } = {}) {
  target.replaceChildren(...CATEGORIES.map((cat) => {
    const head = HEADS[cat.id];
    const items = cat.items.map((it) => (cat.style === "tiles" ? tile : cat.style === "chips" ? chip : listItem)(it, aiEnabled));
    const listClass = cat.style === "tiles" ? "ielts-grid" : cat.style === "chips" ? "chips" : "gen-list";
    return el("section", { class: "category", "aria-labelledby": `cat-${cat.id}` },
      el("div", { class: "category__head" },
        el("span", { class: "category__count", text: String(cat.items.length).padStart(2, "0") }),
        el("h2", { id: `cat-${cat.id}`, text: t(`gen.${head}`) }),
        el("p", { text: t(`gen.${head}Desc`) })),
      el("ul", { class: listClass }, ...items));
  }));
}
