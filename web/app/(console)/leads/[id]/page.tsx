import Link from "next/link";
import { notFound } from "next/navigation";
import { BandBadge, Badge, ErrorPanel, FraudBadge, Notice, PageHead, ScoreBar, StageBadge } from "@/components/ui";
import { BackendError, api } from "@/lib/backend";
import { getSession } from "@/lib/session";
import { naira, percent, relTime, titleCase, who } from "@/lib/format";
import type { LeadDetail, LeadEvent } from "@/lib/types";
import { EraseButton } from "./EraseButton";
import { TraceButton } from "@/components/TraceButton";

export const metadata = { title: "Lead" };

// Facts the system writes itself; shown separately from what the customer told us.
const SYSTEM_FACT = /^(agreed_price:|neg_round:|approved_order:|order:|payment_|fraud_|delivery_changes)/;

function describe(e: LeadEvent): { title: string; detail?: string } {
  const d = e.data as Record<string, unknown>;
  switch (e.kind) {
    case "turn": {
      const sigs = (d.signals as string[] | undefined) ?? [];
      return { title: "Customer message", detail: sigs.length ? `Signals: ${sigs.map(titleCase).join(", ")}` : "No notable signals" };
    }
    case "stage_change": return { title: `Moved to ${titleCase(String(d.to))}`, detail: d.from ? `from ${titleCase(String(d.from))} · ${d.why ?? ""}` : String(d.why ?? "") };
    case "purchase": return { title: "Purchase verified", detail: `${naira(Number(d.amount_kobo))} · ref ${String(d.reference ?? "")}` };
    case "followup_queued": return { title: "Follow-up queued", detail: titleCase(String(d.purpose)) };
    case "fraud_review": return { title: d.cleared ? "Fraud review: cleared" : "Fraud review: concern confirmed", detail: `by ${d.by}` };
    case "landing_form": return { title: "Submitted the landing-page form", detail: String(d.message || "") };
    default: return { title: titleCase(e.kind) };
  }
}

export default async function LeadPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  const session = await getSession();
  let d: LeadDetail;
  try {
    d = await api<LeadDetail>(`/v1/leads/${id}`);
  } catch (e) {
    if (e instanceof BackendError && e.status === 404) notFound();
    return <ErrorPanel message={e instanceof Error ? e.message : "Couldn't load this lead."} />;
  }
  const l = d.lead;
  const customerFacts = Object.entries(d.facts).filter(([k]) => !SYSTEM_FACT.test(k));
  const agreed = Object.entries(d.facts).filter(([k]) => k.startsWith("agreed_price:"));
  const [channel, ...rest] = l.customer_key.split(":");
  const lastTrace = d.events.find((e) => e.trace)?.trace ?? null;

  return (
    <>
      <p className="small"><Link href="/leads">← All leads</Link></p>
      <PageHead title={who(l.customer_key, l.name)} sub={`${titleCase(channel)} · first seen ${relTime(l.created)}`}>
        <StageBadge stage={l.stage} /> <BandBadge band={l.band} /> <FraudBadge risk={l.fraud_risk} />
      </PageHead>

      {l.stage === "FRAUD_SUSPECTED" && (
        <div style={{ marginBottom: "1rem" }}>
          <Notice tone="danger">This conversation is under fraud review. The agent will not complete a sale or promise delivery until you decide in <Link href="/approvals">Approvals</Link>. Replies to the customer stay neutral and polite.</Notice>
        </div>
      )}

      <div className="grid g2">
        <section className="card" aria-labelledby="profile">
          <h2 id="profile">Profile</h2>
          <dl className="stack small" style={{ margin: 0 }}>
            {[
              ["Interest", l.interest ?? "Not yet known"],
              ["Stated budget", naira(l.budget_kobo)],
              ["Buying intent", titleCase(l.intent)],
              ["Main objection", l.objection ? titleCase(l.objection) : "None so far"],
              ["Trust", titleCase(l.trust_level)],
              ["Agreed price", agreed.length ? agreed.map(([k, v]) => `${k.split(":")[1]}: ${naira(Number(v))}`).join(", ") : "None"],
              ["Messages", String(l.attrs.messages ?? 0)],
              ["Last active", relTime(l.last_interaction)],
            ].map(([k, v]) => (
              <div key={k} className="row spread" style={{ borderBottom: "1px solid var(--line)", paddingBottom: "0.45rem" }}>
                <dt className="muted">{k}</dt><dd style={{ margin: 0, fontWeight: 600, textAlign: "right" }}>{v}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section className="card" aria-labelledby="score">
          <div className="cardhead"><h2 id="score">Why this score?</h2><ScoreBar score={l.score} band={l.band} /></div>
          {d.score_reasons.length ? (
            <ul className="stack small" style={{ margin: 0, paddingLeft: "1.1rem", gap: "0.35rem" }}>
              {d.score_reasons.map((r) => <li key={r}>{r}</li>)}
            </ul>
          ) : <p className="muted small">No scoring signals yet.</p>}
          <p className="small muted" style={{ marginTop: "0.9rem" }}>
            Estimated chance of buying: <strong>{percent(l.conversion_probability, 0)}</strong>.
            {!d.score_calibrated && " This is a rule-based estimate, not a measured probability. It becomes reliable once you have enough completed sales to calibrate against."}
          </p>
        </section>
      </div>

      <div className="grid g2" style={{ marginTop: "1rem" }}>
        <section className="card" aria-labelledby="timeline">
          <h2 id="timeline">Activity</h2>
          {d.events.length === 0 ? <p className="muted">Nothing yet.</p> : (
            <ol className="timeline">
              {d.events.slice(0, 30).map((e) => {
                const x = describe(e);
                return (
                  <li key={e.id}>
                    <span className="dot" aria-hidden="true" />
                    <div>
                      <div style={{ fontWeight: 600 }}>{x.title}</div>
                      {x.detail && <div className="small muted">{x.detail}</div>}
                      <div className="small muted">{relTime(e.ts)}{e.trace && <> · <TraceButton trace={e.trace} label="Why?" /></>}</div>
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
        </section>

        <div className="stack">
          <section className="card" aria-labelledby="memory">
            <h2 id="memory">What the agent remembers</h2>
            {customerFacts.length === 0 ? <p className="muted small">Nothing saved about this customer yet.</p> : (
              <dl className="stack small" style={{ margin: 0 }}>
                {customerFacts.map(([k, v]) => (
                  <div key={k} className="row spread"><dt className="muted">{titleCase(k)}</dt><dd style={{ margin: 0, textAlign: "right" }}>{v}</dd></div>
                ))}
              </dl>
            )}
          </section>
          {session?.role === "admin" && (
            <section className="card" aria-labelledby="privacy">
              <h2 id="privacy">Privacy</h2>
              <p className="small muted" style={{ marginBottom: "0.8rem" }}>Under the NDPR a customer can ask you to delete their data. This removes their messages, lead record, orders and memory. A STOP/opt-out record is kept so they are never contacted again.</p>
              <EraseButton channel={channel} userId={rest.join(":")} />
            </section>
          )}
          {lastTrace && <Badge>Latest trace {lastTrace.slice(0, 6)}…</Badge>}
        </div>
      </div>
    </>
  );
}
