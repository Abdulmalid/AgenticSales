import Link from "next/link";
import { Empty, ErrorPanel, FraudBadge, PageHead, ScoreBar, StageBadge, BandBadge } from "@/components/ui";
import { tryApi } from "@/lib/backend";
import { naira, relTime, titleCase, who } from "@/lib/format";
import { STAGE_ORDER, type Lead } from "@/lib/types";

export const metadata = { title: "Leads" };

const BANDS = ["hot", "warm", "cold"] as const;

export default async function Leads({ searchParams }: { searchParams: Promise<{ stage?: string; band?: string }> }) {
  const sp = await searchParams;
  const stage = STAGE_ORDER.includes(sp.stage as never) ? sp.stage : undefined;
  const band = (BANDS as readonly string[]).includes(sp.band ?? "") ? sp.band : undefined;
  const qs = new URLSearchParams({ limit: "200", ...(stage ? { stage } : {}), ...(band ? { band } : {}) });
  const { data, error } = await tryApi<Lead[]>(`/v1/leads?${qs}`);

  const href = (p: { stage?: string; band?: string }) => {
    const q = new URLSearchParams();
    const s = "stage" in p ? p.stage : stage;
    const b = "band" in p ? p.band : band;
    if (s) q.set("stage", s);
    if (b) q.set("band", b);
    return `/leads${q.size ? `?${q}` : ""}`;
  };

  return (
    <>
      <PageHead title="Leads" sub="Everyone the agent is talking to, ranked by how likely they are to buy." />
      <div className="tabs" role="navigation" aria-label="Filter by temperature">
        <Link href={href({ band: undefined })} aria-current={!band ? "page" : undefined}>All</Link>
        {BANDS.map((b) => <Link key={b} href={href({ band: b })} aria-current={band === b ? "page" : undefined}>{titleCase(b)}</Link>)}
      </div>
      <div className="row wrap" style={{ marginBottom: "1rem" }} role="navigation" aria-label="Filter by stage">
        <span className="small muted">Stage:</span>
        <Link className={`btn sm ${!stage ? "primary" : ""}`} href={href({ stage: undefined })}>Any</Link>
        {STAGE_ORDER.map((s) => <Link key={s} className={`btn sm ${stage === s ? "primary" : ""}`} href={href({ stage: s })}>{titleCase(s)}</Link>)}
      </div>

      {error ? <ErrorPanel message={error} /> : (
        <div className="card flush">
          {(data ?? []).length === 0 ? (
            <Empty title="No leads match">Leads appear automatically when customers message you or fill your landing-page form.</Empty>
          ) : (
            <div className="tablewrap">
              <table className="table">
                <thead><tr><th>Customer</th><th>Channel</th><th>Stage</th><th>Interest</th><th>Budget</th><th>Objection</th><th>Score</th><th>Last active</th></tr></thead>
                <tbody>
                  {(data ?? []).map((l) => (
                    <tr key={l.id}>
                      <td data-label="Customer"><Link href={`/leads/${l.id}`} style={{ fontWeight: 650 }}>{who(l.customer_key, l.name)}</Link> <FraudBadge risk={l.fraud_risk} /></td>
                      <td data-label="Channel">{titleCase(l.source)}</td>
                      <td data-label="Stage"><StageBadge stage={l.stage} /></td>
                      <td data-label="Interest">{l.interest ?? "–"}</td>
                      <td data-label="Budget">{naira(l.budget_kobo)}</td>
                      <td data-label="Objection">{l.objection ? titleCase(l.objection) : "–"}</td>
                      <td data-label="Score"><div className="row"><ScoreBar score={l.score} band={l.band} /><BandBadge band={l.band} /></div></td>
                      <td data-label="Last active" className="muted">{relTime(l.last_interaction)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </>
  );
}
