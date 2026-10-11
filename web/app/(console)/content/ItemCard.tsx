"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Badge } from "@/components/ui";
import { useToast } from "@/components/toast";
import { call } from "@/lib/client";
import { relTime, titleCase } from "@/lib/format";
import type { ContentItem } from "@/lib/types";

const TONE = { draft: "warn", pending_approval: "info", approved: "ok", scheduled: "brand", published: "ok", rejected: "neutral" } as const;

export function ItemCard({ item, imageAvailable }: { item: ContentItem; imageAvailable: boolean }) {
  const router = useRouter();
  const toast = useToast();
  const [caption, setCaption] = useState(item.caption);
  const [when, setWhen] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [imgKey, setImgKey] = useState(0);
  const dirty = caption !== item.caption;
  const editable = !["published", "rejected"].includes(item.status);

  async function act(label: string, fn: () => ReturnType<typeof call>, okMsg: string) {
    setBusy(label);
    const r = await fn();
    setBusy(null);
    if (!r.ok) return toast(r.error, "error");
    toast(okMsg, "ok");
    router.refresh();
    return r;
  }

  const save = () => act("save", async () => {
    const r = await call<{ violations: string[] }>(`content/${item.id}`, { method: "PUT", body: { caption } });
    if (r.ok && r.data.violations.length) toast(`Saved, but still flagged: ${r.data.violations[0]}`, "error");
    return r;
  }, "Saved.");

  return (
    <article className="card" aria-labelledby={`it-${item.id}`}>
      <div className="cardhead">
        <div className="row wrap">
          <h2 id={`it-${item.id}`} style={{ fontSize: "1rem" }}>{titleCase(item.platform === "meta" ? "Instagram / Meta" : "TikTok")}{item.surface && ` · ${titleCase(item.surface)}`}</h2>
          <Badge tone={TONE[item.status]}>{titleCase(item.status)}</Badge>
          {item.objective && <Badge>{titleCase(item.objective)}</Badge>}
        </div>
        <span className="small muted">{relTime(item.created)}</span>
      </div>

      {item.violations.length > 0 && (
        <div className="notice warn" style={{ marginBottom: "0.8rem" }}>
          <strong>Needs changes before it can be approved</strong>
          <ul>{item.violations.map((v) => <li key={v}>{v}</li>)}</ul>
        </div>
      )}

      <div className="grid" style={{ gridTemplateColumns: item.media_path ? "minmax(0,1fr) 180px" : "1fr", alignItems: "start" }}>
        <div className="stack">
          <label className="field">
            Caption
            {editable ? (
              <textarea value={caption} onChange={(e) => setCaption(e.target.value)} maxLength={2200} style={{ minHeight: 110 }} />
            ) : <div style={{ whiteSpace: "pre-wrap" }}>{item.caption}</div>}
          </label>
          {item.hashtags.length > 0 && <div className="row wrap">{item.hashtags.map((h) => <Badge key={h} tone="info">#{h}</Badge>)}</div>}
          {item.cta && <p className="small"><strong>Call to action:</strong> {item.cta}</p>}
          {item.image_prompt && <details><summary className="small muted" style={{ cursor: "pointer" }}>Image idea</summary><p className="small" style={{ marginTop: "0.4rem" }}>{item.image_prompt}</p></details>}
          {item.video_script?.beats && (
            <details>
              <summary className="small muted" style={{ cursor: "pointer" }}>Video script{item.video_script.duration_seconds ? ` (${item.video_script.duration_seconds}s)` : ""}</summary>
              <ol className="small" style={{ marginTop: "0.4rem" }}>
                {item.video_script.beats.map((b, i) => <li key={i}><strong>{b.t}</strong>: {b.visual}{b.voiceover && <> · “{b.voiceover}”</>}{b.on_screen_text && <> · on screen: {b.on_screen_text}</>}</li>)}
              </ol>
            </details>
          )}
        </div>
        {item.media_path && (
          // eslint-disable-next-line @next/next/no-img-element
          <img key={imgKey} src={`/api/b/content/${item.id}/media?v=${imgKey}`} alt={item.alt_text ?? "Generated image"} style={{ width: "100%", borderRadius: 10, border: "1px solid var(--line)" }} />
        )}
      </div>

      {item.error && <div className="notice danger" style={{ marginTop: "0.8rem" }}>{item.error}</div>}
      {item.scheduled_for && <p className="small muted" style={{ marginTop: "0.6rem" }}>Scheduled for {new Date(item.scheduled_for).toLocaleString("en-GB")}</p>}

      {editable && (
        <div className="row wrap" style={{ marginTop: "0.9rem" }}>
          {dirty && <button className="btn" disabled={!!busy} onClick={save}>{busy === "save" ? "Saving…" : "Save changes"}</button>}
          {(item.status === "pending_approval" || item.status === "draft") && (
            <button className="btn primary" disabled={!!busy || dirty || item.violations.length > 0}
              title={item.violations.length ? "Fix the flagged wording first" : dirty ? "Save your edits first" : undefined}
              onClick={() => act("approve", () => call(`content/${item.id}/approve`, { method: "POST" }), "Approved.")}>
              {busy === "approve" ? "Approving…" : "Approve"}
            </button>
          )}
          {item.status === "approved" && (
            <>
              <input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} aria-label="Schedule time" style={{ width: "auto" }} />
              <button className="btn primary" disabled={!!busy || !when}
                onClick={() => act("schedule", () => call(`content/${item.id}/schedule`, { method: "POST", body: { when: new Date(when).toISOString() } }), "Scheduled.")}>
                Schedule
              </button>
            </>
          )}
          {imageAvailable && item.image_prompt && (
            <button className="btn" disabled={!!busy} onClick={async () => { const r = await act("image", () => call(`content/${item.id}/image`, { method: "POST" }), "Image created."); if (r?.ok) setImgKey((k) => k + 1); }}>
              {busy === "image" ? "Creating image…" : item.media_path ? "Regenerate image" : "Create image"}
            </button>
          )}
          <button className="btn danger" disabled={!!busy} onClick={() => act("reject", () => call(`content/${item.id}/reject`, { method: "POST" }), "Rejected.")}>Reject</button>
        </div>
      )}
    </article>
  );
}
