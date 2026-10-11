"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Notice } from "@/components/ui";
import { useToast } from "@/components/toast";
import { call } from "@/lib/client";
import { toKobo } from "@/lib/format";
import type { BusinessConfig } from "@/lib/types";

type P = { sku: string; name: string; price: string; floor: string; description: string; in_stock: boolean };
const lines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);
const csv = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

export function BusinessForm({ initial }: { initial: BusinessConfig }) {
  const [c, setC] = useState({
    business_name: initial.business_name, industry: initial.industry, brand_voice: initial.brand_voice,
    target_audience: initial.target_audience, delivery_areas: initial.delivery_areas.join(", "),
    payment_methods: initial.payment_methods.join(", "), refund_policy: initial.refund_policy,
    working_hours: initial.working_hours, business_facts: initial.business_facts.join("\n"),
  });
  const [a, setA] = useState({
    auto: String(initial.approvals.max_discount_pct_auto), hard: String(initial.approvals.max_discount_pct_hard),
    large: String(initial.approvals.large_transaction_kobo / 100),
    refunds: initial.approvals.refunds_need_approval, fraud: initial.approvals.high_fraud_risk_needs_approval,
    posts: initial.approvals.public_posts_need_approval,
  });
  const [products, setProducts] = useState<P[]>(initial.products.map((p) => ({
    sku: p.sku, name: p.name, price: String(p.price_kobo / 100), floor: String(p.floor_price_kobo / 100), description: p.description, in_stock: p.in_stock,
  })));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const toast = useToast();
  const router = useRouter();

  const set = (k: keyof typeof c) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setC({ ...c, [k]: e.target.value });
  const setP = (i: number, patch: Partial<P>) => setProducts(products.map((p, j) => (j === i ? { ...p, ...patch } : p)));

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    let body: BusinessConfig;
    try {
      const auto = Number(a.auto), hard = Number(a.hard);
      if (!(auto >= 0 && auto <= hard && hard <= 100)) throw new Error("Discount limits must satisfy: automatic ≤ hard limit ≤ 100%.");
      const skus = new Set<string>();
      body = {
        ...initial,
        business_name: c.business_name.trim(), industry: c.industry.trim(), brand_voice: c.brand_voice.trim(),
        target_audience: c.target_audience.trim(), delivery_areas: csv(c.delivery_areas), payment_methods: csv(c.payment_methods),
        refund_policy: c.refund_policy.trim(), working_hours: c.working_hours.trim(), business_facts: lines(c.business_facts),
        approvals: {
          ...initial.approvals, max_discount_pct_auto: auto, max_discount_pct_hard: hard, large_transaction_kobo: toKobo(a.large),
          refunds_need_approval: a.refunds, high_fraud_risk_needs_approval: a.fraud, public_posts_need_approval: a.posts,
        },
        products: products.map((p) => {
          const sku = p.sku.trim();
          if (!sku || !p.name.trim()) throw new Error("Every product needs a code (SKU) and a name.");
          if (skus.has(sku)) throw new Error(`Duplicate product code “${sku}”.`);
          skus.add(sku);
          const price = toKobo(p.price), floor = toKobo(p.floor);
          if (floor > price) throw new Error(`${p.name}: the lowest price can't be above the list price.`);
          return { sku, name: p.name.trim(), price_kobo: price, floor_price_kobo: floor, description: p.description.trim(), in_stock: p.in_stock };
        }),
      };
    } catch (ex) {
      return setErr(ex instanceof Error ? ex.message : "Please check the form.");
    }
    setBusy(true);
    const r = await call("config", { method: "PUT", body });
    setBusy(false);
    if (!r.ok) return setErr(r.error);
    toast("Saved. The agent will use these rules from the next message.", "ok");
    router.refresh();
  }

  return (
    <form className="stack" onSubmit={save}>
      <section className="card stack" aria-labelledby="b1">
        <h2 id="b1">About your business</h2>
        <div className="grid g2">
          <label className="field">Business name<input value={c.business_name} onChange={set("business_name")} required /></label>
          <label className="field">What you sell<input value={c.industry} onChange={set("industry")} required placeholder="e.g. phones and accessories" /></label>
          <label className="field">How the agent should sound<input value={c.brand_voice} onChange={set("brand_voice")} placeholder="warm, confident, straight to the point" /><span className="help">It will still mirror each customer's style (formal, casual, Pidgin).</span></label>
          <label className="field">Who you sell to<input value={c.target_audience} onChange={set("target_audience")} placeholder="e.g. working professionals in Lagos" /></label>
          <label className="field">Delivery areas<input value={c.delivery_areas} onChange={set("delivery_areas")} placeholder="Lagos, Abuja, Port Harcourt" /><span className="help">Separate with commas.</span></label>
          <label className="field">Payment methods<input value={c.payment_methods} onChange={set("payment_methods")} placeholder="paystack, bank transfer" /></label>
          <label className="field">Working hours<input value={c.working_hours} onChange={set("working_hours")} placeholder="Mon–Sat, 9am–6pm" /></label>
          <label className="field">Refund / return policy<input value={c.refund_policy} onChange={set("refund_policy")} /></label>
        </div>
        <label className="field">
          Facts the agent may state about your business
          <textarea value={c.business_facts} onChange={set("business_facts")} placeholder={"One per line, e.g.\nCAC registered, RC 1234567\nShop at 12 Computer Village, Ikeja\nDelivery within Lagos takes 1–2 days"} style={{ minHeight: 120 }} />
          <span className="help">The agent will <strong>never</strong> claim registration, licences, guarantees, delivery times or policies that aren't listed here (or in your products). Customers often ask “is this legit?”, so add what you can prove.</span>
        </label>
      </section>

      <section className="card stack" aria-labelledby="b2">
        <div className="cardhead"><h2 id="b2">Products and prices</h2><button type="button" className="btn sm" onClick={() => setProducts([...products, { sku: "", name: "", price: "", floor: "", description: "", in_stock: true }])}>+ Add product</button></div>
        <Notice tone="info">The <strong>lowest price</strong> is a hard floor: the agent can never go below it and never sees it. Anything below the automatic discount limit goes to you for approval.</Notice>
        {products.length === 0 && <p className="muted">No products yet. Add one so the agent can quote real prices.</p>}
        {products.map((p, i) => (
          <fieldset key={i} className="card" style={{ background: "var(--surface-2)" }}>
            <legend className="small muted" style={{ padding: "0 0.4rem" }}>Product {i + 1}</legend>
            <div className="grid g4">
              <label className="field">Code<input value={p.sku} onChange={(e) => setP(i, { sku: e.target.value })} required placeholder="IP15" maxLength={32} /></label>
              <label className="field">Name<input value={p.name} onChange={(e) => setP(i, { name: e.target.value })} required /></label>
              <label className="field">List price (₦)<input value={p.price} onChange={(e) => setP(i, { price: e.target.value })} required inputMode="decimal" /></label>
              <label className="field">Lowest price (₦)<input value={p.floor} onChange={(e) => setP(i, { floor: e.target.value })} required inputMode="decimal" /></label>
            </div>
            <label className="field" style={{ marginTop: "0.7rem" }}>Description<input value={p.description} onChange={(e) => setP(i, { description: e.target.value })} placeholder="Brand new, sealed, 1-year warranty" /></label>
            <div className="row spread" style={{ marginTop: "0.7rem" }}>
              <label className="check"><input type="checkbox" checked={p.in_stock} onChange={(e) => setP(i, { in_stock: e.target.checked })} /> In stock</label>
              <button type="button" className="btn sm danger" onClick={() => setProducts(products.filter((_, j) => j !== i))}>Remove</button>
            </div>
          </fieldset>
        ))}
      </section>

      <section className="card stack" aria-labelledby="b3">
        <h2 id="b3">When the agent must ask you first</h2>
        <div className="grid g3">
          <label className="field">Discount it can give alone (%)<input value={a.auto} onChange={(e) => setA({ ...a, auto: e.target.value })} inputMode="decimal" /><span className="help">It concedes in small steps up to this.</span></label>
          <label className="field">Never discount beyond (%)<input value={a.hard} onChange={(e) => setA({ ...a, hard: e.target.value })} inputMode="decimal" /><span className="help">Between the two, it asks you.</span></label>
          <label className="field">Orders at or above (₦) need approval<input value={a.large} onChange={(e) => setA({ ...a, large: e.target.value })} inputMode="decimal" /></label>
        </div>
        <label className="check"><input type="checkbox" checked={a.fraud} onChange={(e) => setA({ ...a, fraud: e.target.checked })} /> Ask me when a conversation looks risky</label>
        <label className="check"><input type="checkbox" checked={a.refunds} onChange={(e) => setA({ ...a, refunds: e.target.checked })} /> Ask me before any refund</label>
        <label className="check"><input type="checkbox" checked={a.posts} onChange={(e) => setA({ ...a, posts: e.target.checked })} /> Ask me before anything is posted publicly</label>
      </section>

      {err && <Notice tone="danger">{err}</Notice>}
      <div className="row"><button className="btn primary" disabled={busy}>{busy ? "Saving…" : "Save changes"}</button></div>
    </form>
  );
}
