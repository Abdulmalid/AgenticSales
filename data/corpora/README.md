# Raw corpora (not in git)

Place these files in `data/corpora/raw/` (the folder is gitignored because the set is about 600 MB):

- `master_nigerian_pidgin_corpus.jsonl`
- `master_nigerian_english_corpus.jsonl`
- `master_nigerian_conversation_corpus.jsonl`
- `master_agent_guardrails_corpus.jsonl`
- `nigeria_leadgen_corpus.jsonl`
- `master_lead_conversion_corpus.jsonl`
- `master_corpus.jsonl` (retention)
- `master_meta_corpus.jsonl`
- `master_tiktok_corpus.jsonl`

Then build the search index: `python -m agentic_sales.corpus.build`.

Ask the project owner for the shared copy (cloud drive, or a GitHub Release asset in the private repo).
All of this data is LLM-synthesised reference material; see `docs/ARCHITECTURE.md` section 1 for its known flaws.
