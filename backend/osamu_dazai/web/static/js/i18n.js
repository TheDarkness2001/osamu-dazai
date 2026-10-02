// Frontend translation system.
// Dictionaries live in /static/locales/{en,uz,ru}.json. Static markup uses
//   data-i18n="key"                      → textContent
//   data-i18n-attr="aria-label:key,…"    → attributes
// Dynamic UI calls t("key", {vars}). Missing keys fall back to English, then to the key.

import { $$, storage } from "./dom.js";

export const LANGS = ["en", "uz", "ru"];
const STORE_KEY = "dazai-lang";
const cache = new Map();
let current = "en";
let dict = {};
let fallback = {};

async function load(lang) {
  if (!cache.has(lang)) {
    const res = await fetch(`/static/locales/${lang}.json`, { cache: "no-cache" });
    if (!res.ok) throw new Error(`locale ${lang}: ${res.status}`);
    cache.set(lang, await res.json());
  }
  return cache.get(lang);
}

function lookup(obj, key) {
  return key.split(".").reduce((o, k) => (o && typeof o === "object" ? o[k] : undefined), obj);
}

export function t(key, vars = {}) {
  let s = lookup(dict, key);
  if (typeof s !== "string") s = lookup(fallback, key);
  if (typeof s !== "string") return key;
  return s.replace(/\{(\w+)\}/g, (m, name) => (name in vars ? String(vars[name]) : m));
}

export function lang() { return current; }

export function apply(root = document) {
  for (const node of $$("[data-i18n]", root)) node.textContent = t(node.dataset.i18n);
  for (const node of $$("[data-i18n-attr]", root)) {
    for (const pair of node.dataset.i18nAttr.split(",")) {
      const [attr, key] = pair.split(":").map((x) => x.trim());
      if (attr && key) node.setAttribute(attr, t(key));
    }
  }
}

export async function setLang(next, { persist = true } = {}) {
  const target = LANGS.includes(next) ? next : "en";
  try {
    fallback = await load("en");
    dict = await load(target);
    current = target;
  } catch {
    dict = fallback; current = "en";
  }
  document.documentElement.lang = t("meta.lang");
  if (persist) storage.set(STORE_KEY, current);
  apply();
  document.dispatchEvent(new CustomEvent("langchange", { detail: { lang: current } }));
  return current;
}

export function initialLang() {
  const saved = storage.get(STORE_KEY);
  return LANGS.includes(saved) ? saved : "en";
}
