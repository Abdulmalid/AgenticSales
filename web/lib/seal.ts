// Pure session sealing (AES-256-GCM). No Next.js imports so it can be unit-tested directly.
import { createCipheriv, createDecipheriv, createHash, randomBytes } from "node:crypto";

export type Role = "admin" | "staff";
export type Session = { key: string; tenant: string; role: Role; business: string; exp: number };

export function deriveKey(secret: string | undefined, production: boolean): Buffer {
  if (!secret || secret.length < 32) {
    if (production) throw new Error("SESSION_SECRET must be set to 32+ characters");
    // Development only: a fixed key so `next dev` works without setup. Never used in production builds.
    return createHash("sha256").update("dev-only-insecure-secret").digest();
  }
  return createHash("sha256").update(secret).digest();
}

export function seal(session: Session, key: Buffer): string {
  const iv = randomBytes(12);
  const c = createCipheriv("aes-256-gcm", key, iv);
  const ct = Buffer.concat([c.update(JSON.stringify(session), "utf8"), c.final()]);
  return Buffer.concat([iv, c.getAuthTag(), ct]).toString("base64url");
}

export function unseal(token: string | undefined, key: Buffer, now = Date.now()): Session | null {
  if (!token || token.length > 4096) return null;
  try {
    const raw = Buffer.from(token, "base64url");
    if (raw.length < 29) return null;
    const d = createDecipheriv("aes-256-gcm", key, raw.subarray(0, 12));
    d.setAuthTag(raw.subarray(12, 28));
    const s = JSON.parse(Buffer.concat([d.update(raw.subarray(28)), d.final()]).toString("utf8")) as Session;
    if (typeof s.key !== "string" || typeof s.exp !== "number" || s.exp < now) return null;
    if (s.role !== "admin" && s.role !== "staff") return null;
    return s;
  } catch {
    return null; // tampered, truncated, wrong key: all the same to the caller
  }
}
