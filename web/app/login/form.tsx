"use client";
import { useActionState } from "react";
import { login, type LoginState } from "./actions";

export function LoginForm() {
  const [state, action, pending] = useActionState<LoginState, FormData>(login, {});
  return (
    <form action={action} className="stack">
      <label className="field">
        API key
        <input name="key" type="password" autoComplete="off" spellCheck={false} placeholder="ask_…" required aria-describedby={state.error ? "login-err" : undefined} />
      </label>
      {state.error && <div id="login-err" className="notice danger" role="alert">{state.error}</div>}
      <button className="btn primary" type="submit" disabled={pending}>{pending ? "Signing in…" : "Sign in"}</button>
    </form>
  );
}
