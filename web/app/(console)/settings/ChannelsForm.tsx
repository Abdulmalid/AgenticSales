"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Badge, Notice } from "@/components/ui";
import { useToast } from "@/components/toast";
import { call } from "@/lib/client";

type Field = { key: string; label: string; secret?: boolean; help?: string; optional?: boolean };
type Section = { id: string; title: string; blurb: string; fields: Field[]; webhook?: boolean; note?: string };

const SECTIONS: Section[] = [
  { id: "whatsapp", title: "WhatsApp Business", webhook: true,
    blurb: "Customers message your WhatsApp Business number and the agent replies. Uses Meta's WhatsApp Cloud API.",
    fields: [
      { key: "app_secret", label: "App secret", secret: true, help: "Meta app → Settings → Basic" },
      { key: "verify_token", label: "Verify token", help: "Any string you choose; paste the same one in Meta's webhook setup" },
      { key: "access_token", label: "Access token", secret: true, help: "Use a permanent system-user token" },
      { key: "phone_number_id", label: "Phone number ID" },
    ] },
  { id: "instagram", title: "Instagram DMs", webhook: true, blurb: "Replies to Instagram direct messages via Meta.",
    fields: [{ key: "app_secret", label: "App secret", secret: true }, { key: "verify_token", label: "Verify token" }, { key: "access_token", label: "Access token", secret: true }, { key: "page_id", label: "Page / account ID", optional: true }] },
  { id: "facebook", title: "Facebook Messenger", webhook: true, blurb: "Replies to messages on your Facebook page.",
    fields: [{ key: "app_secret", label: "App secret", secret: true }, { key: "verify_token", label: "Verify token" }, { key: "access_token", label: "Page access token", secret: true }, { key: "page_id", label: "Page ID", optional: true }] },
  { id: "x", title: "X (Twitter) DMs", webhook: true, blurb: "Replies to direct messages on X.",
    fields: [{ key: "consumer_secret", label: "API secret (consumer secret)", secret: true }, { key: "user_access_token", label: "User access token", secret: true }] },
  { id: "email", title: "Email", webhook: true, blurb: "Inbound email forwarded by your email provider as a signed webhook; replies go out over SMTP.",
    fields: [
      { key: "webhook_secret", label: "Webhook signing secret", secret: true }, { key: "smtp_host", label: "SMTP host" }, { key: "smtp_port", label: "SMTP port" },
      { key: "username", label: "SMTP username" }, { key: "password", label: "SMTP password", secret: true }, { key: "from_addr", label: "From address" },
    ] },
  { id: "paystack", title: "Paystack payments", webhook: true,
    blurb: "Lets the agent create secure payment links and confirm payments with Paystack. It will never say a payment is received unless Paystack confirms it.",
    fields: [{ key: "secret_key", label: "Secret key", secret: true, help: "Start with a test key (sk_test_…)" }] },
];

export function ChannelsForm({ configured, tenant, backendUrl }: { configured: Record<string, string[]>; tenant: string; backendUrl: string }) {
  return (
    <div className="stack">
      <Notice tone="info">Secrets are write-only: once saved they can't be viewed again, only replaced. Saving a channel replaces all of its fields, so re-enter every field.</Notice>
      {SECTIONS.map((s) => <Channel key={s.id} s={s} saved={configured[s.id]} url={`${backendUrl}/webhooks/${tenant}/${s.id}`} />)}
      <section className="card"><div className="cardhead"><h2>TikTok</h2><Badge>Not available</Badge></div>
        <p className="muted">TikTok doesn't offer businesses an API for reading or answering DMs, so the agent can't chat there. TikTok will be supported for planning and publishing videos once your TikTok developer access is approved.</p></section>
    </div>
  );
}

function Channel({ s, saved, url }: { s: Section; saved?: string[]; url: string }) {
  const [vals, setVals] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const router = useRouter();

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const body = Object.fromEntries(s.fields.filter((f) => vals[f.key]?.trim()).map((f) => [f.key, vals[f.key].trim()]));
    const missing = s.fields.filter((f) => !f.optional && !body[f.key]);
    if (missing.length) return toast(`Please fill in: ${missing.map((m) => m.label).join(", ")}`, "error");
    setBusy(true);
    const r = await call(`secrets/${s.id}`, { method: "PUT", body });
    setBusy(false);
    if (!r.ok) return toast(r.error, "error");
    setVals({});
    toast(`${s.title} saved.`, "ok");
    router.refresh();
  }

  return (
    <details className="card" open={!saved}>
      <summary className="row spread" style={{ cursor: "pointer", listStyle: "none" }}>
        <h2>{s.title}</h2>
        {saved ? <Badge tone="ok">Connected · {saved.length} fields saved</Badge> : <Badge>Not connected</Badge>}
      </summary>
      <form className="stack" onSubmit={save} style={{ marginTop: "0.9rem" }} autoComplete="off">
        <p className="muted small">{s.blurb}</p>
        {s.webhook && (
          <div className="notice info small">
            Webhook URL to give the platform: <span className="mono" style={{ wordBreak: "break-all" }}>{url}</span>
            {url.includes("127.0.0.1") && <> · <strong>Note:</strong> this is a local address; platforms can only call a public one.</>}
          </div>
        )}
        <div className="grid g2">
          {s.fields.map((f) => (
            <label className="field" key={f.key}>
              {f.label}{f.optional && <span className="help"> (optional)</span>}
              <input type={f.secret ? "password" : "text"} value={vals[f.key] ?? ""} onChange={(e) => setVals({ ...vals, [f.key]: e.target.value })}
                autoComplete="off" spellCheck={false} placeholder={saved?.includes(f.key) ? "•••••• saved" : ""} />
              {f.help && <span className="help">{f.help}</span>}
            </label>
          ))}
        </div>
        <div><button className="btn primary" disabled={busy}>{busy ? "Saving…" : saved ? "Replace settings" : "Connect"}</button></div>
      </form>
    </details>
  );
}
