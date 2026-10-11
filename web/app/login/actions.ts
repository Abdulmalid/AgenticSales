"use server";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { callBackend } from "@/lib/backend";
import { clearSession, setSession } from "@/lib/session";

export type LoginState = { error?: string };

// Per-instance throttle (serverless instances do not share memory, so this only slows casual guessing; the real
// defence is that API keys are 256-bit random values).
const attempts = new Map<string, { n: number; reset: number }>();
const WINDOW_MS = 10 * 60_000;
const MAX_ATTEMPTS = 10;

export async function login(_prev: LoginState, formData: FormData): Promise<LoginState> {
  const ip = (await headers()).get("x-forwarded-for")?.split(",")[0].trim() ?? "unknown";
  const now = Date.now();
  const rec = attempts.get(ip);
  if (rec && rec.reset > now && rec.n >= MAX_ATTEMPTS) return { error: "Too many attempts. Try again in a few minutes." };
  attempts.set(ip, rec && rec.reset > now ? { n: rec.n + 1, reset: rec.reset } : { n: 1, reset: now + WINDOW_MS });

  const key = String(formData.get("key") ?? "").trim();
  if (!/^ask_[A-Za-z0-9_-]{20,70}$/.test(key)) return { error: "That doesn't look like an AgenticSales API key (it starts with ask_)." };

  let res: Response;
  try {
    res = await callBackend("/v1/me", key, { timeoutMs: 15_000 });
  } catch {
    return { error: "Can't reach the AgenticSales API right now. Check BACKEND_URL and that the server is running." };
  }
  if (res.status === 401) return { error: "Invalid or revoked API key." };
  if (!res.ok) return { error: `The API returned an error (${res.status}).` };
  const me = (await res.json()) as { tenant_id: string; role: "admin" | "staff"; business_name: string };
  attempts.delete(ip);
  await setSession({ key, tenant: me.tenant_id, role: me.role, business: me.business_name });
  redirect("/");
}

export async function logout(): Promise<void> {
  await clearSession();
  redirect("/login");
}
