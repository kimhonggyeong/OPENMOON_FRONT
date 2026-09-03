import type {
  AgentKnowledge,
  AgentMemory,
  ChatMessage,
  ChatResponse,
  Draft,
  GeneralChatMessage,
  GeneralChatResponse,
  HistoryCandidate,
  MailDetail,
  MailListItem,
  OpenPriceSourceResult,
  PriceCandidate
  , ProductCatalog
  , QuotationStorageMode
  , QuotationStorageOptions
} from "./types";

const API = "/api";

const sessionUser = new URLSearchParams(window.location.search).get("user_id") || "";
export const syncEventsUrl = `${API}/sync/events?user_id=${encodeURIComponent(sessionUser)}`;
let connectionEnded = false;
export function endConnection() {
  if (connectionEnded) return;
  connectionEnded = true;
  window.dispatchEvent(new Event("openmoon-disconnected"));
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  if (connectionEnded) throw new Error("서버 연결이 종료되었습니다.");
  const response = await fetch(`${API}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", "X-Openmoon-User": sessionUser, ...(options?.headers || {}) }
  });
  if (response.status === 410) endConnection();
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(Array.isArray(body.detail)
      ? body.detail
          .map((error: { msg?: string }) => (error.msg || "입력값을 확인해주세요.").replace(/^Value error,\s*/, ""))
          .join("\n")
      : body.detail || response.statusText);
  }
  return response.json() as Promise<T>;
}

export const api = {
  prepareDraftDownload: async (draftId: number, format: "excel" | "pdf", fallbackName: string) => {
    if (connectionEnded) throw new Error("서버 연결이 종료되었습니다.");
    const route = format === "excel" ? "file" : "customer-pdf";
    const response = await fetch(`${API}/quotations/${draftId}/${route}`, {
      headers: { "X-Openmoon-User": sessionUser }
    });
    if (response.status === 410) endConnection();
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || "견적서 파일을 내려받지 못했습니다.");
    }
    const disposition = response.headers.get("Content-Disposition") || "";
    const encodedName = /filename\*=UTF-8''([^;]+)/i.exec(disposition)?.[1];
    const plainName = /filename="([^"]+)"/i.exec(disposition)?.[1];
    let filename = plainName || fallbackName;
    if (encodedName) {
      try { filename = decodeURIComponent(encodedName); } catch { /* 기본 파일명 사용 */ }
    }
    return { blob: await response.blob(), filename };
  },
  syncState: () => request<{
    revision: number;
    changed_at?: string | null;
    method?: string | null;
    path?: string | null;
  }>("/sync/state"),
  productCatalog: () => request<ProductCatalog>("/products/catalog"),
  listMails: (status?: string, search?: string) => {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (search) params.set("search", search);
    return request<MailListItem[]>(`/mails?${params.toString()}`);
  },
  getMail: (id: number) => request<MailDetail>(`/mails/${id}`),
  setMailStar: (id: number, starred: boolean) =>
    request<MailListItem>(`/mails/${id}/star`, {
      method: "PATCH",
      body: JSON.stringify({ starred })
    }),
  mailHearts: () => request<Record<string, { hearted: boolean; user_id?: string | null; user_name?: string | null; color?: string | null; updated_at?: string | null }>>("/lan-hearts"),
  setMailHeart: (mailKey: string, hearted: boolean, profile: { user_id: string; user_name: string; color: string }) =>
    request<{ mail_key: string; hearted: boolean; user_id?: string | null; user_name?: string | null; color?: string | null }>("/lan-hearts", {
      method: "PUT",
      body: JSON.stringify({ mail_key: mailKey, hearted, ...profile })
    }),
  listPresence: () => request<Array<{ user_id: string; user_name: string; color: string; last_seen: string }>>("/lan-presence"),
  updatePresence: (profile: { user_id: string; user_name: string; color: string }) =>
    request<Array<{ user_id: string; user_name: string; color: string; last_seen: string }>>("/lan-presence", {
      method: "PUT",
      body: JSON.stringify(profile)
    }),
  removePresence: (userId: string) =>
    request<Array<{ user_id: string; user_name: string; color: string; last_seen: string }>>(`/lan-presence/${encodeURIComponent(userId)}`, {
      method: "DELETE",
      keepalive: true
    }),  deleteMail: (id: number) =>
    request<{ deleted: number; mode: string; imap_deleted: boolean }>(
      `/mails/${id}`,
      { method: "DELETE" }
    ),
  analyzeMail: (id: number) => request<MailDetail>(`/mails/${id}/analyze`, { method: "POST" }),
  saveAnalysis: (id: number, payload: unknown) =>
    request<MailDetail>(`/mails/${id}/analysis`, { method: "PATCH", body: JSON.stringify(payload) }),
  syncMails: (limit = 50) =>
    request<{ imported: number; skipped: number; failed: number }>("/mails/sync", {
      method: "POST",
      body: JSON.stringify({ limit, include_existing: false })
    }),
  uploadEml: async (files: File[]) => {
    if (connectionEnded) throw new Error("서버 연결이 종료되었습니다.");
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    const response = await fetch(`${API}/mails/import-eml`, { method: "POST", headers: { "X-Openmoon-User": sessionUser }, body: form });
    if (response.status === 410) endConnection();
    if (!response.ok) throw new Error((await response.json()).detail || "EML 업로드 실패");
    return response.json() as Promise<MailListItem[]>;
  },
  prices: (id: number) => request<PriceCandidate[]>(`/mails/${id}/price-candidates`),
  history: (id: number) => request<HistoryCandidate[]>(`/mails/${id}/history`),
  companyHistory: (id: number) => request<HistoryCandidate[]>(`/mails/${id}/history?scope=company`),
  chatMessages: (id: number) => request<ChatMessage[]>(`/mails/${id}/chat`),
  sendChat: (id: number, message: string) =>
    request<ChatResponse>(`/mails/${id}/chat`, {
      method: "POST",
      body: JSON.stringify({ message })
    }),
  generalChatMessages: () => request<GeneralChatMessage[]>("/chat/general"),
  sendGeneralChat: (message: string) =>
    request<GeneralChatResponse>("/chat/general", {
      method: "POST",
      body: JSON.stringify({ message })
    }),
  resolveReview: (issueId: number, value: unknown) =>
    request<MailDetail>(`/reviews/${issueId}/resolve`, {
      method: "POST",
      body: JSON.stringify({ resolution_value: value, apply_to_field: true })
    }),
  quotationStorageOptions: (mailId: number) =>
    request<QuotationStorageOptions>(`/quotations/storage-options/${mailId}`),
  createDraft: (mailId: number, mode: QuotationStorageMode, filePath: string) =>
    request<Draft>(`/quotations/from-mail/${mailId}`, {
      method: "POST",
      body: JSON.stringify({ mode, file_path: filePath })
    }),
  listDrafts: () => request<Draft[]>("/quotations"),
  updateDraftEmail: (
    id: number,
    payload: { email_subject: string; email_body?: string | null; email_recipients?: string[] }
  ) =>
    request<Draft>(`/quotations/${id}/email`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    }),
  emailPreview: (id: number, employeeKey = "kim_heejung") => request<{
    subject: string;
    body: string;
    recipient?: string | null;
    recipients: string[];
    customer_recipient?: string | null;
    delivery_mode: string;
    attachment_path?: string | null;
    attachment_name?: string | null;
  }>(`/quotations/${id}/email-preview?employee_key=${encodeURIComponent(employeeKey)}`),  approveDraft: (id: number, employeeKey: string) => request<Draft>(`/quotations/${id}/approve`, {
    method: "POST",
    body: JSON.stringify({ employee_key: employeeKey })
  }),
  sendDraft: (id: number) => request<Draft>(`/quotations/${id}/send`, { method: "POST" }),
  deleteDraft: (id: number) => request<{ deleted: number }>(`/quotations/${id}`, { method: "DELETE" }),
  importPriceTable: (path?: string) =>
    request("/import/price-table", { method: "POST", body: JSON.stringify({ path: path || null }) }),
  importHistory: (path: string) =>
    request("/import/quotation-history", { method: "POST", body: JSON.stringify({ path }) }),
  syncQuotationHistory: () => request<{ processed: number; synced: number; failed: number; errors: Array<{ draft_id: number; error: string }> }>("/data-admin/quotation-history/sync", { method: "POST" }),
  priceItems: (search = "") => request<Array<Record<string, unknown>>>(`/data-admin/price-items?search=${encodeURIComponent(search)}`),
  createPriceItem: (payload: Record<string, unknown>) => request<Record<string, unknown>>("/data-admin/price-items", { method: "POST", body: JSON.stringify(payload) }),
  updatePriceItem: (id: number, payload: Record<string, unknown>) => request<Record<string, unknown>>(`/data-admin/price-items/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  deletePriceItem: (id: number) => request<{ deleted: number }>(`/data-admin/price-items/${id}`, { method: "DELETE" }),

  openPriceSource: (sourceSheet?: string | null, sourceCell?: string | null) =>
    request<OpenPriceSourceResult>("/agent/open-price-source", {
      method: "POST",
      body: JSON.stringify({
        source_sheet: sourceSheet || null,
        source_cell: sourceCell || null
      })
    }),
  openHistorySource: (sourceFile: string, sourceSheet: string) =>
    request<OpenPriceSourceResult>("/mails/history/open-source", {
      method: "POST",
      body: JSON.stringify({ source_file: sourceFile, source_sheet: sourceSheet })
    }),

  agentMemories: () => request<AgentMemory[]>("/agent/memories"),
  updateAgentMemory: (id: number, payload: Partial<AgentMemory>) =>
    request<AgentMemory>(`/agent/memories/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    }),
  deleteAgentMemory: (id: number) =>
    request<{ deleted: number }>(`/agent/memories/${id}`, { method: "DELETE" }),

  agentKnowledge: () => request<AgentKnowledge[]>("/agent/knowledge"),
  createAgentKnowledge: (payload: {
    category: string;
    title: string;
    content: string;
    product_name?: string | null;
    material_name?: string | null;
    usage_context?: string | null;
    tags?: string | null;
    priority?: number;
  }) =>
    request<AgentKnowledge>("/agent/knowledge", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  updateAgentKnowledge: (id: number, payload: Partial<AgentKnowledge>) =>
    request<AgentKnowledge>(`/agent/knowledge/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    }),
  deleteAgentKnowledge: (id: number) =>
    request<{ deleted: number }>(`/agent/knowledge/${id}`, { method: "DELETE" }),

  settingsStatus: () => request<Record<string, unknown>>("/settings/status"),
  settingsPaths: () => request<Record<string, string>>("/settings/paths")
};
