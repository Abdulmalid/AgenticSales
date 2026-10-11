"use client";
import { useRef, useState } from "react";
import { call } from "@/lib/client";
import { naira, titleCase } from "@/lib/format";
import type { AuditEvent } from "@/lib/types";

type Step = { icon: string; title: string; lines: string[]; tone?: "warn" | "danger" | "ok" };

/** Turn raw audit records into plain-language steps a business owner can read. Exported for testing. */
export function explain(events: AuditEvent[]): Step[] {
  const steps: Step[] = [];
  const list = (x: unknown): string[] => (Array.isArray(x) ? x.map(String) : []);
  for (const e of events) {
    const v = e as Record<string, unknown>;
    switch (e.kind) {
      case "analysis": {
        const sigs = (v.signals as [string, string][] | undefined) ?? [];
        steps.push({
          icon: "👂", title: "Understood the message",
          lines: [
            `Style: ${titleCase(String(v.register))}${v.source ? ` (read by ${String(v.source).includes("llm") ? "AI + rules" : "rules only"})` : ""}`,
            sigs.length ? `Signals: ${sigs.map(([n, ev]) => `${titleCase(n)}${ev ? ` ("${ev}")` : ""}`).join(", ")}` : "No notable buying signals",
            ...(v.urgency && v.urgency !== "low" ? [`Urgency: ${v.urgency}`] : []),
          ],
        });
        break;
      }
      case "lead": {
        const ch = v.stage_change as [string, string, string] | null;
        steps.push({
          icon: "📈", title: `Lead is ${titleCase(String(v.stage))} · score ${v.score} (${v.band})`,
          lines: [...(ch ? [`Moved from ${titleCase(ch[0])} to ${titleCase(ch[1])}: ${ch[2]}`] : []), ...list(v.reasons)],
        });
        break;
      }
      case "fraud": {
        const risk = String(v.risk);
        steps.push({
          icon: "🛡️", title: `Fraud check: ${risk.toLowerCase()} risk`, tone: risk === "HIGH" ? "danger" : risk === "MEDIUM" ? "warn" : "ok",
          lines: risk === "LOW" ? ["Nothing suspicious."] : [...list(v.reasons), `Recommended: ${v.action}`],
        });
        break;
      }
      case "model_plan": {
        const acts = (v.actions as { tool: string; args: Record<string, unknown> }[] | undefined) ?? [];
        steps.push({
          icon: "🧠", title: "Drafted a reply",
          lines: [...(v.note ? [String(v.note)] : []), ...(acts.length ? [`Planned actions: ${acts.map((a) => titleCase(a.tool)).join(", ")}`] : ["No tools needed"])],
        });
        break;
      }
      case "tool_call": {
        const st = String(v.status);
        const args = v.args as Record<string, unknown> | undefined;
        const price = args?.offered_price_kobo ? ` at ${naira(Number(args.offered_price_kobo))}` : "";
        steps.push({
          icon: "🔧", title: `${titleCase(String(v.tool))}${price}: ${titleCase(st)}`,
          tone: st === "denied" || st === "error" ? "warn" : st === "needs_approval" ? "warn" : undefined,
          lines: v.message ? [String(v.message)] : [],
        });
        break;
      }
      case "reply_retry":
        steps.push({ icon: "✏️", title: "Draft failed a safety check, rewrote it once", tone: "warn", lines: list(v.problems) });
        break;
      case "reply_blocked":
        steps.push({ icon: "⛔", title: "Reply blocked by a safety check", tone: "danger", lines: list(v.problems) });
        break;
      case "fallback":
        steps.push({ icon: "🙋", title: "Handed to a human", tone: "warn", lines: [String(v.reason ?? "")] });
        break;
      case "fraud_recheck":
        steps.push({ icon: "🛡️", title: `Fraud re-check after payment lookup: ${String(v.risk).toLowerCase()}`, tone: v.risk === "HIGH" ? "danger" : "warn", lines: list(v.reasons) });
        break;
      case "reply_sent":
        steps.push({ icon: "💬", title: v.escalated ? "Sent reply and flagged for you" : "Sent reply", tone: v.escalated ? "warn" : "ok", lines: [`"${String(v.reply)}"`] });
        break;
      case "opt_out":
        steps.push({ icon: "🚫", title: "Customer opted out. No more messages will be sent", lines: [] });
        break;
      case "duplicate_webhook_ignored":
        steps.push({ icon: "♻️", title: "Duplicate delivery ignored", lines: [] });
        break;
      default:
        break; // retrieval etc.: internal detail, not shown
    }
  }
  return steps;
}

export function TraceButton({ trace, label = "Why did the AI do this?" }: { trace: string; label?: string }) {
  const dlg = useRef<HTMLDialogElement>(null);
  const [steps, setSteps] = useState<Step[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function open() {
    dlg.current?.showModal();
    if (steps) return;
    const r = await call<AuditEvent[]>(`audit/${trace}`);
    if (r.ok) setSteps(explain(r.data)); else setErr(r.error);
  }

  return (
    <>
      <button className="btn sm ghost" style={{ padding: "0 0.2rem", minHeight: 0, textDecoration: "underline" }} onClick={open}>{label}</button>
      <dialog ref={dlg} aria-labelledby={`t-${trace}`}>
        <div className="dhead">
          <h2 id={`t-${trace}`}>How the agent decided</h2>
          <button className="btn sm" onClick={() => dlg.current?.close()}>Close</button>
        </div>
        <div className="dbody">
          {err && <div className="notice danger">{err}</div>}
          {!steps && !err && <p className="muted">Loading…</p>}
          {steps && steps.length === 0 && <p className="muted">No details recorded.</p>}
          {steps && (
            <ol className="stack" style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {steps.map((s, i) => (
                <li key={i} className={`notice ${s.tone ?? "info"}`} style={s.tone ? undefined : { background: "var(--surface-2)", color: "var(--text)" }}>
                  <div style={{ fontWeight: 650 }}><span aria-hidden="true">{s.icon} </span>{s.title}</div>
                  {s.lines.length > 0 && <ul>{s.lines.map((l, j) => <li key={j}>{l}</li>)}</ul>}
                </li>
              ))}
            </ol>
          )}
          <p className="small muted" style={{ marginTop: "0.9rem" }}>Trace {trace}. Every decision is logged so you can audit it later.</p>
        </div>
      </dialog>
    </>
  );
}
