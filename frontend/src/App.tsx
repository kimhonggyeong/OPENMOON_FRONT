import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Archive,
  CheckCircle2,
  ChevronRight,
  FileDown,
  FileSpreadsheet,
  Inbox,
  Loader2,
  MailCheck,
  MessageCircle,
  RefreshCw,
  Save,
  Search,
  Send,
  Settings,
  Sparkles,
  Star,
  Trash2,
  Upload,
  XCircle
} from "lucide-react";
import { api } from "./api";
import type { ChatMessage, Draft, HistoryCandidate, MailDetail, MailItem, MailListItem, PriceCandidate, ReviewIssue } from "./types";

const STATUS_LABELS: Record<string, string> = {
  NEW: "신규",
  ANALYZING: "분석 중",
  REVIEW_REQUIRED: "검토 필요",
  READY_FOR_QUOTE: "견적 가능",
  QUOTE_CREATED: "견적 생성",
  APPROVED: "승인 완료",
  SENT: "발송 완료",
  FAILED: "처리 실패",
  NOT_RELEVANT: "견적 업무 아님"
};

const CATEGORY_LABELS: Record<string, string> = {
  order: "주문",
  quotation_request: "견적 요청",
  advertisement: "광고",
  inquiry: "일반 문의",
  shipping: "배송",
  payment: "결제",
  other: "기타"
};

const REQUEST_TYPE_LABELS: Record<string, string> = {
  quotation: "견적",
  production: "제작",
  design_draft: "시안",
  revision: "수정",
  reorder: "재주문",
  delivery: "배송",
  payment: "결제",
  inquiry: "문의",
  advertisement: "광고",
  other: "기타"
};

const COMMITMENT_LABELS: Record<string, string> = {
  confirmed: "제작 확정",
  unconfirmed: "미확정",
  unclear: "불명확"
};

function categoryLabel(category?: string | null) {
  if (!category) return "미분석";
  return CATEGORY_LABELS[category] ?? category;
}

function requestTypeLabel(requestType: string) {
  return REQUEST_TYPE_LABELS[requestType] ?? requestType;
}

function commitmentLabel(status?: string | null) {
  if (!status) return "미확인";
  return COMMITMENT_LABELS[status] ?? status;
}

function confidenceLabel(confidence?: number | null) {
  if (confidence == null) return "미확인";

  const percent = Math.round(confidence * 100);

  if (confidence >= 0.85) {
    return `${percent}% · 높음`;
  }

  if (confidence >= 0.65) {
    return `${percent}% · 보통`;
  }

  return `${percent}% · 낮음`;
}

function priceEvidence(item: MailItem) {
  const price = item.evidence?.price;
  if (!price || typeof price !== "object") return null;
  const data = price as Record<string, unknown>;
  const source = String(data.source || data.type || "").toLowerCase();
  const labels: Record<string, string> = {
    history: "기존 견적서",
    price_table: "단가표 DB",
    mail: "메일 원문",
    manual: "직접 입력",
    unresolved: "미확정"
  };
  return {
    label: labels[source] || String(data.source || data.type || "가격 근거"),
    reference: typeof data.reference === "string" ? data.reference : "",
    reason: typeof data.reason === "string" ? data.reason : "",
    score: typeof data.score === "number" ? data.score : null
  };
}

const NAV_ITEMS = [
  { key: "mail", label: "이메일", icon: Inbox },
  { key: "review", label: "검토 필요", icon: AlertTriangle },
  { key: "draft", label: "견적서", icon: FileSpreadsheet },
  { key: "settings", label: "설정", icon: Settings }
] as const;

type ViewKey = (typeof NAV_ITEMS)[number]["key"];

function money(value?: number | null) {
  return value == null ? "-" : `${value.toLocaleString("ko-KR")}원`;
}

function formatDate(value?: string | null) {
  if (!value) return "날짜 미확인";
  return new Date(value).toLocaleString("ko-KR", { dateStyle: "short", timeStyle: "short" });
}

function statusClass(status: string) {
  return `status status-${status.toLowerCase().replaceAll("_", "-")}`;
}

function App() {
  const [view, setView] = useState<ViewKey>("mail");
  const [mails, setMails] = useState<MailListItem[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [mail, setMail] = useState<MailDetail | null>(null);
  const [prices, setPrices] = useState<PriceCandidate[]>([]);
  const [history, setHistory] = useState<HistoryCandidate[]>([]);
  const [companyHistory, setCompanyHistory] = useState<HistoryCandidate[]>([]);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [loading, setLoading] = useState(false);
  const [bulkAnalyzing, setBulkAnalyzing] = useState(false);
  const [analyzingIds, setAnalyzingIds] = useState<Set<number>>(new Set());
  const [notice, setNotice] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [search, setSearch] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const autoSyncingRef = useRef(false);

  const statusFilter = view === "review" ? "REVIEW_REQUIRED" : undefined;

  async function loadMails(keepSelection = true) {
    try {
      const data = await api.listMails(statusFilter, search || undefined);
      setMails(data);
      if (!keepSelection || !selectedId || !data.some((item) => item.id === selectedId)) {
        setSelectedId(data[0]?.id ?? null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function loadMail(id: number) {
    setLoading(true);
    setError("");
    try {
      const detail = await api.getMail(id);
      setMail(detail);
      const [priceData, historyData, companyHistoryData] = await Promise.all([
        api.prices(id),
        api.history(id),
        api.companyHistory(id)
      ]);
      setPrices(priceData);
      setHistory(historyData);
      setCompanyHistory(companyHistoryData);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  async function toggleMailStar(item: MailListItem) {
    const starred = !item.starred;
    setMails((current) => current.map((row) => row.id === item.id ? { ...row, starred } : row));
    if (mail?.id === item.id) setMail({ ...mail, starred });

    try {
      const updated = await api.setMailStar(item.id, starred);
      setMails((current) => current.map((row) => row.id === item.id ? { ...row, starred: updated.starred } : row));
      setMail((current) => current?.id === item.id ? { ...current, starred: updated.starred } : current);

      // 별표 변경 직후 다음 받은편지함의 나머지 중요 표시 상태도 자동으로 맞춘다.
      try {
        await api.syncMails(50);
        await loadMails();
      } catch (syncError) {
        // 해당 별표는 이미 다음 서버에 저장됐으므로 되돌리지 않고 동기화 오류만 알린다.
        setError(syncError instanceof Error ? syncError.message : String(syncError));
      }
    } catch (err) {
      setMails((current) => current.map((row) => row.id === item.id ? { ...row, starred: item.starred } : row));
      setMail((current) => current?.id === item.id ? { ...current, starred: item.starred } : current);
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function loadDrafts() {
    try {
      setDrafts(await api.listDrafts());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  useEffect(() => {
    if (view === "draft") loadDrafts();
    else if (view !== "settings") loadMails(false);
  }, [view]);

  useEffect(() => {
    if (selectedId && view !== "draft" && view !== "settings") loadMail(selectedId);
    else setMail(null);
  }, [selectedId, view]);

  useEffect(() => {
    if (view === "draft" || view === "settings") return;

    async function autoSyncMails() {
      if (document.hidden || autoSyncingRef.current) return;
      autoSyncingRef.current = true;
      try {
        await api.syncMails(50);
        await loadMails();
      } catch {
        // 자동 동기화 실패는 다음 주기에 다시 시도하고, 수동 작업을 방해하지 않는다.
      } finally {
        autoSyncingRef.current = false;
      }
    }

    const intervalId = window.setInterval(autoSyncMails, 3 * 60 * 1000);
    const handleVisibilityChange = () => {
      if (!document.hidden) autoSyncMails();
    };
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      window.clearInterval(intervalId);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [view, search, selectedId]);

  const blocking = useMemo(
    () => mail?.reviews.filter((issue) => !issue.resolved && issue.severity === "blocking") ?? [],
    [mail]
  );

  function showNotice(message: string) {
    setNotice(message);
    window.setTimeout(() => setNotice(""), 3500);
  }

  async function runAction(action: () => Promise<unknown>, success: string, refresh = true) {
    setLoading(true);
    setError("");
    try {
      await action();
      showNotice(success);
      if (refresh && selectedId) {
        await loadMails();
        await loadMail(selectedId);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  async function uploadEml(files: FileList | null) {
    if (!files?.length) return;
    await runAction(() => api.uploadEml(Array.from(files)), `${files.length}개 EML을 가져왔습니다.`, false);
    await loadMails(false);
  }

  async function analyzeAllNewMails() {
    if (bulkAnalyzing) return;

    setBulkAnalyzing(true);
    setError("");
    let completed = 0;
    let failed = 0;

    try {
      // 검색어와 현재 화면 필터에 관계없이 전체 신규 메일을 가져온다.
      const allMails = await api.listMails();
      const pending = allMails.filter((item) => item.status === "NEW");

      if (!pending.length) {
        showNotice("분석할 신규 메일이 없습니다.");
        return;
      }

      for (const item of pending) {
        setAnalyzingIds((current) => new Set(current).add(item.id));
        setMails((current) => current.map((row) => row.id === item.id ? { ...row, status: "ANALYZING" } : row));

        try {
          const analyzed = await api.analyzeMail(item.id);
          completed += 1;
          setMails((current) => current.map((row) => row.id === item.id ? analyzed : row));
          if (selectedId === item.id) setMail(analyzed);
        } catch {
          failed += 1;
        } finally {
          setAnalyzingIds((current) => {
            const next = new Set(current);
            next.delete(item.id);
            return next;
          });
        }
      }

      await loadMails();
      if (selectedId) await loadMail(selectedId);
      showNotice(`신규 메일 ${completed}건 분석 완료${failed ? ` · 실패 ${failed}건` : ""}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setAnalyzingIds(new Set());
      setBulkAnalyzing(false);
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">YM</div>
          <div>
            <strong>YullinMoon</strong>
            <span>AI 견적 업무 보조</span>
          </div>
        </div>
        <nav>
          {NAV_ITEMS.map(({ key, label, icon: Icon }) => (
            <button key={key} className={view === key ? "nav-item active" : "nav-item"} onClick={() => setView(key)}>
              <Icon size={19} />
              <span>{label}</span>
              {key === "review" && mails.filter((item) => item.status === "REVIEW_REQUIRED").length > 0 && (
                <b className="nav-count">{mails.filter((item) => item.status === "REVIEW_REQUIRED").length}</b>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-note">
          <AlertTriangle size={17} />
          누락·충돌이 있는 메일은 자동 견적에서 제외됩니다.
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div>
            <h1>{NAV_ITEMS.find((item) => item.key === view)?.label}</h1>
            <p>{view === "mail" ? "고객 메일, AI 분석, 가격 근거를 한 화면에서 검토합니다." : view === "review" ? "필수정보가 누락된 메일만 모아 처리합니다." : view === "draft" ? "생성·승인·발송 상태를 관리합니다." : "초기 데이터와 연결 상태를 설정합니다."}</p>
          </div>
          <div className="top-actions">
            {(view === "mail" || view === "review") && (
              <>
                <input ref={fileRef} type="file" accept=".eml" multiple hidden onChange={(event) => uploadEml(event.target.files)} />
                <button className="button secondary" onClick={() => fileRef.current?.click()}><Upload size={17} /> EML 가져오기</button>
                <button className="button primary" onClick={() => runAction(() => api.syncMails(50), "메일 동기화가 완료되었습니다.")}><RefreshCw size={17} /> 메일 동기화</button>
              </>
            )}
          </div>
        </header>

        {notice && <div className="toast success"><CheckCircle2 size={18} />{notice}</div>}
        {error && <div className="toast error"><XCircle size={18} />{error}<button onClick={() => setError("")}>×</button></div>}

        {view === "draft" ? (
          <DraftView drafts={drafts} reload={loadDrafts} runAction={runAction} />
        ) : view === "settings" ? (
          <SettingsView runAction={runAction} />
        ) : (
          <div className="workbench">
            <section className="mail-column panel">
              <div className="panel-header">
                <div>
                  <strong>{view === "review" ? "검토 대기 메일" : "받은 메일"}</strong>
                  <span>{mails.length}건</span>
                </div>
                <div className="panel-actions">
                  {view === "mail" && <button className="button secondary compact bulk-analyze-button" disabled={bulkAnalyzing} onClick={analyzeAllNewMails}>{bulkAnalyzing ? <Loader2 className="spin" size={14} /> : <Sparkles size={14} />} 전체 분석</button>}
                  <button className="icon-button" onClick={() => loadMails()} title="새로고침"><RefreshCw size={17} /></button>
                </div>
              </div>
              <div className="search-box"><Search size={16} /><input value={search} onChange={(e) => setSearch(e.target.value)} onKeyDown={(e) => e.key === "Enter" && loadMails(false)} placeholder="기관, 담당자, 제목 검색" /></div>
              <div className="mail-list">
                {mails.map((item) => (
                  <div key={item.id} className={selectedId === item.id ? "mail-card selected" : "mail-card"} role="button" tabIndex={0} onClick={() => setSelectedId(item.id)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") setSelectedId(item.id); }}>
                    <div className="mail-card-top"><span className="mail-status-wrap"><button className={item.starred ? "mail-star starred" : "mail-star"} onClick={(event) => { event.stopPropagation(); toggleMailStar(item); }} aria-label={item.starred ? "별표 해제" : "별표 표시"} title={item.starred ? "별표 해제" : "별표 표시"}><Star size={16} fill={item.starred ? "currentColor" : "none"} /></button><span className={statusClass(item.status)}>{STATUS_LABELS[item.status]}</span>{(item.status === "ANALYZING" || analyzingIds.has(item.id)) && <Loader2 className="spin mail-loading" size={14} />}</span><time>{formatDate(item.outer_sent_at || item.original_sent_at)}</time></div>
                    <strong>{item.original_subject || item.outer_subject || "제목 없음"}</strong>
                    <p>{item.customer_organization || item.original_sender_name || item.original_sender_email || "고객 미확인"}</p>
                    <small>{item.summary || "아직 분석되지 않은 메일입니다."}</small>
                  </div>
                ))}
                {!mails.length && <div className="empty-state"><Inbox size={32} /><p>표시할 메일이 없습니다.</p></div>}
              </div>
            </section>

            <section className="mail-view panel">
              {loading && !mail ? <Loading /> : mail ? <OriginalMail mail={mail} /> : <EmptySelect />}
            </section>

            <section className="analysis-view panel">
              {mail ? (
                <AnalysisPanel
                  mail={mail}
                  prices={prices}
                  blocking={blocking}
                  onAnalyze={() => runAction(() => api.analyzeMail(mail.id), "AI 분석이 완료되었습니다.")}
                  onSave={(payload) => runAction(() => api.saveAnalysis(mail.id, payload), "분석 내용을 저장했습니다.")}
                  onResolve={(issue, value) => runAction(() => api.resolveReview(issue.id, value), "검토 항목을 반영했습니다.")}
                  onCreate={() => runAction(() => api.createDraft(mail.id), "견적서 초안을 생성했습니다.")}
                  loading={loading}
                />
              ) : <EmptySelect />}
            </section>

            <section className="chat-view panel">
              {mail ? <ChatPanel mail={mail} onMailChanged={(updated) => { setMail(updated); loadMails(); }} /> : <EmptySelect />}
            </section>

            <section className="bottom-panel panel">
              <HistoryAndPricing companyHistory={companyHistory} history={history} prices={prices} />
            </section>
          </div>
        )}
      </main>
    </div>
  );
}

function ChatPanel({ mail, onMailChanged }: { mail: MailDetail; onMailChanged: (mail: MailDetail) => void }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [chatError, setChatError] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setMessages([]);
    setChatError("");
    api.chatMessages(mail.id).then(setMessages).catch((err) => setChatError(err instanceof Error ? err.message : String(err)));
  }, [mail.id]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function send() {
    const message = text.trim();
    if (!message || sending) return;
    setText("");
    setSending(true);
    setChatError("");
    try {
      const result = await api.sendChat(mail.id, message);
      setMessages((current) => [...current, result.user_message, result.assistant_message]);
      onMailChanged(result.mail);
    } catch (err) {
      setText(message);
      setChatError(err instanceof Error ? err.message : String(err));
    } finally {
      setSending(false);
    }
  }

  return <div className="column-content chat-content">
    <div className="panel-header sticky"><div><strong><MessageCircle size={17} /> 견적 에이전트</strong><span>대화·수정 이력 저장</span></div></div>
    <div className="chat-intro">견적 DB와 단가표를 참고해 답변합니다. “수량을 2개로 바꿔줘”처럼 말하면 현재 초안에도 반영합니다.</div>
    <div className="chat-messages">
      {!messages.length && <div className="chat-empty"><MessageCircle size={28} /><p>이 메일의 견적에 관해 질문하거나 변경을 요청해 보세요.</p></div>}
      {messages.map((message) => <div key={message.id} className={`chat-message ${message.role}`}>
        <div>{message.content}</div>
        {!!message.evidence?.length && <div className="chat-evidence">{message.evidence.slice(0, 4).map((row, index) => <span key={index}>{row.type === "history" ? "기존 견적" : row.type === "price_table" ? "단가표 DB" : row.type === "user_instruction" ? "사용자 확정" : "근거"} · {row.label}</span>)}</div>}
        <time>{formatDate(message.created_at)}</time>
      </div>)}
      {sending && <div className="chat-message assistant pending"><Loader2 className="spin" size={16} /> 답변과 변경 사항을 확인하고 있습니다.</div>}
      <div ref={endRef} />
    </div>
    {chatError && <div className="chat-error">{chatError}</div>}
    <div className="chat-input"><textarea value={text} onChange={(event) => setText(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); send(); } }} placeholder="질문 또는 변경 명령 입력" /><button className="button primary compact" onClick={send} disabled={sending || !text.trim()}>{sending ? <Loader2 className="spin" size={16} /> : <Send size={16} />} 전송</button></div>
  </div>;
}

function OriginalMail({ mail }: { mail: MailDetail }) {
  return (
    <div className="column-content">
      <div className="panel-header sticky"><div><strong>원본 고객 메일</strong><span>전달 {mail.forward_depth || 0}단계</span></div></div>
      <div className="mail-meta">
        <h2>{mail.original_subject || mail.outer_subject}</h2>
        <dl><dt>보낸 사람</dt><dd>{mail.original_sender_name} &lt;{mail.original_sender_email}&gt;</dd><dt>받는 사람</dt><dd>{mail.original_recipient || "-"}</dd><dt>요청 시각</dt><dd>{formatDate(mail.original_sent_at)}</dd></dl>
      </div>
      <article className="mail-body">{mail.original_body || "본문이 없습니다."}</article>
      <div className="attachment-section">
        <h3>첨부파일 <span>{mail.attachments.length}</span></h3>
        {mail.attachments.map((attachment) => (
          <a key={attachment.id} className="attachment-card" href={`/api/mails/attachments/${attachment.id}/file`} target="_blank" rel="noreferrer">
            <FileDown size={18} /><div><strong>{attachment.filename}</strong><small>{(attachment.size_bytes / 1024).toFixed(1)}KB · {attachment.status}</small></div><ChevronRight size={17} />
          </a>
        ))}
        {!mail.attachments.length && <p className="muted">첨부파일 없음</p>}
      </div>
    </div>
  );
}

function AnalysisPanel({ mail, prices, blocking, onAnalyze, onSave, onResolve, onCreate, loading }: {
  mail: MailDetail;
  prices: PriceCandidate[];
  blocking: ReviewIssue[];
  onAnalyze: () => void;
  onSave: (payload: unknown) => void;
  onResolve: (issue: ReviewIssue, value: unknown) => void;
  onCreate: () => void;
  loading: boolean;
}) {
  const [form, setForm] = useState<MailDetail>(mail);
  useEffect(() => setForm(mail), [mail]);

  function patchItem(index: number, patch: Partial<MailItem>) {
    const items = [...form.items];
    items[index] = { ...items[index], ...patch };
    setForm({ ...form, items });
  }

  function save() {
    onSave({
      customer_organization: form.customer_organization,
      customer_department: form.customer_department,
      customer_name: form.customer_name,
      customer_phone: form.customer_phone,
      customer_email: form.customer_email,
      delivery_place: form.delivery_place,
      payment_terms: form.payment_terms,
      requested_date: form.requested_date,
      request_types: form.request_types,
      commitment_status: form.commitment_status,
      summary: form.summary,
      reason: form.reason,
      items: form.items
    });
  }

  return (
    <div className="column-content analysis-content">
      <div className="panel-header sticky"><div><strong>AI 분석 및 최종 검토</strong><span className={statusClass(mail.status)}>{STATUS_LABELS[mail.status]}</span></div><button className="button compact" onClick={onAnalyze} disabled={loading}>{loading ? <Loader2 className="spin" size={16} /> : <Sparkles size={16} />} 분석</button></div>
      <div className="analysis-result-section">
        <div className="analysis-result-title">
          <div>
            <h3>메일 분석 결과</h3>
            <p>AI가 판단한 메일 분류와 견적 업무 처리 기준입니다.</p>
          </div>

          <span
            className={
              mail.is_order_related
                ? "order-related-badge active"
                : "order-related-badge inactive"
            }
          >
            {mail.is_order_related
              ? "견적 업무 관련"
              : "견적 업무 아님"}
          </span>
        </div>

        <div className="analysis-result-grid">
          <div className="analysis-result-card">
            <span className="analysis-result-label">
              메일 분류
            </span>

            <strong>
              {categoryLabel(mail.category)}
            </strong>
          </div>

          <div className="analysis-result-card">
            <span className="analysis-result-label">
              제작 확정 상태
            </span>

            <strong>
              {commitmentLabel(mail.commitment_status)}
            </strong>
          </div>

          <div className="analysis-result-card">
            <span className="analysis-result-label">
              AI 확신도
            </span>

            <strong>
              {confidenceLabel(mail.confidence)}
            </strong>
          </div>

          <div className="analysis-result-card">
            <span className="analysis-result-label">
              메일상 전체 금액
            </span>

            <strong>
              {money(mail.total_amount)}
            </strong>
          </div>
        </div>

        <div className="analysis-detail-block">
          <span className="analysis-result-label">
            요청 유형
          </span>

          <div className="request-type-list">
            {mail.request_types.length > 0 ? (
              mail.request_types.map((requestType) => (
                <span
                  key={requestType}
                  className="request-type-chip"
                >
                  {requestTypeLabel(requestType)}
                </span>
              ))
            ) : (
              <span className="analysis-empty-text">
                확인된 요청 유형이 없습니다.
              </span>
            )}
          </div>
        </div>

        <div className="analysis-detail-block">
          <span className="analysis-result-label">
            분석 요약
          </span>

          <p className="analysis-result-text">
            {mail.summary || "분석 요약이 없습니다."}
          </p>
        </div>

        <div className="analysis-detail-block">
          <span className="analysis-result-label">
            판단 근거
          </span>

          <p className="analysis-result-text">
            {mail.reason || "판단 근거가 없습니다."}
          </p>
        </div>

        <div className="analysis-detail-block">
          <span className="analysis-result-label">
            누락 정보
          </span>

          {mail.missing_information.length > 0 ? (
            <div className="missing-information-list">
              {mail.missing_information.map(
                (information, index) => (
                  <span
                    key={`${information}-${index}`}
                    className="missing-information-chip"
                  >
                    {information}
                  </span>
                )
              )}
            </div>
          ) : (
            <p className="analysis-empty-text">
              AI가 확인한 누락 정보가 없습니다.
            </p>
          )}
        </div>
      </div>
      {mail.reviews.filter((issue) => !issue.resolved).length > 0 && (
        <div className="review-box">
          <h3><AlertTriangle size={18} /> {blocking.length > 0 ? "검토 필요" : "참고 사항"} {mail.reviews.filter((issue) => !issue.resolved).length}건</h3>
          {mail.reviews.filter((issue) => !issue.resolved).map((issue) => <ReviewRow key={issue.id} issue={issue} onResolve={onResolve} />)}
        </div>
      )}

      <div className="form-section">
        <h3>고객 정보</h3>
        <div className="form-grid two">
          <Field label="기관명" value={form.customer_organization} onChange={(value) => setForm({ ...form, customer_organization: value })} />
          <Field label="담당자" value={form.customer_name} onChange={(value) => setForm({ ...form, customer_name: value })} />
          <Field label="이메일" value={form.customer_email} onChange={(value) => setForm({ ...form, customer_email: value })} />
          <Field label="전화번호" value={form.customer_phone} onChange={(value) => setForm({ ...form, customer_phone: value })} />
          <Field label="납품 장소" value={form.delivery_place} onChange={(value) => setForm({ ...form, delivery_place: value })} />
          <Field label="희망 일정" value={form.requested_date} onChange={(value) => setForm({ ...form, requested_date: value })} />
        </div>
      </div>

      <div className="form-section">
        <div className="section-title"><h3>주문 품목</h3><button className="text-button" onClick={() => setForm({ ...form, items: [...form.items, { product_name: "", evidence: {} }] })}>+ 품목 추가</button></div>
        {form.items.map((item, index) => (
          <div className="item-editor" key={item.id ?? `new-${index}`}>
            <div className="item-number">{index + 1}</div>
            <div className="form-grid two">
              <Field label="품목" value={item.product_name} onChange={(value) => patchItem(index, { product_name: value })} />
              <Field label="규격 설명" value={item.specification} onChange={(value) => patchItem(index, { specification: value })} />
              <NumberField label="가로(mm)" value={item.width_mm} onChange={(value) => patchItem(index, { width_mm: value })} />
              <NumberField label="세로(mm)" value={item.height_mm} onChange={(value) => patchItem(index, { height_mm: value })} />
              <NumberField label="수량" value={item.quantity} onChange={(value) => patchItem(index, { quantity: value })} />
              <Field label="단위" value={item.unit} onChange={(value) => patchItem(index, { unit: value })} />
              <Field label="용지" value={item.paper} onChange={(value) => patchItem(index, { paper: value })} />
              <Field label="단면·양면" value={item.print_sides} onChange={(value) => patchItem(index, { print_sides: value })} />
              <Field label="재질" value={item.material} onChange={(value) => patchItem(index, { material: value })} />
              <NumberField label="확정 단가" value={item.unit_price} onChange={(value) => patchItem(index, { unit_price: value == null ? null : Math.round(value), confirmed: value != null, evidence: value == null ? item.evidence : { ...item.evidence, price: { source: "manual", type: "MANUAL", reason: "담당자가 직접 입력한 단가" } } })} />
            </div>
            {priceEvidence(item) && <div className="price-evidence"><span>단가 출처</span><strong>{priceEvidence(item)?.label}</strong>{priceEvidence(item)?.score != null && <em>점수 {priceEvidence(item)?.score?.toFixed(1)}</em>}<small title={priceEvidence(item)?.reference || priceEvidence(item)?.reason}>{priceEvidence(item)?.reference || priceEvidence(item)?.reason}</small></div>}
            <label className="field full"><span>디자인·문구 요청</span><textarea value={item.design_request || item.detail_text || ""} onChange={(e) => patchItem(index, { design_request: e.target.value })} /></label>
          </div>
        ))}
        {!form.items.length && <p className="muted">추출된 품목이 없습니다. AI 분석을 실행하거나 품목을 추가하세요.</p>}
      </div>

      <div className="form-section"><h3>분석 요약</h3><textarea className="summary-input" value={form.summary || ""} onChange={(e) => setForm({ ...form, summary: e.target.value })} /></div>
      {blocking.length > 0 && <p className="blocking-note">필수 검토 {blocking.length}건을 해결해야 견적서를 생성할 수 있습니다.</p>}
      <div className="action-bar"><button className="button secondary" onClick={save}><Save size={17} /> 수정 저장</button><button className="button primary" disabled={blocking.length > 0 || !form.items.length} onClick={onCreate}><FileSpreadsheet size={17} /> 견적서 생성</button></div>
    </div>
  );
}

function ReviewRow({ issue, onResolve }: { issue: ReviewIssue; onResolve: (issue: ReviewIssue, value: unknown) => void }) {
  const [value, setValue] = useState("");
  const suggestion = issue.suggestions[0] as Record<string, unknown> | undefined;
  const suggestedValue = suggestion && typeof suggestion === "object" ? suggestion.value : suggestion;
  const suggestionUnit = suggestion && typeof suggestion === "object" && suggestion.unit ? String(suggestion.unit) : "";
  const suggestionMessage = suggestion && typeof suggestion === "object" && suggestion.message ? String(suggestion.message) : "";
  return (
    <div className={`review-row ${issue.severity}`}>
      <div><strong>{issue.message}</strong><small>{issue.code}</small></div>
      <div className="review-resolve">
        {suggestedValue != null && <button className="suggestion-chip" title={suggestionMessage} onClick={() => onResolve(issue, suggestedValue)}>{suggestion?.source === "quotation_history_db" ? "최근 주문 기준 예상" : "추천"} {String(suggestedValue)}{suggestionUnit}</button>}
        <input placeholder="직접 입력" value={value} onChange={(e) => setValue(e.target.value)} />
        <button className="icon-button" disabled={!value} onClick={() => onResolve(issue, Number.isNaN(Number(value)) ? value : Number(value))}><CheckCircle2 size={17} /></button>
      </div>
    </div>
  );
}

function HistoryAndPricing({ companyHistory, history, prices }: { companyHistory: HistoryCandidate[]; history: HistoryCandidate[]; prices: PriceCandidate[] }) {
  const [tab, setTab] = useState<"company" | "history" | "price">("company");
  const historyRows = tab === "company" ? companyHistory : history;
  return (
    <div className="bottom-content">
      <div className="bottom-tabs"><button className={tab === "company" ? "active" : ""} onClick={() => setTab("company")}>동일 회사 견적 <span>{companyHistory.length}</span></button><button className={tab === "history" ? "active" : ""} onClick={() => setTab("history")}>동일 고객 과거 견적 <span>{history.length}</span></button><button className={tab === "price" ? "active" : ""} onClick={() => setTab("price")}>현재 단가 후보 <span>{prices.length}</span></button></div>
      <div className="table-wrap">
        {tab !== "price" ? (
          <table><thead><tr><th>견적일</th><th>고객</th><th>품목</th><th>규격</th><th>수량</th><th>단가</th><th>근거</th></tr></thead><tbody>{historyRows.map((row, index) => <tr key={`${row.quotation_id}-${index}`}><td>{row.quotation_date || "-"}</td><td>{row.customer_name || "-"}</td><td>{row.product_name}</td><td>{row.specification || "-"}</td><td>{row.quantity ?? "-"}</td><td>{money(row.unit_price)}</td><td title={row.source_file}>{row.source_sheet}</td></tr>)}{!historyRows.length && <tr><td colSpan={7} className="empty-cell">{tab === "company" ? "동일 회사의 과거 견적이 없습니다." : "동일 고객의 과거 견적이 없습니다."}</td></tr>}</tbody></table>
        ) : (
          <table>
  <thead>
    <tr>
      <th>품목</th>
      <th>단가</th>
      <th>총금액</th>
      <th>출처</th>
      <th>점수</th>
      <th>판정</th>
      <th>근거</th>
    </tr>
  </thead>

  <tbody>
    {prices.map((row, index) => {
      const sourceLabels: Record<string, string> = {
        history: "기존 견적",
        price_table: "단가표",
        mail: "메일",
        unresolved: "미확정"
      };

      return (
        <tr key={`${row.item_id}-${index}`}>
          <td>{row.product_name}</td>

          <td>
            {money(row.unit_price)}
          </td>

          <td>
            {money(row.amount)}
          </td>

          <td>
            {sourceLabels[row.source] ?? row.source}
          </td>

          <td>
            {row.score.toFixed(1)}
          </td>

          <td>
            <span
              className={
                row.needs_review
                  ? "match candidate"
                  : "match exact"
              }
            >
              {row.unit_price == null
                ? "미확정"
                : row.needs_review
                  ? "검토 필요"
                  : "자동 적용"}
            </span>
          </td>

          <td
            title={
              row.reference
              || row.reason
            }
          >
            {row.reference
              || row.reason}
          </td>
        </tr>
      );
    })}

    {!prices.length && (
      <tr>
        <td
          colSpan={7}
          className="empty-cell"
        >
          가격 후보가 없습니다.
        </td>
      </tr>
    )}
  </tbody>
</table>
        )}
      </div>
    </div>
  );
}

function DraftView({ drafts, reload, runAction }: { drafts: Draft[]; reload: () => Promise<void>; runAction: (action: () => Promise<unknown>, success: string, refresh?: boolean) => Promise<void> }) {
  return <div className="page-card"><div className="page-card-header"><div><h2>견적서 목록</h2><p>같은 메일에서 다시 생성하면 기존 견적서가 업데이트됩니다.</p></div><button className="icon-button" onClick={reload}><RefreshCw size={18} /></button></div><div className="draft-grid">{drafts.map((draft) => <article className="draft-card" key={draft.id}><div className="draft-top"><span className={`status status-${draft.status.toLowerCase()}`}>{draft.status}</span><small>#{draft.id}</small></div><h3>{draft.customer_name}</h3><p>{draft.items.map((item) => item.product_name).join(", ") || "품목 없음"}</p><strong>{money(draft.total_amount)}</strong><div className="draft-actions"><a className="button secondary compact" href={`/api/quotations/${draft.id}/file`}><FileDown size={16} /> Excel</a>{draft.status === "DRAFT" && <button className="button primary compact" onClick={() => runAction(() => api.approveDraft(draft.id), "견적서를 승인했습니다.", false).then(reload)}><CheckCircle2 size={16} /> 승인</button>}{draft.status === "APPROVED" && <button className="button danger compact" onClick={() => runAction(() => api.sendDraft(draft.id), "메일을 발송했습니다.", false).then(reload)}><Send size={16} /> 발송</button>}<button className="button danger compact" onClick={() => { if (window.confirm("이 견적서를 삭제할까요?")) runAction(() => api.deleteDraft(draft.id), "견적서를 삭제했습니다.", false).then(reload); }}><Trash2 size={16} /> 삭제</button></div>{draft.error_message && <small className="error-text">{draft.error_message}</small>}</article>)}{!drafts.length && <div className="empty-state wide"><Archive size={38} /><p>생성된 견적서가 없습니다.</p></div>}</div></div>;
}

function SettingsView({ runAction }: { runAction: (action: () => Promise<unknown>, success: string, refresh?: boolean) => Promise<void> }) {
  const [status, setStatus] = useState<Record<string, unknown>>({});
  const [paths, setPaths] = useState<Record<string, string>>({});
  useEffect(() => { api.settingsStatus().then(setStatus); api.settingsPaths().then(setPaths); }, []);
  return <div className="settings-layout"><section className="page-card"><h2>연결 상태</h2><div className="status-grid"><StatusTile label="OpenAI" enabled={Boolean(status.openai_configured)} /><StatusTile label="Daum 메일" enabled={Boolean(status.mail_configured)} /><StatusTile label="실제 발송" enabled={Boolean(status.live_send_enabled)} warning /></div><div className="path-list">{Object.entries(paths).map(([key, value]) => <div key={key}><span>{key}</span><code>{value || "미설정"}</code></div>)}</div></section><section className="page-card"><h2>사용자 데이터 연결</h2><div className="settings-block"><h3>현재 단가표 DB</h3><p>사용자님의 price_table.db가 가격 엔진에 정상 연결됐는지 확인합니다.</p><button className="button primary" onClick={() => runAction(() => api.importPriceTable(), "단가표 DB 연결을 확인했습니다.", false)}><FileSpreadsheet size={17} /> 단가표 DB 확인</button></div><div className="settings-block"><h3>기존 견적 이력 DB</h3><p>사용자님의 quotation_history.db가 가격 엔진에 정상 연결됐는지 확인합니다.</p><button className="button primary" onClick={() => runAction(() => api.importHistory(""), "견적 이력 DB 연결을 확인했습니다.", false)}><Archive size={17} /> 견적 이력 DB 확인</button></div></section></div>;
}

function StatusTile({ label, enabled, warning = false }: { label: string; enabled: boolean; warning?: boolean }) { return <div className={`status-tile ${enabled ? (warning ? "warning" : "enabled") : "disabled"}`}>{enabled ? <CheckCircle2 size={22} /> : <XCircle size={22} />}<div><strong>{label}</strong><span>{enabled ? "설정됨" : "미설정"}</span></div></div>; }
function Field({ label, value, onChange }: { label: string; value?: string | null; onChange: (value: string) => void }) { return <label className="field"><span>{label}</span><input value={value || ""} onChange={(e) => onChange(e.target.value)} /></label>; }
function NumberField({ label, value, onChange }: { label: string; value?: number | null; onChange: (value: number | null) => void }) { return <label className="field"><span>{label}</span><input type="number" value={value ?? ""} onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} /></label>; }
function Loading() { return <div className="empty-state"><Loader2 className="spin" size={36} /><p>불러오는 중입니다.</p></div>; }
function EmptySelect() { return <div className="empty-state"><MailCheck size={38} /><p>왼쪽에서 메일을 선택하세요.</p></div>; }

export default App;
