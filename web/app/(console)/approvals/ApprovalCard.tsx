"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Badge } from "@/components/ui";
import { TraceButton } from "@/components/TraceButton";
import { useToast } from "@/components/toast";
import { call } from "@/lib/client";
import { naira, titleCase } from "@/lib/format";

type Props = {
  id: number; action: string; who: string; customerKey: string; when: string; trace: string;
  payload: Record<string, unknown>; reasons: string[]; product: { sku: string; name: string; price_kobo: number } | null;
};

const COPY: Record<string, { title: string; approve: string; deny: string; help: string; tone: "warn" | "danger" | "info" }> = {
  discount: { title: "Discount request", approve: "Approve this price", deny: "Decline", tone: "warn",
    help: "Approving records the price for this customer and tells them. Declining tells them politely that the listed price stands." },
  order: { title: "Large order", approve: "Approve order", deny: "Decline", tone: "warn",
    help: "Approving lets the agent send this customer a payment link. They'll be asked for their email." },
  fraud_review: { title: "Possible fraud: your decision", approve: "Clear this customer", deny: "Confirm concern", tone: "danger",
    help: "Clearing returns them to normal selling. Confirming the concern keeps the lead frozen and stops all outreach to them." },
  human_handoff: { title: "Needs a human", approve: "Mark as handled", deny: "Dismiss", tone: "info",
    help: "The agent wasn't sure what to do or something went wrong. You can send the customer a reply below." },
  payment_mismatch: { title: "Payment doesn't match the order", approve: "Acknowledge", deny: "Dismiss", tone: "danger",
    help: "The payment gateway reported a different amount than the order. Don't release goods until you've checked." },
};

export function ApprovalCard(p: Props) {
  const c = COPY[p.action] ?? { title: titleCase(p.action), approve: "Approve", deny: "Decline", help: "", tone: "info" as const };
  const router = useRouter();
  const toast = useToast();
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState<null | "yes" | "no">(null);
  const [done, setDone] = useState<string | null>(null);

  const price = typeof p.payload.offered_price_kobo === "number" ? p.payload.offered_price_kobo : null;
  const pct = price && p.product ? ((p.product.price_kobo - price) / p.product.price_kobo) * 100 : null;

  async function decide(approve: boolean) {
    setBusy(approve ? "yes" : "no");
    const r = await call<{ detail: string }>(`approvals/${p.id}/decision`, { method: "POST", body: { approve, reply_text: reply.trim() || null } });
    setBusy(null);
    if (!r.ok) {
      toast(r.status === 409 ? "Someone already decided this one." : r.error, "error");
      if (r.status === 409) router.refresh();
      return;
    }
    setDone(r.data.detail);
    toast(r.data.detail === "applied" ? "Decision applied." : r.data.detail, r.data.detail === "applied" ? "ok" : "info");
    router.refresh();
  }

  return (
    <article className="card" aria-labelledby={`ap-${p.id}`}>
      <div className="cardhead">
        <div>
          <h2 id={`ap-${p.id}`}>{c.title}</h2>
          <div className="small muted">{p.who} · {p.when} · <TraceButton trace={p.trace} label="Why?" /></div>
        </div>
        <Badge tone={c.tone}>Waiting</Badge>
      </div>

      {p.action === "discount" && price !== null && (
        <p style={{ marginBottom: "0.7rem" }}>
          Customer is asking for <strong>{p.product?.name ?? String(p.payload.sku)}</strong> at <strong>{naira(price)}</strong>
          {p.product && <> (list {naira(p.product.price_kobo)}{pct !== null && <>, <strong>{pct.toFixed(1)}% off</strong></>})</>}.
        </p>
      )}
      {p.action === "order" && <p style={{ marginBottom: "0.7rem" }}>{String(p.payload.qty)} × {p.product?.name ?? String(p.payload.sku)}{typeof p.payload.unit_kobo === "number" && <> at {naira(p.payload.unit_kobo)} each</>}.</p>}
      {p.action === "fraud_review" && typeof p.payload.action === "string" && <div className="notice danger" style={{ marginBottom: "0.7rem" }}>{p.payload.action}</div>}

      {p.reasons.length > 0 && (
        <ul className="small" style={{ margin: "0 0 0.8rem", paddingLeft: "1.1rem" }}>
          {p.reasons.map((r, i) => <li key={i}>{r}</li>)}
        </ul>
      )}
      <p className="small muted" style={{ marginBottom: "0.8rem" }}>{c.help}</p>

      {done ? <div className="notice ok">{done === "applied" ? "Done." : done}</div> : (
        <div className="stack">
          <label className="field">
            Message to the customer <span className="help">Optional. Prices in it are checked against your price list before sending.</span>
            <textarea value={reply} onChange={(e) => setReply(e.target.value)} maxLength={1000} placeholder="Leave empty to send the standard message" />
          </label>
          <div className="row wrap">
            <button className="btn primary" disabled={busy !== null} onClick={() => decide(true)}>{busy === "yes" ? "Working…" : c.approve}</button>
            <button className="btn" disabled={busy !== null} onClick={() => decide(false)}>{busy === "no" ? "Working…" : c.deny}</button>
          </div>
        </div>
      )}
    </article>
  );
}
