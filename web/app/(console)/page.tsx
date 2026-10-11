import Link from "next/link";
import { Badge, Empty, ErrorPanel, FraudBadge, PageHead, ScoreBar, Stat, StageBadge, Notice } from "@/components/ui";
import { Icon } from "@/components/icons";
import { tryApi } from "@/lib/backend";
import { getSession } from "@/lib/session";
import { naira, percent, relTime, titleCase, who } from "@/lib/format";
import { STAGE_ORDER, type Approval, type Funnel, type Lead, type Me } from "@/lib/types";

export const metadata = { title: "Overview" };

const ACTION_LABEL: Record<string, string> = {
  discount: "Discount request", order: "Large order", fraud_review: "Fraud review", human_handoff: "Needs a human",
  payment_mismatch: "Payment mismatch",
};

export default async function Overview() {
  const session = await getSession();
  const [funnel, me, approvals, hot] = await Promise.all([
    tryApi<Funnel>("/v1/analytics/funnel"),
    tryApi<Me>("/v1/me"),
    tryApi<Approval[]>("/v1/approvals"),
    tryApi<Lead[]>("/v1/leads?band=hot&limit=6"),
  ]);
  if (funnel.error && !funnel.data) return <><PageHead title="Overview" /><ErrorPanel message={funnel.error} /></>;
  const f = funnel.data!;
  const max = Math.max(1, ...STAGE_ORDER.map((s) => f.by_stage[s] ?? 0));
  const pending = approvals.data ?? [];

  return (
    <>
      <PageHead title={`Welcome back${session ? `, ${session.business}` : ""}`} sub="Here's what your AI sales team has been doing." />

      {me.data && me.data.channels_configured.length === 0 && (
        <div style={{ marginBottom: "1rem" }}>
          <Notice tone="info">
            No sales channel is connected yet, so the agent can only talk to you in the <Link href="/playground">Playground</Link>.
            {session?.role === "admin" && <> Connect WhatsApp, Instagram or email in <Link href="/settings?tab=channels">Settings → Channels</Link>.</>}
          </Notice>
        </div>
      )}

      <div className="grid g4">
        <Stat label="Total leads" value={f.total_leads} icon={<Icon name="leads" />} href="/leads" />
        <Stat label="Hot leads" value={f.hot_leads} hint="Likely to buy soon" icon={<Icon name="flame" />} href="/leads?band=hot" />
        <Stat label="Revenue" value={naira(f.revenue_kobo, { compact: true })} hint={`${f.orders} verified order${f.orders === 1 ? "" : "s"}`} icon={<Icon name="money" />} href="/analytics" />
        <Stat label="Conversion" value={percent(f.conversion_rate)} hint={f.avg_days_to_convert != null ? `Avg ${f.avg_days_to_convert} days to buy` : "No sales yet"} icon={<Icon name="target" />} href="/analytics" />
      </div>

      <div className="grid gmain" style={{ marginTop: "1rem" }}>
        <section className="card" aria-labelledby="needs">
          <div className="cardhead">
            <h2 id="needs">Needs your attention</h2>
            <Link href="/approvals" className="small">View all</Link>
          </div>
          {approvals.error ? <Notice tone="warn">Couldn't load approvals.</Notice> : pending.length === 0 ? (
            <Empty title="You're all caught up">Nothing is waiting for your decision.</Empty>
          ) : (
            <div className="stack">
              {pending.slice(0, 5).map((a) => (
                <Link key={a.id} href="/approvals" className="row spread" style={{ color: "inherit", textDecoration: "none", padding: "0.6rem 0", borderBottom: "1px solid var(--line)" }}>
                  <div className="grow">
                    <div style={{ fontWeight: 650 }}>{ACTION_LABEL[a.action] ?? titleCase(a.action)}</div>
                    <div className="small muted">{who(a.customer_key)} · {relTime(a.created)}</div>
                  </div>
                  <Badge tone={a.action === "fraud_review" ? "danger" : "warn"}>Review</Badge>
                </Link>
              ))}
            </div>
          )}
        </section>

        <section className="card" aria-labelledby="pipe">
          <h2 id="pipe">Pipeline</h2>
          <div>
            {STAGE_ORDER.filter((s) => s !== "FRAUD_SUSPECTED" || (f.by_stage[s] ?? 0) > 0).map((s) => (
              <div className="funnelrow" key={s}>
                <span className="small">{titleCase(s)}</span>
                <div className="bar"><span style={{ width: `${((f.by_stage[s] ?? 0) / max) * 100}%`, background: s === "FRAUD_SUSPECTED" ? "var(--danger)" : undefined }} /></div>
                <span className="small mono" style={{ textAlign: "right" }}>{f.by_stage[s] ?? 0}</span>
              </div>
            ))}
          </div>
        </section>
      </div>

      <section className="card flush" style={{ marginTop: "1rem" }} aria-labelledby="hotleads">
        <div className="cardhead" style={{ padding: "1rem 1.1rem 0" }}>
          <h2 id="hotleads">Hottest leads</h2>
          <Link href="/leads?band=hot" className="small">See all</Link>
        </div>
        {hot.error ? <div style={{ padding: "1rem" }}><Notice tone="warn">Couldn't load leads.</Notice></div> : (hot.data ?? []).length === 0 ? (
          <Empty title="No hot leads yet">When a customer shows strong buying signals they will appear here.</Empty>
        ) : (
          <div className="tablewrap">
            <table className="table">
              <thead><tr><th>Customer</th><th>Stage</th><th>Interest</th><th>Score</th><th>Last active</th></tr></thead>
              <tbody>
                {(hot.data ?? []).map((l) => (
                  <tr key={l.id}>
                    <td data-label="Customer"><Link href={`/leads/${l.id}`} style={{ fontWeight: 650 }}>{who(l.customer_key, l.name)}</Link> <FraudBadge risk={l.fraud_risk} /></td>
                    <td data-label="Stage"><StageBadge stage={l.stage} /></td>
                    <td data-label="Interest">{l.interest ?? "–"}</td>
                    <td data-label="Score"><ScoreBar score={l.score} band={l.band} /></td>
                    <td data-label="Last active" className="muted">{relTime(l.last_interaction)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
