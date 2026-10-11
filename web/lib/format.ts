// Display helpers. Money is integer kobo everywhere in the API; only format at the edge.

export function naira(kobo: number | null | undefined, opts: { compact?: boolean } = {}): string {
  if (kobo === null || kobo === undefined || Number.isNaN(kobo)) return "–";
  const n = kobo / 100;
  if (opts.compact && Math.abs(n) >= 1_000_000) return `₦${(n / 1_000_000).toFixed(n >= 10_000_000 ? 0 : 1)}M`;
  if (opts.compact && Math.abs(n) >= 10_000) return `₦${Math.round(n / 1000)}k`;
  return "₦" + new Intl.NumberFormat("en-NG", { maximumFractionDigits: 0 }).format(n);
}

export function toKobo(naira: string | number): number {
  const n = typeof naira === "number" ? naira : Number(String(naira).replace(/[₦,\s]/g, ""));
  if (!Number.isFinite(n) || n < 0) throw new Error("invalid amount");
  return Math.round(n * 100);
}

export function percent(x: number | null | undefined, digits = 1): string {
  return x === null || x === undefined ? "–" : `${(x * 100).toFixed(digits)}%`;
}

export function relTime(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "–";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "–";
  const s = Math.round((now - t) / 1000);
  if (s < 0) return "just now";
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)}d ago`;
  return new Date(t).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function titleCase(s: string): string {
  return s.replace(/[_-]+/g, " ").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
}

// "customer key" looks like "whatsapp:2348012345678". Show something friendlier, and mask most of a phone number.
export function who(customerKey: string, name?: string | null): string {
  if (name) return name;
  const [channel, id] = customerKey.split(":", 2);
  if (!id) return customerKey;
  const masked = /^\d{10,15}$/.test(id) ? `${id.slice(0, 4)}•••${id.slice(-3)}` : id.length > 18 ? id.slice(0, 15) + "…" : id;
  return `${masked}`.concat(channel === "web" ? " (web)" : "");
}
