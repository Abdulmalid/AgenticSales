// Shapes returned by the Python API (see agentic_sales/server/app.py).

export type Stage =
  | "NEW" | "DISCOVERED" | "CONTACTED" | "ENGAGED" | "QUALIFIED" | "NEGOTIATING"
  | "READY_TO_BUY" | "CONVERTED" | "RETAINED" | "LOST" | "FRAUD_SUSPECTED";

export const STAGE_ORDER: Stage[] = [
  "NEW", "ENGAGED", "QUALIFIED", "NEGOTIATING", "READY_TO_BUY", "CONVERTED", "RETAINED", "LOST", "FRAUD_SUSPECTED",
];

export type Me = {
  tenant_id: string;
  role: "admin" | "staff";
  business_name: string;
  products: { sku: string; name: string; price_kobo: number }[];
  pending_approvals: number;
  channels_configured: string[];
  models: { text: string | null; image: boolean };
};

export type Lead = {
  id: number;
  customer_key: string;
  source: string;
  stage: Stage;
  name: string | null;
  interest: string | null;
  budget_kobo: number | null;
  intent: "low" | "medium" | "high";
  objection: string | null;
  trust_level: string;
  fraud_risk: "LOW" | "MEDIUM" | "HIGH";
  score: number;
  band: "cold" | "warm" | "hot";
  conversion_probability: number;
  last_interaction: string | null;
  created: string | null;
  attrs: Record<string, unknown>;
};

export type LeadEvent = { id: number; ts: string; kind: string; data: Record<string, unknown>; trace: string | null };

export type LeadDetail = {
  lead: Lead;
  score_reasons: string[];
  score_calibrated: boolean;
  events: LeadEvent[];
  facts: Record<string, string>;
};

export type Funnel = {
  total_leads: number;
  by_stage: Record<string, number>;
  converted: number;
  conversion_rate: number;
  revenue_kobo: number;
  orders: number;
  avg_days_to_convert: number | null;
  hot_leads: number;
  fraud_suspected: number;
  by_source: Record<string, { leads: number; converted: number }>;
};

export type Approval = {
  id: number;
  trace: string;
  customer_key: string;
  action: string;
  payload: string; // JSON
  reasons: string; // JSON array
  status: string;
  created: string;
};

export type ContentItem = {
  id: number;
  campaign_id: string;
  platform: "meta" | "tiktok";
  surface: string | null;
  objective: string | null;
  caption: string;
  hashtags: string[];
  cta: string | null;
  image_prompt: string | null;
  video_script: { duration_seconds?: number; beats?: { t: string; visual: string; voiceover: string; on_screen_text: string }[] } | null;
  alt_text: string | null;
  media_path: string | null;
  status: "draft" | "pending_approval" | "approved" | "scheduled" | "published" | "rejected";
  violations: string[];
  created: string;
  decided_by: string | null;
  scheduled_for: string | null;
  published_ref: string | null;
  error: string | null;
};

export type CampaignPlan = {
  campaign_id: string;
  item_ids: number[];
  strategy: string;
  violations: Record<string, string[]>;
  guidance_used: string[];
  guidance_cautions: string[];
  relaxed_filters: string[];
};

export type CampaignReport = {
  campaign_id: string;
  impressions: number;
  clicks: number;
  ctr: number | null;
  leads: number;
  conversions: number;
  revenue_kobo: number;
  comparison: { arms: { variant: string; n: number; successes: number; rate: number }[]; verdict: string; reason: string };
};

export type AuditEvent = { ts: string; kind: string; trace: string } & Record<string, unknown>;

export type ChatReply = {
  reply: string;
  escalated: boolean;
  trace: string;
  lead_stage: Stage | null;
  lead_score: number | null;
  fraud_risk: "LOW" | "MEDIUM" | "HIGH";
  analysis: string;
};

export type OutboxItem = { id: number; customer_key: string; text: string; purpose: string; status: string; error: string | null; created: string };

export type BusinessConfig = {
  business_name: string;
  industry: string;
  products: { sku: string; name: string; price_kobo: number; floor_price_kobo: number; description: string; in_stock: boolean }[];
  brand_voice: string;
  target_audience: string;
  delivery_areas: string[];
  payment_methods: string[];
  refund_policy: string;
  business_facts: string[];
  working_hours: string;
  preferred_channels: string[];
  approvals: {
    max_discount_pct_auto: number;
    max_discount_pct_hard: number;
    refunds_need_approval: boolean;
    high_fraud_risk_needs_approval: boolean;
    large_transaction_kobo: number;
    public_posts_need_approval: boolean;
  };
  retention_schedule: Record<string, string>;
};
