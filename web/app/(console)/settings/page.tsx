import Link from "next/link";
import { redirect } from "next/navigation";
import { ErrorPanel, PageHead } from "@/components/ui";
import { publicBackendUrl, tryApi } from "@/lib/backend";
import { getSession } from "@/lib/session";
import type { BusinessConfig, OutboxItem } from "@/lib/types";
import { Automation } from "./Automation";
import { BusinessForm } from "./BusinessForm";
import { ChannelsForm } from "./ChannelsForm";
import { LandingForm } from "./LandingForm";

export const metadata = { title: "Settings" };
const TABS = [["business", "Business & rules"], ["channels", "Channels & payments"], ["automation", "Automation"], ["website", "Landing page"]] as const;

export default async function Settings({ searchParams }: { searchParams: Promise<{ tab?: string }> }) {
  const session = await getSession();
  if (!session) redirect("/login");
  if (session.role !== "admin") redirect("/");
  const requested = (await searchParams).tab;
  const tab = TABS.some(([k]) => k === requested) ? requested! : "business";

  return (
    <>
      <PageHead title="Settings" sub="Teach the agent about your business and set the rules it must follow." />
      <div className="tabs" role="navigation" aria-label="Settings sections">
        {TABS.map(([k, label]) => <Link key={k} href={`/settings?tab=${k}`} aria-current={tab === k ? "page" : undefined}>{label}</Link>)}
      </div>
      {tab === "business" && <BusinessTab />}
      {tab === "channels" && <ChannelsTab tenant={session.tenant} />}
      {tab === "automation" && <AutomationTab />}
      {tab === "website" && <LandingForm siteUrl={`${publicBackendUrl()}/sites/${session.tenant}`} />}
    </>
  );
}

async function BusinessTab() {
  const { data, error } = await tryApi<BusinessConfig>("/v1/config");
  if (!data) return <ErrorPanel message={error ?? "Couldn't load your settings."} />;
  return <BusinessForm initial={data} />;
}

async function ChannelsTab({ tenant }: { tenant: string }) {
  const { data, error } = await tryApi<Record<string, string[]>>("/v1/secrets");
  if (!data) return <ErrorPanel message={error ?? "Couldn't load channel settings."} />;
  return <ChannelsForm configured={data} tenant={tenant} backendUrl={publicBackendUrl()} />;
}

async function AutomationTab() {
  const { data } = await tryApi<OutboxItem[]>("/v1/outbox?limit=30");
  return <Automation outbox={data ?? []} />;
}
