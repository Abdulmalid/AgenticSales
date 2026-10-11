"""Corpus family definitions.

Each raw JSONL file is a *family* with its own schema. A family declares the
canonical keys (used to repair LLM-garbled keys such as ``vulnerable_bot_anti_patient``)
and the knowledge domain its records belong to. Domains keep language, sales and
guardrail knowledge separately retrievable instead of one undifferentiated pool.
"""
from __future__ import annotations

from dataclasses import dataclass

# Knowledge domains (see docs/ARCHITECTURE.md §3). Business, customer and product
# knowledge are NOT corpus domains: they live in tenant-scoped stores.
NG_LANGUAGE = "ng_language"        # how Nigerians communicate (Pidgin, registers, pragmatics)
NG_CONVERSATION = "ng_conversation"  # Nigerian pragmatics: bargaining, indirectness, greetings, repair
NG_SALES = "ng_sales"              # Nigerian-market sales/lead-gen playbooks
SALES_GENERAL = "sales_general"    # general conversion / retention methodology
SMM = "smm"                        # social-media marketing: Meta (IG/FB/WhatsApp/Threads) + TikTok
AGENT_GUARDRAILS = "agent_guardrails"  # fraud/payment/injection dialogue precedents

DOMAINS = (NG_LANGUAGE, NG_CONVERSATION, SMM, NG_SALES, SALES_GENERAL, AGENT_GUARDRAILS)


@dataclass(frozen=True)
class Family:
    name: str
    filename: str
    domain: str
    canonical_keys: tuple[str, ...]
    aliases: dict[str, str]
    # keys excluded from the searchable body (pure metadata / noise)
    meta_keys: tuple[str, ...] = (
        "report_id", "title", "knowledge_layer", "subtopic", "subtopic_path", "tags",
        "created_at", "updated_at", "review_status", "source", "confidence", "freshness",
        "embedding_hint",
    )


_AG_ALIASES = {
    "authentic_customer_in_bound": "authentic_customer_inbound",
    "customer_inbound": "authentic_customer_inbound",
    "agent_inner_chain_of_thought": "agent_internal_chain_of_thought",
    "agent_reply": "exact_agent_reply",
    "agent_exact_reply": "exact_agent_reply",
    "commercial_guardrails_enforced": "commercial_guardrail_enforced",
    "customer_profile_tone": "customer_profile.tone",
    "customer_profile_language_blend": "customer_profile.language_blend",
}

FAMILIES: tuple[Family, ...] = (
    Family(
        "pidgin", "master_nigerian_pidgin_corpus.jsonl", NG_LANGUAGE,
        ("report_id", "title", "knowledge_layer", "subtopic", "register_tier", "dialect_region",
         "linguistic_thesis", "technical_analysis", "verbatim_corpus_utterance",
         "syntactic_or_morphological_rule", "regional_comparative_table",
         "sociolinguistic_dynamics", "computational_nlp_challenges", "tags", "created_at",
         "review_status"),
        {"syntactical_or_morphological_rule": "syntactic_or_morphological_rule",
         "syntactically_or_morphological_rule": "syntactic_or_morphological_rule",
         "syntactically_or_morphologically_rule": "syntactic_or_morphological_rule"},
    ),
    Family(
        "nigerian_english", "master_nigerian_english_corpus.jsonl", NG_LANGUAGE,
        ("report_id", "title", "knowledge_layer", "subtopic", "register_tier", "linguistic_thesis",
         "technical_analysis", "authentic_multi_turn_dialogue", "phrase_training_block",
         "comparative_dialect_analysis", "phonological_or_syntactic_notation",
         "sociolinguistic_prestige_index", "nlp_computational_notes", "tags", "created_at",
         "review_status"),
        {},
    ),
    Family(
        "nigerian_conversation", "master_nigerian_conversation_corpus.jsonl", NG_CONVERSATION,
        ("report_id", "title", "knowledge_layer", "subtopic", "situational_domain", "pragmatic_thesis",
         "technical_analysis", "authentic_conversation_sample", "phrase_training_block",
         "non_verbal_kinesics", "conversational_repair_or_deescalation",
         "sociolinguistic_power_dynamics", "computational_ai_guidelines", "tags", "created_at",
         "review_status"),
        # systematic typo present in ~99.9% of the raw records
        {"aauthentic_conversation_sample": "authentic_conversation_sample"},
    ),
    Family(
        "meta", "master_meta_corpus.jsonl", SMM,
        ("report_id", "title", "platform_corpus", "knowledge_layer", "subtopic", "coverage",
         "nigeria_context", "summary", "full_knowledge_block", "key_principles", "playbook",
         "agent_instructions", "anti_patterns", "metrics_and_evidence", "qa_pairs",
         "platform_specific", "tags", "created_at", "review_status"),
        {"playbox": "playbook", "playboard": "playbook", "playphone_or_playbook": "playbook",
         "full_knowledge_bar": "full_knowledge_block", "nigeria_content": "nigeria_context",
         "nigerian_context": "nigeria_context"},
        # metrics_and_evidence is LLM-generated statistics: kept out of the searchable body
        meta_keys=("report_id", "title", "knowledge_layer", "subtopic", "tags", "created_at",
                   "review_status", "platform_corpus", "metrics_and_evidence"),
    ),
    Family(
        "tiktok", "master_tiktok_corpus.jsonl", SMM,
        ("report_id", "title", "platform_corpus", "knowledge_layer", "subtopic", "coverage",
         "nigeria_context", "summary", "full_knowledge_block", "key_principles", "playbook",
         "agent_instructions", "anti_patterns", "metrics_and_evidence", "qa_pairs",
         "platform_specific", "tags", "created_at", "review_status"),
        {"playbox": "playbook", "playboard": "playbook", "playphone_or_playbook": "playbook",
         "full_knowledge_bar": "full_knowledge_block", "nigeria_content": "nigeria_context",
         "nigerian_context": "nigeria_context"},
        meta_keys=("report_id", "title", "knowledge_layer", "subtopic", "tags", "created_at",
                   "review_status", "platform_corpus", "metrics_and_evidence"),
    ),
    Family(
        "leadgen_ng", "nigeria_leadgen_corpus.jsonl", NG_SALES,
        ("report_id", "title", "knowledge_layer", "subtopic", "subtopic_path", "content_type",
         "funnel_stage", "lead_type_applicable", "industry_applicability",
         "company_size_applicability", "summary", "full_knowledge_block", "key_principles",
         "statistics", "actionable_insights", "agent_instructions", "anti_patterns", "source",
         "confidence", "freshness", "language", "locale_specificity", "tags", "embedding_hint",
         "qa_pairs", "created_at", "updated_at", "review_status"),
        {},
    ),
    Family(
        "retention", "master_corpus.jsonl", SALES_GENERAL,
        ("report_id", "title", "knowledge_layer", "subtopic", "subtopic_path", "content_type",
         "funnel_stage", "lead_type_applicable", "industry_applicability",
         "company_size_applicability", "summary", "full_knowledge_block", "key_principles",
         "statistics", "actionable_insights", "agent_instructions", "anti_patterns", "source",
         "confidence", "freshness", "language", "locale_specificity", "tags", "embedding_hint",
         "qa_pairs", "created_at", "updated_at", "review_status"),
        {},
    ),
    Family(
        "conversion", "master_lead_conversion_corpus.jsonl", SALES_GENERAL,
        ("report_id", "title", "knowledge_layer", "subtopic", "funnel_stage", "target_model",
         "executive_thesis", "technical_framework_and_mechanics", "mathematical_model",
         "verbatim_script_or_ui_copy", "actionable_sop", "empirical_benchmarks",
         "failure_mode_analysis", "expert_case_study_qa", "tags", "created_at", "review_status"),
        {"execution_thesis": "executive_thesis", "failure_model_analysis": "failure_mode_analysis",
         "failure__mode_analysis": "failure_mode_analysis",
         "technical_framework_and_metrics": "technical_framework_and_mechanics"},
    ),
    Family(
        "guardrails", "master_agent_guardrails_corpus.jsonl", AGENT_GUARDRAILS,
        ("report_id", "title", "knowledge_layer", "subtopic", "commercial_channel",
         "customer_profile", "authentic_customer_inbound", "agent_internal_chain_of_thought",
         "executable_tool_call", "exact_agent_reply", "commercial_guardrail_enforced",
         "vulnerable_bot_anti_pattern", "claude_prompt_engineering_tip", "tags", "created_at",
         "review_status"),
        _AG_ALIASES,
    ),
)

BY_FILENAME = {f.filename: f for f in FAMILIES}
BY_NAME = {f.name: f for f in FAMILIES}
