import "server-only";
import { redirect } from "next/navigation";
import { getSession } from "./session";

export class BackendError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export const backendUrl = () => (process.env.BACKEND_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
export const publicBackendUrl = () => (process.env.BACKEND_PUBLIC_URL ?? backendUrl()).replace(/\/+$/, "");

type Init = { method?: string; body?: unknown; timeoutMs?: number };

/** Low-level call with an explicit key (used by login before a session exists). */
export async function callBackend(path: string, apiKey: string, init: Init = {}): Promise<Response> {
  return fetch(backendUrl() + path, {
    method: init.method ?? "GET",
    headers: { Authorization: `Bearer ${apiKey}`, ...(init.body !== undefined ? { "Content-Type": "application/json" } : {}) },
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
    cache: "no-store",
    signal: AbortSignal.timeout(init.timeoutMs ?? 60_000),
  });
}

/** Server-component data fetch using the signed-in session. Redirects to /login when not authenticated. */
export async function api<T>(path: string, init: Init = {}): Promise<T> {
  const s = await getSession();
  if (!s) redirect("/login");
  let res: Response;
  try {
    res = await callBackend(path, s.key, init);
  } catch {
    throw new BackendError(503, "The AgenticSales API is unreachable.");
  }
  if (res.status === 401) redirect("/login?expired=1");
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const j = await res.json();
      if (typeof j?.detail === "string") detail = j.detail;
    } catch {}
    throw new BackendError(res.status, detail);
  }
  return (await res.json()) as T;
}

/** Like api() but never throws: used for optional widgets so one failing panel does not blank the page. */
export async function tryApi<T>(path: string): Promise<{ data: T | null; error: string | null }> {
  try {
    return { data: await api<T>(path), error: null };
  } catch (e) {
    // redirect() throws a special error that must propagate
    if (e && typeof e === "object" && "digest" in e && String((e as { digest: unknown }).digest).startsWith("NEXT_REDIRECT")) throw e;
    return { data: null, error: e instanceof Error ? e.message : "Unavailable" };
  }
}
