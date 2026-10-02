// API client. Same endpoints and payloads as before the redesign; errors are localized here.

import { t } from "./i18n.js";

let password = (() => { try { return sessionStorage.getItem("dazai-password") || ""; } catch { return ""; } })();

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export async function getConfig() {
  const res = await fetch("/api/config");
  if (!res.ok) throw new ApiError(res.status, t("err.generic", { status: res.status }));
  return res.json();
}

export async function post(path, form) {
  let res;
  try {
    res = await fetch(path, { method: "POST", body: form, headers: password ? { "X-Dazai-Password": password } : {} });
  } catch {
    throw new ApiError(0, t("err.network"));
  }
  if (res.status === 401) {
    const p = window.prompt(`${t("err.401")}\n${t("err.passwordPrompt")}:`);
    if (p) {
      password = p;
      try { sessionStorage.setItem("dazai-password", p); } catch { /* ignore */ }
      return post(path, form);
    }
    throw new ApiError(401, t("err.401"));
  }
  if (!res.ok) {
    const known = ["400", "413", "415", "422", "429"].includes(String(res.status));
    throw new ApiError(res.status, known ? t(`err.${res.status}`) : t("err.generic", { status: res.status }));
  }
  return res.json();
}

export async function fetchSample(name) {
  const res = await fetch(`/api/samples/${encodeURIComponent(name)}`);
  if (!res.ok) throw new ApiError(res.status, t("err.sample"));
  return new File([await res.blob()], name, {
    type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" });
}

export function downloadBase64(b64, name) {
  const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], {
    type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" }));
  const a = document.createElement("a");
  a.href = url; a.download = name; document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
