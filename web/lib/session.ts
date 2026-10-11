import "server-only";
import { cookies } from "next/headers";
import { deriveKey, seal, unseal, type Session } from "./seal";

export const COOKIE = "as_session";
export const SESSION_HOURS = 8;

const key = () => deriveKey(process.env.SESSION_SECRET, process.env.NODE_ENV === "production");

export async function getSession(): Promise<Session | null> {
  return unseal((await cookies()).get(COOKIE)?.value, key());
}

export async function setSession(s: Omit<Session, "exp">): Promise<void> {
  const exp = Date.now() + SESSION_HOURS * 3600_000;
  (await cookies()).set(COOKIE, seal({ ...s, exp }, key()), {
    httpOnly: true,                                  // JavaScript in the page can never read the API key
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: SESSION_HOURS * 3600,
  });
}

export async function clearSession(): Promise<void> {
  (await cookies()).delete(COOKIE);
}
