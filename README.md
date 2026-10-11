# AgenticSales

An AI sales representative and business-automation platform built for Nigerian businesses. It talks to customers on WhatsApp, Instagram, Messenger, X and email, qualifies and scores leads, negotiates within rules the owner sets, checks for fraud, verifies payments through the gateway, follows up after sales, and plans social-media content, all while keeping the owner in control through approvals.

> Build an AI sales employee, not an AI chatbot.

## What's here

| Path | What it is |
|---|---|
| `agentic_sales/` | Python backend: agents, tools, policy, memory, leads, fraud, payments, channels, content, HTTP API |
| `web/` | Next.js console (leads, approvals, playground, content, analytics, settings), deployed on Vercel |
| `tests/` | ~126 offline tests (scripted models, fake gateway, FastAPI TestClient) |
| `docs/ARCHITECTURE.md` | Design, audit of the original code, safety properties, **honest status of every subsystem** |
| `docs/DEPLOY.md` | Hosting the API + deploying the console |
| `data/eval/` | Owner-labelled Nigerian customer messages for measuring the language/signal layer (`sealed/` is an acceptance set: **score it, never read or tune against it**) |
| `scripts/seed_demo.py` | Seeds a demo business with realistic data |

## Quick start

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt      # Linux/macOS: .venv/bin/python
cp .env.example .env                                          # add GEMINI_API_KEY and/or ANTHROPIC_API_KEY
.venv/Scripts/python -m agentic_sales.cli tenant-create --id demo --config examples/demo_business.json   # prints an admin key once
.venv/Scripts/python -m agentic_sales.cli serve               # API on :8000

cd web && npm install && cp .env.example .env.local           # set BACKEND_URL, SESSION_SECRET
npm run dev                                                   # console on :3000
```

Tests: `python -X utf8 -m unittest discover -s tests` and `cd web && npm test`. Browser walkthrough: `node web/e2e/smoke.mjs` (see `web/README.md`).

## The knowledge corpora are not in git

Nine research corpora (about 600 MB: Nigerian Pidgin, Nigerian English, conversation pragmatics, guardrails, lead-gen, conversion, retention, and Meta/TikTok marketing) power retrieval. They're too large for normal git and are shared separately. Put the `.jsonl` files in `data/corpora/raw/` (see `data/corpora/README.md`) and run:

```bash
python -m agentic_sales.corpus.build      # about 3 minutes, writes data/index/corpus.db (~850 MB, gitignored)
```
The agent still works without them but loses the Nigerian-language and guardrail retrieval.

## Ground rules for contributors
- **Never commit secrets.** `.env`, `data/tenants/`, `data/auth.db` and `web/.env.local` are gitignored; keep it that way. Rotate any key that is ever pasted into chat or a ticket.
- **Policy lives in code, not prompts.** Prices, discounts, payment confirmation and escalation are enforced by `policy/`, `tools/`, and `security/`; changes there need tests.
- **Don't tune against `data/eval/sealed/`.** Use `holdout_dev` for iteration; the sealed set is the honest number.
- Several integrations (Paystack, WhatsApp/Meta, X, email, image generation) are written to the platforms' docs but **have not run against the live services**: see `docs/ARCHITECTURE.md` section 9.
