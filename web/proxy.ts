// Optimistic gate only: redirect to /login when there is no session cookie. Real authorization happens on the
// Python API with the API key; this just avoids rendering console pages for anonymous visitors.
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function proxy(request: NextRequest) {
  const has = request.cookies.get("as_session")?.value;
  if (!has) {
    const url = new URL("/login", request.url);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  // everything except the login page, the BFF (which answers 401 itself), and static assets
  matcher: ["/((?!login|api/|_next/|favicon.ico|icon.svg).*)"],
};
