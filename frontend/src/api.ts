import type {
  AgentKnowledge,
  AgentMemory,
  ChatMessage,
  ChatResponse,
  Draft,
  HistoryCandidate,
  MailDetail,
  MailListItem,
  OpenPriceSourceResult,
  PriceCandidate
} from "./types";

const API = "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json", ...(options?.headers || {}) },
    ...options
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail || response.statusText);
  }
  return response.json() as Promise<T>;
}

export const api = {
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
  analyzeMail: (id: number) => request<MailDetail>(`/mails/${id}/analyze`, { method: "POST" }),
  saveAnalysis: (id: number, payload: unknown) =>
    request<MailDetail>(`/mails/${id}/analysis`, { method: "PATCH", body: JSON.stringify(payload) }),
  syncMails: (limit = 50) =>
    request<{ imported: number; skipped: number; failed: number }>("/mails/sync", {
      method: "POST",
      body: JSON.stringify({ limit, include_existing: false })
    }),
  uploadEml: async (files: File[]) => {
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    const response = await fetch(`${API}/mails/import-eml`, { method: "POST", body: form });
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
  resolveReview: (issueId: number, value: unknown) =>
    request<MailDetail>(`/reviews/${issueId}/resolve`, {
      method: "POST",
      body: JSON.stringify({ resolution_value: value, apply_to_field: true })
    }),
  createDraft: (mailId: number) => request<Draft>(`/quotations/from-mail/${mailId}`, { method: "POST" }),
  listDrafts: () => request<Draft[]>("/quotations"),
  approveDraft: (id: number) => request<Draft>(`/quotations/${id}/approve`, { method: "POST" }),
  sendDraft: (id: number) => request<Draft>(`/quotations/${id}/send`, { method: "POST" }),
  deleteDraft: (id: number) => request<{ deleted: number }>(`/quotations/${id}`, { method: "DELETE" }),
  importPriceTable: (path?: string) =>
    request("/import/price-table", { method: "POST", body: JSON.stringify({ path: path || null }) }),
  importHistory: (path: string) =>
    request("/import/quotation-history", { method: "POST", body: JSON.stringify({ path }) }),

  openPriceSource: (sourceSheet?: string | null, sourceCell?: string | null) =>
    request<OpenPriceSourceResult>("/agent/open-price-source", {
      method: "POST",
      body: JSON.stringify({
        source_sheet: sourceSheet || null,
        source_cell: sourceCell || null
      })
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
