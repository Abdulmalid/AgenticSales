// Rules for what the browser may ask the BFF to forward to the Python API. Pure and unit-tested.

// First path segment under /v1 that the console is allowed to reach.
export const ALLOWED_ROOTS = new Set([
  "me", "leads", "approvals", "outbox", "followups", "content", "analytics", "config", "secrets",
  "chat", "audit", "landing", "customers",
]);
const METHODS = new Set(["GET", "POST", "PUT", "DELETE"]);
const SEGMENT = /^[A-Za-z0-9_\-.]{1,64}$/;
export const MAX_BODY_BYTES = 256 * 1024;

export type ProxyCheck = { ok: true; backendPath: string } | { ok: false; status: number; reason: string };

export function checkProxyRequest(a: {
  method: string;
  segments: string[];
  origin: string | null;      // Origin header, if any
  selfOrigin: string;         // this app's own origin
  csrfHeader: string | null;
  contentLength: number | null;
}): ProxyCheck {
  const method = a.method.toUpperCase();
  if (!METHODS.has(method)) return { ok: false, status: 405, reason: "method not allowed" };
  if (a.segments.length === 0 || a.segments.length > 4 || !a.segments.every((s) => SEGMENT.test(s) && s !== "." && s !== "..")) {
    return { ok: false, status: 400, reason: "bad path" };
  }
  if (!ALLOWED_ROOTS.has(a.segments[0])) return { ok: false, status: 404, reason: "not found" };
  if (method !== "GET") {
    // CSRF: SameSite=Lax cookie + custom header + same-origin Origin. All three must hold.
    if (a.csrfHeader !== "1") return { ok: false, status: 403, reason: "missing csrf header" };
    if (a.origin !== null && a.origin !== a.selfOrigin) return { ok: false, status: 403, reason: "cross-origin request" };
  }
  if (a.contentLength !== null && a.contentLength > MAX_BODY_BYTES) return { ok: false, status: 413, reason: "body too large" };
  return { ok: true, backendPath: "/v1/" + a.segments.join("/") };
}

// Only these response types are passed through; anything else is replaced with a generic error.
export function passthroughType(contentType: string | null): "json" | "image" | "other" {
  const t = (contentType ?? "").split(";")[0].trim().toLowerCase();
  if (t === "application/json") return "json";
  if (t === "image/png" || t === "image/jpeg") return "image";
  return "other";
}
