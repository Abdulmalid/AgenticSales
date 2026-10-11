# AgenticSales console

Next.js 16 (App Router) dashboard for business owners and staff: leads, approvals, playground, content studio, analytics and settings. It talks to the Python API through server-side routes only.

```
npm install
cp .env.example .env.local        # BACKEND_URL, BACKEND_PUBLIC_URL, SESSION_SECRET
npm run dev                       # http://localhost:3000   (API must be running; see ../docs/DEPLOY.md)
npm test                          # unit tests (session sealing, proxy policy, formatters)
npm run build && npm start        # production mode
node e2e/smoke.mjs                # real-browser walkthrough (needs Chrome, the API, a seeded tenant: see ../scripts/seed_demo.py)
```

## How it is built
- `lib/seal.ts`: AES-256-GCM session sealing (pure, unit-tested). `lib/session.ts` stores it in an httpOnly, SameSite=Lax cookie. The API key is never sent to browser JavaScript.
- `app/api/b/[...path]/route.ts`: the only way the browser reaches the API. `lib/policy.ts` allow-lists areas, requires a CSRF header and same-origin `Origin` on writes, caps bodies at 256 KB and passes through only JSON and PNG/JPEG.
- `proxy.ts`: redirects anonymous visitors to `/login`. The real authorisation is the API key on the Python API, so a forged cookie gets nothing.
- Pages are server components that fetch with the session; interactive parts are small client components.
- Staff can't open Settings (and the API refuses their config/secret calls regardless).
- Dark mode, phone layout with bottom navigation, keyboard focus styles, skip link, `prefers-reduced-motion`.

## Known limits
- The login throttle is per server instance (serverless instances don't share memory). API keys are 256-bit random, so guessing isn't realistic, but add a shared limiter (e.g. Upstash) before exposing this widely.
- Publishing to social platforms isn't connected, so Content ends at "approved / scheduled".
- No user management screen yet: create keys with the CLI.
