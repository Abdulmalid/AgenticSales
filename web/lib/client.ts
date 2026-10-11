// Browser-side helper for the BFF (/api/b/...). Never touches the API key: the cookie is httpOnly.
export type CallResult<T> = { ok: true; data: T } | { ok: false; error: string; status: number };

export async function call<T = unknown>(
  path: string,
  opts: { method?: "GET" | "POST" | "PUT" | "DELETE"; body?: unknown; signal?: AbortSignal } = {},
): Promise<CallResult<T>> {
  const method = opts.method ?? "GET";
  try {
    const res = await fetch(`/api/b/${path.replace(/^\/+/, "")}`, {
      method,
      headers: { ...(opts.body !== undefined ? { "Content-Type": "application/json" } : {}), ...(method !== "GET" ? { "x-csrf": "1" } : {}) },
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: opts.signal,
      credentials: "same-origin",
    });
    if (res.status === 401) {
      window.location.href = "/login?expired=1";
      return { ok: false, error: "Session expired", status: 401 };
    }
    const type = res.headers.get("content-type") ?? "";
    const payload = type.includes("json") ? await res.json() : null;
    if (!res.ok) {
      const d = payload?.detail;
      const msg = typeof d === "string" ? d : Array.isArray(d) ? d.map((x: { msg?: string }) => x.msg).filter(Boolean).join("; ") : `Request failed (${res.status})`;
      return { ok: false, error: msg, status: res.status };
    }
    return { ok: true, data: payload as T };
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") return { ok: false, error: "Cancelled", status: 0 };
    return { ok: false, error: "Network error. Check your connection and try again.", status: 0 };
  }
}
