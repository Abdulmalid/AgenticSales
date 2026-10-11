"use client";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { useToast } from "@/components/toast";
import { call } from "@/lib/client";

export function EraseButton({ channel, userId }: { channel: string; userId: string }) {
  const dlg = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const router = useRouter();

  async function erase() {
    setBusy(true);
    const r = await call(`customers/${encodeURIComponent(channel)}/${encodeURIComponent(userId)}`, { method: "DELETE" });
    setBusy(false);
    if (r.ok) {
      toast("Customer data erased.", "ok");
      dlg.current?.close();
      router.push("/leads");
      router.refresh();
    } else toast(r.error, "error");
  }

  return (
    <>
      <button className="btn danger" onClick={() => dlg.current?.showModal()}>Erase this customer's data</button>
      <dialog ref={dlg} aria-labelledby="erase-title">
        <div className="dhead"><h2 id="erase-title">Erase customer data?</h2></div>
        <div className="dbody stack">
          <p>This permanently deletes the conversation, lead record, orders and memory for this customer. It cannot be undone.</p>
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <button className="btn" onClick={() => dlg.current?.close()}>Cancel</button>
            <button className="btn danger" onClick={erase} disabled={busy}>{busy ? "Erasing…" : "Erase permanently"}</button>
          </div>
        </div>
      </dialog>
    </>
  );
}
