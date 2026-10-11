// Presentational pieces usable from server and client components.
import type { ReactNode } from "react";
import { titleCase } from "@/lib/format";
import type { Stage } from "@/lib/types";

export function PageHead({ title, sub, children }: { title: string; sub?: string; children?: ReactNode }) {
  return (
    <div className="pagehead">
      <div>
        <h1>{title}</h1>
        {sub && <p className="sub">{sub}</p>}
      </div>
      {children && <div className="row wrap">{children}</div>}
    </div>
  );
}

export function Badge({ tone = "neutral", children }: { tone?: "neutral" | "ok" | "warn" | "danger" | "info" | "brand"; children: ReactNode }) {
  return <span className={`badge ${tone === "neutral" ? "" : tone}`}>{children}</span>;
}

const STAGE_TONE: Record<Stage, "neutral" | "ok" | "warn" | "danger" | "info" | "brand"> = {
  NEW: "neutral", DISCOVERED: "neutral", CONTACTED: "info", ENGAGED: "info", QUALIFIED: "brand",
  NEGOTIATING: "warn", READY_TO_BUY: "ok", CONVERTED: "ok", RETAINED: "ok", LOST: "neutral", FRAUD_SUSPECTED: "danger",
};
export const StageBadge = ({ stage }: { stage: Stage }) => <Badge tone={STAGE_TONE[stage]}>{titleCase(stage)}</Badge>;

export function BandBadge({ band }: { band: "cold" | "warm" | "hot" }) {
  return <Badge tone={band === "hot" ? "warn" : band === "warm" ? "info" : "neutral"}>{band === "hot" ? "🔥 Hot" : titleCase(band)}</Badge>;
}

export function FraudBadge({ risk }: { risk: "LOW" | "MEDIUM" | "HIGH" }) {
  if (risk === "LOW") return null;
  return <Badge tone={risk === "HIGH" ? "danger" : "warn"}>{risk === "HIGH" ? "Fraud review" : "Watch"}</Badge>;
}

export function ScoreBar({ score, band }: { score: number; band: "cold" | "warm" | "hot" }) {
  return (
    <div className="row" style={{ gap: "0.5rem" }} title={`Score ${score}/100`}>
      <div className={`bar ${band}`} style={{ width: 90 }} role="meter" aria-valuenow={score} aria-valuemin={0} aria-valuemax={100} aria-label="Lead score">
        <span style={{ width: `${score}%` }} />
      </div>
      <span className="small mono">{score}</span>
    </div>
  );
}

export function Stat({ label, value, hint, href, icon }: { label: string; value: ReactNode; hint?: ReactNode; href?: string; icon?: ReactNode }) {
  const body = (
    <>
      <div className="label">{icon}{label}</div>
      <div className="value">{value}</div>
      {hint && <div className="hint">{hint}</div>}
    </>
  );
  return href ? (
    <a className="card stat" href={href}>{body}</a>
  ) : (
    <div className="card stat">{body}</div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <strong>{title}</strong>
      {children}
    </div>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "warn" | "danger" | "ok"; children: ReactNode }) {
  return <div className={`notice ${tone}`} role={tone === "danger" ? "alert" : "status"}>{children}</div>;
}

export function ErrorPanel({ message }: { message: string }) {
  return (
    <div className="card">
      <Notice tone="danger">{message}</Notice>
    </div>
  );
}
