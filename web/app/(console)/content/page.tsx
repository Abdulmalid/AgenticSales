import Link from "next/link";
import { ErrorPanel, Notice, PageHead } from "@/components/ui";
import { tryApi } from "@/lib/backend";
import { titleCase } from "@/lib/format";
import type { ContentItem, Me } from "@/lib/types";
import { ItemCard } from "./ItemCard";
import { Planner } from "./Planner";

export const metadata = { title: "Content" };

const FILTERS = ["all", "pending_approval", "draft", "approved", "scheduled", "published", "rejected"] as const;

export default async function Content({ searchParams }: { searchParams: Promise<{ status?: string }> }) {
  const sp = await searchParams;
  const status = (FILTERS as readonly string[]).includes(sp.status ?? "") && sp.status !== "all" ? sp.status : undefined;
  const [list, me] = await Promise.all([
    tryApi<ContentItem[]>(`/v1/content${status ? `?status=${status}` : ""}`),
    tryApi<Me>("/v1/me"),
  ]);
  if (list.error && !list.data) return <><PageHead title="Content" /><ErrorPanel message={list.error} /></>;

  return (
    <>
      <PageHead title="Content studio" sub="Plan Instagram, WhatsApp and TikTok posts from proven Nigerian playbooks. Nothing is published without your approval." />
      <div style={{ marginBottom: "1rem" }}>
        <Notice tone="info">Publishing straight to Instagram, Facebook or TikTok isn't connected yet. Approved posts are kept here ready to copy and post, and will publish automatically once those accounts are linked.</Notice>
      </div>
      <Planner imageAvailable={me.data?.models.image ?? false} />

      <div className="tabs" style={{ marginTop: "1.4rem" }} role="navigation" aria-label="Filter content by status">
        {FILTERS.map((f) => (
          <Link key={f} href={f === "all" ? "/content" : `/content?status=${f}`} aria-current={(f === "all" ? !status : status === f) ? "page" : undefined}>
            {titleCase(f)}
          </Link>
        ))}
      </div>
      {list.data!.length === 0 ? (
        <div className="card empty"><strong>No content here yet</strong>Describe a campaign above and the agent will draft posts for you to review.</div>
      ) : (
        <div className="stack">
          {list.data!.map((it) => <ItemCard key={it.id} item={it} imageAvailable={me.data?.models.image ?? false} />)}
        </div>
      )}
    </>
  );
}
