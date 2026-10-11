// Small inline icon set (24x24, stroke). Decorative: aria-hidden.
import type { ReactNode } from "react";

function Svg({ children, size = 20 }: { children: ReactNode; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  );
}

export const icons = {
  home: <Svg><path d="M3 11l9-8 9 8" /><path d="M5 10v10h14V10" /></Svg>,
  leads: <Svg><circle cx="9" cy="8" r="3.2" /><path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6" /><path d="M17 5a3 3 0 010 6M21 20c0-2.6-1.6-4.8-4-5.6" /></Svg>,
  approvals: <Svg><path d="M5 12l4.5 4.5L19 7" /><rect x="3" y="3" width="18" height="18" rx="4" /></Svg>,
  chat: <Svg><path d="M4 5h16v11H9l-5 4z" /></Svg>,
  content: <Svg><rect x="3" y="4" width="18" height="16" rx="3" /><circle cx="9" cy="10" r="2" /><path d="M21 16l-5-4-8 8" /></Svg>,
  analytics: <Svg><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></Svg>,
  settings: <Svg><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z" /></Svg>,
  more: <Svg><circle cx="5" cy="12" r="1.2" /><circle cx="12" cy="12" r="1.2" /><circle cx="19" cy="12" r="1.2" /></Svg>,
  shield: <Svg><path d="M12 3l8 3v6c0 4.5-3.2 7.8-8 9-4.8-1.2-8-4.5-8-9V6z" /></Svg>,
  money: <Svg><rect x="2" y="6" width="20" height="12" rx="2" /><circle cx="12" cy="12" r="2.5" /></Svg>,
  flame: <Svg><path d="M12 3c1 3-2 4-2 7a2 2 0 004 0c2 1.5 3 3 3 5a5 5 0 01-10 0c0-4 3-6 5-12z" /></Svg>,
  target: <Svg><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="5" /><circle cx="12" cy="12" r="1" /></Svg>,
  out: <Svg><path d="M9 4H5v16h4M16 8l4 4-4 4M20 12H9" /></Svg>,
};

export type IconName = keyof typeof icons;
export const Icon = ({ name }: { name: IconName }) => icons[name];
