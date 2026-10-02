// UploadZone: drag & drop, click/keyboard browse, file preview, remove, loading/success/error states.
// The real <input type="file"> stays in the DOM (visually covering the drop area) for full accessibility.

import { el, icon, formatBytes } from "./dom.js";
import { t } from "./i18n.js";

const ACCEPT = [".docx", ".txt", ".md"];

export class UploadZone {
  constructor(mount, { id, maxBytes = 5 * 1024 * 1024, samples = [], onSample } = {}) {
    this.mount = mount;
    this.id = id;
    this.maxBytes = maxBytes;
    this.samples = samples;
    this.onSample = onSample;
    this.file = null;
    this.render();
  }

  render() {
    const inputId = `${this.id}-file`;
    this.input = el("input", { class: "upload__input", type: "file", id: inputId, accept: ACCEPT.join(","),
      "aria-describedby": `${inputId}-types ${inputId}-msg` });
    this.input.addEventListener("change", () => this.input.files[0] && this.setFile(this.input.files[0]));

    this.titleDefault = el("span", { class: "upload__title-default" });
    this.titleDrag = el("span", { class: "upload__title-drag" });
    this.browse = el("span", { class: "upload__browse" });
    this.orText = el("span");
    this.types = el("span", { class: "upload__types", id: `${inputId}-types` });
    const drop = el("label", { class: "upload__drop", for: inputId },
      el("span", { class: "upload__glyph" }, icon("file-up", "icon-lg")),
      el("span", { class: "upload__title" }, this.titleDefault, this.titleDrag),
      el("span", { class: "t-secondary" }, this.orText, " ", this.browse),
      this.types,
      this.input);

    this.fileName = el("div", { class: "upload__file-name" });
    this.fileMeta = el("div", { class: "upload__file-meta t-meta" });
    this.fileBadge = el("span", { class: "upload__file-icon" });
    this.stateOk = el("span", { class: "upload__state upload__state--ok" }, icon("circle-check", "icon-sm"));
    this.stateErr = el("span", { class: "upload__state upload__state--err" }, icon("circle-alert", "icon-sm"));
    this.replaceBtn = el("button", { type: "button", class: "btn btn--quiet", onclick: () => this.input.click() });
    this.removeBtn = el("button", { type: "button", class: "btn btn--quiet", onclick: () => this.clear(true) },
      icon("x", "icon-sm"));
    this.removeLabel = el("span");
    this.removeBtn.append(this.removeLabel);
    const fileCard = el("div", { class: "upload__file", role: "group" },
      this.fileBadge,
      el("div", {}, this.fileName, this.fileMeta),
      el("div", { class: "upload__file-actions" }, this.replaceBtn, this.removeBtn),
      el("div", { class: "upload__progress", role: "progressbar", "aria-hidden": "true" }));

    this.message = el("p", { class: "upload__message", id: `${inputId}-msg`, role: "alert" });

    this.sampleWrap = el("div", { class: "samples" });
    this.root = el("div", { class: "upload" }, drop, fileCard, this.message, this.sampleWrap);

    // drag & drop (on the whole component so dropping on the file card replaces the file)
    let depth = 0;
    this.root.addEventListener("dragenter", (e) => { e.preventDefault(); depth++; this.root.classList.add("is-dragging"); });
    this.root.addEventListener("dragover", (e) => { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; });
    this.root.addEventListener("dragleave", () => { if (--depth <= 0) { depth = 0; this.root.classList.remove("is-dragging"); } });
    this.root.addEventListener("drop", (e) => {
      e.preventDefault(); depth = 0; this.root.classList.remove("is-dragging");
      const f = e.dataTransfer.files[0];
      if (f) this.setFile(f);
    });

    this.mount.replaceChildren(this.root);
    this.translate();
  }

  translate() {
    this.titleDefault.textContent = t("upload.drop");
    this.titleDrag.textContent = t("upload.dragActive");
    this.orText.textContent = t("upload.or");
    this.browse.textContent = t("upload.browse");
    this.types.textContent = t("upload.types", { mb: Math.round(this.maxBytes / 1024 / 1024) });
    this.replaceBtn.textContent = t("upload.replace");
    this.removeLabel.textContent = t("upload.remove");
    this.removeBtn.setAttribute("aria-label", t("upload.remove"));
    this.sampleWrap.replaceChildren(
      el("span", { text: t("upload.sampleLabel") }),
      ...this.samples.map((s) => el("button", { type: "button", class: "btn btn--quiet", text: t(s.label),
        onclick: () => this.onSample?.(s.name) })));
    if (this.file) this.describe();
  }

  kindLabel(name) {
    const ext = name.split(".").pop().toLowerCase();
    return { docx: t("upload.kindDocx"), txt: t("upload.kindText"), md: t("upload.kindMd") }[ext] ?? ext;
  }

  describe() {
    const ext = this.file.name.split(".").pop().toLowerCase();
    this.fileBadge.textContent = ext;
    this.fileName.textContent = this.file.name;
    this.fileMeta.replaceChildren(el("span", { text: this.kindLabel(this.file.name) }),
      el("span", { text: formatBytes(this.file.size) }), this.stateOk, this.stateErr);
  }

  validate(file) {
    const ext = `.${file.name.split(".").pop().toLowerCase()}`;
    if (!ACCEPT.includes(ext)) return t("upload.errType");
    if (file.size === 0) return t("upload.errEmpty");
    if (file.size > this.maxBytes) return t("upload.errSize", { mb: Math.round(this.maxBytes / 1024 / 1024) });
    return "";
  }

  setFile(file) {
    const problem = this.validate(file);
    if (problem) { this.showError(problem); this.input.value = ""; return false; }
    this.file = file;
    this.message.textContent = "";
    this.root.classList.remove("is-success", "is-error");
    this.root.classList.add("has-file");
    this.describe();
    return true;
  }

  clear(focus = false) {
    this.file = null;
    this.input.value = "";
    this.message.textContent = "";
    this.root.classList.remove("has-file", "is-success", "is-error", "is-loading");
    if (focus) this.input.focus();
  }

  showError(message) {
    this.message.textContent = message;
    this.root.classList.add("is-error");
    this.root.classList.remove("is-success");
  }

  setState(state) {
    this.root.classList.toggle("is-loading", state === "loading");
    this.root.classList.toggle("is-success", state === "success");
    this.root.classList.toggle("is-error", state === "error");
  }

  setMax(bytes) { this.maxBytes = bytes; this.translate(); }
}
