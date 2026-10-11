"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Badge, Empty, Notice } from "@/components/ui";
import { useToast } from "@/components/toast";
import { call } from "@/lib/client";
import { relTime, titleCase, who } from "@/lib/format";
import type { OutboxItem } from "@/lib/types";

const TONE: Record<string, "ok" | "warn" | "danger" | "neutral"> = { sent: "ok", pending: "neutral", needs_template: "warn", failed: "danger", skipped_opt_out: "neutral" };
const EXPLAIN: Record<string, string> = {
  needs_template: "Outside WhatsApp/Instagram's 24-hour reply window. These platforms only allow a pre-approved template message after that.",
  skipped_opt_out: "Customer asked not to be contacted.",
};

export function Automation({ outbox }: { outbox: OutboxItem[] }) {
  const toast = useToast();
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);

  async function run(label: string, path: string, fmt: (d: Record<string, unknown>) => string) {
    setBusy(label);
    const r = await call<Record<string, unknown>>(path, { method: "POST" });
    setBusy(null);
    if (!r.ok) return toast(r.error, "error");
    toast(fmt(r.data), "ok");
    router.refresh();
  }

  return (
    <div className="stack">
      <section className="card stack" aria-labelledby="auto">
        <h2 id="auto">Follow-ups and messages</h2>
        <p className="muted">After a sale the agent schedules check-ins (thank-you, satisfaction check, related products). Leads that go quiet get one recovery message, and are marked lost after three weeks. Run these now, or have your server call them on a schedule.</p>
        <div className="row wrap">
          <button className="btn primary" disabled={!!busy} onClick={() => run("fu", "followups/run", (d) => `Queued ${(d.followups as { enqueued: number }).enqueued} follow-up(s).`)}>{busy === "fu" ? "Running…" : "Run follow-ups now"}</button>
          <button className="btn" disabled={!!busy} onClick={() => run("fl", "outbox/flush", (d) => `Sent ${d.sent} · waiting ${d.needs_template} · failed ${d.failed}.`)}>{busy === "fl" ? "Sending…" : "Send queued messages now"}</button>
        </div>
        <Notice tone="warn">Nothing runs on a timer yet. Until your server is set up to call these two actions every few minutes, follow-ups only go out when you press the buttons.</Notice>
      </section>

      <section className="card flush" aria-labelledby="ob">
        <h2 id="ob" style={{ padding: "1rem 1.1rem 0" }}>Outgoing messages</h2>
        {outbox.length === 0 ? <Empty title="Nothing queued">Follow-ups and approved replies appear here before they're sent.</Empty> : (
          <div className="tablewrap">
            <table className="table">
              <thead><tr><th>To</th><th>Message</th><th>Reason</th><th>Status</th><th>When</th></tr></thead>
              <tbody>{outbox.map((o) => (
                <tr key={o.id}>
                  <td data-label="To">{who(o.customer_key)}</td>
                  <td data-label="Message" style={{ maxWidth: 340 }}>{o.text}</td>
                  <td data-label="Reason">{titleCase(o.purpose)}</td>
                  <td data-label="Status"><Badge tone={TONE[o.status] ?? "neutral"}>{titleCase(o.status)}</Badge>{(EXPLAIN[o.status] || o.error) && <div className="small muted" style={{ maxWidth: 240 }}>{EXPLAIN[o.status] ?? o.error}</div>}</td>
                  <td data-label="When" className="muted">{relTime(o.created)}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
