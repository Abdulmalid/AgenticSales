# Architecture & Audit

## 1. Audit of the inherited code (Gemini)

| # | Problem | Why it matters | Resolution |
|---|---|---|---|
| 1 | Five "agents" were keyword-grep wrappers over corpora. No model, tools, memory, tenancy, or actions. | It's a report generator, not an agent. | Replaced by orchestrator + sales agent with a model layer, tools, policy and memory (Phase 1). Other agents come in later phases. |
| 2 | `BaseAgent` searched `title/summary/full_knowledge_block/tags`. Only 2 of 5 corpora have `summary`/`full_knowledge_block`. | Guardrail and Pidgin agents effectively searched titles only. | Per-family schemas in `corpus/families.py`; body text is built from the fields each family really has. |
| 3 | Each agent loaded its whole corpus into RAM (~311 MB parsed, 5x) and did substring matching (`"tin" in text` also matches "writing"). | Slow startup, memory-heavy, no ranking. | SQLite FTS5 index with BM25 + byte offsets back into the raw files; records are read on demand. |
| 4 | Hard-coded `/home/cyboida/AgenticSales`. | Does not run on any other machine. | Paths are relative/configurable. |
| 5 | Corpora contain LLM-corrupted keys (`vulentrable_bot_anti_pattern`, `authentic_customer_inund`, ~100 variants), corrupted layer labels (`AG03_BOOKOSNG_...`), and duplicate `report_id`s (54-237 per file in four of the five). | Agents silently read nothing from damaged records. | `corpus/repair.py` repairs keys/layers deterministically and drops unusable records; `build` prints a repair report. Raw files are never modified. |
| 6 | The guardrail corpus has 5,664 distinct `tool_name`s across 10,000 records, and sample replies like "we have verified your TIN against our database" with no verification step. | Tool names are not a usable tool schema, and the replies teach hallucinated verification. | The corpus is used only for rules and anti-patterns (what *not* to say). Tools are defined in code (`tools/`). Replies/tool calls from the corpus are never copied. |
| 7 | The Nigerian leadgen corpus is B2B outbound/channel playbooks, not conversational sales. Retrieval for "last price" returned logistics affiliate-marketing playbooks. | Irrelevant context degrades replies. | Domain separated (`ng_sales`) and withheld from conversational turns; reserved for the Lead-Gen agent. |
| 8 | The Pidgin corpus is academic linguistics (phonology, TAM, ...). | Useful for usage examples and rules, not as a source of sales behaviour. | `ng_language` domain, queried only when the customer actually writes Pidgin. |
| 9 | `__pycache__` was staged; 311 MB of data sits in git with no LFS. | Repo bloat. | `.gitignore` added, pycache unstaged. **Recommendation: Git LFS or external storage for `data/corpora/raw`.** |

**Update:** the Nigerian English and Nigerian conversation corpora are now ingested (3 of 5 Nigerian corpora are 'reference' style, all LLM-synthesised analyses with embedded dialogue). `NC07_COMMERCIAL_BARGAINING_SCRIPTS` is the first real sales-conversation material. Retrieval is still lexical BM25: measured on sample messages it is good for bargaining and "I'll get back to you", and irrelevant for trust-concern and social-register messages, so those triggers are disabled. A semantic (embedding) retriever is the next upgrade. **Register detection is now learned.** `language/train.py` trains a Naive Bayes classifier (formal / casual / Pidgin; word uni+bigrams) on the 6,644 customer messages in the guardrails corpus whose `language_blend` label is unambiguous (mixed blends excluded). It is blended with the lexical heuristics and temperature-calibrated (T=16, fitted on held-out log-loss). Social-media style stays heuristic: no corpus labels it. On a held-out 20%: **76.2% agreement with corpus labels (old heuristics: 63.6%); 84% when confidence >= 0.6**. Caveats: labels are synthetic and "casual" overlaps heavily with Pidgin in this data (most errors are casual<->Pidgin; formal vs. informal is much cleaner); the heuristic blend weight was chosen on the same held-out split; validate on real chat logs before relying on it. Retrain: `python -m agentic_sales.language.train`. The sales-signal detectors (`extract_signals`) are still hand-written and have not been evaluated against labelled data.

**Original corpus gap:** nothing in the five files is real Nigerian *conversational sales* data
(haggling, hesitation, "I'll get back to you", trust questions) except the synthetic guardrail dialogues. The two
incoming Nigerian-English corpora should be ingested as a new family under `ng_language` / a new `ng_dialogue`
domain with a register label per utterance. Those labelled utterances are what should train/replace the
heuristic register and signal detectors in `language/analysis.py`.

## 2. Layout

```
agentic_sales/
  core/        InboundMessage (channel-agnostic), TenantContext, audit log
  config/      BusinessConfig (products, floor prices, approval rules, retention schedule)
  models/      TextModel/MediaModel protocols, ModelRouter (task -> provider), Anthropic provider
  corpus/      families (schemas+domains), repair, build (FTS5 index), store (retrieval), context (task routing)
  language/    register detection, evidence-bearing sales signals, style planning
  memory/      per-tenant SQLite: short-term chat, customer facts, approvals queue, idempotency
  policy/      deterministic discount/refund/fulfilment decisions
  tools/       ToolRegistry (schema-validated, audited, ctx injected) + built-ins
  security/    untrusted-input fencing, injection flags, reply (output) guard
  agents/      sales (prompting/parsing), orchestrator (turn pipeline)
data/corpora/raw/   original corpora (untouched)      data/index/   derived, gitignored
data/tenants/<id>/  business.json, memory.db, audit.jsonl
```

## 3. Knowledge architecture

| Domain | Source | Used for |
|---|---|---|
| `ng_language` | Pidgin + Nigerian English corpora | usage examples, only for Pidgin-writing customers |
| `ng_conversation` | Nigerian conversation corpus | pragmatics: what bargaining/hedging phrases *mean* and how an AI misreads them (layers `NC07` bargaining, `NC04` indirectness, `NC06` conflict). Used for interpretation only, not as reply templates |
| `smm` | Meta (Instagram, Facebook, WhatsApp, Threads) + TikTok corpora (~20k records) | the future SMM / Content / Media agents, via `corpus/smm.py` (see section 8) |
| `ng_sales` | Nigeria leadgen corpus | Lead-Gen agent (Phase 2), not chat turns |
| `sales_general` | retention + conversion corpora | Retention / conversion agents (Phase 2) |
| `agent_guardrails` | guardrails corpus | rules & anti-patterns for payment/haggling/injection turns |
| business / product | `BusinessConfig` (tenant) | authoritative prices, policies |
| customer | `TenantMemory` (tenant) | preferences, objections, history |

## 4. Turn pipeline and safety properties

`inbound -> clean/fence -> register + signals + style -> retrieval -> model plan -> tools under policy -> finalise -> reply guard -> audit`

- **Customer text is data.** It is normalised, length-bounded, stripped of invisible characters, fenced in the user turn only, and never appears in the system prompt. Injection heuristics are a *risk signal*; the actual defence is below.
- **Policy is code.** The model can only call `propose_price`; `PolicyEngine` decides ALLOW / REQUIRE_APPROVAL / DENY from tenant config. Floor prices are never put in the prompt.
- **Tools are constrained.** Tenant and customer identity come from a server-built `ToolContext`; unknown tools/args are rejected; every call is audited.
- **Output guard.** A reply quoting a ₦ amount not from the product list, a tool result or the customer, or claiming payment is confirmed, is blocked and escalated to a human.
- **Tenant isolation** is structural (one SQLite file / audit file per tenant, path derived from validated `TenantContext`). Still required before any hosted deployment: authenticated tenant resolution at the API edge, secrets storage, per-tenant rate limits.
- **Errors fail safe:** unparseable output or model failure -> neutral holding message + human-handoff row.

## 5. Phase status

| Phase | Status |
|---|---|
| 1 Core: orchestration, model abstraction, tools, memory, business config, corpus system | **Built** (this change) |
| 2 Sales intelligence: lead profile/stages/scoring, qualification, retention scheduler, fuller conversion agent | Next. Signals + customer memory are the inputs. |
| 3 Fraud: risk scoring with confidence + reasons, payment verification **tool** | Not built. Requires a real gateway integration (Paystack verify/webhook). Until then the agent is prohibited from confirming payments. |
| 4 Channels (WhatsApp, IG, FB, Email, TikTok) | Not built. Adapters only need to emit `InboundMessage` and verify webhook signatures. Needs Meta/TikTok credentials and app review. |
| 5-7 Content, media, landing pages, analytics, autonomy | Not built. `MediaModel` interface fixed; no provider connected. |

## 6. Running

```
python -m agentic_sales.corpus.build                       # build index (~30 s)
python -X utf8 -m unittest discover -s tests               # offline tests, no API key
python -X utf8 -m agentic_sales.cli analyze "Oga, how much be the last price?"
# chat: copy examples/demo_business.json to data/tenants/demo/business.json, set ANTHROPIC_API_KEY
python -X utf8 -m agentic_sales.cli chat --tenant demo
```

## 7. Detector validation status (read before trusting the numbers)

Labelled evaluation sets live in `data/eval/`; score any file with `python -m agentic_sales.language.evaluate <file>`.

| Set | What it is | Result |
|---|---|---|
| `customer_messages_naija.jsonl` (115, owner-labelled: register + 5 signal types) | real-style Nigerian seller messages | First run **72% register**; signal recall: negotiation 47%, payment_claim 20%, stalling 12%, trust 15%. After rules were revised from the owner's labelling conventions: **84% register**; signal F1 roughly 0.7-0.94. **These post-fix numbers are optimistic**: the rules were tuned while looking at this exact set. |
| `customer_messages_general_en.jsonl` (75) | general English support (airline/IT), unlabelled for register | 0 of 75 misread as Pidgin (72 formal, 3 casual). Not a Nigerian/sales validation. |

Findings that changed the design: the owner's "social" = rapport-building talk (greetings, well-wishing, compliments on a page), not just emoji/slang; "casual" includes relaxed-but-polite English; pay-on-delivery is *stalling* (trust only when paired with scam fear). Known weak spots: casual vs formal for short plain-English messages (9 of 16 casual still read formal), `trust_concern` recall 65%, `price_inquiry` recall 77%. **Next validation step: a fresh labelled batch that the rules have never seen.**

### Holdout result (the honest number)

A second owner-labelled batch (85 messages; adds `ready_to_buy`, `delivery_concern`, `urgency`) was split deterministically: `customer_messages_holdout_dev.jsonl` (38, studied and tuned on) and `data/eval/sealed/` (47, **never read**, only scored).

| Metric | Set 1 (tuned) | Holdout dev (tuned) | **Sealed (unseen)** before -> after round-2 rules |
|---|---|---|---|
| Register accuracy | 84% | 87% | **72% -> 72%** |
| negotiation recall | 91% | 100% | 58% -> 75% |
| stalling recall | 88% | 80% | 43% -> 57% |
| delivery_concern recall | - | 85% | 55% -> 60% |
| ready_to_buy recall | - | 87% | **21% -> 26%** |
| trust_concern recall | 70% | 80% | **0% -> 0%** |
| urgency recall | - | 73% | 64% -> 64% |

Precision on unseen data is generally good (0.9+ for negotiation, delivery, ready_to_buy, urgency); **recall is the weakness**. Tuning on a few dozen messages mostly memorises phrasings: the dev half rose to ~85% while unseen recall barely moved for the hardest signals. **Conclusion: hand-written cue rules have plateaued; do not tune further on small batches.** The rules remain the fast, auditable first pass and the fallback. The next step is an LLM-based signal/intent extractor (reasoning model, structured output) evaluated on these same files, with rules as fallback. The sealed set is the acceptance test: do not read or tune against it.

## 8. SMM knowledge (Meta + TikTok)

`master_meta_corpus.jsonl` and `master_tiktok_corpus.jsonl` are indexed as the `smm` domain (~20k records; 41 unusable records dropped). No SMM agent exists yet; this is the knowledge layer it will sit on.

- **Facets are normalised at index time** (`corpus/facets.py`). The raw values are inconsistent free text (`Instagram`/`instagram`, `WHATSAPP`, `e_commerce`/`E-Commerce`, 692 distinct region strings). Now: `platform` (meta|tiktok), `surface` (instagram, instagram_reels, whatsapp, facebook_marketplace, threads, short_form, live_selling, ...), `objective` (awareness, consideration, engagement, lead_generation, conversion, retention, trust_building), `industries` (ecommerce, retail, fashion, beauty, food_beverage, fintech, ...), `register` (english|pidgin|mixed), `region` (44 values). About 8% of objectives and 4% of industries still fall into "other".
- **API:** `smm_guidance(store, query, platform=, objective=, industry=, surface=, region=, register=)` returns `SmmGuidance`: playbook steps (rated `automatable` vs `owner_advisory`, which tells the agent what it may do itself vs. recommend), anti-patterns, platform specs (hooks, script beats, caption blueprints, comment-to-DM flows), and Nigerian market context (price band, trust barriers, seasonal triggers). If filters match nothing they are relaxed one at a time and **reported** in `dropped_filters`. CLI: `python -m agentic_sales.cli smm "<query>" --platform tiktok --objective conversion --industry food_beverage`.
- **Not exposed:** `metrics_and_evidence`. Those figures are LLM-generated (e.g. "74.2% first-second retention across 50 Lagos accounts"); they are not indexed and must never be quoted to a business.
- **Cautions** are attached to ~29% of records: sample payment links (never reuse), health/efficacy/absolute claims (e.g. "clears acne", "100% organic"), and regulatory approvals (NAFDAC/SON). Example copy is style, not text to publish. Nigerian advertising rules (NAFDAC, ARCON, FCCPC) apply to anything the future agent posts; claim substantiation must come from the business, and publishing stays behind the human-approval policy.
- **Open items:** retrieval is lexical (BM25), as elsewhere. WhatsApp/Instagram `reply_scenarios` and `comment_to_dm_flow` could also inform the sales-chat agent, but are deliberately not wired into it until validated. Whether the playbooks actually work is untested: this corpus is synthetic, and the real test is campaign results measured by the Analytics agent (Phase 6).

## 9. Backend status (end of build day 1)

Everything below is implemented, covered by tests (about 120, run offline with scripted models), and wired through one HTTP API. "Live-verified" means exercised against the real external service.

| Subsystem | Where | Tests | Live-verified? |
|---|---|---|---|
| Turn pipeline (analyse -> lead -> fraud posture -> retrieve -> model -> tools -> guards -> audit) | `agents/orchestrator.py` | yes | Yes, with Gemini (see 9.2) |
| Signal/register extraction (LLM + rules union, rules fallback) | `language/analyzer.py`, `llm_signals.py` | yes | Yes: sealed set, register 89%, micro-F1 0.76 vs rules 0.61 |
| Leads: stages, transparent score, qualification | `leads/` | yes | Via the live conversation |
| Retention: purchase schedule, stale-lead recovery, opt-outs | `leads/retention.py` | yes | No (needs a scheduler + a real send) |
| Fraud: banded risk + confidence + reasons, never accuses | `fraud/engine.py` | yes | n/a (logic) |
| Payments: orders, links, gateway-verified confirmation | `payments/` | yes (fake gateway) | **No: no Paystack key** |
| Channels: WhatsApp, Instagram, Messenger, X, Email adapters; TikTok placeholder | `channels/` | yes (docs-based fixtures) | **No: no platform credentials** |
| Outbox dispatcher (24h window, opt-out, retry) | `channels/dispatch.py` | yes | No |
| Content/SMM agent: plan, lint, approve, edit, schedule, image | `agents/content.py` | yes | Planning: no (not run live). Image: **blocked, Google free-tier quota 0** |
| Publishers (Meta/TikTok/X posting) | interface only | n/a | **Not built** (needs credentials + app review) |
| Landing pages (escaped, CSP, honeypot form) | `webpages/landing.py` | yes | No |
| Analytics: funnel, revenue, A/B with significance gate | `analytics.py` | yes | n/a |
| Approvals resolution (discount/order/fraud) | `approvals.py` | yes | n/a |
| API + tenant auth (hashed keys, admin/staff) | `server/` | yes (TestClient) | Run in-process only; not deployed |

### 9.1 Safety properties (each has a test)
Customer text is fenced and never in the system prompt. Prices: the model proposes, `PolicyEngine` decides, and concessions move down a server-side ladder (40%, 70%, 100% of the auto-discount limit) that the model is never told about. Replies are blocked and rewritten once (then handed to a human) if they contain an unauthorised price, a payment-confirmed claim without gateway verification, or an unsupported business claim (registered, licensed, certified, "100% safe", "genuine/original", invented delivery times or pay-on-delivery policies) unless the owner listed it in `business_facts`. The payment amount is always set by the server; only references the platform issued can be verified; confirmation is idempotent. Fraud HIGH requires corroboration from two independent signal families (or a gateway amount mismatch), freezes the lead, restricts tools, and stays polite. Webhooks need a valid platform signature checked against that tenant's stored secret. Opt-outs (STOP) are honoured everywhere and survive erasure; erasure (NDPR) removes the rest.

### 9.2 What the first live run showed (and what was fixed)
A live Pidgin conversation against the real server found problems unit tests could not: the agent conceded straight to the limit of its authority, invented trust claims ("registered business", "100% protected") and an invented pay-on-delivery policy, missed the product and the stated budget, and dropped to plain-text replies because history was replayed as plain text. All were fixed and have regression tests. After the fixes: prices are stated, no invented claims, the injection attempt is refused politely, out-of-authority discounts are queued.

### 9.3 Known gaps (be honest before onboarding a real business)
- **Latency.** Two model calls per turn (analysis + reply). On the free Gemini tier, 4-15 s on a good day and 22-52 s under load. Needs a paid tier / faster model, or merging analysis into the reply call.
- **Claude not connected.** The supplied key authenticates but is not workspace-scoped; Anthropic requires `ANTHROPIC_WORKSPACE_ID`. Set it and `MODEL_PROVIDER=anthropic`.
- **Image generation** needs billing enabled on the Google project. **Video** (Veo) has no provider code yet.
- **Social publishing, TikTok DMs, Meta/X app approval, Paystack** need credentials the project does not have. The adapters follow public docs but have never touched the live APIs; expect small payload differences on first contact.
- **No scheduler.** Follow-ups, outbox flush and scheduled posts run when `/v1/followups/run`, `/v1/outbox/flush` or `publish_due` are called; production needs a cron/worker calling them.
- **No admin UI.** Approvals, leads and content are API-only.
- **Single process.** Per-tenant lock, in-memory rate limiter, SQLite. Fine for pilots; move to Postgres + a queue + Redis limiter to scale.
- **Secrets** are plaintext JSON on disk (permissions only). Encrypt before hosting other people's credentials.
- **Lead score probability is a heuristic**, flagged `calibrated=false`. Fit it once purchases exist.
- **Signal recall** is the best available, not great: sealed-set recall for trust_concern 29% and ready_to_buy 53% with the earlier prompt; the final "ready_to_buy" wording was tuned on dev data only.
- **Operational:** rotate the API keys that were pasted into chat. Never commit `.env`.

## 10. Running it

```
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt
cp .env.example .env                       # then fill in keys (see below)
python -m agentic_sales.corpus.build       # one-time, ~3 minutes, builds data/index/corpus.db
.venv/Scripts/python -m agentic_sales.cli tenant-create --id demo --config examples/demo_business.json   # prints the admin API key once
.venv/Scripts/python -m agentic_sales.cli serve                                                          # http://127.0.0.1:8000
curl -X POST localhost:8000/v1/chat -H "Authorization: Bearer ask_..." -H "Content-Type: application/json" -d '{"user_id":"ada","text":"Oga how much be the iPhone 15?"}'
```
Connect a channel: `PUT /v1/secrets/whatsapp` with `app_secret`, `verify_token`, `access_token`, `phone_number_id`, then point Meta's webhook at `/webhooks/<tenant>/whatsapp`. Paystack: `PUT /v1/secrets/paystack {"secret_key": ...}` and webhook `/webhooks/<tenant>/paystack`.
