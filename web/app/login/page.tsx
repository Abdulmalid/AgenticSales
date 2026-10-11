import type { Metadata } from "next";
import { LoginForm } from "./form";

export const metadata: Metadata = { title: "Sign in" };

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ expired?: string }> }) {
  const { expired } = await searchParams;
  return (
    <div className="loginwrap">
      <div className="card logincard stack">
        <div className="brand"><span className="logo">A</span><span>AgenticSales</span></div>
        <div>
          <h1>Sign in</h1>
          <p className="muted" style={{ marginTop: "0.3rem" }}>Paste the API key for your business. It is shown once when your workspace is created.</p>
        </div>
        {expired && <div className="notice warn">Your session ended. Please sign in again.</div>}
        <LoginForm />
        <p className="small muted">The key is encrypted into a secure cookie on the server and is never exposed to the page.</p>
      </div>
    </div>
  );
}
