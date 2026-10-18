// API service for communicating with FastAPI backend
import { API_CONFIG } from '../../config/api';
import { clearLeadGenSessionOnAuthEnd } from '../clearLeadGenSession';

/**
 * Chat / lead-search endpoints use `/chat` or `/leads`. Inbox URLs also contain `/leads`
 * (e.g. …/inbox/threads/{id}/leads/{id}/reply) — exclude any `/inbox` path so timeouts never
 * show lead-search copy (also covers `/inbox` without a trailing slash).
 */
function isLeadSearchTimeoutCopyEndpoint(endpoint: string): boolean {
  const p = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  if (p.includes('/inbox')) return false;
  return p.includes('/chat') || p.includes('/leads');
}

export interface ApiResponse<T = any> {
  data?: T;
  error?: string;
  message?: string;
  /** Set when the API returns HTTP 402 with credit exhaustion (e.g. chat / lead gen). */
  insufficientCredits?: boolean;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface SignupRequest {
  username: string;
  email: string;
  password: string;
}

export interface TokenResponse {
  access_token?: string;
  token_type?: string;
  /** Admin accounts: password OK — finish with email OTP before tokens are issued */
  requires_2fa?: boolean;
  email?: string;
  message?: string;
}

export interface UserResponse {
  id: string;
  email: string;
  username: string;
  is_active: boolean;
  email_verified?: boolean;
  is_superuser?: boolean;
  is_admin?: boolean;
  role?: string | null;
  created_at?: string;
  first_login_at?: string;
  last_login_at?: string;
  full_name?: string;
  department?: string;
  location?: string;
  website?: string;
  bio?: string;
  profile_image?: string;
  /** From GET /auth/me — SYSTEM = managed pool, USER = own mailboxes */
  email_sending_mode?: 'SYSTEM' | 'USER' | null;
}

export interface OTPRequest {
  email: string;
}

export interface OTPVerificationRequest {
  code: string;
}

export interface OTPResponse {
  message: string;
  expires_at?: string;
  can_resend_in?: number;
}

export interface OTPVerificationResponse {
  success: boolean;
  message: string;
  user_id?: string;
  access_token?: string;
  token_type?: string;
}

// Chat and Lead Management Interfaces
export interface ChatRequest {
  message: string;
  conversation_id?: string;
}

export interface ChatRecoveryAction {
  id: string;
  label: string;
  message: string;
}

export interface ChatResponse {
  status: string;
  message: string;
  context?: {
    industry?: string;
    location?: string;
    country?: string;
    anchor?: string;
    radius_km?: number;
  };
  log_id?: string;
  lead_count?: number;
  leads?: LeadBase[]; // For guest users - leads returned directly
  timestamp?: string;
  recovery_kind?: string;
  actions?: ChatRecoveryAction[];
  exhausted?: {
    industry?: string;
    city?: string;
    log_id?: string | null;
    nearby?: Array<{ city?: string; available?: number; deliverable?: number }>;
  };
}

export interface ContactFormPayload {
  full_name: string;
  email: string;
  company_name?: string | null;
  subject: string;
  message: string;
}

export interface ContactFormResponseBody {
  message: string;
}

export interface LeadBase {
  business_name: string;
  industry?: string;
  email?: string;
  contact_number?: string;
  address?: string;
  website?: string;
  lead_score?: number;
  services?: string | null;
  website_summary?: string | null;
  business_description?: string | null;
}

export interface LeadLogLeadResponse extends LeadBase {
  id: string;
  created_at: string;
  updated_at: string;
  enrichment_status?: 'processing' | 'done' | 'failed';
  last_contacted?: string;
  outreach_status?: 'not_started' | 'contacted' | 'replied' | 'no_response';
}

export interface EnrichmentStatusResponse {
  log_id: string;
  summary: {
    processing: number;
    done: number;
    failed: number;
    total: number;
  };
  leads: Array<{
    id: string;
    email: string | null;
    enrichment_status: 'processing' | 'done' | 'failed';
    lead_score: number | null;
  }>;
}

export interface LeadLogResponse {
  id: string;
  chat_title: string;
  query: string;
  promoted: boolean;
  created_at: string;
  leads: LeadLogLeadResponse[];
}

export interface LeadLogListResponse {
  id: string;
  chat_title: string;
  query: string;
  promoted: boolean;
  created_at: string;
  lead_count: number;
}

export interface LeadResponse extends LeadBase {
  id: string;
  starred?: boolean;
  created_at: string;
  updated_at: string;
  last_contacted?: string;
  campaign_status?: string;
  outreach_status?: string;
  /** Manually added or Excel import — not from lead generation. */
  is_user_added?: boolean;
}

export interface ChatCompleteRequest {
  action: 'save' | 'cancel';
  log_id: string;
  selected_lead_ids?: string[];
}

export interface PromoteLeadsRequest {
  selected_lead_ids?: string[];
}

export interface LeadCreateRequest {
  business_name: string;
  industry?: string;
  email?: string;
  contact_number?: string;
  address?: string;
  website?: string;
  lead_score?: number;
}

export interface LeadUpdateRequest {
  business_name?: string;
  industry?: string;
  email?: string;
  contact_number?: string;
  address?: string;
  website?: string;
  lead_score?: number;
}

export interface GetLeadsParams {
  search?: string;
  min_score?: number;
  max_score?: number;
}

/** Summary from POST /leads/upload (Excel import). */
export interface LeadExcelUploadResult {
  imported: number;
  skipped_duplicates: number;
  skipped_duplicates_existing?: number;
  skipped_duplicates_in_file?: number;
  failed_rows: number;
  blank_rows?: number;
  truncated_rows: number;
  total_processed: number;
  rows_in_file?: number;
}

/** Summary from POST /leads/leadlogs/:id/promote */
export interface PromoteLeadsResult {
  count: number;
  skipped: number;
  reused?: number;
  total_leads?: number;
  promoted_leads?: number;
  all_promoted?: boolean;
  /** Lead Database UUIDs — use these for Create Campaign step 2 */
  lead_ids?: string[];
  message?: string;
}

// Campaign interfaces
export interface CampaignGoal {
  id: string;
  name: string;
  description?: string;
  created_at?: string;
}

export interface CampaignCategory {
  id: string;
  name: string;
  description?: string;
  created_at?: string;
}

export interface CampaignCreateRequest {
  name: string;
  description?: string;
  goal_id?: string;
  category_id?: string;
  tags?: string[];
}

export interface CampaignUpdateRequest {
  name?: string;
  description?: string;
  goal_id?: string;
  category_id?: string;
  tags?: string[];
  email_sending_mode?: 'SYSTEM' | 'USER';
}

export interface CampaignResponse {
  id: string;
  name: string;
  description?: string;
  goal_id?: string;
  category_id?: string;
  tags?: string[];
  status: string;
  lead_count: number;
  avg_lead_score: number;
  email_subject?: string;
  email_content?: string;
  email_sending_mode?: 'SYSTEM' | 'USER';
  sender_email?: string;
  created_at: string;
  updated_at: string;
  launched_at?: string | null;
}

export interface CampaignCreateResponse {
  id: string;
  name: string;
  description?: string;
  goal_id?: string;
  category_id?: string;
  tags?: string[];
  status: string;
  created_at: string;
  updated_at: string;
}

export interface PaginatedCampaignResponse {
  current_page: number;
  per_page: number;
  total_items: number;
  total_pages: number;
  data: CampaignResponse[];
}

export interface PaginatedList<T> {
  current_page: number;
  per_page: number;
  total_items: number;
  total_pages: number;
  data: T[];
}

const CAMPAIGN_LIST_PAGE_SIZE = 200;

export interface CampaignLeadSyncRequest {
  lead_ids: string[];
}

export interface CampaignLeadInfo {
  id: string;
  business_name: string;
  email?: string | null;
  industry?: string | null;
  address?: string | null;
  contact_number?: string | null;
  website?: string | null;
  lead_score?: number | null;
  services?: string | null;
  website_summary?: string | null;
  business_description?: string | null;
}

export interface CampaignLeadResponse {
  id: string;
  campaign_id: string;
  lead_id?: string | null;
  created_at: string;
  context_score?: 'full' | 'partial' | 'none' | null;
  effective_depth?: 'basic' | 'standard' | 'deep' | null;
  email_status?: string | null;
  email_sent_at?: string | null;
  lead?: CampaignLeadInfo | null;
  is_user_added?: boolean;
}

export interface ToneOption {
  id: string;
  label: string;
}

export interface ToneTierTone {
  id: string;
  label: string;
  description: string;
}

export interface ToneTierResponse {
  tier_plan: string;
  tier_label: string;
  min_plan: string;
  min_plan_rank: number;
  unlocked: boolean;
  badge: string;
  tones: ToneTierTone[];
}

export interface PlanCapabilitiesResponse {
  plan: string;
  max_depth: string;
  label: string;
  description: string;
  external_research: boolean;
  available_fields: string[];
  tone_options: ToneOption[];
  tone_tiers?: ToneTierResponse[];
  default_tone?: string;
}

export interface PersonalizationSummary {
  total: number;
  full: number;
  partial: number;
  none: number;
}

export interface CampaignPersonalizationResponse {
  campaign_id: string;
  tone: string;
  plan_capabilities: PlanCapabilitiesResponse;
  summary: PersonalizationSummary;
  leads: Array<{
    campaign_lead_id: string;
    lead_id?: string | null;
    business_name?: string | null;
    context_score: string;
    effective_depth: string;
    thin_context: boolean;
  }>;
}

export interface CampaignDraftRequest {
  draft_type: 'TEMPLATE' | 'AI' | 'MANUAL';
  template_id?: string;
  email_subject?: string;
  email_content?: string;
  ai_email_prompt?: string;
}

export interface AIDraftRequest {
  tone: string;
  description?: string;
}

export interface CampaignDraftResponse {
  campaign_id: string;
  draft_type: string;
  template_id?: string;
  email_subject?: string;
  email_content?: string;
  tone?: string;
  description?: string;
  ai_email_prompt?: string;
}

export interface SpamCheckRequest {
  subject: string;
  body: string;
  fast_mode?: boolean;
}

export interface SpamCheckResponse {
  spam_score: number;
  risk_level: string;
  reasons: string[];
  suggestions: string[];
  rewritten_subject?: string;
  rewritten_body?: string;
  rewritten_spam_score?: number;
  rewritten_risk_level?: string;
}

export interface CampaignLeadEmailRow {
  id: string;
  campaign_id: string;
  campaign_lead_id?: string | null;
  lead_id?: string | null;
  lead_index: number;
  business_name?: string | null;
  email?: string | null;
  location?: string | null;
  lead_score?: number | null;
  context_score?: string | null;
  subject?: string | null;
  body?: string | null;
  generation_status: string;
  compliance_status: string;
  spam_score?: number | null;
  risk_level?: string | null;
  review_status: string;
  regeneration_count: number;
  variant_metadata?: Record<string, unknown> | null;
  last_error?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CampaignEmailGenerationStatus {
  campaign_id: string;
  total: number;
  complete: number;
  queued?: number;
  generating?: number;
  pending: number;
  ready: number;
  failed: number;
  compliance_passed: number;
  compliance_failed: number;
  is_complete: boolean;
  instant_generated?: number;
  queued_background?: boolean;
  remaining?: number;
  already_running?: boolean;
  message?: string;
}

export interface CampaignEmailReviewSummary {
  campaign_id: string;
  has_per_lead_emails: boolean;
  total: number;
  pending_review: number;
  approved: number;
  rejected: number;
  generation_in_progress: number;
  generation_failed: number;
  ready_for_review: number;
  can_launch: boolean;
  launch_blockers: string[];
  updated?: number;
}

export interface LaunchReadinessCheck {
  key: string;
  label: string;
  passed: boolean;
  message: string;
}

export interface CampaignLaunchReadiness {
  campaign_id: string;
  campaign_status: string;
  can_launch: boolean;
  launch_blockers: string[];
  checks: LaunchReadinessCheck[];
  approved_to_send: number;
  skipped_rejected: number;
  email_sending_mode?: string | null;
}

export interface CampaignLaunchResult {
  campaign_id: string;
  status: string;
  queued: number;
  approved: number;
  skipped_rejected: number;
  message: string;
}

export interface CampaignSendStatus {
  campaign_id: string;
  campaign_status: string;
  total_jobs: number;
  queued: number;
  sending: number;
  sent: number;
  failed: number;
  in_progress: number;
  is_complete: boolean;
  progress_percent: number;
}

export interface CampaignLaunchView {
  campaign: CampaignResponse;
  readiness?: CampaignLaunchReadiness | null;
  status?: CampaignSendStatus | null;
}

export interface EmailTemplate {
  id: string;
  user_id: string;
  name: string;
  subject: string;
  content: string;
  created_at: string;
  updated_at: string;
  category?: 'professional' | 'value-proposition' | 'network-outreach';
  usage_count?: number; // Number of times this template has been used in campaigns
  is_favorite?: boolean; // Whether the template is marked as favorite
}

export interface EmailTemplateCreateRequest {
  name: string;
  subject: string;
  content: string;
  category?: string;
}

export interface EmailTemplateUpdateRequest {
  name?: string;
  subject?: string;
  content?: string;
  category?: string;
  is_favorite?: boolean;
}

// Campaign Insight interfaces
export interface DailyStat {
  date: string;
  day: string;
  sent: number;
  opened: number;
  clicked: number;
  bounced: number;
  replied: number;
}

export interface CampaignTrackingMetrics {
  total_leads: number;
  outreached_today: number;
  total_outreached: number;
  failed: number;
  remaining: number;
  /** null when no estimate exists (campaign not ongoing, or no mailbox capacity) */
  estimated_completion_days: number | null;
  /** ISO date (YYYY-MM-DD) the last remaining lead is expected to be contacted; null when no estimate exists */
  estimated_completion_date: string | null;
  daily_outreach_rate: number;
}

export interface CampaignInsightResponse {
  campaign_id: string;
  campaign_name: string;
  status: string;
  total_sent: number;
  total_opened: number;
  total_clicked: number;
  total_bounced: number;
  total_delivered: number;
  total_replied: number;
  total_failed?: number;
  open_rate: number;
  click_rate: number;
  bounce_rate: number;
  delivery_rate: number;
  reply_rate: number;
  daily_stats: DailyStat[];
  tracking?: CampaignTrackingMetrics;
}

// Company interfaces
export interface CompanyCreateRequest {
  role: string;
  company_name: string;
  company_size: string;
  company_website?: string;
  target_industry: string;
  target_location: string;
  target_specific_business?: string;
  experience_with_lead_gen_tools: string;
  lead_generation_expect_monthly: string;
}

export interface CompanyUpdateRequest {
  role?: string;
  company_name?: string;
  company_size?: string;
  company_website?: string;
  target_industry?: string;
  target_specific_business?: string;
  target_location?: string;
  experience_with_lead_gen_tools?: string;
  lead_generation_expect_monthly?: string;
  industry?: string;
  company_description?: string;
  products_and_services?: Array<Record<string, any>>;
  business_offers?: string[];
  unique_selling_point?: string[];
  customer_goals?: string[];
  problems_solved?: string[];
  benefits?: string[];
  achievements?: string[];
  business_email?: string;
  country?: string;
  state?: string;
  city?: string;
  postal_code?: string;
}

export interface CompanyResponse {
  id: string;
  user_id: string;
  role?: string;
  company_name?: string;
  company_size?: string;
  company_website?: string;
  target_industry?: string;
  target_specific_business?: string;
  target_location?: string;
  experience_with_lead_gen_tools?: string;
  lead_generation_expect_monthly?: string;
  industry?: string;
  company_description?: string;
  products_and_services?: Array<Record<string, any>>;
  business_offers?: string[];
  unique_selling_point?: string[];
  customer_goals?: string[];
  problems_solved?: string[];
  benefits?: string[];
  achievements?: string[];
  business_email?: string;
  country?: string;
  state?: string;
  city?: string;
  postal_code?: string;
  created_at: string;
  updated_at: string;
}

// Domain interfaces
export interface DomainCreateRequest {
  domain_name: string;
  daily_limit?: number;
  is_active?: boolean;
}

export interface DomainUpdateRequest {
  domain_name?: string;
  daily_limit?: number;
  is_active?: boolean;
}

export interface DomainResponse {
  id: string;
  domain_name: string;
  daily_limit: number;
  is_active: boolean;
  sent_today: number;
}

// Mailbox interfaces
export interface MailboxCreateRequest {
  email: string;
  username: string;
  password: string;
  smtp_host: string;
  smtp_port?: number;
  receive_email: string;
  imap_username: string;
  imap_password: string;
  imap_host: string;
  imap_port?: number;
  provider?: string;
  domain_id?: string;
}

export interface MailboxUpdateRequest {
  smtp_host?: string;
  smtp_port?: number;
  imap_host?: string;
  imap_port?: number;
  password?: string;
  is_active?: boolean;
}

export interface MailboxResponse {
  id: string;
  email: string;
  provider: string;
  domain_id: string | null;
  smtp_host: string;
  port: number;
  imap_host: string;
  imap_port: number;
  daily_limit: number;
  sent_today: number;
  is_active: boolean;
  last_used: string;
}

// Inbox interfaces
export interface InboxItem {
  lead_id: string;
  lead_email: string;
  lead_name?: string;
  lead_address?: string;
  lead_contact?: string;
  lead_industry?: string;
  lead_score?: number;
  sent_email?: string;
  last_reply?: string;
  last_reply_time?: string;
  last_sent_time?: string;
  last_message_id?: string;
  activity_id: string;
  campaign_id: string;
  campaign_name: string;
  starred?: boolean;
}

export interface InboxResponse {
  total: number;
  items: InboxItem[];
  page?: number;
  per_page?: number;
}

/** One row in GET /inbox/threads — one thread per campaign. */
export interface InboxThreadListItem {
  id: string;
  campaign_id: string;
  campaign_name: string;
  subject?: string | null;
  last_message_at?: string | null;
  /** ISO datetime — thread creation ≈ when campaign sending started */
  sent_at?: string | null;
  total_recipients: number;
  replied_count: number;
  /** Recipient email opens (EmailActivity.opened) — same source as campaign Open Rate */
  opened_count: number;
  unread_reply_count: number;
  /** Distinct leads the Evecta user has replied to in this thread */
  user_reply_count?: number;
  /**
   * Distinct leads the Evecta user opened (all inbound read) but has not replied to.
   * Lets a campaign stay in Opened even when other leads are Unread or Sent.
   */
  opened_unreplied_count?: number;
  is_starred: boolean;
}

export interface InboxLeadConversationSummary {
  lead_id: string;
  lead_email?: string | null;
  lead_name?: string | null;
  lead_industry?: string | null;
  lead_score?: number | null;
  latest_reply?: string | null;
  replied_at?: string | null;
  is_read: boolean;
  message_count: number;
  /** True when the Evecta user sent a reply in this lead conversation */
  has_user_replied?: boolean;
}

export interface InboxThreadDetail {
  id: string;
  campaign_id: string;
  campaign_name: string;
  subject?: string | null;
  campaign_description?: string | null;
  campaign_status?: string | null;
  campaign_created_at?: string | null;
  thread_started_at?: string | null;
  total_recipients: number;
  unread_reply_count: number;
  is_starred: boolean;
  /** USER-mode only — own Gmail/IMAP From address; omit for system mail */
  email_sending_mode?: 'SYSTEM' | 'USER' | string | null;
  sender_email?: string | null;
  replies: InboxLeadConversationSummary[];
}

export interface InboxThreadMessage {
  id: string;
  direction: string;
  sender_email?: string | null;
  recipient_email?: string | null;
  body?: string | null;
  message_id?: string | null;
  sent_at: string;
  is_read: boolean;
}

export interface LeadConversationResponse {
  lead_id: string;
  lead_email?: string | null;
  lead_name?: string | null;
  messages: InboxThreadMessage[];
}

export interface ThreadReplyResponse {
  id: string;
  message_id?: string | null;
  sent_at: string;
  sender_email?: string | null;
  recipient_email?: string | null;
}

// Billing (Stripe) — credits are split into independent pools (lead / email_gen / outreach)
export type CreditPoolId = 'lead' | 'email_gen' | 'outreach';

export interface CreditPoolBalance {
  balance: number;
  display_denominator: number;
  label: string;
}

// Admin AI usage reporting
export interface AiUsageSummary {
  input_tokens: number;
  output_tokens: number;
  reasoning_tokens: number;
  cached_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number;
  request_count: number;
  failed_count: number;
  from_date?: string | null;
  to_date?: string | null;
  provider?: string | null;
}

export interface AiUsageByFeatureItem extends AiUsageSummary {
  feature: string;
}

export interface AiUsageByModelItem extends AiUsageSummary {
  provider: string;
  model: string;
}

export interface AiUsageByDayItem extends AiUsageSummary {
  day: string;
}

export interface AiUsageByMonthItem extends AiUsageSummary {
  month: string;
  year: number;
  month_number: number;
}

export interface AiUsageByUserItem extends AiUsageSummary {
  user_id?: string | null;
  email?: string | null;
  username?: string | null;
}

export interface AiUsageByUserMonthItem extends AiUsageSummary {
  month: string;
  user_id?: string | null;
  email?: string | null;
  username?: string | null;
}

export interface AiUsageCreditsByUserItem {
  user_id: string;
  email?: string | null;
  username?: string | null;
  credits_spent_lead: number;
  credits_spent_email_gen: number;
  credits_spent_outreach: number;
  credits_spent_total: number;
  credits_remaining_lead: number;
  credits_remaining_email_gen: number;
  credits_remaining_outreach: number;
}

export interface AdminTopupRequest {
  user_id: string;
  lead?: number;
  email_gen?: number;
  outreach?: number;
  reason?: string;
}

export interface AdminTopupPoolGrant {
  pool: string;
  amount: number;
  balance_after: number;
}

export interface AdminTopupResponse {
  user_id: string;
  email?: string | null;
  grants: AdminTopupPoolGrant[];
  balances: Record<string, number>;
}

export interface AdminUserBalanceResponse {
  user_id: string;
  email?: string | null;
  username?: string | null;
  balances: Record<string, number>;
  topup_balances: Record<string, number>;
  subscription_balances: Record<string, number>;
}

export interface AdminTopupHistoryItem {
  id: string;
  user_id: string;
  email?: string | null;
  username?: string | null;
  pool: string;
  amount: number;
  action: string;
  description?: string | null;
  created_at: string;
}

export interface GeminiStatusEventItem {
  id: string;
  http_status?: number | null;
  error_kind: string;
  message?: string | null;
  feature?: string | null;
  model?: string | null;
  user_id?: string | null;
  created_at: string;
}

export interface GeminiStatusTrack {
  status: 'ok' | 'credit_exhausted' | 'rate_limited' | 'unavailable';
  title: string;
  message: string;
  http_status?: number | null;
  error_kind?: string | null;
  last_success_at?: string | null;
  last_error_at?: string | null;
  events: GeminiStatusEventItem[];
}

/** @deprecated Use GeminiStatusTrack */
export type GeminiCreditTrack = GeminiStatusTrack;
export type GeminiPurchaseSummary = GeminiStatusTrack;

export type ExternalApiProvider = 'hunter' | 'google_places';

export interface ExternalApiUsageSummary {
  provider: string;
  total_units: number;
  estimated_cost_usd: number;
  request_count: number;
  failed_count: number;
  success_count: number;
}

export interface ExternalApiUsageByApiItem {
  api_name: string;
  total_units: number;
  estimated_cost_usd: number;
  request_count: number;
  failed_count: number;
}

export interface ExternalApiUsageByDayItem {
  day: string;
  total_units: number;
  estimated_cost_usd: number;
  request_count: number;
  failed_count: number;
}

export interface ExternalApiUsageEventItem {
  id: string;
  provider: string;
  api_name: string;
  feature: string;
  units: number;
  unit_cost_usd?: number | null;
  estimated_cost_usd: number;
  latency_ms?: number | null;
  http_status?: number | null;
  status: string;
  meta?: string | null;
  created_at: string;
}

export interface ExternalApiUsageTrack {
  provider: string;
  summary: ExternalApiUsageSummary;
  by_api: ExternalApiUsageByApiItem[];
  by_day: ExternalApiUsageByDayItem[];
  recent_events: ExternalApiUsageEventItem[];
}

export interface BillingCreditBalanceResponse {
  pools: Partial<Record<CreditPoolId, CreditPoolBalance>>;
  plan: string;
  costs: Record<string, number>;
  action_pools?: Partial<Record<string, CreditPoolId>>;
  /** @deprecated Legacy single balance — prefer pools.lead.balance */
  balance?: number;
  /** @deprecated Legacy single denominator — prefer pools.*.display_denominator */
  display_denominator?: number;
}

export interface BillingCreditTransaction {
  id: string;
  amount: number;
  action: string;
  pool?: CreditPoolId | string | null;
  description: string | null;
  created_at: string;
}

export interface BillingCreditHistoryResponse {
  transactions: BillingCreditTransaction[];
}

export interface BillingSubscriptionResponse {
  plan: string;
  plan_billing_interval?: 'month' | 'year' | null;
  /** Per-pool allowance for the billing period */
  credits_per_period?: number | Partial<Record<CreditPoolId, number>>;
  stripe_customer_id: string | null;
  stripe_subscription_id: string | null;
  /** Per-pool monthly plan credits from PLANS */
  credits?: number | Partial<Record<CreditPoolId, number>>;
  leads_per_search: number | undefined;
  /** When set, subscription is already scheduled to cancel at period end */
  cancel_at?: string | null;
}

export interface BillingCheckoutSessionResponse {
  checkout_url: string;
}

export interface BillingConfirmCheckoutResponse {
  status: string;
  plan?: string;
  already_active?: boolean;
  credits_added?: number | Partial<Record<CreditPoolId, number>>;
}

export interface BillingTopupPoolOption {
  pool: CreditPoolId;
  label: string;
  price_per_credit: number;
  max: number;
}

export interface BillingTopupOptionsResponse {
  available?: boolean;
  reason?: string;
  min: number;
  step: number;
  /** Per-pool caps + pricing (preferred) */
  pools?: BillingTopupPoolOption[];
  /** @deprecated Legacy flat max / rate when pools is absent */
  max?: number;
  price_per_credit?: number;
  examples?: { credits: number; price_usd: number }[];
}

export type BillingTopupCheckoutRequest = Partial<Record<CreditPoolId, number>>;

export interface BillingTopupCheckoutResponse {
  checkout_url: string;
  credits?: number;
  price_usd?: number;
  price_usd_by_pool?: Partial<Record<CreditPoolId, number>>;
}

// Email Reply interfaces
export interface EmailReplyCreateRequest {
  activity_id: string;
  reply_text: string;
}

export interface EmailReplyResponse {
  status: string;
  reply_id: string;
  lead_id: string;
  campaign_id: string;
  reply_text: string;
  sent_at: string;
}

// Email Insight Interfaces
export interface SystemEmailInsightsResponse {
  total_sent: number;
  remaining: number;
  delivery_rate: number;
  bounce_rate: number;
  active_accounts: number;
  avg_daily_sending: number;
  monthly_usage_percent: number;
}

export interface UserEmailOverviewResponse {
  total_accounts: number;
  sent_today: number;
  delivery_rate: number;
  healthy_accounts: number;
  active_accounts: number;
}

export interface UserEmailAccount {
  email: string;
  provider: string;
  status: string;
  health: string;
  delivery_rate: number;
  total_sent: number;
}

// System Mailbox Interfaces
export interface SystemMailboxCreateRequest {
  domain_id: string;
  email: string;
  smtp_host: string;
  smtp_user: string;
  smtp_password: string;
  smtp_port?: number;
  receive_email: string;
  receive_username: string;
  receive_password: string;
  imap_host: string;
  imap_port?: number;
  daily_limit?: number;
  provider?: string;
  can_receive?: boolean;
  is_active?: boolean;
}

export interface SystemMailboxUpdateRequest {
  domain_id?: string;
  email?: string;
  smtp_host?: string;
  smtp_user?: string;
  smtp_password?: string;
  smtp_port?: number;
  receive_email?: string;
  receive_username?: string;
  receive_password?: string;
  imap_host?: string;
  imap_port?: number;
  daily_limit?: number;
  is_active?: boolean;
  can_receive?: boolean;
  provider?: string;
}

export interface SystemMailboxResponse {
  id: string;
  mailbox_type: string;
  domain_id: string;
  email: string;
  provider: string;
  smtp_host: string;
  smtp_user: string;
  port: number;
  imap_host: string;
  imap_port: number;
  receive_email: string;
  receive_username: string;
  receive_password?: string;
  can_receive: boolean;
  daily_limit: number;
  sent_today: number;
  is_active: boolean;
  last_used: string;
}

// System Domain Interfaces
export interface SystemDomainCreateRequest {
  name: string;
  daily_limit?: number;
}

export interface SystemDomainUpdateRequest {
  name?: string;
  daily_limit?: number;
  is_active?: boolean;
}

export interface SystemDomainResponse {
  id: string;
  domain_name: string;
  daily_limit: number;
  sent_today: number;
  is_active: boolean;
  last_used: string;
  created_at?: string;
  updated_at?: string;
}

// Google Auth interfaces
export interface GoogleAuthResponse {
  redirect_url: string;
}

// Role & Permission interfaces
export interface Permission {
  id: string;
  name: string;
  description?: string;
  group?: string;
  created_at?: string;
}

export interface Role {
  id: string;
  name: string;
  description?: string;
  permissions?: Permission[];
  created_at?: string;
  updated_at?: string;
}

export interface RoleCreateRequest {
  name: string;
  description?: string;
  permission_ids?: string[];
}

export interface RoleUpdateRequest {
  name?: string;
  description?: string;
}

export interface PermissionCreateRequest {
  name: string;
  description?: string;
  group?: string;
}

export interface PermissionUpdateRequest {
  name?: string;
  description?: string;
  group?: string;
}

export interface AssignPermissionsRequest {
  permission_ids: string[];
}

export interface GroupedPermissions {
  [group: string]: Permission[];
}

// User Management (Admin) interfaces
export interface UserList {
  id: string;
  email: string;
  username: string;
  full_name?: string;
  is_active: boolean;
  is_superuser?: boolean;
  email_verified?: boolean;
  role?: {
    id: string;
    name: string;
  };
  role_obj?: {
    id: string;
    name: string;
  };
  plan?: string | null;
  plan_billing_interval?: string | null;
  first_login_at?: string | null;
  last_login_at?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface UserListPage {
  items: UserList[];
  total: number;
  limit: number;
  offset: number;
}

export type AdminPlanId = 'free' | 'starter' | 'growth' | 'scale';

export interface AdminUserPlanUpdateRequest {
  plan: AdminPlanId;
  plan_billing_interval?: 'month' | 'year';
}

export interface AdminUserPlanUpdateResponse {
  id: string;
  email: string;
  username?: string;
  plan: string;
  plan_billing_interval?: string | null;
  previous_plan?: string;
  credits_granted?: Record<string, number>;
  changed: boolean;
  message: string;
}

export interface AdminUserCreateRequest {
  full_name: string;
  email: string;
  username: string;
  password: string;
  role_id: string;
  is_active: boolean;
  override_permission_ids?: string[];
}

export interface AdminUserUpdateRequest {
  full_name?: string;
  email?: string;
  username?: string;
  password?: string;
  role_id?: string;
  is_active?: boolean;
  override_permission_ids?: string[];
}

export interface UserPermissionsOverrides {
  permission_ids: string[];
}

export interface UserEffectivePermissions {
  user_id: string;
  permissions: Permission[];
}

export interface UserDetailsResponse {
  user: {
    id: string;
    full_name?: string;
    email: string;
    username: string;
    is_active: boolean;
    email_verified?: boolean;
    created_at: string;
    updated_at: string;
    department?: string;
    location?: string;
    website?: string;
    bio?: string;
    profile_image?: string;
  };
  role: {
    id: string;
    name: string;
    permissions: Permission[];
  };
  overrides: {
    permission_ids: string[];
  };
  effective_permissions: {
    permissions: Permission[];
  };
}

class ApiService {
  private isHandlingTokenExpiration: boolean = false;
  private isRefreshingToken: boolean = false;
  // Frontend-owned chat conversation id. resetChat() (New Chat) rotates it, so every
  // message after that lands on a fresh backend thread — no server-side rotate race.
  private chatConversationId: string = '';

  constructor() {
    this.chatConversationId = this.loadConversationId();
    try {
      localStorage.removeItem('access_token');
    } catch {
      /* ignore */
    }
  }

  private freshConversationId(): string {
    const id =
      typeof crypto !== 'undefined' && crypto.randomUUID
        ? crypto.randomUUID()
        : Math.random().toString(36).slice(2) + Date.now().toString(36);
    try { sessionStorage.setItem('chatConversationId', id); } catch { /* ignore */ }
    return id;
  }

  private loadConversationId(): string {
    try {
      const existing = sessionStorage.getItem('chatConversationId');
      if (existing) return existing;
    } catch { /* ignore */ }
    return this.freshConversationId();
  }
  
  // Always get fresh baseURL from API_CONFIG to avoid stale values
  private getBaseURL(): string {
    let baseURL = API_CONFIG.BASE_URL;
    const isHttps = typeof window !== 'undefined' && window.location.protocol === 'https:';
    
    // Force HTTPS if page is HTTPS
    if (isHttps && baseURL.startsWith('http://')) {
      console.warn('⚠️ API baseURL uses HTTP but page is HTTPS. Converting to HTTPS.');
      baseURL = baseURL.replace('http://', 'https://');
    }
    
    return baseURL;
  }

  // Handle token expiration - clear token and redirect to login
  private handleTokenExpiration(): void {
    // Prevent multiple simultaneous logout attempts
    if (this.isHandlingTokenExpiration) {
      return;
    }
    this.isHandlingTokenExpiration = true;

    // Session cookies are HttpOnly; JS must not keep a bearer token.
    this.clearLegacyAccessToken();

    clearLeadGenSessionOnAuthEnd();

    // Set logout flag in localStorage to notify other tabs
    localStorage.setItem('user_logged_out', Date.now().toString());
    
    // Dispatch storage event for same-origin tabs
    window.dispatchEvent(new StorageEvent('storage', {
      key: 'user_logged_out',
      newValue: Date.now().toString()
    }));

    // Only redirect if we're not already on the auth page
    const currentPath = window.location.pathname;
    if (!currentPath.startsWith('/auth') && !currentPath.startsWith('/login')) {
      // Redirect to login page
      window.location.href = '/auth';
    }

    // Reset flag after a delay to allow retry if needed
    setTimeout(() => {
      this.isHandlingTokenExpiration = false;
    }, 1000);
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<ApiResponse<T>> {
    // Always get fresh baseURL to avoid stale values
    let baseURL = this.getBaseURL();
    const isHttps = typeof window !== 'undefined' && window.location.protocol === 'https:';
    
    // Ensure endpoint starts with /
    const normalizedEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
    
    const url = `${baseURL}${normalizedEndpoint}`;
    
    // CRITICAL: Fix HTTP URLs on HTTPS pages
    let finalUrl = url;
    if (isHttps && url.startsWith('http://')) {
      console.error('❌ CRITICAL: Request URL uses HTTP but page is HTTPS:', url);
      console.error('BaseURL:', baseURL, 'Endpoint:', normalizedEndpoint);
      console.error('API_CONFIG.BASE_URL:', API_CONFIG.BASE_URL);
      console.error('Window location:', window.location.href);
      
      // Force HTTPS
      finalUrl = url.replace('http://', 'https://');
      console.warn('🔧 Auto-correcting to HTTPS:', finalUrl);
      
      // Also ensure /api is present if missing
      if (!finalUrl.includes('/api') && finalUrl.includes('evecta.io')) {
        finalUrl = finalUrl.replace('evecta.io/', 'evecta.io/api/');
        console.warn('🔧 Adding /api to URL:', finalUrl);
      }
    }
    
    const config: RequestInit = {
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
      credentials: 'include',
      ...options,
    };

    try {
      const response = await fetch(finalUrl, config);
      
      // Clone response to be able to read it multiple times if needed
      const clonedResponse = response.clone();
      
      // Try to parse JSON first (FastAPI usually returns JSON, but DELETE might return 204 No Content)
      let data: any = {};
      let responseText: string = '';
      // For 204 No Content, there's no body to parse
      if (response.status === 204) {
        data = {};
      } else {
        try {
          responseText = await response.text();
          if (responseText) {
            // Check if response is HTML (Cloudflare error page)
            if (responseText.trim().startsWith('<!DOCTYPE html>') || 
                responseText.includes('Gateway time-out') ||
                responseText.includes('504: Gateway time-out')) {
              // Store as detail for later processing
              data = { detail: responseText, isHtml: true };
            } else {
              data = JSON.parse(responseText);
            }
          }
        } catch (jsonError) {
          console.log("❌ JSON Parse Error:", jsonError);
          // If JSON parsing fails, check if it's HTML
          if (responseText && (responseText.trim().startsWith('<!DOCTYPE html>') || 
                               responseText.includes('Gateway time-out'))) {
            data = { detail: responseText, isHtml: true };
          } else {
          // If JSON parsing fails, try to get text from cloned response
          try {
            const text = await clonedResponse.text();
            data = { detail: text || response.statusText || 'An error occurred' };
          } catch (textError) {
            console.log("❌ Text Parse Error:", textError);
            data = { detail: response.statusText || 'An error occurred' };
            }
          }
        }
      }

      if (!response.ok) {
        // Handle 504 Gateway Timeout - Show user-friendly message for lead search/generation
        if (response.status === 504 || data.isHtml) {
          // Check if response is HTML (Cloudflare error page)
          const contentType = response.headers.get('content-type') || '';
          const isHtmlResponse = contentType.includes('text/html') || 
                                data.isHtml ||
                                (typeof data.detail === 'string' && data.detail.includes('<!DOCTYPE html>')) ||
                                (typeof data.detail === 'string' && data.detail.includes('Gateway time-out')) ||
                                (typeof data.detail === 'string' && data.detail.includes('504'));
          
          // Lead-search copy only for real chat/lead gen — not inbox …/threads/…/leads/…/reply (path contains /leads/)
          if (isHtmlResponse && isLeadSearchTimeoutCopyEndpoint(endpoint)) {
            return {
              error: "The time is out for searching the leads. Please try again.",
              message: "The time is out for searching the leads. Please try again.",
              data: undefined,
            };
          }
          
          // Generic timeout message for other endpoints
          if (isHtmlResponse) {
            return {
              error: "Request timed out. Please try again.",
              message: "Request timed out. Please try again.",
              data: undefined,
            };
          }
        }
        
        // Handle 401 Unauthorized - Token expired or invalid
        if (response.status === 401) {
          // Check if this is an auth endpoint (login, signup, refresh) - don't logout on those
          const isAuthEndpoint = endpoint.includes('/auth/login') || 
                                 endpoint.includes('/auth/register') || 
                                 endpoint.includes('/auth/refresh') ||
                                 endpoint.includes('/auth/google') ||
                                 endpoint.includes('/auth/me') ||
                                 endpoint.includes('/auth/logout');
          
          // Check if this is a waitlist status check - don't trigger logout on this
          const isWaitlistCheck = endpoint.includes('/waitlist-status');
          
          if (!isAuthEndpoint && !isWaitlistCheck && !this.isRefreshingToken) {
            // Try to refresh the token first before logging out
            console.log("🔒 Access token expired. Attempting to refresh...");
            
            try {
              this.isRefreshingToken = true;
              const refreshResponse = await this.refreshToken();
              
              if (refreshResponse.data) {
                // Token refresh successful - retry the original request
                console.log("✅ Token refreshed successfully. Retrying original request...");
                this.isRefreshingToken = false;
                
                // Retry the original request with the new token
                return this.request<T>(endpoint, options);
              } else {
                // Refresh failed - log out user
                console.log("❌ Token refresh failed. Logging out user...");
                this.isRefreshingToken = false;
                this.handleTokenExpiration();
                
                return {
                  error: "Your session has expired. Please log in again.",
                  message: "Your session has expired. Please log in again.",
                  data: undefined,
                };
              }
            } catch (refreshError) {
              // Refresh failed - log out user
              console.log("❌ Token refresh error:", refreshError);
              this.isRefreshingToken = false;
              this.handleTokenExpiration();
              
              return {
                error: "Your session has expired. Please log in again.",
                message: "Your session has expired. Please log in again.",
                data: undefined,
              };
            }
          }
        }

        console.log("❌ API Error Response:", {
          status: response.status,
          statusText: response.statusText,
          data: data,
          rawData: JSON.stringify(data)
        });
        
        // Extract error message from various possible formats
        let errorMessage: string | null = null;
        
        // Handle case where detail is an object (e.g., {code: "WAITLISTED", message: "..."})
        if (data?.detail) {
          if (typeof data.detail === 'object' && data.detail !== null && 'message' in data.detail) {
            errorMessage = data.detail.message;
          } else if (typeof data.detail === 'string') {
            errorMessage = data.detail;
          }
        }
        
        // Fallback to other error fields if detail didn't provide a string
        if (!errorMessage) {
          errorMessage = 
            data?.message || 
            data?.error || 
            (typeof data === 'string' ? data : null) ||
            `Error ${response.status}: ${response.statusText}`;
        }
        
        // Ensure we have a string error message
        if (!errorMessage || typeof errorMessage !== 'string') {
          // If errorMessage is still an object or null, try to extract from data directly
          if (typeof errorMessage === 'object' && errorMessage !== null) {
            errorMessage = (errorMessage as any)?.message || (errorMessage as any)?.detail || JSON.stringify(errorMessage);
          } else if (!errorMessage) {
            // Fallback to a generic error message
            errorMessage = `Error ${response.status}: ${response.statusText}`;
          } else {
            errorMessage = String(errorMessage);
          }
        }
        
        // Final safety check - ensure it's a string
        if (typeof errorMessage !== 'string') {
          errorMessage = String(errorMessage);
        }
        
        console.log("🔍 Extracted error message:", errorMessage);
        console.log("🔍 Error message type:", typeof errorMessage);
        console.log("🔍 Returning error response:", { error: errorMessage, message: errorMessage });

        const detailObj =
          data?.detail && typeof data.detail === 'object' && data.detail !== null
            ? (data.detail as Record<string, unknown>)
            : null;
        const insufficientCredits =
          response.status === 402 && detailObj?.error === 'insufficient_credits';

        // Explicitly return error response with no data property
        return {
          error: errorMessage,
          message: errorMessage,
          data: undefined, // Explicitly set to undefined to avoid confusion
          ...(insufficientCredits ? { insufficientCredits: true } : {}),
        };
      }

      // For successful DELETE requests (204 No Content), return success response
      if (response.status === 204) {
        return {
          data: undefined,
          message: 'Successfully deleted',
        };
      }

      // Handle BaseResponse format (FastAPI endpoints that return BaseResponse)
      // BaseResponse has structure: { status, message, data } — require `message` so we do not
      // mis-detect other objects that happen to have `status` + `data` (e.g. proxies).
      if (
        data &&
        typeof data === 'object' &&
        'data' in data &&
        'status' in data &&
        'message' in data
      ) {
        return { data: data.data, message: data.message };
      }

      // For direct model responses (like arrays or single objects), return as is
      return { data };
    } catch (error) {
      console.log("💥 Network Error:", error);
      
      // Check if this is a timeout-related error
      const isTimeoutError = error instanceof Error && (
        error.message.includes('timeout') ||
        error.message.includes('Timeout') ||
        error.message.includes('time-out') ||
        error.message.includes('TIMEOUT') ||
        error.name === 'TimeoutError' ||
        error.name === 'AbortError'
      );
      
      // Same rule as 504 HTML branch: lead-search copy only for /chat or /leads outside /inbox/
      if (isTimeoutError && isLeadSearchTimeoutCopyEndpoint(endpoint)) {
        return {
          error: "The time is out for searching the leads. Please try again.",
          message: "The time is out for searching the leads. Please try again.",
          data: undefined,
        };
      }
      
      if (isTimeoutError) {
        return {
          error: "Request timed out. Please try again.",
          message: "Request timed out. Please try again.",
          data: undefined,
        };
      }
      
      return {
        error: error instanceof Error ? error.message : 'Network error',
        message: error instanceof Error ? error.message : 'Network error',
      };
    }
  }

  // Authentication methods
  async login(credentials: LoginRequest): Promise<ApiResponse<TokenResponse>> {
    const response = await this.request<TokenResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify(credentials),
    });

    // Admin 2FA challenge — no tokens yet
    if (response.data?.requires_2fa) {
      return response;
    }

    return response;
  }

  async verifyAdminLogin2FA(email: string, otpCode: string): Promise<ApiResponse<TokenResponse>> {
    const response = await this.request<TokenResponse>('/auth/login/verify-2fa', {
      method: 'POST',
      body: JSON.stringify({ email, otp_code: otpCode }),
    });

    return response;
  }

  async resendAdminLogin2FA(email: string): Promise<ApiResponse<{ status?: string; message?: string }>> {
    return this.request<{ status?: string; message?: string }>('/auth/login/resend-2fa', {
      method: 'POST',
      body: JSON.stringify({ email }),
    });
  }

  async signup(userData: SignupRequest): Promise<ApiResponse<UserResponse>> {
    const response = await this.request<UserResponse>('/auth/register', {
      method: 'POST',
      body: JSON.stringify(userData),
    });

    // If backend returned an error, throw so callers can handle in catch
    if (response.error || !response.data) {
      let message = response.error || response.message || 'Signup failed';
      // Handle case where error might be an object
      if (typeof message === 'object' && message !== null) {
        message = (message as any)?.message || (message as any)?.detail || String(message);
      }
      // Ensure message is a string
      if (typeof message !== 'string') {
        message = String(message);
      }
      // Throwing ensures upstream catch receives a single normalized message
      throw new Error(message);
    }

    return response;
  }

  async refreshToken(): Promise<ApiResponse<TokenResponse>> {
    // Make a direct fetch call to avoid infinite recursion (don't use this.request)
    const url = `${this.getBaseURL()}/auth/refresh`;
    
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include', // Important for cookies (refresh token)
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        return {
          error: data.detail || data.message || 'Failed to refresh token',
          message: data.detail || data.message || 'Failed to refresh token',
          data: undefined,
        };
      }

      const data: TokenResponse = await response.json();
      return { data };
    } catch (error) {
      console.error('Refresh token error:', error);
      return {
        error: error instanceof Error ? error.message : 'Network error during token refresh',
        message: error instanceof Error ? error.message : 'Network error during token refresh',
        data: undefined,
      };
    }
  }

  async logout(): Promise<ApiResponse> {
    const response = await this.request('/auth/logout', {
      method: 'POST',
    });

    // Always clear local session. If the server returned an error (e.g. missing refresh
    // cookie), we still must drop the access token or the next page load will call
    // /auth/me, repopulate the user, and PublicRoute will send the user back to /dashboard.
    this.setAccessToken(null);

    return response;
  }

  async getCurrentUser(): Promise<ApiResponse<UserResponse>> {
    return this.request<UserResponse>('/auth/me');
  }

  async checkWaitlistStatus(): Promise<ApiResponse<{ is_on_waitlist: boolean; total_users: number; user_limit_reached: boolean }>> {
    return this.request<{ is_on_waitlist: boolean; total_users: number; user_limit_reached: boolean }>('/auth/waitlist-status');
  }

  async updateUserProfile(data: { 
    username?: string; 
    email?: string;
    full_name?: string;
    department?: string;
    location?: string;
    website?: string;
    bio?: string;
    profile_image?: string;
  }): Promise<ApiResponse<UserResponse>> {
    // Remove email from data - users cannot change their email
    const { email, ...dataWithoutEmail } = data;
    return this.request<UserResponse>('/auth/me', {
      method: 'PATCH',
      body: JSON.stringify(dataWithoutEmail),
    });
  }

  async changePassword(data: {
    current_password: string;
    new_password: string;
  }): Promise<ApiResponse<UserResponse>> {
    return this.request<UserResponse>('/auth/me/password', {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  async forgotPassword(email: string): Promise<ApiResponse<{ message: string }>> {
    return this.request<{ message: string }>('/auth/forgot-password', {
      method: 'POST',
      body: JSON.stringify({ email }),
    });
  }

  async verifyResetOTP(email: string, otp_code: string): Promise<ApiResponse<{ message: string }>> {
    return this.request<{ message: string }>('/auth/verify-reset-otp', {
      method: 'POST',
      body: JSON.stringify({ email, otp_code }),
    });
  }

  async resetPassword(payload: {
    email: string;
    otp_code: string;
    new_password: string;
  }): Promise<ApiResponse<{ message: string }>> {
    return this.request<{ message: string }>('/auth/reset-password', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  // OTP methods
  async sendOTP(email: string): Promise<ApiResponse<OTPResponse>> {
    return this.request<OTPResponse>('/otp/send', {
      method: 'POST',
      body: JSON.stringify({ email }),
    });
  }

  async verifyOTP(
    userId: string,
    email: string,
    code: string
  ): Promise<ApiResponse<OTPVerificationResponse>> {
    return this.request<OTPVerificationResponse>(`/otp/verify/${userId}`, {
      method: 'POST',
      body: JSON.stringify({ code, email }),
    });
  }

  async checkOTPStatus(userId: string, email: string): Promise<ApiResponse<OTPResponse>> {
    const params = new URLSearchParams({ email });
    return this.request<OTPResponse>(`/otp/status/${userId}?${params.toString()}`);
  }

  // Utility methods — cookies are HttpOnly; these only drop any leftover localStorage token.
  private clearLegacyAccessToken(): void {
    try {
      localStorage.removeItem('access_token');
    } catch {
      /* ignore */
    }
  }

  setAccessToken(_token: string | null) {
    this.clearLegacyAccessToken();
  }

  getAccessToken(): string | null {
    return null;
  }

  isAuthenticated(): boolean {
    return false;
  }

  // Chat methods
  /** Non-streaming fallback — prefer sendChatMessageStream for the live UI. */
  async sendChatMessage(message: string): Promise<ApiResponse<ChatResponse>> {
    return this.request<ChatResponse>('/chat', {
      method: 'POST',
      body: JSON.stringify({ message, conversation_id: this.chatConversationId }),
    });
  }

  /**
   * Streaming chat via POST /chat/stream (SSE over fetch — EventSource can't send POST bodies).
   * Calls onToken for each {"type":"token"} event so the UI can grow the reply incrementally.
   * Resolves with the same ApiResponse<ChatResponse> shape as /chat once {"type":"done"} arrives
   * (or an error response for {"type":"error"} / HTTP failures).
   * A turn may emit zero token events before done (e.g. out-of-credits) — that is normal.
   */
  async sendChatMessageStream(
    message: string,
    onToken?: (content: string) => void,
  ): Promise<ApiResponse<ChatResponse>> {
    const endpoint = '/chat/stream';
    const body = JSON.stringify({ message, conversation_id: this.chatConversationId });

    const run = async (): Promise<ApiResponse<ChatResponse>> => {
      let baseURL = this.getBaseURL();
      const isHttps = typeof window !== 'undefined' && window.location.protocol === 'https:';
      const normalizedEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
      let finalUrl = `${baseURL}${normalizedEndpoint}`;
      if (isHttps && finalUrl.startsWith('http://')) {
        finalUrl = finalUrl.replace('http://', 'https://');
        if (!finalUrl.includes('/api') && finalUrl.includes('evecta.io')) {
          finalUrl = finalUrl.replace('evecta.io/', 'evecta.io/api/');
        }
      }

      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      };

      let response: Response;
      try {
        response = await fetch(finalUrl, {
          method: 'POST',
          headers,
          credentials: 'include',
          body,
        });
      } catch (error) {
        const isTimeoutError =
          error instanceof Error &&
          (error.message.includes('timeout') ||
            error.message.includes('Timeout') ||
            error.name === 'TimeoutError' ||
            error.name === 'AbortError');
        if (isTimeoutError) {
          return {
            error: 'The time is out for searching the leads. Please try again.',
            message: 'The time is out for searching the leads. Please try again.',
            data: undefined,
          };
        }
        return {
          error: error instanceof Error ? error.message : 'Network error',
          message: error instanceof Error ? error.message : 'Network error',
        };
      }

      if (!response.ok) {
        // 401 → refresh + retry once (same pattern as request())
        if (response.status === 401 && !this.isRefreshingToken) {
          try {
            this.isRefreshingToken = true;
            const refreshResponse = await this.refreshToken();
            this.isRefreshingToken = false;
            if (refreshResponse.data) {
              return run();
            }
            this.handleTokenExpiration();
            return {
              error: 'Your session has expired. Please log in again.',
              message: 'Your session has expired. Please log in again.',
              data: undefined,
            };
          } catch {
            this.isRefreshingToken = false;
            this.handleTokenExpiration();
            return {
              error: 'Your session has expired. Please log in again.',
              message: 'Your session has expired. Please log in again.',
              data: undefined,
            };
          }
        }

        let errorMessage = `Error ${response.status}: ${response.statusText}`;
        let insufficientCredits = false;
        try {
          const responseText = await response.text();
          if (
            response.status === 504 ||
            responseText.trim().startsWith('<!DOCTYPE html>') ||
            responseText.includes('Gateway time-out')
          ) {
            return {
              error: 'The time is out for searching the leads. Please try again.',
              message: 'The time is out for searching the leads. Please try again.',
              data: undefined,
            };
          }
          if (responseText) {
            try {
              const data = JSON.parse(responseText);
              if (data?.detail) {
                if (typeof data.detail === 'object' && data.detail !== null && 'message' in data.detail) {
                  errorMessage = String(data.detail.message);
                } else if (typeof data.detail === 'string') {
                  errorMessage = data.detail;
                }
              } else if (typeof data?.message === 'string') {
                errorMessage = data.message;
              }
              const detailObj =
                data?.detail && typeof data.detail === 'object' && data.detail !== null
                  ? (data.detail as Record<string, unknown>)
                  : null;
              insufficientCredits =
                response.status === 402 && detailObj?.error === 'insufficient_credits';
            } catch {
              /* keep statusText fallback */
            }
          }
        } catch {
          /* keep statusText fallback */
        }
        return {
          error: errorMessage,
          message: errorMessage,
          data: undefined,
          ...(insufficientCredits ? { insufficientCredits: true } : {}),
        };
      }

      if (!response.body) {
        return {
          error: 'Chat stream is unavailable. Please try again.',
          message: 'Chat stream is unavailable. Please try again.',
          data: undefined,
        };
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      const handleSsePayload = (raw: string): ApiResponse<ChatResponse> | 'continue' => {
        const trimmed = raw.trim();
        if (!trimmed) return 'continue';
        // Each SSE event is one or more "data: ..." lines
        const dataLines = trimmed
          .split('\n')
          .map((line) => line.trimEnd())
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).trimStart());
        if (dataLines.length === 0) return 'continue';
        let event: { type?: string; content?: string; data?: ChatResponse; message?: string };
        try {
          event = JSON.parse(dataLines.join('\n'));
        } catch {
          console.warn('[chat/stream] Skipping unparseable SSE chunk:', trimmed.slice(0, 200));
          return 'continue';
        }
        if (event.type === 'token') {
          if (typeof event.content === 'string' && event.content.length > 0) {
            onToken?.(event.content);
          }
          return 'continue';
        }
        if (event.type === 'done') {
          return { data: (event.data ?? {}) as ChatResponse };
        }
        if (event.type === 'error') {
          const msg =
            (typeof event.message === 'string' && event.message) ||
            'Chat processing failed. Please try again.';
          return { error: msg, message: msg, data: undefined };
        }
        return 'continue';
      };

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const parts = buffer.split('\n\n');
          buffer = parts.pop() ?? '';
          for (const part of parts) {
            const result = handleSsePayload(part);
            if (result !== 'continue') {
              try {
                await reader.cancel();
              } catch {
                /* ignore */
              }
              return result;
            }
          }
        }
        // Flush trailing buffer (in case the final event lacked a trailing blank line)
        if (buffer.trim()) {
          const result = handleSsePayload(buffer);
          if (result !== 'continue') return result;
        }
        return {
          error: 'Chat stream ended unexpectedly. Please try again.',
          message: 'Chat stream ended unexpectedly. Please try again.',
          data: undefined,
        };
      } catch (error) {
        const isTimeoutError =
          error instanceof Error &&
          (error.message.includes('timeout') ||
            error.message.includes('Timeout') ||
            error.name === 'TimeoutError' ||
            error.name === 'AbortError');
        if (isTimeoutError) {
          return {
            error: 'The time is out for searching the leads. Please try again.',
            message: 'The time is out for searching the leads. Please try again.',
            data: undefined,
          };
        }
        return {
          error: error instanceof Error ? error.message : 'Network error',
          message: error instanceof Error ? error.message : 'Network error',
        };
      }
    };

    return run();
  }

  /** Public contact page — delivers to mail@evecta.io on the server (no auth). */
  async submitContactForm(
    payload: ContactFormPayload,
  ): Promise<ApiResponse<ContactFormResponseBody>> {
    return this.request<ContactFormResponseBody>('/contact', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async resetChat(): Promise<ApiResponse<{ status: string; message: string }>> {
    // New Chat: tell the server which thread to hard-delete, then rotate CLIENT-SIDE
    // so the next message lands on a fresh backend thread (no rotate race).
    // Long-term memory (recent searches) is kept server-side — only this transcript dies.
    const previousConversationId = this.chatConversationId;
    this.chatConversationId = this.freshConversationId();
    return this.request<{ status: string; message: string }>('/chat/reset', {
      method: 'POST',
      body: JSON.stringify({
        conversation_id: previousConversationId || undefined,
      }),
    });
  }

  // Lead Management methods
  async completeChatSession(payload: ChatCompleteRequest): Promise<ApiResponse> {
    return this.request('/leads/chat/complete', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async getLeadLogs(): Promise<ApiResponse<LeadLogListResponse[]>> {
    return this.request<LeadLogListResponse[]>('/leads/leadlogs');
  }

  async getLeadLogById(logId: string): Promise<ApiResponse<LeadLogResponse>> {
    return this.request<LeadLogResponse>(`/leads/leadlogs/${logId}`);
  }

  async getEnrichmentStatus(logId: string): Promise<ApiResponse<EnrichmentStatusResponse>> {
    return this.request<EnrichmentStatusResponse>(`/leads/leadlogs/${logId}/enrichment-status`);
  }

  async promoteLeadsFromLog(
    logId: string,
    selectedLeadIds?: string[]
  ): Promise<ApiResponse<PromoteLeadsResult>> {
    const body: { selected_lead_ids?: string[] } = {};
    if (selectedLeadIds && selectedLeadIds.length > 0) {
      body.selected_lead_ids = selectedLeadIds;
    }
    return this.request<PromoteLeadsResult>(`/leads/leadlogs/${logId}/promote`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
  }

  async getLeads(params?: GetLeadsParams): Promise<ApiResponse<LeadResponse[]>> {
    // Backend paginates (default limit 50). Lead list UIs expect the full set, so fetch every page.
    const pageSize = 200; // API allows up to 200 per page
    const maxPages = 500;
    const all: LeadResponse[] = [];
    const seenIds = new Set<string>();
    let page = 1;

    for (; page <= maxPages; page++) {
      const queryParams = new URLSearchParams();
      if (params?.search) queryParams.append('search', params.search);
      if (params?.min_score !== undefined) queryParams.append('min_score', params.min_score.toString());
      if (params?.max_score !== undefined) queryParams.append('max_score', params.max_score.toString());
      queryParams.append('page', page.toString());
      queryParams.append('limit', pageSize.toString());

      const endpoint = `/leads?${queryParams.toString()}`;
      const res = await this.request<LeadResponse[]>(endpoint);

      if (res.error || res.data === undefined) {
        return res;
      }

      const batch = Array.isArray(res.data) ? res.data : [];
      for (const lead of batch) {
        const id = lead?.id;
        if (!id || seenIds.has(id)) continue;
        seenIds.add(id);
        all.push(lead);
      }
      if (batch.length < pageSize) break;
    }

    return { data: all };
  }

  async getLeadById(leadId: string): Promise<ApiResponse<LeadResponse>> {
    return this.request<LeadResponse>(`/leads/${leadId}`);
  }

  async getLeadsByIds(leadIds: string[]): Promise<ApiResponse<LeadResponse[]>> {
    return this.request<LeadResponse[]>('/leads/bulk-get', {
      method: 'POST',
      body: JSON.stringify({ lead_ids: leadIds }),
    });
  }

  async createLead(payload: LeadCreateRequest): Promise<ApiResponse<LeadResponse>> {
    return this.request<LeadResponse>('/leads', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async updateLead(leadId: string, payload: LeadUpdateRequest): Promise<ApiResponse<LeadResponse>> {
    return this.request<LeadResponse>(`/leads/${leadId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  async deleteLead(leadId: string): Promise<ApiResponse> {
    return this.request(`/leads/${leadId}`, {
      method: 'DELETE',
    });
  }

  /**
   * Delete many leads in one request. The backend caps each call at 1000 ids,
   * so callers with more must chunk (see LeadDatabase.confirmRemoveLeads).
   */
  async deleteLeads(leadIds: string[]): Promise<ApiResponse> {
    return this.request(`/leads/bulk-delete`, {
      method: 'POST',
      body: JSON.stringify({ lead_ids: leadIds }),
    });
  }

  async toggleLeadStar(leadId: string): Promise<ApiResponse<{ id: string; starred: boolean }>> {
    return this.request<{ id: string; starred: boolean }>(`/leads/${leadId}/star`, {
      method: 'PUT',
    });
  }

  /**
   * Import leads from an Excel file (.xlsx / .xls). Uses multipart/form-data (not JSON).
   * Backend expects a header row; at least one column mapping to company/business name is required.
   */
  async uploadLeadsFromExcel(file: File): Promise<ApiResponse<LeadExcelUploadResult>> {
    const buildUrl = (): string => {
      let baseURL = this.getBaseURL();
      const isHttps = typeof window !== 'undefined' && window.location.protocol === 'https:';
      let finalUrl = `${baseURL}/leads/upload`;
      if (isHttps && finalUrl.startsWith('http://')) {
        finalUrl = finalUrl.replace('http://', 'https://');
      }
      if (!finalUrl.includes('/api') && finalUrl.includes('evecta.io') && !finalUrl.includes('staging')) {
        finalUrl = finalUrl.replace('evecta.io/', 'evecta.io/api/');
      }
      return finalUrl;
    };

    const doFetch = async (): Promise<Response> => {
      const finalUrl = buildUrl();
      const headers: HeadersInit = {};
      const formData = new FormData();
      formData.append('file', file);
      return fetch(finalUrl, {
        method: 'POST',
        body: formData,
        credentials: 'include',
        headers,
      });
    };

    const parseError = (data: any, response: Response): string => {
      let errorMessage: string | null = null;
      if (data?.detail) {
        if (typeof data.detail === 'object' && data.detail !== null && 'message' in data.detail) {
          errorMessage = (data.detail as { message?: string }).message ?? null;
        } else if (typeof data.detail === 'string') {
          errorMessage = data.detail;
        }
      }
      if (!errorMessage) {
        errorMessage =
          data?.message ||
          data?.error ||
          `Error ${response.status}: ${response.statusText}`;
      }
      return typeof errorMessage === 'string' ? errorMessage : String(errorMessage);
    };

    try {
      let response = await doFetch();

      if (response.status === 401 && !this.isRefreshingToken) {
        try {
          this.isRefreshingToken = true;
          const refreshResponse = await this.refreshToken();
          this.isRefreshingToken = false;
          if (refreshResponse.data) {
            response = await doFetch();
          } else {
            this.handleTokenExpiration();
            return {
              error: 'Your session has expired. Please log in again.',
              message: 'Your session has expired. Please log in again.',
            };
          }
        } catch {
          this.isRefreshingToken = false;
          this.handleTokenExpiration();
          return {
            error: 'Your session has expired. Please log in again.',
            message: 'Your session has expired. Please log in again.',
          };
        }
      }

      const responseText = await response.text();
      let data: Record<string, unknown> = {};
      if (responseText) {
        try {
          data = JSON.parse(responseText) as Record<string, unknown>;
        } catch {
          data = { detail: responseText };
        }
      }

      if (!response.ok) {
        return {
          error: parseError(data, response),
          message: parseError(data, response),
        };
      }

      if (
        data &&
        typeof data === 'object' &&
        'data' in data &&
        'status' in data &&
        'message' in data
      ) {
        return {
          data: data.data as LeadExcelUploadResult,
          message: typeof data.message === 'string' ? data.message : undefined,
        };
      }

      return { data: data as unknown as LeadExcelUploadResult };
    } catch (error) {
      return {
        error: error instanceof Error ? error.message : 'Network error',
        message: error instanceof Error ? error.message : 'Network error',
      };
    }
  }

  // Campaign methods
  async createCampaign(payload: CampaignCreateRequest): Promise<ApiResponse<CampaignCreateResponse>> {
    return this.request<CampaignCreateResponse>('/campaigns', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async getCampaigns(params?: {
    search?: string;
    min_avg_score?: number;
    max_avg_score?: number;
    page?: number;
    per_page?: number;
  }): Promise<ApiResponse<PaginatedCampaignResponse>> {
    const queryParams = new URLSearchParams();
    if (params?.search) queryParams.append('search', params.search);
    if (params?.min_avg_score !== undefined) queryParams.append('min_avg_score', params.min_avg_score.toString());
    if (params?.max_avg_score !== undefined) queryParams.append('max_avg_score', params.max_avg_score.toString());
    if (params?.page !== undefined) queryParams.append('page', params.page.toString());
    if (params?.per_page !== undefined) {
      queryParams.append('per_page', String(Math.min(Math.max(params.per_page, 1), CAMPAIGN_LIST_PAGE_SIZE)));
    }
    
    const queryString = queryParams.toString();
    const endpoint = queryString ? `/campaigns?${queryString}` : '/campaigns';
    
    return this.request<PaginatedCampaignResponse>(endpoint);
  }

  async getCampaignById(campaignId: string): Promise<ApiResponse<CampaignResponse>> {
    return this.request<CampaignResponse>(`/campaigns/${campaignId}`);
  }

  async updateCampaign(campaignId: string, payload: CampaignUpdateRequest): Promise<ApiResponse<CampaignResponse>> {
    return this.request<CampaignResponse>(`/campaigns/${campaignId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  async deleteCampaign(campaignId: string): Promise<ApiResponse> {
    return this.request(`/campaigns/${campaignId}`, {
      method: 'DELETE',
    });
  }

  async syncCampaignLeads(campaignId: string, leadIds: string[]): Promise<ApiResponse> {
    return this.request(`/campaigns/${campaignId}/leads`, {
      method: 'POST',
      body: JSON.stringify({ lead_ids: leadIds }),
    });
  }

  private async fetchAllPaginated<T>(path: string): Promise<ApiResponse<T[]>> {
    const joiner = path.includes('?') ? '&' : '?';
    const first = await this.request<PaginatedList<T>>(
      `${path}${joiner}page=1&per_page=${CAMPAIGN_LIST_PAGE_SIZE}`,
    );
    if (first.error || !first.data) {
      return { error: first.error, data: [] };
    }
    const items = [...(first.data.data ?? [])];
    const totalPages = first.data.total_pages || 1;
    for (let page = 2; page <= totalPages; page++) {
      const next = await this.request<PaginatedList<T>>(
        `${path}${joiner}page=${page}&per_page=${CAMPAIGN_LIST_PAGE_SIZE}`,
      );
      if (next.data?.data) items.push(...next.data.data);
    }
    return { data: items };
  }

  async getCampaignLeads(campaignId: string): Promise<ApiResponse<CampaignLeadResponse[]>> {
    return this.fetchAllPaginated<CampaignLeadResponse>(`/campaigns/${campaignId}/leads`);
  }

  async getCampaignPersonalization(
    campaignId: string,
    tone?: string
  ): Promise<ApiResponse<CampaignPersonalizationResponse>> {
    const query = tone ? `?tone=${encodeURIComponent(tone)}` : '';
    return this.request<CampaignPersonalizationResponse>(
      `/campaigns/${campaignId}/personalization${query}`
    );
  }

  async saveCampaignDraft(campaignId: string): Promise<ApiResponse> {
    return this.request(`/campaigns/${campaignId}/save-draft`, {
      method: 'POST',
    });
  }

  async sendTestEmail(campaignId: string): Promise<ApiResponse> {
    return this.request(`/campaigns/${campaignId}/send-test-email`, {
      method: 'POST',
    });
  }

  async launchCampaign(campaignId: string): Promise<ApiResponse<CampaignLaunchResult>> {
    return this.request<CampaignLaunchResult>(`/campaigns/${campaignId}/launch`, {
      method: 'POST',
    });
  }

  async getCampaignLaunchReadiness(campaignId: string): Promise<ApiResponse<CampaignLaunchReadiness>> {
    return this.request<CampaignLaunchReadiness>(`/campaigns/${campaignId}/launch/readiness`);
  }

  async getCampaignSendStatus(campaignId: string): Promise<ApiResponse<CampaignSendStatus>> {
    return this.request<CampaignSendStatus>(`/campaigns/${campaignId}/launch/status`);
  }

  async getCampaignLaunchView(campaignId: string): Promise<ApiResponse<CampaignLaunchView>> {
    return this.request<CampaignLaunchView>(`/campaigns/${campaignId}/launch`);
  }

  async setCampaignEmailSendingMode(emailSendingMode: 'SYSTEM' | 'USER'): Promise<ApiResponse<{ message: string; updated_count: number; email_sending_mode: string }>> {
    return this.request<{ message: string; updated_count: number; email_sending_mode: string }>('/campaigns/email-sending-mode', {
      method: 'PUT',
      body: JSON.stringify({ email_sending_mode: emailSendingMode }),
    });
  }

  // Campaign Goals
  async getCampaignGoals(): Promise<ApiResponse<CampaignGoal[]>> {
    return this.fetchAllPaginated<CampaignGoal>('/campaign-goals');
  }

  async createCampaignGoal(payload: { name: string }): Promise<ApiResponse<CampaignGoal>> {
    return this.request<CampaignGoal>('/campaign-goals', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async updateCampaignGoal(goalId: string, payload: { name: string }): Promise<ApiResponse<CampaignGoal>> {
    return this.request<CampaignGoal>(`/campaign-goals/${goalId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  async deleteCampaignGoal(goalId: string): Promise<ApiResponse> {
    return this.request(`/campaign-goals/${goalId}`, {
      method: 'DELETE',
    });
  }

  // Campaign Categories
  async getCampaignCategories(): Promise<ApiResponse<CampaignCategory[]>> {
    return this.fetchAllPaginated<CampaignCategory>('/campaign-categories');
  }

  async createCampaignCategory(payload: { name: string }): Promise<ApiResponse<CampaignCategory>> {
    return this.request<CampaignCategory>('/campaign-categories', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async updateCampaignCategory(categoryId: string, payload: { name: string }): Promise<ApiResponse<CampaignCategory>> {
    return this.request<CampaignCategory>(`/campaign-categories/${categoryId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  async deleteCampaignCategory(categoryId: string): Promise<ApiResponse> {
    return this.request(`/campaign-categories/${categoryId}`, {
      method: 'DELETE',
    });
  }

  // Campaign Preview
  async getCampaignPreview(campaignId: string): Promise<ApiResponse<any>> {
    return this.request<any>(`/campaigns/${campaignId}/preview`);
  }

  // Campaign Draft
  async getCampaignDraft(campaignId: string): Promise<ApiResponse<CampaignDraftResponse>> {
    return this.request<CampaignDraftResponse>(`/campaigns/${campaignId}/draft`);
  }

  async updateCampaignDraftTemplate(campaignId: string, payload: CampaignDraftRequest): Promise<ApiResponse<CampaignDraftResponse>> {
    return this.request<CampaignDraftResponse>(`/campaigns/${campaignId}/draft`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  async updateCampaignDraftManual(campaignId: string, payload: CampaignDraftRequest): Promise<ApiResponse<CampaignDraftResponse>> {
    return this.request<CampaignDraftResponse>(`/campaigns/${campaignId}/draft/manual`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  async generateCampaignDraftAI(campaignId: string, payload: AIDraftRequest): Promise<ApiResponse<CampaignDraftResponse>> {
    const controller = new AbortController();
    const t = window.setTimeout(() => controller.abort(), 360_000);
    try {
      return await this.request<CampaignDraftResponse>(`/campaigns/${campaignId}/draft/ai`, {
        method: 'POST',
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
    } finally {
      window.clearTimeout(t);
    }
  }

  async getPersonalizationCapabilities(): Promise<ApiResponse<PlanCapabilitiesResponse>> {
    return this.request<PlanCapabilitiesResponse>('/personalization/capabilities');
  }

  async checkEmailSpam(campaignId: string, payload: SpamCheckRequest): Promise<ApiResponse<SpamCheckResponse>> {
    // Default fast_mode: skips extra validation LLM round-trips (much quicker; same primary analysis).
    const body = { ...payload, fast_mode: payload.fast_mode !== false };
    return this.request<SpamCheckResponse>(`/campaigns/${campaignId}/draft/spam-check`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
  }

  async generateCampaignLeadEmails(
    campaignId: string,
    options?: { regenerateAll?: boolean; regenerateFailed?: boolean },
  ): Promise<ApiResponse<CampaignEmailGenerationStatus>> {
    const params = new URLSearchParams();
    if (options?.regenerateAll) params.set('regenerate_all', 'true');
    if (options?.regenerateFailed) params.set('regenerate_failed', 'true');
    const query = params.toString() ? `?${params.toString()}` : '';
    return this.request<CampaignEmailGenerationStatus>(
      `/campaigns/${campaignId}/emails/generate${query}`,
      {
        method: 'POST',
      },
    );
  }

  async getCampaignLeadEmailsStatus(campaignId: string): Promise<ApiResponse<CampaignEmailGenerationStatus>> {
    return this.request<CampaignEmailGenerationStatus>(`/campaigns/${campaignId}/emails/status`);
  }

  async resumeCampaignLeadEmailGeneration(
    campaignId: string,
  ): Promise<ApiResponse<CampaignEmailGenerationStatus>> {
    return this.request<CampaignEmailGenerationStatus>(`/campaigns/${campaignId}/emails/resume`, {
      method: 'POST',
    });
  }

  async cancelCampaignLeadEmailGeneration(
    campaignId: string,
  ): Promise<ApiResponse<CampaignEmailGenerationStatus>> {
    return this.request<CampaignEmailGenerationStatus>(`/campaigns/${campaignId}/emails/cancel`, {
      method: 'POST',
    });
  }

  async discardCampaignLeadEmails(
    campaignId: string,
  ): Promise<ApiResponse<CampaignEmailGenerationStatus>> {
    return this.request<CampaignEmailGenerationStatus>(`/campaigns/${campaignId}/emails/discard`, {
      method: 'POST',
    });
  }

  async getCampaignLeadEmails(campaignId: string): Promise<ApiResponse<CampaignLeadEmailRow[]>> {
    return this.fetchAllPaginated<CampaignLeadEmailRow>(`/campaigns/${campaignId}/emails`);
  }

  async getCampaignEmailReviewSummary(campaignId: string): Promise<ApiResponse<CampaignEmailReviewSummary>> {
    return this.request<CampaignEmailReviewSummary>(`/campaigns/${campaignId}/emails/review`);
  }

  async approveCampaignEmails(
    campaignId: string,
    payload: { email_ids?: string[]; approve_all?: boolean }
  ): Promise<ApiResponse<CampaignEmailReviewSummary>> {
    return this.request<CampaignEmailReviewSummary>(`/campaigns/${campaignId}/emails/review/approve`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async rejectCampaignEmails(
    campaignId: string,
    payload: { email_ids?: string[]; reject_all_pending?: boolean }
  ): Promise<ApiResponse<CampaignEmailReviewSummary>> {
    return this.request<CampaignEmailReviewSummary>(`/campaigns/${campaignId}/emails/review/reject`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async regenerateCampaignLeadEmail(
    campaignId: string,
    emailId: string
  ): Promise<ApiResponse<{ email: CampaignLeadEmailRow; message: string }>> {
    return this.request<{ email: CampaignLeadEmailRow; message: string }>(
      `/campaigns/${campaignId}/emails/${emailId}/regenerate`,
      { method: 'POST' }
    );
  }

  async updateCampaignLeadEmail(
    campaignId: string,
    emailId: string,
    payload: { subject: string; body: string; mark_spam_passed?: boolean }
  ): Promise<ApiResponse<{ email: CampaignLeadEmailRow; message: string }>> {
    return this.request<{ email: CampaignLeadEmailRow; message: string }>(
      `/campaigns/${campaignId}/emails/${emailId}`,
      {
        method: 'PATCH',
        body: JSON.stringify(payload),
      }
    );
  }

  // Email Templates
  async getEmailTemplates(): Promise<ApiResponse<EmailTemplate[]>> {
    return this.request<EmailTemplate[]>('/email-templates');
  }

  async getEmailTemplateById(templateId: string): Promise<ApiResponse<EmailTemplate>> {
    return this.request<EmailTemplate>(`/email-templates/${templateId}`);
  }

  async createEmailTemplate(payload: EmailTemplateCreateRequest): Promise<ApiResponse<EmailTemplate>> {
    return this.request<EmailTemplate>('/email-templates', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async updateEmailTemplate(templateId: string, payload: EmailTemplateUpdateRequest): Promise<ApiResponse<EmailTemplate>> {
    return this.request<EmailTemplate>(`/email-templates/${templateId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  async toggleTemplateFavorite(templateId: string): Promise<ApiResponse<EmailTemplate>> {
    return this.request<EmailTemplate>(`/email-templates/${templateId}/toggle-favorite`, {
      method: 'PATCH',
    });
  }

  async deleteEmailTemplate(templateId: string): Promise<ApiResponse> {
    return this.request(`/email-templates/${templateId}`, {
      method: 'DELETE',
    });
  }

  async getEmailTemplateUsageStats(): Promise<ApiResponse<{ [templateId: string]: number }>> {
    return this.request<{ [templateId: string]: number }>('/email-templates/usage-stats');
  }

  async getEmailTemplateCategories(): Promise<ApiResponse<Array<{ value: string; label: string }>>> {
    return this.request<Array<{ value: string; label: string }>>('/email-templates/categories');
  }

  // Campaign Insight
  async getCampaignInsight(
    campaignId: string, 
    startDate?: string, 
    endDate?: string
  ): Promise<ApiResponse<CampaignInsightResponse>> {
    const params = new URLSearchParams();
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);
    const queryString = params.toString();
    const url = `/campaigns/${campaignId}/insight${queryString ? `?${queryString}` : ''}`;
    return this.request<CampaignInsightResponse>(url);
  }

  // Company
  async createCompany(payload: CompanyCreateRequest): Promise<ApiResponse<CompanyResponse>> {
    return this.request<CompanyResponse>('/company', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async getMyCompany(): Promise<ApiResponse<CompanyResponse>> {
    return this.request<CompanyResponse>('/company/me');
  }

  async updateCompany(companyId: string, payload: CompanyUpdateRequest): Promise<ApiResponse<CompanyResponse>> {
    return this.request<CompanyResponse>(`/company/${companyId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  // Billing (Stripe — server webhook is not exposed to the SPA)
  async getBillingCreditBalance(): Promise<ApiResponse<BillingCreditBalanceResponse>> {
    return this.request<BillingCreditBalanceResponse>('/billing/credits/balance');
  }

  async getBillingCreditHistory(): Promise<ApiResponse<BillingCreditHistoryResponse>> {
    return this.request<BillingCreditHistoryResponse>('/billing/credits/history');
  }

  async getBillingSubscription(): Promise<ApiResponse<BillingSubscriptionResponse>> {
    return this.request<BillingSubscriptionResponse>('/billing/subscription');
  }

  async createBillingCheckoutSession(plan: string): Promise<ApiResponse<BillingCheckoutSessionResponse>> {
    return this.request<BillingCheckoutSessionResponse>('/billing/create-checkout-session', {
      method: 'POST',
      body: JSON.stringify({ plan }),
    });
  }

  /** Sync DB after Stripe redirect if webhook was delayed or unreachable. */
  async confirmCheckoutSession(sessionId: string): Promise<ApiResponse<BillingConfirmCheckoutResponse>> {
    return this.request<BillingConfirmCheckoutResponse>('/billing/confirm-checkout-session', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId }),
    });
  }

  async getBillingTopupOptions(): Promise<ApiResponse<BillingTopupOptionsResponse>> {
    return this.request<BillingTopupOptionsResponse>('/billing/topup/options');
  }

  async createBillingTopupCheckoutSession(
    creditsOrPools: number | BillingTopupCheckoutRequest,
  ): Promise<ApiResponse<BillingTopupCheckoutResponse>> {
    const body: BillingTopupCheckoutRequest =
      typeof creditsOrPools === 'number'
        ? { lead: creditsOrPools }
        : {
            lead: creditsOrPools.lead ?? 0,
            email_gen: creditsOrPools.email_gen ?? 0,
            outreach: creditsOrPools.outreach ?? 0,
          };
    return this.request<BillingTopupCheckoutResponse>('/billing/topup/create-checkout-session', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  }

  async cancelBillingSubscription(): Promise<ApiResponse<{ message: string }>> {
    return this.request<{ message: string }>('/billing/cancel', {
      method: 'POST',
    });
  }

  /** Stripe Customer Portal (payment methods, cancel at period end, invoices). */
  async createBillingPortalSession(): Promise<ApiResponse<{ url: string }>> {
    return this.request<{ url: string }>('/billing/create-portal-session', {
      method: 'POST',
    });
  }

  async submitCancellationFeedback(
    reason: string,
    details?: string,
  ): Promise<ApiResponse<{ status: string; message?: string }>> {
    return this.request<{ status: string; message?: string }>('/billing/cancellation-feedback', {
      method: 'POST',
      body: JSON.stringify({ reason, details: details?.trim() || undefined }),
    });
  }

  // Admin AI usage reporting
  async getAiUsageSummary(params?: {
    from?: string;
    to?: string;
    provider?: string;
    feature?: string;
    model?: string;
  }): Promise<ApiResponse<AiUsageSummary>> {
    const q = new URLSearchParams();
    if (params?.from) q.set('from_date', params.from);
    if (params?.to) q.set('to_date', params.to);
    if (params?.provider) q.set('provider', params.provider);
    if (params?.feature) q.set('feature', params.feature);
    if (params?.model) q.set('model', params.model);
    const qs = q.toString();
    return this.request<AiUsageSummary>(`/ai-usage/summary${qs ? `?${qs}` : ''}`);
  }

  async getAiUsageByFeature(params?: {
    from?: string;
    to?: string;
    provider?: string;
  }): Promise<ApiResponse<AiUsageByFeatureItem[]>> {
    const q = new URLSearchParams();
    if (params?.from) q.set('from_date', params.from);
    if (params?.to) q.set('to_date', params.to);
    if (params?.provider) q.set('provider', params.provider);
    const qs = q.toString();
    return this.request<AiUsageByFeatureItem[]>(`/ai-usage/by-feature${qs ? `?${qs}` : ''}`);
  }

  async getAiUsageByModel(params?: {
    from?: string;
    to?: string;
    provider?: string;
  }): Promise<ApiResponse<AiUsageByModelItem[]>> {
    const q = new URLSearchParams();
    if (params?.from) q.set('from_date', params.from);
    if (params?.to) q.set('to_date', params.to);
    if (params?.provider) q.set('provider', params.provider);
    const qs = q.toString();
    return this.request<AiUsageByModelItem[]>(`/ai-usage/by-model${qs ? `?${qs}` : ''}`);
  }

  async getAiUsageByDay(params?: {
    from?: string;
    to?: string;
    provider?: string;
    feature?: string;
  }): Promise<ApiResponse<AiUsageByDayItem[]>> {
    const q = new URLSearchParams();
    if (params?.from) q.set('from_date', params.from);
    if (params?.to) q.set('to_date', params.to);
    if (params?.provider) q.set('provider', params.provider);
    if (params?.feature) q.set('feature', params.feature);
    const qs = q.toString();
    return this.request<AiUsageByDayItem[]>(`/ai-usage/by-day${qs ? `?${qs}` : ''}`);
  }

  async getAiUsageByMonth(params?: {
    from?: string;
    to?: string;
    provider?: string;
  }): Promise<ApiResponse<AiUsageByMonthItem[]>> {
    const q = new URLSearchParams();
    if (params?.from) q.set('from_date', params.from);
    if (params?.to) q.set('to_date', params.to);
    if (params?.provider) q.set('provider', params.provider);
    const qs = q.toString();
    return this.request<AiUsageByMonthItem[]>(`/ai-usage/by-month${qs ? `?${qs}` : ''}`);
  }

  async getAiUsageByUser(params?: {
    from?: string;
    to?: string;
    provider?: string;
  }): Promise<ApiResponse<AiUsageByUserItem[]>> {
    const q = new URLSearchParams();
    if (params?.from) q.set('from_date', params.from);
    if (params?.to) q.set('to_date', params.to);
    if (params?.provider) q.set('provider', params.provider);
    const qs = q.toString();
    return this.request<AiUsageByUserItem[]>(`/ai-usage/by-user${qs ? `?${qs}` : ''}`);
  }

  async getAiUsageByUserMonth(params?: {
    from?: string;
    to?: string;
    provider?: string;
  }): Promise<ApiResponse<AiUsageByUserMonthItem[]>> {
    const q = new URLSearchParams();
    if (params?.from) q.set('from_date', params.from);
    if (params?.to) q.set('to_date', params.to);
    if (params?.provider) q.set('provider', params.provider);
    const qs = q.toString();
    return this.request<AiUsageByUserMonthItem[]>(`/ai-usage/by-user-month${qs ? `?${qs}` : ''}`);
  }

  async getAiUsageCreditsByUser(params?: {
    from?: string;
    to?: string;
  }): Promise<ApiResponse<AiUsageCreditsByUserItem[]>> {
    const q = new URLSearchParams();
    if (params?.from) q.set('from_date', params.from);
    if (params?.to) q.set('to_date', params.to);
    const qs = q.toString();
    return this.request<AiUsageCreditsByUserItem[]>(`/ai-usage/credits-by-user${qs ? `?${qs}` : ''}`);
  }

  async recomputeAiUsageCosts(): Promise<
    ApiResponse<{
      updated: number;
      unchanged: number;
      total_cost_before_usd: number;
      total_cost_after_usd: number;
      message: string;
      pricing_source?: string | null;
      pricing_source_url?: string | null;
      pricing_fingerprint?: string | null;
      pricing_error?: string | null;
    }>
  > {
    return this.request('/ai-usage/recompute-costs', { method: 'POST' });
  }

  async getAiUsagePricing(refresh = false): Promise<
    ApiResponse<{
      source: string;
      source_url?: string | null;
      fetched_at?: number | null;
      age_seconds?: number | null;
      model_count: number;
      fingerprint: string;
      error?: string | null;
      models: Record<string, Record<string, number>>;
      google_maps_apis?: Array<{
        api_name: string;
        label: string;
        endpoint?: string;
        unit_cost_usd: number;
        unit_label?: string;
        free_monthly?: number | null;
        notes?: string;
      }>;
      google_maps_source?: string;
      google_maps_source_url?: string;
    }>
  > {
    const qs = refresh ? '?refresh=true' : '';
    return this.request(`/ai-usage/pricing${qs}`);
  }

  async adminTopupCredits(payload: AdminTopupRequest): Promise<ApiResponse<AdminTopupResponse>> {
    return this.request<AdminTopupResponse>('/billing/admin/topup', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async getAdminUserCreditBalance(userId: string): Promise<ApiResponse<AdminUserBalanceResponse>> {
    return this.request<AdminUserBalanceResponse>(`/billing/admin/users/${userId}/balance`);
  }

  async getAdminTopupHistory(limit = 50): Promise<ApiResponse<AdminTopupHistoryItem[]>> {
    return this.request<AdminTopupHistoryItem[]>(`/billing/admin/topup/history?limit=${limit}`);
  }

  async getGeminiPurchaseSummary(): Promise<ApiResponse<GeminiStatusTrack>> {
    return this.getGeminiCreditTrack();
  }

  async getGeminiCreditTrack(): Promise<ApiResponse<GeminiStatusTrack>> {
    return this.request<GeminiStatusTrack>('/gemini-purchases/track');
  }

  async getExternalApiUsageTrack(
    provider: ExternalApiProvider,
    params?: { from?: string; to?: string },
  ): Promise<ApiResponse<ExternalApiUsageTrack>> {
    const q = new URLSearchParams();
    q.set('provider', provider);
    if (params?.from) q.set('from_date', params.from);
    if (params?.to) q.set('to_date', params.to);
    return this.request<ExternalApiUsageTrack>(`/external-api-usage/track?${q.toString()}`);
  }

  // Google Auth
  async getGoogleAuthUrl(): Promise<string> {
    // Google auth login endpoint redirects, so we need to construct the URL
    return `${this.getBaseURL()}/auth/google/login`;
  }

  // Roles & Permissions
  async createRole(payload: RoleCreateRequest): Promise<ApiResponse<Role>> {
    return this.request<Role>('/roles/', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async getRoles(): Promise<ApiResponse<Role[]>> {
    return this.request<Role[]>('/roles/');
  }

  async getRoleById(roleId: string): Promise<ApiResponse<Role>> {
    return this.request<Role>(`/roles/${roleId}`);
  }

  async updateRole(roleId: string, payload: RoleUpdateRequest): Promise<ApiResponse<Role>> {
    return this.request<Role>(`/roles/${roleId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  }

  async deleteRole(roleId: string): Promise<ApiResponse> {
    return this.request(`/roles/${roleId}`, {
      method: 'DELETE',
    });
  }

  async assignPermissionsToRole(roleId: string, payload: AssignPermissionsRequest): Promise<ApiResponse<Role>> {
    return this.request<Role>(`/roles/${roleId}/assign`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async createPermission(payload: PermissionCreateRequest): Promise<ApiResponse<Permission>> {
    return this.request<Permission>('/roles/permissions', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async getPermissions(): Promise<ApiResponse<Permission[]>> {
    return this.request<Permission[]>('/roles/permissions');
  }

  async getGroupedPermissions(): Promise<ApiResponse<GroupedPermissions>> {
    return this.request<GroupedPermissions>('/roles/permissions/grouped');
  }

  async updatePermission(permissionId: string, payload: PermissionUpdateRequest): Promise<ApiResponse<Permission>> {
    return this.request<Permission>(`/roles/permissions/${permissionId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  }

  async deletePermission(permissionId: string): Promise<ApiResponse> {
    return this.request(`/roles/permissions/${permissionId}`, {
      method: 'DELETE',
    });
  }

  // User Management (Admin)
  async getAllUsers(): Promise<ApiResponse<UserList[]>> {
    const pageSize = 200;
    const items: UserList[] = [];
    let offset = 0;
    let total = Infinity;
    while (items.length < total && offset < 10_000) {
      const res = await this.request<UserListPage>(
        `/users/?limit=${pageSize}&offset=${offset}`,
      );
      if (res.error) {
        return { error: res.error, message: res.message, data: undefined };
      }
      const page = res.data;
      total = page?.total ?? 0;
      const chunk = page?.items ?? [];
      items.push(...chunk);
      if (chunk.length < pageSize) break;
      offset += pageSize;
    }
    return { data: items };
  }

  async updateUserPlan(
    userId: string,
    payload: AdminUserPlanUpdateRequest,
  ): Promise<ApiResponse<AdminUserPlanUpdateResponse>> {
    return this.request<AdminUserPlanUpdateResponse>(`/users/${userId}/plan`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  }

  async getUserDetails(userId: string): Promise<ApiResponse<UserDetailsResponse>> {
    return this.request<UserDetailsResponse>(`/users/${userId}/details`);
  }

  async createUser(payload: AdminUserCreateRequest): Promise<ApiResponse<any>> {
    return this.request<any>('/users/create', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async updateUser(userId: string, payload: AdminUserUpdateRequest): Promise<ApiResponse<any>> {
    return this.request<any>(`/users/${userId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  }

  async deleteUser(userId: string): Promise<ApiResponse> {
    return this.request(`/users/${userId}/hard`, {
      method: 'DELETE',
    });
  }

  async updateUserRole(userId: string, roleId: string): Promise<ApiResponse<any>> {
    return this.request<any>(`/users/${userId}/role?role_id=${roleId}`, {
      method: 'PATCH',
    });
  }

  async getUserPermissionOverrides(userId: string): Promise<ApiResponse<UserPermissionsOverrides>> {
    return this.request<UserPermissionsOverrides>(`/users/${userId}/permissions/overrides`);
  }

  async updateUserPermissionOverrides(userId: string, payload: UserPermissionsOverrides): Promise<ApiResponse<any>> {
    return this.request<any>(`/users/${userId}/permissions/overrides`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  }

  async clearUserPermissionOverrides(userId: string): Promise<ApiResponse> {
    return this.request(`/users/${userId}/permissions/overrides`, {
      method: 'DELETE',
    });
  }

  async getUserEffectivePermissions(userId: string): Promise<ApiResponse<UserEffectivePermissions>> {
    return this.request<UserEffectivePermissions>(`/users/${userId}/permissions/effective`);
  }

  async resetUserPermissions(userId: string): Promise<ApiResponse<any>> {
    return this.request<any>(`/users/${userId}/permissions/reset`, {
      method: 'POST',
    });
  }

  // Domain methods
  async createDomain(payload: DomainCreateRequest): Promise<ApiResponse<DomainResponse>> {
    return this.request<DomainResponse>('/domains/', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async getDomains(): Promise<ApiResponse<DomainResponse[]>> {
    return this.request<DomainResponse[]>('/domains/');
  }

  async getDomainById(domainId: string): Promise<ApiResponse<DomainResponse>> {
    return this.request<DomainResponse>(`/domains/${domainId}`);
  }

  async updateDomain(domainId: string, payload: DomainUpdateRequest): Promise<ApiResponse<DomainResponse>> {
    return this.request<DomainResponse>(`/domains/${domainId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  async deleteDomain(domainId: string): Promise<ApiResponse> {
    return this.request(`/domains/${domainId}`, {
      method: 'DELETE',
    });
  }

  // Mailbox methods
  async createMailbox(payload: MailboxCreateRequest): Promise<ApiResponse<MailboxResponse>> {
    return this.request<MailboxResponse>('/mailboxes/', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async getAllMailboxes(): Promise<ApiResponse<MailboxResponse[]>> {
    return this.request<MailboxResponse[]>('/mailboxes/');
  }

  async getEmailStatistics(): Promise<ApiResponse<{
    sent_today: number;
    delivery_rate: number;
    bounce_rate: number;
    total_sent: number;
    total_delivered: number;
    total_bounced: number;
  }>> {
    return this.request('/mailboxes/statistics');
  }

  async getMailboxesByDomain(domainId: string): Promise<ApiResponse<MailboxResponse[]>> {
    return this.request<MailboxResponse[]>(`/mailboxes/domain/${domainId}`);
  }

  async getMailboxById(mailboxId: string): Promise<ApiResponse<MailboxResponse>> {
    return this.request<MailboxResponse>(`/mailboxes/${mailboxId}`);
  }

  async updateMailbox(mailboxId: string, payload: MailboxUpdateRequest): Promise<ApiResponse<MailboxResponse>> {
    return this.request<MailboxResponse>(`/mailboxes/${mailboxId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  async deleteMailbox(mailboxId: string): Promise<ApiResponse> {
    return this.request(`/mailboxes/${mailboxId}`, {
      method: 'DELETE',
    });
  }

  async connectGoogleMailbox(campaignId?: string): Promise<ApiResponse<{ auth_url: string }>> {
    const url = campaignId 
      ? `/mailboxes/google/connect?campaign_id=${encodeURIComponent(campaignId)}`
      : '/mailboxes/google/connect';
    return this.request<{ auth_url: string }>(url, {
      method: 'POST',
    });
  }

  async updateEmailSendingMode(emailSendingMode: string): Promise<ApiResponse<{ email_sending_mode: string }>> {
    return this.request<{ email_sending_mode: string }>('/mailboxes/email-sending-mode', {
      method: 'PUT',
      body: JSON.stringify({ email_sending_mode: emailSendingMode }),
    });
  }

  // Inbox methods
  async getInbox(params?: {
    campaignId?: string;
    page?: number;
    perPage?: number;
  }): Promise<ApiResponse<InboxResponse>> {
    const search = new URLSearchParams();
    if (params?.campaignId) search.set('campaign_id', params.campaignId);
    if (params?.page != null) search.set('page', String(params.page));
    if (params?.perPage != null) search.set('per_page', String(params.perPage));
    const qs = search.toString();
    return this.request<InboxResponse>(`/inbox${qs ? `?${qs}` : ''}`);
  }

  async toggleInboxStar(activityId: string): Promise<ApiResponse<{ id: string; starred: boolean }>> {
    return this.request<{ id: string; starred: boolean }>(`/inbox/${activityId}/star`, {
      method: 'POST',
    });
  }

  private fetchRepliesInFlight: Promise<ApiResponse<InboxResponse>> | null = null;

  /** IMAP/Gmail sync can be slow; staging may hang without server timeouts — abort so UI never sticks on "Syncing…". */
  async fetchReplies(): Promise<ApiResponse<InboxResponse>> {
    // Inbox mount effects can double-fire (StrictMode) — share one in-flight
    // sync instead of hitting the rate-limited endpoint twice concurrently
    if (this.fetchRepliesInFlight) return this.fetchRepliesInFlight;
    this.fetchRepliesInFlight = (async () => {
      const controller = new AbortController();
      const timeoutMs = 120_000;
      const tid = setTimeout(() => controller.abort(), timeoutMs);
      try {
        return await this.request<InboxResponse>(`/inbox/fetch-replies`, {
          method: 'POST',
          signal: controller.signal,
        });
      } finally {
        clearTimeout(tid);
        this.fetchRepliesInFlight = null;
      }
    })();
    return this.fetchRepliesInFlight;
  }

  async listInboxThreads(params?: { page?: number; perPage?: number }): Promise<ApiResponse<InboxThreadListItem[]>> {
    const search = new URLSearchParams();
    if (params?.page != null) search.set('page', String(params.page));
    if (params?.perPage != null) search.set('per_page', String(params.perPage));
    const qs = search.toString();
    return this.request<InboxThreadListItem[]>(`/inbox/threads${qs ? `?${qs}` : ''}`);
  }

  async getInboxThread(threadId: string): Promise<ApiResponse<InboxThreadDetail>> {
    return this.request<InboxThreadDetail>(`/inbox/threads/${threadId}`);
  }

  async getInboxLeadConversation(threadId: string, leadId: string): Promise<ApiResponse<LeadConversationResponse>> {
    return this.request<LeadConversationResponse>(`/inbox/threads/${threadId}/leads/${leadId}`);
  }

  async replyToInboxThreadLead(
    threadId: string,
    leadId: string,
    message: string
  ): Promise<ApiResponse<ThreadReplyResponse>> {
    return this.request<ThreadReplyResponse>(`/inbox/threads/${threadId}/leads/${leadId}/reply`, {
      method: 'POST',
      body: JSON.stringify({ message }),
    });
  }

  async markInboxThreadRead(threadId: string): Promise<ApiResponse<{ id: string; unread_reply_count: number }>> {
    return this.request<{ id: string; unread_reply_count: number }>(`/inbox/threads/${threadId}/read`, {
      method: 'PATCH',
    });
  }

  async toggleInboxThreadStar(threadId: string): Promise<ApiResponse<{ id: string; is_starred: boolean }>> {
    return this.request<{ id: string; is_starred: boolean }>(`/inbox/threads/${threadId}/star`, {
      method: 'PATCH',
    });
  }

  // Email Reply methods
  async replyToLead(payload: EmailReplyCreateRequest): Promise<ApiResponse<EmailReplyResponse>> {
    return this.request<EmailReplyResponse>('/emails/reply', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  // Webhook (for reference, typically called by external services)
  async handleWebhookEvent(eventData: any): Promise<ApiResponse<any>> {
    return this.request<any>('/webhook/email-events', {
      method: 'POST',
      body: JSON.stringify(eventData),
      headers: {
        'X-Key': '', // This should be set by the webhook caller, not frontend
      },
    });
  }

  // Email Insight methods
  async trackEmailOpen(campaignId: string, leadId: string): Promise<ApiResponse<{ message: string }>> {
    return this.request<{ message: string }>(`/email-accounts/email/open?campaign_id=${campaignId}&lead_id=${leadId}`);
  }

  async getSystemEmailInsights(): Promise<ApiResponse<SystemEmailInsightsResponse>> {
    return this.request<SystemEmailInsightsResponse>('/email-accounts/system/insights');
  }

  async getUserEmailOverview(): Promise<ApiResponse<UserEmailOverviewResponse>> {
    return this.request<UserEmailOverviewResponse>('/email-accounts/user/overview');
  }

  async getUserEmailAccounts(): Promise<ApiResponse<UserEmailAccount[]>> {
    return this.request<UserEmailAccount[]>('/email-accounts/user/accounts');
  }

  // System Mailbox methods
  async createSystemMailbox(payload: SystemMailboxCreateRequest): Promise<ApiResponse<SystemMailboxResponse>> {
    return this.request<SystemMailboxResponse>('/system/mailboxes/', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async getSystemMailboxes(): Promise<ApiResponse<SystemMailboxResponse[]>> {
    return this.request<SystemMailboxResponse[]>('/system/mailboxes/');
  }

  async updateSystemMailbox(
    mailboxId: string,
    payload: SystemMailboxUpdateRequest,
  ): Promise<ApiResponse<SystemMailboxResponse>> {
    return this.request<SystemMailboxResponse>(`/system/mailboxes/${mailboxId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  async deleteSystemMailbox(mailboxId: string): Promise<ApiResponse<{ status: string }>> {
    return this.request<{ status: string }>(`/system/mailboxes/${mailboxId}`, {
      method: 'DELETE',
    });
  }

  // System Domain methods
  async createSystemDomain(payload: SystemDomainCreateRequest): Promise<ApiResponse<SystemDomainResponse>> {
    return this.request<SystemDomainResponse>('/system/domains/', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  async getSystemDomains(): Promise<ApiResponse<SystemDomainResponse[]>> {
    return this.request<SystemDomainResponse[]>('/system/domains/');
  }

  async updateSystemDomain(
    domainId: string,
    payload: SystemDomainUpdateRequest,
  ): Promise<ApiResponse<SystemDomainResponse>> {
    return this.request<SystemDomainResponse>(`/system/domains/${domainId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  }

  async deleteSystemDomain(domainId: string): Promise<ApiResponse<{ status: string }>> {
    return this.request<{ status: string }>(`/system/domains/${domainId}`, {
      method: 'DELETE',
    });
  }
}

// Create and export a singleton instance
export const apiService = new ApiService();
export default apiService;
