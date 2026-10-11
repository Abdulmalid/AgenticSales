"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Notice } from "@/components/ui";
import { useToast } from "@/components/toast";
import { call } from "@/lib/client";
import { titleCase } from "@/lib/format";
import type { CampaignPlan } from "@/lib/types";

const OBJECTIVES = ["awareness", "consideration", "engagement", "lead_generation", "conversion", "retention", "trust_building"];
const SURFACES: Record<string, string[]> = {
  meta: ["", "instagram", "instagram_reels", "whatsapp", "facebook", "facebook_marketplace", "threads"],
  tiktok: ["", "short_form", "live_selling", "storytime", "skit", "ugc_brief"],
};

export function Planner({ imageAvailable }: { imageAvailable: boolean }) {
  const [platform, setPlatform] = useState<"meta" | "tiktok">("meta");
  const [objective, setObjective] = useState("conversion");
  const [surface, setSurface] = useState("");
  const [brief, setBrief] = useState("");
  const [n, setN] = useState(1);
  const [video, setVideo] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<CampaignPlan | null>(null);
  const toast = useToast();
  const router = useRouter();

  async function plan(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setResult(null);
    const r = await call<CampaignPlan>("content/plan", {
      method: "POST",
      body: { brief, platform, objective, surface: surface || null, n_posts: n, want_video: video },
    });
    setBusy(false);
    if (!r.ok) return toast(r.error, "error");
    setResult(r.data);
    toast(`Drafted ${r.data.item_ids.length} post${r.data.item_ids.length === 1 ? "" : "s"}.`, "ok");
    router.refresh();
  }

  const flagged = result ? Object.keys(result.violations).length : 0;

  return (
    <form className="card stack" onSubmit={plan} aria-labelledby="newcamp">
      <h2 id="newcamp">New campaign</h2>
      <label className="field">
        What do you want to promote?
        <textarea value={brief} onChange={(e) => setBrief(e.target.value)} required minLength={3} maxLength={2000}
          placeholder="e.g. Launch of our new Ankara tote bags. Target working women in Lagos. Weekend sale." />
      </label>
      <div className="grid g4">
        <label className="field">Platform
          <select value={platform} onChange={(e) => { setPlatform(e.target.value as "meta" | "tiktok"); setSurface(""); }}>
            <option value="meta">Instagram / Facebook / WhatsApp</option><option value="tiktok">TikTok</option>
          </select>
        </label>
        <label className="field">Format
          <select value={surface} onChange={(e) => setSurface(e.target.value)}>
            {SURFACES[platform].map((s) => <option key={s} value={s}>{s ? titleCase(s) : "Any"}</option>)}
          </select>
        </label>
        <label className="field">Goal
          <select value={objective} onChange={(e) => setObjective(e.target.value)}>
            {OBJECTIVES.map((o) => <option key={o} value={o}>{titleCase(o)}</option>)}
          </select>
        </label>
        <label className="field">Number of posts
          <select value={n} onChange={(e) => setN(Number(e.target.value))}>{[1, 2, 3, 4, 5].map((x) => <option key={x}>{x}</option>)}</select>
        </label>
      </div>
      <label className="check"><input type="checkbox" checked={video} onChange={(e) => setVideo(e.target.checked)} /> Include a short video script</label>
      <div className="row wrap">
        <button className="btn primary" type="submit" disabled={busy}>{busy ? "Planning… this can take up to a minute" : "Draft posts"}</button>
        {!imageAvailable && <span className="small muted">Image generation isn't enabled on this server.</span>}
      </div>

      {result && (
        <div className="stack">
          {result.strategy && <div className="notice info"><strong>Strategy.</strong> {result.strategy}</div>}
          {flagged > 0 && <Notice tone="warn">{flagged} draft{flagged === 1 ? " was" : "s were"} flagged for risky wording (health claims, unsupported approvals, payment links or wrong prices). They stay as drafts until you edit them.</Notice>}
          {result.guidance_cautions.length > 0 && (
            <Notice tone="warn">
              The playbooks used contain example wording that must not be copied as-is:
              <ul>{result.guidance_cautions.map((c) => <li key={c}>{c}</li>)}</ul>
            </Notice>
          )}
          {result.guidance_used.length > 0 && <p className="small muted">Based on: {result.guidance_used.join(" · ")}{result.relaxed_filters.length > 0 && ` (matched loosely: no exact ${result.relaxed_filters.join(", ")} match)`}</p>}
        </div>
      )}
    </form>
  );
}
