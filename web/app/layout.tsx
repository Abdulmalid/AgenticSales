import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "AgenticSales", template: "%s · AgenticSales" },
  description: "Your AI sales team for Nigerian businesses: leads, approvals, content and conversations in one place.",
  robots: { index: false, follow: false }, // a private console, not a public site
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#0b6e4f" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <a className="skip" href="#main">Skip to content</a>
        {children}
      </body>
    </html>
  );
}
