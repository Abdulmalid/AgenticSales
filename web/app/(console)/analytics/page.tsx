import { Badge, Empty, ErrorPanel, Notice, PageHead, Stat } from "@/components/ui";
import { tryApi } from "@/lib/backend";
import { naira, percent, titleCase } from "@/lib/format";
import type { CampaignReport, Funnel } from "@/lib/types";
import { MetricsForm } from "./MetricsForm";

export const metadata = { title: "Analytics" };

export default async function Analytics() {
  const [f, c] = await Promise.all([tryApi<Funnel>("/v1/analytics/funnel"), tryApi<CampaignReport[]>("/v1/analytics/campaigns")]);
  if (f.error && !f.data) return <><PageHead title="Analytics" /><ErrorPanel message={f.error} /></>;
  const fun = f.data!;
  const sources = Object.entries(fun.by_source).sort((a, b) => b[1].leads - a[1].leads);

  return (
    <>
      <PageHead title="Analytics" sub="What's working: where leads come from, what converts, and how your campaigns compare." />
      <div className="grid g4">
        <Stat label="Leads" value={fun.total_leads} />
        <Stat label="Customers" value={fun.converted} hint={`${percent(fun.conversion_rate)} of leads`} />
        <Stat label="Revenue" value={naira(fun.revenue_kobo)} hint={`${fun.orders} order${fun.orders === 1 ? "" : "s"} confirmed by the payment gateway`} />
        <Stat label="Avg time to buy" value={fun.avg_days_to_convert != null ? `${fun.avg_days_to_convert}d` : "–"} />
      </div>

      <div className="grid g2" style={{ marginTop: "1rem" }}>
        <section className="card flush" aria-labelledby="src">
          <h2 id="src" style={{ padding: "1rem 1.1rem 0" }}>Where leads come from</h2>
          {sources.length === 0 ? <Empty title="No leads yet" /> : (
            <div className="tablewrap">
              <table className="table">
                <thead><tr><th>Source</th><th>Leads</th><th>Customers</th><th>Rate</th></tr></thead>
                <tbody>{sources.map(([s, v]) => (
                  <tr key={s}><td data-label="Source">{titleCase(s)}</td><td data-label="Leads">{v.leads}</td><td data-label="Customers">{v.converted}</td><td data-label="Rate">{percent(v.leads ? v.converted / v.leads : 0)}</td></tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </section>
        <MetricsForm />
      </div>

      <section className="card flush" style={{ marginTop: "1rem" }} aria-labelledby="camps">
        <h2 id="camps" style={{ padding: "1rem 1.1rem 0" }}>Campaigns</h2>
        <div style={{ padding: "0.6rem 1.1rem" }}>
          <Notice tone="info">A winner is only declared when there's enough traffic (100+ visitors per version) and the gap is statistically meaningful. Otherwise you'll see "inconclusive" rather than a misleading result.</Notice>
        </div>
        {c.error ? <div style={{ padding: "1rem" }}><Notice tone="warn">{c.error}</Notice></div> : (c.data ?? []).length === 0 ? (
          <Empty title="No campaign results yet">Record results for a campaign using the form above.</Empty>
        ) : (
          <div className="tablewrap">
            <table className="table">
              <thead><tr><th>Campaign</th><th>Impressions</th><th>Clicks</th><th>CTR</th><th>Leads</th><th>Sales</th><th>Revenue</th><th>Verdict</th></tr></thead>
              <tbody>
                {(c.data ?? []).map((r) => (
                  <tr key={r.campaign_id}>
                    <td data-label="Campaign" className="mono">{r.campaign_id}</td>
                    <td data-label="Impressions">{r.impressions.toLocaleString()}</td>
                    <td data-label="Clicks">{r.clicks.toLocaleString()}</td>
                    <td data-label="CTR">{percent(r.ctr, 2)}</td>
                    <td data-label="Leads">{r.leads}</td>
                    <td data-label="Sales">{r.conversions}</td>
                    <td data-label="Revenue">{naira(r.revenue_kobo)}</td>
                    <td data-label="Verdict">
                      <Badge tone={r.comparison.verdict.includes("better") ? "ok" : "neutral"}>{r.comparison.verdict === "inconclusive" ? "Inconclusive" : r.comparison.verdict}</Badge>
                      <div className="small muted">{r.comparison.reason}</div>
                    </td>
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
