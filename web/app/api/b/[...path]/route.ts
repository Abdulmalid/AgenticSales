// Backend-for-frontend proxy. The browser never sees the API key: this handler reads it from the
// encrypted httpOnly session cookie and attaches it server-side. See lib/policy.ts for the rules.
import type { NextRequest } from "next/server";
import { callBackend } from "@/lib/backend";
import { checkProxyRequest, MAX_BODY_BYTES, passthroughType } from "@/lib/policy";
import { getSession } from "@/lib/session";

export const maxDuration = 60; // model calls can be slow

type Ctx = { params: Promise<{ path: string[] }> };

async function handle(req: NextRequest, ctx: Ctx): Promise<Response> {
  const session = await getSession();
  if (!session) return Response.json({ detail: "Not signed in" }, { status: 401 });

  const { path } = await ctx.params;
  const check = checkProxyRequest({
    method: req.method,
    segments: path,
    origin: req.headers.get("origin"),
    selfOrigin: req.nextUrl.origin,
    csrfHeader: req.headers.get("x-csrf"),
    contentLength: req.headers.get("content-length") ? Number(req.headers.get("content-length")) : null,
  });
  if (!check.ok) return Response.json({ detail: check.reason }, { status: check.status });

  let body: unknown;
  if (req.method !== "GET" && req.method !== "DELETE") {
    const text = await req.text();
    if (text.length > MAX_BODY_BYTES) return Response.json({ detail: "body too large" }, { status: 413 });
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        return Response.json({ detail: "invalid JSON" }, { status: 400 });
      }
    }
  }

  const search = req.nextUrl.search; // query strings (filters) pass through; the path was validated
  let upstream: Response;
  try {
    upstream = await callBackend(check.backendPath + search, session.key, { method: req.method, body });
  } catch {
    return Response.json({ detail: "The AgenticSales API is unreachable." }, { status: 503 });
  }

  const kind = passthroughType(upstream.headers.get("content-type"));
  if (kind === "image") {
    return new Response(await upstream.arrayBuffer(), {
      status: upstream.status,
      headers: { "Content-Type": upstream.headers.get("content-type")!, "Cache-Control": "private, max-age=600", "X-Content-Type-Options": "nosniff" },
    });
  }
  if (kind === "json") {
    // 401 from upstream means the stored key was revoked: tell the client to re-authenticate
    return new Response(await upstream.text(), { status: upstream.status, headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
  }
  return Response.json({ detail: "Unexpected response from the API" }, { status: 502 });
}

export { handle as GET, handle as POST, handle as PUT, handle as DELETE };
