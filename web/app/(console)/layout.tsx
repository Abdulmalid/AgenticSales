import { redirect } from "next/navigation";
import { logout } from "@/app/login/actions";
import { BottomNav, SideNav } from "@/components/Nav";
import { ToastProvider } from "@/components/toast";
import { Icon } from "@/components/icons";
import { tryApi } from "@/lib/backend";
import { getSession } from "@/lib/session";
import type { Me } from "@/lib/types";

export default async function ConsoleLayout({ children }: { children: React.ReactNode }) {
  const session = await getSession();
  if (!session) redirect("/login");
  const { data: me } = await tryApi<Me>("/v1/me");
  const pending = me?.pending_approvals ?? 0;

  return (
    <ToastProvider>
      <div className="shell">
        <aside className="sidebar">
          <div className="brand">
            <span className="logo">A</span>
            <span>AgenticSales</span>
          </div>
          <SideNav role={session.role} pending={pending} />
          <div className="foot">
            <div className="small" style={{ fontWeight: 650 }}>{session.business}</div>
            <div className="small muted">{session.role === "admin" ? "Owner / admin" : "Staff"}</div>
            <form action={logout} style={{ marginTop: "0.6rem" }}>
              <button className="btn sm ghost" type="submit" style={{ paddingLeft: 0 }}>
                <Icon name="out" /> Sign out
              </button>
            </form>
          </div>
        </aside>
        <div>
          <header className="topbar">
            <div className="brand"><span className="logo">A</span><span>{session.business}</span></div>
            <form action={logout}><button className="btn sm ghost" type="submit" aria-label="Sign out"><Icon name="out" /></button></form>
          </header>
          <main id="main" className="main">{children}</main>
        </div>
        <BottomNav role={session.role} pending={pending} />
      </div>
    </ToastProvider>
  );
}
