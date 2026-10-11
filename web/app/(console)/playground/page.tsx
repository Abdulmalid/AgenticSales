import { Notice, PageHead } from "@/components/ui";
import { tryApi } from "@/lib/backend";
import type { Me } from "@/lib/types";
import { Chat } from "./Chat";

export const metadata = { title: "Playground" };

export default async function Playground() {
  const { data: me } = await tryApi<Me>("/v1/me");
  return (
    <>
      <PageHead title="Playground" sub="Chat with your agent exactly as a customer would. Nothing here is sent to a real customer." />
      {me && !me.models.text && (
        <div style={{ marginBottom: "1rem" }}>
          <Notice tone="warn">No AI model is configured on the server, so the agent can't reply. Set a model API key in the backend's environment.</Notice>
        </div>
      )}
      <Chat product={me?.products[0]?.name ?? "your product"} />
    </>
  );
}
