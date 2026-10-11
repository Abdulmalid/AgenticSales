"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useToast } from "@/components/toast";
import { call } from "@/lib/client";
import { toKobo } from "@/lib/format";

export function MetricsForm() {
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const router = useRouter();

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const n = (k: string) => Math.max(0, Math.floor(Number(f.get(k) || 0)));
    let revenue = 0;
    try { revenue = f.get("revenue") ? toKobo(String(f.get("revenue"))) : 0; } catch { return toast("Revenue must be a number.", "error"); }
    setBusy(true);
    const r = await call("analytics/campaign-metrics", {
      method: "POST",
      body: { campaign_id: String(f.get("campaign")).trim(), variant: String(f.get("variant")).trim() || "A", impressions: n("impressions"), clicks: n("clicks"), leads: n("leads"), conversions: n("conversions"), revenue_kobo: revenue },
    });
    setBusy(false);
    if (!r.ok) return toast(r.error, "error");
    toast("Results recorded.", "ok");
    (e.target as HTMLFormElement).reset();
    router.refresh();
  }

  return (
    <form className="card stack" onSubmit={submit} aria-labelledby="rec">
      <h2 id="rec">Record campaign results</h2>
      <div className="grid g2">
        <label className="field">Campaign ID<input name="campaign" required maxLength={40} placeholder="cmp-1a2b3c4d" /></label>
        <label className="field">Version<input name="variant" maxLength={10} placeholder="A" defaultValue="A" /></label>
        <label className="field">Impressions<input name="impressions" type="number" min={0} /></label>
        <label className="field">Clicks / chats started<input name="clicks" type="number" min={0} /></label>
        <label className="field">Leads<input name="leads" type="number" min={0} /></label>
        <label className="field">Sales<input name="conversions" type="number" min={0} /></label>
      </div>
      <label className="field">Revenue (₦)<input name="revenue" inputMode="decimal" placeholder="0" /></label>
      <button className="btn primary" disabled={busy}>{busy ? "Saving…" : "Save results"}</button>
    </form>
  );
}
