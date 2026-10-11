import { Empty, ErrorPanel, PageHead } from "@/components/ui";
import { tryApi } from "@/lib/backend";
import { relTime, who } from "@/lib/format";
import type { Approval, Me } from "@/lib/types";
import { ApprovalCard } from "./ApprovalCard";

export const metadata = { title: "Approvals" };

function parse<T>(s: string, fallback: T): T {
  try { return JSON.parse(s) as T; } catch { return fallback; }
}

export default async function Approvals() {
  const [list, me] = await Promise.all([tryApi<Approval[]>("/v1/approvals"), tryApi<Me>("/v1/me")]);
  if (list.error && !list.data) return <><PageHead title="Approvals" /><ErrorPanel message={list.error} /></>;
  const products = Object.fromEntries((me.data?.products ?? []).map((p) => [p.sku, p]));

  return (
    <>
      <PageHead title="Approvals" sub="Decisions your AI agent won't make on its own: discounts beyond its limit, large orders, fraud reviews and hand-offs." />
      {list.data!.length === 0 ? (
        <div className="card"><Empty title="Nothing waiting on you">When the agent needs a decision it will appear here, and the customer is told you're checking.</Empty></div>
      ) : (
        <div className="stack">
          {list.data!.map((a) => (
            <ApprovalCard
              key={a.id}
              id={a.id}
              action={a.action}
              who={who(a.customer_key)}
              customerKey={a.customer_key}
              when={relTime(a.created)}
              trace={a.trace}
              payload={parse<Record<string, unknown>>(a.payload, {})}
              reasons={parse<string[]>(a.reasons, [])}
              product={products[String(parse<Record<string, unknown>>(a.payload, {}).sku)] ?? null}
            />
          ))}
        </div>
      )}
    </>
  );
}
