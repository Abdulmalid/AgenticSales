# Deploying

```
Browser ──► Vercel (web/, Next.js console) ──server-side proxy──► API host (Python, Docker) ──► Gemini / Claude / Paystack / Meta
                                                                       ▲
                                    WhatsApp / Instagram / Messenger / X / email webhooks ┘  (these point at the API host, NOT Vercel)
```

The console never holds the API key in the browser: `/login` verifies it, then stores it **encrypted in an httpOnly cookie** and the Next.js server attaches it to every request. Only the API host needs to be reachable by Meta/X/Paystack.

## 1. Host the API (needs a persistent disk)

Vercel cannot run this part: each business's data is SQLite on disk, replies take 5-50 s, and webhooks must be answered reliably. Use any host with a volume (Railway, Fly.io, Render, a VPS).

| Setting | Value |
|---|---|
| Build | `Dockerfile` in the repo root (not yet build-tested: Docker's engine was off when written) |
| Volume | mount at `/data` (tenant DBs, secrets, media, search index). **Back it up.** |
| Port | `8000` (or `PORT`) |
| Env | `GEMINI_API_KEY` and/or `ANTHROPIC_API_KEY` (+ `ANTHROPIC_WORKSPACE_ID`), `MODEL_PROVIDER`, `AGENTIC_DATA_DIR=/data` |
| HTTPS | required (the host usually terminates TLS) |

Optional but recommended: copy `data/corpora/raw/*.jsonl` to `/data/corpora/raw/` and run `python -m agentic_sales.corpus.build` once on the host (about 3 min, ~850 MB index). Without it the agent still works, but loses the Nigerian-language and guardrail retrieval.

Create your first business and API key on the host (the key is printed once):
```
python -m agentic_sales.cli tenant-create --id my-shop --config examples/demo_business.json
```

## 2. Deploy the console to Vercel

You sign in; I never need your password or token in chat.
```
cd web
npx vercel login                       # opens a browser
npx vercel link                        # create/select the project; set Root Directory to "web" if linking from the repo root
npx vercel env add BACKEND_URL production          # https://<your-api-host>
npx vercel env add BACKEND_PUBLIC_URL production   # same URL (shown to owners for webhook setup)
npx vercel env add SESSION_SECRET production       # openssl rand -base64 48   (32+ chars; the app refuses to start without it)
npx vercel --prod
```
Or import the GitHub repo in the Vercel dashboard with **Root Directory = `web`** and add the same three variables.

**Function timeout.** Replying to a customer takes one or two model calls. On free-tier models that was 4-50 s. Vercel's Hobby plan caps functions at 60 s at most, so a slow Playground turn can time out there even though the real WhatsApp path (API host, not Vercel) is unaffected. Pro raises the limit, and a faster paid model fixes the cause.

## 3. Connect channels
In the console: **Settings → Channels**. It shows the exact webhook URL for each channel (it points at `BACKEND_PUBLIC_URL`). In Meta's developer console set the callback URL and the same verify token. Meta/X/TikTok app approval and the credentials are yours to obtain; none are included.

## 4. Before real customers
- Rotate any API key that was ever pasted into a chat or committed. Keep `.env` out of git (already ignored).
- Put a scheduler on the API host that calls `POST /v1/followups/run` and `POST /v1/outbox/flush` every few minutes (the console's Settings → Automation has buttons, but nothing runs on a timer yet).
- Encrypt `secrets.json` at rest or move it to your host's secret manager.
- The API's per-tenant lock and SQLite suit a pilot (tens of businesses), not scale.

## Git-based deploys (Vercel)

The console deploys from the private GitHub repo `Abdulmalid/AgenticSales` (the Vercel project's Root Directory is `web`). Pushes to `main` deploy to production; other branches get previews.

- **Commit author must be a GitHub account.** Vercel blocks a deployment when it cannot map the commit author's email to a GitHub account ("couldn't find a Git account for the commit author"). Either add your commit email under GitHub Settings -> Emails (verified), or commit with the private address `ID+USERNAME@users.noreply.github.com` (`git config user.email ...`).
- **Collaborators on a Hobby plan.** Vercel Hobby deploys private personal repos from the owner's pushes; teammates' pushes are blocked unless they are members of the Vercel team. Add them under the Vercel team's Members (a paid seat on Pro), or have them open pull requests that the owner merges.
- CLI deploys from `web/` no longer work once Root Directory is `web`; deploy from the repo root or push to `main`.
