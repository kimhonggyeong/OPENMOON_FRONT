export type MailStatus =
  | "NEW"
  | "ANALYZING"
  | "REVIEW_REQUIRED"
  | "READY_FOR_QUOTE"
  | "QUOTE_CREATED"
  | "APPROVED"
  | "SENT"
  | "FAILED"
  | "NOT_RELEVANT";

export type MailCategory =
  | "order"
  | "quotation_request"
  | "advertisement"
  | "inquiry"
  | "shipping"
  | "payment"
  | "other";

export type CommitmentStatus =
  | "confirmed"
  | "unconfirmed"
  | "unclear";

export interface Attachment {
  id: number;
  filename: string;
  content_type?: string | null;
  size_bytes: number;
  status: string;
  extracted_text?: string | null;
  analysis_summary?: string | null;
  error_message?: string | null;
}

export interface MailItem {
  id?: number;
  position?: number;

  product_name: string;
  normalized_product?: string | null;
  specification?: string | null;

  width_mm?: number | null;
  height_mm?: number | null;
  size_name?: string | null;

  quantity?: number | null;
  unit?: string | null;

  paper?: string | null;
  print_sides?: string | null;
  material?: string | null;

  unit_price?: number | null;
  amount?: number | null;

  detail_text?: string | null;
  schedule_note?: string | null;
  design_request?: string | null;

  evidence?: Record<string, unknown>;
  confirmed?: boolean;
}

export interface ReviewIssue {
  id: number;
  code: string;
  field_name?: string | null;
  message: string;
  severity: "warning" | "blocking";
  suggestions: Array<Record<string, unknown> | string | number>;
  resolved: boolean;
  resolution_value?: unknown;
}

export interface MailListItem {
  id: number;
  status: MailStatus;
  starred: boolean;

  outer_subject?: string | null;
  original_subject?: string | null;

  original_sender_name?: string | null;
  original_sender_email?: string | null;

  customer_organization?: string | null;
  outer_sent_at?: string | null;
  original_sent_at?: string | null;
  summary?: string | null;

  created_at: string;
}

export interface MailDetail extends MailListItem {
  forward_depth: number;

  outer_sender_name?: string | null;
  outer_sender_email?: string | null;
  outer_recipient?: string | null;
  outer_body?: string | null;

  original_recipient?: string | null;
  original_body?: string | null;

  customer_department?: string | null;
  customer_name?: string | null;
  customer_phone?: string | null;
  customer_email?: string | null;

  delivery_place?: string | null;
  payment_terms?: string | null;
  requested_date?: string | null;

  category?: MailCategory | null;
  is_order_related: boolean;
  total_amount?: number | null;

  request_types: string[];
  commitment_status?: CommitmentStatus | null;

  confidence?: number | null;
  reason?: string | null;

  missing_information: string[];

  analysis_payload?: Record<string, unknown>;

  attachments: Attachment[];
  items: MailItem[];
  reviews: ReviewIssue[];
}

export interface PriceCandidate {
  item_id: number;
  item_index: number;

  product_name: string;

  unit_price?: number | null;
  amount?: number | null;

  source: string;
  reference?: string | null;

  score: number;
  reason: string;

  needs_review: boolean;

  // 기존 API 호환 필드
  exact: boolean;

  source_sheet: string;
  source_cell: string;

  context?: string | null;
  vat?: string | null;
  automation_status?: string | null;
}

export interface HistoryCandidate {
  quotation_id: number;
  quotation_date?: string | null;

  customer_name: string;

  product_name: string;
  specification?: string | null;

  width_mm?: number | null;
  height_mm?: number | null;

  quantity?: number | null;
  unit_price?: number | null;
  amount?: number | null;

  source_file: string;
  source_sheet: string;
}

export interface DraftItem {
  id: number;
  position: number;

  product_name: string;
  specification?: string | null;

  quantity?: number | null;
  unit?: string | null;

  unit_price?: number | null;
  amount?: number | null;

  note?: string | null;

  price_source: Record<string, unknown>;
}

export interface Draft {
  id: number;
  mail_id: number;

  status: string;
  file_path: string;

  customer_name: string;
  total_amount?: number | null;

  email_subject?: string | null;
  email_body?: string | null;

  approved_at?: string | null;
  sent_at?: string | null;
  sent_to?: string | null;

  error_message?: string | null;

  items: DraftItem[];
}

export interface ChatMessage {
  id: number;
  mail_id: number;
  role: "user" | "assistant";
  content: string;
  evidence: Array<{ type?: string; label?: string; source_file?: string }>;
  action_payload: Record<string, unknown>;
  created_at: string;
}

export interface ChatResponse {
  user_message: ChatMessage;
  assistant_message: ChatMessage;
  mail: MailDetail;
  draft_updated: boolean;
}
