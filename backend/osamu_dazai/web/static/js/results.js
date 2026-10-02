// ResultPanel renderers for the validator and Format Repair. Pure functions of the API response,
// so a language switch simply re-renders the last result.

import { el, icon } from "./dom.js";
import { t } from "./i18n.js";
import { downloadBase64 } from "./api.js";

export function renderEmpty(target, page) {
  target.replaceChildren(el("div", { class: "empty" },
    el("span", { class: "empty__icon" }, icon(page === "repair" ? "wrench" : "file-search")),
    el("div", {}, el("h3", { text: t(`${page}.emptyTitle`) }), el("p", { text: t(`${page}.emptyDesc`) }))));
}

export function renderError(target, message) {
  target.replaceChildren(el("div", { class: "notice notice--error result", role: "alert" },
    icon("circle-alert"), el("p", { text: message })));
}

function badge(severity) {
  return el("span", { class: `badge badge--${severity === "error" ? "error" : "warning"}`,
    text: t(severity === "error" ? "result.error" : "result.warning") });
}

function issueRow(i, n) {
  const excerpt = i.excerpt ? el("code", { class: "issue__excerpt", text: i.excerpt }) : null;
  return el("li", { class: "issue", "data-severity": i.severity, style: `animation-delay:${Math.min(n, 12) * 25}ms` },
    el("div", { class: "issue__head-row" }, badge(i.severity)),
    el("div", { class: "issue__loc" }, el("span", { class: "issue__mlabel", text: t("result.colLocation") }),
      i.location, el("span", { class: "issue__code", text: i.code })),
    el("div", {}, el("span", { class: "issue__mlabel", text: t("result.colIssue") }),
      el("p", { class: "issue__problem", text: i.problem }), excerpt),
    el("div", { class: "issue__expected" }, el("span", { class: "issue__mlabel", text: t("result.colExpected") }),
      i.expected || "—"),
    el("div", { class: "issue__fix" }, el("span", { class: "issue__mlabel", text: t("result.colFix") }),
      i.suggestion || "—"));
}

export function issueList(issues, { filters = true } = {}) {
  const frag = [];
  const errors = issues.filter((i) => i.severity === "error").length;
  const warnings = issues.length - errors;
  const list = el("ul", { class: "issues" },
    el("li", { class: "issues__head t-label", "aria-hidden": "true" },
      el("span", { text: t("result.colSeverity") }), el("span", { text: t("result.colLocation") }),
      el("span", { text: t("result.colIssue") }), el("span", { text: t("result.colExpected") }),
      el("span", { text: t("result.colFix") })),
    ...issues.map(issueRow));
  if (filters && errors && warnings) {
    const buttons = [["all", t("result.filterAll"), issues.length], ["error", t("result.filterErrors"), errors],
      ["warning", t("result.filterWarnings"), warnings]].map(([key, label, count]) =>
      el("button", { type: "button", class: "filter", "aria-pressed": key === "all" ? "true" : "false", "data-filter": key },
        label, el("span", { class: "filter__count", text: count })));
    const bar = el("div", { class: "filters", role: "toolbar" }, ...buttons);
    bar.addEventListener("click", (e) => {
      const b = e.target.closest("[data-filter]");
      if (!b) return;
      for (const x of buttons) x.setAttribute("aria-pressed", String(x === b));
      for (const row of list.querySelectorAll(".issue")) {
        row.hidden = b.dataset.filter !== "all" && row.dataset.severity !== b.dataset.filter;
      }
    });
    frag.push(bar);
  }
  frag.push(list);
  return frag;
}

function summary(kind, title, sub, meta) {
  const glyph = { ok: "circle-check", bad: "circle-alert", warn: "triangle-alert" }[kind];
  return el("div", { class: "result__summary" },
    el("span", { class: `result__status result__status--${kind}` }, icon(glyph, "icon-lg")),
    el("div", {}, el("div", { class: "result__title", text: title }), sub ? el("p", { class: "result__sub", text: sub }) : null),
    meta ? el("div", { class: "result__meta t-meta", text: meta }) : null);
}

export function renderValidation(target, r) {
  const kindLabel = t(`doctype.${r.kind}`);
  const meta = t("result.meta", { file: r.file, lines: r.lines, kind: kindLabel });
  const counts = t("result.counts", { errors: r.errors, warnings: r.warnings });
  const panel = el("div", { class: "panel result" },
    r.passed && !r.issues.length
      ? summary("ok", t("result.valid"), t("result.validDesc"), meta)
      : summary(r.passed ? "warn" : "bad", r.passed ? t("result.valid") : t("result.invalid"), counts, meta));
  if (r.issues.length) {
    panel.append(el("div", { class: "result__body" }, ...issueList(r.issues)),
      el("p", { class: "result__note", text: t("result.englishNote") }));
  }
  target.replaceChildren(panel);
}

function opRow(o, n) {
  const label = t(`repair.op_${o.kind}`);
  const lines = [];
  if (o.before) lines.push(el("div", { class: "op__line op__line--before" },
    el("span", { text: t("repair.before") }), el("code", { text: o.before })));
  if (o.after?.length) lines.push(el("div", { class: "op__line op__line--after" },
    el("span", { text: t("repair.after") }), el("code", { text: o.after.join("\n") })));
  return el("li", { class: "op", style: `animation-delay:${Math.min(n, 12) * 25}ms` },
    el("div", { class: "op__kind" }, el("strong", { text: label === `repair.op_${o.kind}` ? o.kind : label }),
      el("span", { class: "t-meta", text: o.line ? t("repair.line", { n: o.line }) : t("repair.wholeDoc") }),
      el("span", { class: "t-meta", text: t("repair.confidence", { c: o.confidence.toFixed(2) }) })),
    el("div", { class: "op__diff" }, ...lines, o.reason ? el("span", { class: "t-caption", text: o.reason }) : null));
}

function flagRow(f, n) {
  return el("li", { class: "op op--review", style: `animation-delay:${Math.min(n, 12) * 25}ms` },
    el("div", { class: "op__kind" }, el("span", { class: "badge badge--warning", text: t("repair.statReview") }),
      el("span", { class: "t-meta", text: t("repair.line", { n: f.line }) }),
      el("span", { class: "t-meta", text: t("repair.confidence", { c: f.confidence.toFixed(2) }) })),
    el("div", { class: "op__diff" }, el("p", { class: "issue__problem", text: `${f.problem} — ${f.proposal}` }),
      el("div", { class: "op__line op__line--before" }, el("span", { text: t("result.text") }),
        el("code", { text: f.excerpt }))));
}

function disclosure(title, count, kind, body, open = true) {
  return el("details", { class: "disclosure", open },
    el("summary", {}, icon("chevron-right", "icon-sm"), el("span", { text: title }),
      el("span", { class: `badge badge--${kind}`, text: String(count) })),
    el("div", { class: "disclosure__body" }, body));
}

export function renderRepair(target, r) {
  const repaired = r.ops.filter((o) => o.kind !== "trim").length;
  const review = r.flags.length;
  const remaining = r.validation ? r.validation.errors : 0;
  const detected = repaired + review + (r.exported ? 0 : remaining);
  const panel = el("div", { class: "panel result" });

  if (!r.preserved) {
    panel.append(summary("bad", t("repair.rejected"), t("repair.rejectedDesc"), r.file));
  } else {
    panel.append(summary(r.exported ? "ok" : "warn", r.exported ? t("repair.complete") : t("repair.attention"),
      null, `${r.file} · ${t(`doctype.${r.kind}`)}`));
    panel.append(el("div", { class: "stats" },
      el("div", { class: "stat" }, el("div", { class: "stat__value", text: detected }),
        el("div", { class: "stat__label t-label", text: t("repair.statDetected") })),
      el("div", { class: "stat stat--ok" }, el("div", { class: "stat__value", text: repaired }),
        el("div", { class: "stat__label t-label", text: t("repair.statRepaired") })),
      el("div", { class: `stat ${review ? "stat--warn" : ""}` }, el("div", { class: "stat__value", text: review }),
        el("div", { class: "stat__label t-label", text: t("repair.statReview") }))));
    if (r.exported) {
      const btn = el("button", { type: "button", class: "btn btn--primary" }, icon("download", "icon-sm"),
        el("span", { text: t("repair.download") }));
      btn.addEventListener("click", () => downloadBase64(r.docx_base64, r.download_name));
      panel.append(el("div", { class: "download-row" }, btn,
        el("p", {}, icon("circle-check", "icon-sm"), el("span", { text: t("repair.validated") }))));
    } else {
      panel.append(el("div", { class: "download-row" },
        el("p", {}, icon("info", "icon-sm"), el("span", { text: t("repair.notExported") }))));
    }
  }
  const realOps = r.ops.filter((o) => o.kind !== "trim");
  if (r.flags.length) panel.append(disclosure(t("repair.reviewTitle"), r.flags.length, "warning",
    el("ul", { class: "ops" }, ...r.flags.map(flagRow))));
  if (realOps.length) panel.append(disclosure(t("repair.appliedTitle"), realOps.length, "success",
    el("ul", { class: "ops" }, ...realOps.map(opRow)), !r.flags.length));
  const issues = r.validation?.issues ?? [];
  if (issues.length) panel.append(disclosure(t("repair.remainingTitle"), issues.length, "error",
    el("div", {}, ...issueList(issues, { filters: false }))));
  if (r.groups?.length) panel.append(disclosure(t("repair.groupsTitle"), r.groups.length, "neutral",
    el("ul", { class: "groups" }, ...r.groups.map((g) => el("li", { text: g }))), false));
  if (issues.length || r.flags.length) panel.append(el("p", { class: "result__note", text: t("result.englishNote") }));
  target.replaceChildren(panel);
}
