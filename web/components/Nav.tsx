"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon, type IconName } from "./icons";

type Item = { href: string; label: string; icon: IconName; adminOnly?: boolean };
const ITEMS: Item[] = [
  { href: "/", label: "Overview", icon: "home" },
  { href: "/leads", label: "Leads", icon: "leads" },
  { href: "/approvals", label: "Approvals", icon: "approvals" },
  { href: "/playground", label: "Playground", icon: "chat" },
  { href: "/content", label: "Content", icon: "content" },
  { href: "/analytics", label: "Analytics", icon: "analytics" },
  { href: "/settings", label: "Settings", icon: "settings", adminOnly: true },
];
const MOBILE_MAIN = ["/", "/leads", "/approvals", "/content"];

function active(path: string, href: string) {
  return href === "/" ? path === "/" : path === href || path.startsWith(href + "/");
}

export function SideNav({ role, pending }: { role: "admin" | "staff"; pending: number }) {
  const path = usePathname();
  return (
    <nav className="nav" aria-label="Main">
      {ITEMS.filter((i) => !i.adminOnly || role === "admin").map((i) => (
        <Link key={i.href} href={i.href} aria-current={active(path, i.href) ? "page" : undefined}>
          <Icon name={i.icon} />
          {i.label}
          {i.href === "/approvals" && pending > 0 && <span className="count">{pending}</span>}
        </Link>
      ))}
    </nav>
  );
}

export function BottomNav({ role, pending }: { role: "admin" | "staff"; pending: number }) {
  const path = usePathname();
  const items = ITEMS.filter((i) => !i.adminOnly || role === "admin");
  const main = items.filter((i) => MOBILE_MAIN.includes(i.href));
  const more = items.filter((i) => !MOBILE_MAIN.includes(i.href));
  return (
    <nav className="bottomnav" aria-label="Main">
      {main.map((i) => (
        <Link key={i.href} href={i.href} aria-current={active(path, i.href) ? "page" : undefined}>
          <Icon name={i.icon} />
          {i.label}
          {i.href === "/approvals" && pending > 0 && <span className="count">{pending}</span>}
        </Link>
      ))}
      <details>
        <summary>
          <Icon name="more" />
          More
        </summary>
        <div>
          {more.map((i) => (
            <Link key={i.href} href={i.href} aria-current={active(path, i.href) ? "page" : undefined}>
              <Icon name={i.icon} />
              {i.label}
            </Link>
          ))}
        </div>
      </details>
    </nav>
  );
}
