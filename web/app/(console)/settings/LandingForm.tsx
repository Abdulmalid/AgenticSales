"use client";
import { useState } from "react";
import { Notice } from "@/components/ui";
import { useToast } from "@/components/toast";
import { call } from "@/lib/client";

export function LandingForm({ siteUrl }: { siteUrl: string }) {
  const [busy, setBusy] = useState(false);
  const [published, setPublished] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const toast = useToast();

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setErr(null);
    const f = new FormData(e.currentTarget);
    const v = (k: string) => String(f.get(k) ?? "").trim();
    setBusy(true);
    const r = await call("landing", {
      method: "POST",
      body: {
        whatsapp: v("whatsapp").replace(/\D/g, ""), phone: v("phone") || null, location: v("location") || null, tagline: v("tagline") || null,
        description: v("description") || null, primary_color: v("primary"), accent_color: v("accent"),
        logo_url: v("logo") || null, hero_image_url: v("hero") || null,
      },
    });
    setBusy(false);
    if (!r.ok) return setErr(r.error);
    setPublished(true);
    toast("Landing page published.", "ok");
  }

  return (
    <form className="card stack" onSubmit={submit} aria-labelledby="lp">
      <h2 id="lp">One-page website</h2>
      <p className="muted">Builds a fast, mobile-friendly page from your products and prices, with a WhatsApp button and a lead form. Leads from the form appear under Leads and the agent follows up.</p>
      <div className="grid g2">
        <label className="field">WhatsApp number<input name="whatsapp" required inputMode="tel" placeholder="2348012345678" /><span className="help">Full international format, digits only.</span></label>
        <label className="field">Phone (shown on page)<input name="phone" placeholder="0801 234 5678" /></label>
        <label className="field">Location<input name="location" placeholder="12 Computer Village, Ikeja, Lagos" /></label>
        <label className="field">Headline<input name="tagline" maxLength={120} placeholder="Original phones, delivered across Lagos" /></label>
        <label className="field" style={{ gridColumn: "1 / -1" }}>Short description<textarea name="description" maxLength={300} /></label>
        <label className="field">Main colour<input name="primary" type="color" defaultValue="#0b6e4f" /></label>
        <label className="field">Button colour<input name="accent" type="color" defaultValue="#f4a300" /></label>
        <label className="field">Logo image link<input name="logo" type="url" placeholder="https://…" /><span className="help">Must start with https://</span></label>
        <label className="field">Banner image link<input name="hero" type="url" placeholder="https://…" /></label>
      </div>
      {err && <Notice tone="danger">{err}</Notice>}
      <div className="row wrap">
        <button className="btn primary" disabled={busy}>{busy ? "Publishing…" : "Publish page"}</button>
        {published && <a className="btn" href={siteUrl} target="_blank" rel="noopener noreferrer">Open your page ↗</a>}
      </div>
      {siteUrl.includes("127.0.0.1") && <p className="small muted">Your page is served by the API server. Its address is local for now; it becomes public once the API is hosted.</p>}
    </form>
  );
}
