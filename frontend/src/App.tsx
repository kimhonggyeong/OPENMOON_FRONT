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
  Maximize2,
  Minimize2,
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
import type {
  AgentKnowledge,
  AgentMemory,
  ChatMessage,
  Draft,
  HistoryCandidate,
  MailDetail,
  MailItem,
  MailListItem,
  PriceCandidate,
  ReviewIssue
} from "./types";

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

const NAV_ITEMS = [
  { key: "mail", label: "이메일", icon: Inbox },
  { key: "review", label: "검토 필요", icon: AlertTriangle },
  { key: "draft", label: "견적서", icon: FileSpreadsheet },
  { key: "settings", label: "설정", icon: Settings }
] as const;

type ViewKey = (typeof NAV_ITEMS)[number]["key"];

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
  if (confidence >= 0.85) return `${percent}% · 높음`;
  if (confidence >= 0.65) return `${percent}% · 보통`;
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

function money(value?: number | null) {
  return value == null ? "-" : `${value.toLocaleString("ko-KR")}원`;
}

function supplyAmount(item: MailItem) {
  if (item.quantity != null && item.unit_price != null) {
    return Math.round(Number(item.quantity) * Number(item.unit_price));
  }
  return item.amount ?? null;
}

function quoteTotal(items: MailItem[]) {
  const values = items
    .map(supplyAmount)
    .filter((value): value is number => value != null);
  if (!values.length) return null;
  return values.reduce((sum, value) => sum + value, 0);
}

function formatDate(value?: string | null) {
  if (!value) return "날짜 미확인";
  return new Date(value).toLocaleString("ko-KR", {
    dateStyle: "short",
    timeStyle: "short"
  });
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
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
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
    } catch (err) {
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
    if (view === "draft") void loadDrafts();
    else if (view !== "settings") void loadMails(false);
  }, [view]);

  useEffect(() => {
    if (selectedId && view !== "draft" && view !== "settings") void loadMail(selectedId);
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
        // 다음 주기에 다시 시도합니다.
      } finally {
        autoSyncingRef.current = false;
      }
    }

    const intervalId = window.setInterval(autoSyncMails, 3 * 60 * 1000);
    const handleVisibilityChange = () => {
      if (!document.hidden) void autoSyncMails();
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
      const allMails = await api.listMails();
      const pending = allMails.filter((item) => item.status === "NEW");
      if (!pending.length) {
        showNotice("분석할 신규 메일이 없습니다.");
        return;
      }
      for (const item of pending) {
        setAnalyzingIds((current) => new Set(current).add(item.id));
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
          <div><strong>YullinMoon</strong><span>AI 견적 업무 보조</span></div>
        </div>
        <nav>
          {NAV_ITEMS.map(({ key, label, icon: Icon }) => (
            <button key={key} className={view === key ? "nav-item active" : "nav-item"} onClick={() => setView(key)}>
              <Icon size={19} /><span>{label}</span>
              {key === "review" && mails.filter((item) => item.status === "REVIEW_REQUIRED").length > 0 && (
                <b className="nav-count">{mails.filter((item) => item.status === "REVIEW_REQUIRED").length}</b>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-note"><AlertTriangle size={17} />누락·충돌이 있는 메일은 자동 견적에서 제외됩니다.</div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div>
            <h1>{NAV_ITEMS.find((item) => item.key === view)?.label}</h1>
            <p>{view === "mail" ? "고객 메일, AI 분석, 가격 근거를 한 화면에서 검토합니다." : view === "review" ? "필수정보가 누락된 메일만 모아 처리합니다." : view === "draft" ? "생성·승인·발송 상태를 관리합니다." : "Agent 지식, 기억과 연결 상태를 설정합니다."}</p>
          </div>
          <div className="top-actions">
            {(view === "mail" || view === "review") && (
              <>
                <input ref={fileRef} type="file" accept=".eml" multiple hidden onChange={(event) => void uploadEml(event.target.files)} />
                <button className="button secondary" onClick={() => fileRef.current?.click()}><Upload size={17} /> EML 가져오기</button>
                <button className="button primary" onClick={() => void runAction(() => api.syncMails(50), "메일 동기화가 완료되었습니다.")}><RefreshCw size={17} /> 메일 동기화</button>
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
                <div><strong>{view === "review" ? "검토 대기 메일" : "받은 메일"}</strong><span>{mails.length}건</span></div>
                <div className="panel-actions">
                  {view === "mail" && <button className="button secondary compact bulk-analyze-button" disabled={bulkAnalyzing} onClick={() => void analyzeAllNewMails()}>{bulkAnalyzing ? <Loader2 className="spin" size={14} /> : <Sparkles size={14} />} 전체 분석</button>}
                  <button className="icon-button" onClick={() => void loadMails()} title="새로고침"><RefreshCw size={17} /></button>
                </div>
              </div>
              <div className="search-box"><Search size={16} /><input value={search} onChange={(event) => setSearch(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void loadMails(false); }} placeholder="기관, 담당자, 제목 검색" /></div>
              <div className="mail-list">
                {mails.map((item) => (
                  <div key={item.id} className={selectedId === item.id ? "mail-card selected" : "mail-card"} role="button" tabIndex={0} onClick={() => setSelectedId(item.id)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") setSelectedId(item.id); }}>
                    <div className="mail-card-top">
                      <span className="mail-status-wrap">
                        <button className={item.starred ? "mail-star starred" : "mail-star"} onClick={(event) => { event.stopPropagation(); void toggleMailStar(item); }} aria-label={item.starred ? "별표 해제" : "별표 표시"}><Star size={16} fill={item.starred ? "currentColor" : "none"} /></button>
                        <span className={statusClass(item.status)}>{STATUS_LABELS[item.status]}</span>
                        {(item.status === "ANALYZING" || analyzingIds.has(item.id)) && <Loader2 className="spin mail-loading" size={14} />}
                      </span>
                      <time>{formatDate(item.outer_sent_at || item.original_sent_at)}</time>
                    </div>
                    <strong>{item.original_subject || item.outer_subject || "제목 없음"}</strong>
                    <p>{item.customer_organization || item.original_sender_name || item.original_sender_email || "고객 미확인"}</p>
                    <small>{item.summary || "아직 분석되지 않은 메일입니다."}</small>
                  </div>
                ))}
                {!mails.length && <div className="empty-state"><Inbox size={32} /><p>표시할 메일이 없습니다.</p></div>}
              </div>
            </section>

            <section className="mail-view panel">{loading && !mail ? <Loading /> : mail ? <OriginalMail mail={mail} /> : <EmptySelect />}</section>
            <section className="analysis-view panel">
              {mail ? <AnalysisPanel mail={mail} blocking={blocking} onAnalyze={() => void runAction(() => api.analyzeMail(mail.id), "AI 분석이 완료되었습니다.")} onSave={(payload) => void runAction(() => api.saveAnalysis(mail.id, payload), "분석 내용을 저장했습니다.")} onResolve={(issue, value) => void runAction(() => api.resolveReview(issue.id, value), "검토 항목을 반영했습니다.")} onCreate={() => void runAction(() => api.createDraft(mail.id), "견적서 초안을 생성했습니다.")} loading={loading} /> : <EmptySelect />}
            </section>
            <section className="chat-view panel">{mail ? <ChatPanel mail={mail} onMailChanged={(updated) => { setMail(updated); void loadMails(); }} /> : <EmptySelect />}</section>
            <section className="bottom-panel panel"><HistoryAndPricing companyHistory={companyHistory} history={history} prices={prices} /></section>
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
  const [chatNotice, setChatNotice] = useState("");
  const [openingKey, setOpeningKey] = useState("");
  const [expanded, setExpanded] = useState(false);
  const [quoteExpanded, setQuoteExpanded] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setMessages([]);
    setChatError("");
    setChatNotice("");
    setExpanded(false);
    setQuoteExpanded(false);
    api.chatMessages(mail.id).then(setMessages).catch((err) => setChatError(err instanceof Error ? err.message : String(err)));
  }, [mail.id]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && expanded) setExpanded(false);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [expanded]);

  async function send() {
    const message = text.trim();
    if (!message || sending) return;
    setText("");
    setSending(true);
    setChatError("");
    setChatNotice("");
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

  async function openPriceLocation(sheet?: string | null, cell?: string | null, key = "price") {
    if (openingKey) return;
    setOpeningKey(key);
    setChatError("");
    setChatNotice("");
    try {
      const result = await api.openPriceSource(sheet || null, cell || null);
      const suffix = [result.sheet, result.cell].filter(Boolean).join(" / ");
      if (result.mode === "excel_com") {
        setChatNotice(result.warning || (suffix ? `Excel에서 단가표를 열었습니다: ${suffix}` : "Excel에서 단가표를 열었습니다."));
      } else if (result.mode === "default_viewer") {
        setChatNotice(result.warning || "기본 XLSX 뷰어로 단가표 파일을 열었습니다.");
      } else if (result.mode === "file_explorer") {
        setChatNotice(result.warning || "XLSX 연결 프로그램이 없어 파일 위치를 열었습니다.");
      } else {
        setChatNotice(result.warning || (suffix ? `단가표를 열었습니다: ${suffix}` : "단가표 파일을 열었습니다."));
      }
    } catch (err) {
      setChatError(err instanceof Error ? err.message : String(err));
    } finally {
      setOpeningKey("");
    }
  }

  function evidenceTitle(type?: string) {
    if (type === "price_table") return "단가표";
    if (type === "price") return "가격 후보";
    if (type === "history") return "과거 견적";
    if (type === "knowledge") return "회사 지식";
    if (type === "memory") return "장기기억";
    if (type === "memory_saved") return "기억 저장";
    if (type === "agent_action") return "견적 변경";
    if (type === "quotation") return "견적서";
    if (type === "excel_opened") return "가격표";
    if (type === "user_instruction") return "사용자 확정";
    return "확인 근거";
  }

  function renderEvidence(message: ChatMessage) {
    if (!message.evidence?.length) return null;
    return (
      <div className="agent-evidence-list">
        {message.evidence.slice(0, 8).map((row, index) => {
          const locations = Array.isArray(row.locations) ? row.locations.filter((location) => location?.sheet || location?.cell) : [];
          const preview = Array.isArray(row.preview) ? row.preview.filter(Boolean).slice(0, expanded ? 5 : 3) : [];
          const canOpen = row.type === "price_table" || row.type === "price" || row.type === "excel_opened";
          return (
            <div className={`agent-evidence-card evidence-${row.type || "default"}`} key={`${message.id}-${index}`}>
              <div className="agent-evidence-head"><strong>{evidenceTitle(row.type)}</strong>{typeof row.count === "number" && <span>{row.count}건</span>}</div>
              <p>{row.label || "Agent가 업무 자료를 확인했습니다."}</p>
              {preview.length > 0 && <div className="agent-evidence-preview">{preview.map((value, previewIndex) => <span key={previewIndex}>{value}</span>)}</div>}
              {locations.length > 0 && (
                <div className="agent-location-list">
                  {locations.slice(0, expanded ? 6 : 3).map((location, locationIndex) => {
                    const locationKey = `${message.id}-${index}-${locationIndex}`;
                    return (
                      <div className="agent-location-row" key={locationKey}>
                        <span>{location.sheet || "단가표"}{location.cell ? ` / ${location.cell}` : ""}</span>
                        {canOpen && <button type="button" className="agent-open-excel" disabled={Boolean(openingKey)} onClick={() => void openPriceLocation(location.sheet, location.cell, locationKey)}>{openingKey === locationKey ? <Loader2 className="spin" size={13} /> : <FileSpreadsheet size={13} />} 열기</button>}
                      </div>
                    );
                  })}
                </div>
              )}
              {canOpen && locations.length === 0 && row.source_file && (
                <button type="button" className="agent-open-excel standalone" disabled={Boolean(openingKey)} onClick={() => void openPriceLocation(null, null, `${message.id}-${index}-file`)}><FileSpreadsheet size={13} /> 가격표 파일 열기</button>
              )}
            </div>
          );
        })}
      </div>
    );
  }

  const total = quoteTotal(mail.items);

  return (
    <>
      {expanded && <button className="agent-expand-backdrop" aria-label="에이전트 축소" onClick={() => setExpanded(false)} />}
      <div className={`column-content chat-content ${expanded ? "agent-expanded" : ""}`}>
        <div className="panel-header sticky agent-header">
          <div className="agent-header-title">
            <strong><MessageCircle size={17} /> 견적 에이전트</strong>
            <span>회사 지식·기억·과거 견적·단가표</span>
          </div>
          <div className="agent-header-actions">
            <button
              type="button"
              className="agent-toolbar-button"
              disabled={Boolean(openingKey)}
              onClick={() => void openPriceLocation(null, null, "toolbar-price-file")}
              title="원본 단가표 파일 열기"
            >
              {openingKey === "toolbar-price-file" ? <Loader2 className="spin" size={14} /> : <FileSpreadsheet size={14} />}
              가격표 열기
            </button>
            <button type="button" className="icon-button" onClick={() => setExpanded((value) => !value)} title={expanded ? "에이전트 축소" : "에이전트 크게 보기"}>
              {expanded ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
            </button>
          </div>
        </div>

        {!!mail.items.length && (
          <div className={`agent-quote-preview ${quoteExpanded ? "open" : "collapsed"}`}>
            <button type="button" className="agent-quote-summary" onClick={() => setQuoteExpanded((value) => !value)}>
              <span><strong>현재 견적</strong><small>{mail.items.length}개 품목</small></span>
              <span><b>{money(total)}</b><small>{quoteExpanded ? "접기" : "상세"}</small></span>
            </button>
            {quoteExpanded && (
              <>
                <div className="agent-quote-items">
                  {mail.items.slice(0, expanded ? 10 : 4).map((item, index) => (
                    <div className="agent-quote-row" key={item.id ?? index}>
                      <div><strong>{item.product_name || `품목 ${index + 1}`}</strong><small>{item.specification || [item.width_mm, item.height_mm].filter(Boolean).join(" × ") || "규격 미확인"}</small></div>
                      <span>{item.quantity ?? "-"}{item.unit || ""}</span><span>{money(item.unit_price)}</span><b>{money(supplyAmount(item))}</b>
                    </div>
                  ))}
                </div>
                <div className="agent-quote-total"><span>견적 합계</span><strong>{money(total)}</strong></div>
              </>
            )}
          </div>
        )}

        <div className="chat-messages">
          {!messages.length && <div className="chat-empty"><MessageCircle size={28} /><p>견적, 과거 이력, 단가표, 재질을 질문하거나 변경을 요청해 보세요.</p></div>}
          {messages.map((message) => (
            <div key={message.id} className={`chat-message ${message.role}`}>
              <div className="chat-message-body">{message.content}</div>
              {message.role === "assistant" && renderEvidence(message)}
              <time>{formatDate(message.created_at)}</time>
            </div>
          ))}
          {sending && <div className="chat-message assistant pending"><Loader2 className="spin" size={16} /> 자료를 확인하고 있습니다.</div>}
          <div ref={endRef} />
        </div>

        {chatNotice && <div className="chat-notice"><CheckCircle2 size={14} />{chatNotice}</div>}
        {chatError && <div className="chat-error">{chatError}</div>}

        <div className="chat-input">
          <textarea value={text} onChange={(event) => setText(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void send(); } }} placeholder="질문 또는 변경 명령 입력" />
          <button className="button primary compact" onClick={() => void send()} disabled={sending || !text.trim()}>{sending ? <Loader2 className="spin" size={16} /> : <Send size={16} />} 전송</button>
        </div>
      </div>
    </>
  );
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

function AnalysisPanel({ mail, blocking, onAnalyze, onSave, onResolve, onCreate, loading }: {
  mail: MailDetail;
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
    const current = items[index];
    items[index] = { ...current, ...patch };
    const updated = items[index];
    if (updated.quantity != null && updated.unit_price != null) {
      updated.amount = Math.round(Number(updated.quantity) * Number(updated.unit_price));
    }
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
        <div className="analysis-result-title"><div><h3>메일 분석 결과</h3><p>AI가 판단한 메일 분류와 견적 업무 처리 기준입니다.</p></div><span className={mail.is_order_related ? "order-related-badge active" : "order-related-badge inactive"}>{mail.is_order_related ? "견적 업무 관련" : "견적 업무 아님"}</span></div>
        <div className="analysis-result-grid">
          <div className="analysis-result-card"><span className="analysis-result-label">메일 분류</span><strong>{categoryLabel(mail.category)}</strong></div>
          <div className="analysis-result-card"><span className="analysis-result-label">제작 확정 상태</span><strong>{commitmentLabel(mail.commitment_status)}</strong></div>
          <div className="analysis-result-card"><span className="analysis-result-label">AI 확신도</span><strong>{confidenceLabel(mail.confidence)}</strong></div>
          <div className="analysis-result-card"><span className="analysis-result-label">메일상 전체 금액</span><strong>{money(mail.total_amount)}</strong></div>
        </div>
        <div className="analysis-detail-block"><span className="analysis-result-label">요청 유형</span><div className="request-type-list">{mail.request_types.length > 0 ? mail.request_types.map((type) => <span key={type} className="request-type-chip">{requestTypeLabel(type)}</span>) : <span className="analysis-empty-text">확인된 요청 유형이 없습니다.</span>}</div></div>
        <div className="analysis-detail-block"><span className="analysis-result-label">분석 요약</span><p className="analysis-result-text">{mail.summary || "분석 요약이 없습니다."}</p></div>
        <div className="analysis-detail-block"><span className="analysis-result-label">판단 근거</span><p className="analysis-result-text">{mail.reason || "판단 근거가 없습니다."}</p></div>
        <div className="analysis-detail-block"><span className="analysis-result-label">누락 정보</span>{mail.missing_information.length > 0 ? <div className="missing-information-list">{mail.missing_information.map((information, index) => <span key={`${information}-${index}`} className="missing-information-chip">{information}</span>)}</div> : <p className="analysis-empty-text">AI가 확인한 누락 정보가 없습니다.</p>}</div>
      </div>

      {mail.reviews.filter((issue) => !issue.resolved).length > 0 && (
        <div className="review-box"><h3><AlertTriangle size={18} /> {blocking.length > 0 ? "검토 필요" : "참고 사항"} {mail.reviews.filter((issue) => !issue.resolved).length}건</h3>{mail.reviews.filter((issue) => !issue.resolved).map((issue) => <ReviewRow key={issue.id} issue={issue} onResolve={onResolve} />)}</div>
      )}

      <div className="form-section"><h3>고객 정보</h3><div className="form-grid two"><Field label="기관명" value={form.customer_organization} onChange={(value) => setForm({ ...form, customer_organization: value })} /><Field label="담당자" value={form.customer_name} onChange={(value) => setForm({ ...form, customer_name: value })} /><Field label="이메일" value={form.customer_email} onChange={(value) => setForm({ ...form, customer_email: value })} /><Field label="전화번호" value={form.customer_phone} onChange={(value) => setForm({ ...form, customer_phone: value })} /><Field label="납품 장소" value={form.delivery_place} onChange={(value) => setForm({ ...form, delivery_place: value })} /><Field label="희망 일정" value={form.requested_date} onChange={(value) => setForm({ ...form, requested_date: value })} /></div></div>

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
              <ReadOnlyField label="공급금액" value={money(supplyAmount(item))} />
            </div>
            {priceEvidence(item) && <div className="price-evidence"><span>단가 출처</span><strong>{priceEvidence(item)?.label}</strong>{priceEvidence(item)?.score != null && <em>점수 {priceEvidence(item)?.score?.toFixed(1)}</em>}<small title={priceEvidence(item)?.reference || priceEvidence(item)?.reason}>{priceEvidence(item)?.reference || priceEvidence(item)?.reason}</small></div>}
            <label className="field full"><span>디자인·문구 요청</span><textarea value={item.design_request || item.detail_text || ""} onChange={(event) => patchItem(index, { design_request: event.target.value })} /></label>
          </div>
        ))}
        {!form.items.length && <p className="muted">추출된 품목이 없습니다. AI 분석을 실행하거나 품목을 추가하세요.</p>}
        {!!form.items.length && <div className="analysis-quote-total"><span>분석 견적 합계</span><strong>{money(quoteTotal(form.items))}</strong></div>}
      </div>

      <div className="form-section"><h3>분석 요약</h3><textarea className="summary-input" value={form.summary || ""} onChange={(event) => setForm({ ...form, summary: event.target.value })} /></div>
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
        <input placeholder="직접 입력" value={value} onChange={(event) => setValue(event.target.value)} />
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
          <table><thead><tr><th>품목</th><th>단가</th><th>총금액</th><th>출처</th><th>점수</th><th>판정</th><th>근거</th></tr></thead><tbody>{prices.map((row, index) => { const sourceLabels: Record<string, string> = { history: "기존 견적", price_table: "단가표", mail: "메일", unresolved: "미확정" }; return <tr key={`${row.item_id}-${index}`}><td>{row.product_name}</td><td>{money(row.unit_price)}</td><td>{money(row.amount)}</td><td>{sourceLabels[row.source] ?? row.source}</td><td>{row.score.toFixed(1)}</td><td><span className={row.needs_review ? "match candidate" : "match exact"}>{row.unit_price == null ? "미확정" : row.needs_review ? "검토 필요" : "자동 적용"}</span></td><td title={row.reference || row.reason}>{row.reference || row.reason}</td></tr>; })}{!prices.length && <tr><td colSpan={7} className="empty-cell">가격 후보가 없습니다.</td></tr>}</tbody></table>
        )}
      </div>
    </div>
  );
}

function DraftView({ drafts, reload, runAction }: { drafts: Draft[]; reload: () => Promise<void>; runAction: (action: () => Promise<unknown>, success: string, refresh?: boolean) => Promise<void> }) {
  return (
    <div className="page-card">
      <div className="page-card-header"><div><h2>견적서 목록</h2><p>같은 메일에서 다시 생성하면 기존 견적서가 업데이트됩니다.</p></div><button className="icon-button" onClick={() => void reload()}><RefreshCw size={18} /></button></div>
      <div className="draft-grid">
        {drafts.map((draft) => (
          <article className="draft-card" key={draft.id}>
            <div className="draft-top"><span className={`status status-${draft.status.toLowerCase()}`}>{draft.status}</span><small>#{draft.id}</small></div>
            <h3>{draft.customer_name}</h3><p>{draft.items.map((item) => item.product_name).join(", ") || "품목 없음"}</p><strong>{money(draft.total_amount)}</strong>
            <div className="draft-actions"><a className="button secondary compact" href={`/api/quotations/${draft.id}/file`}><FileDown size={16} /> Excel</a>{draft.status === "DRAFT" && <button className="button primary compact" onClick={() => void runAction(() => api.approveDraft(draft.id), "견적서를 승인했습니다.", false).then(reload)}><CheckCircle2 size={16} /> 승인</button>}{draft.status === "APPROVED" && <button className="button danger compact" onClick={() => void runAction(() => api.sendDraft(draft.id), "메일을 발송했습니다.", false).then(reload)}><Send size={16} /> 발송</button>}<button className="button danger compact" onClick={() => { if (window.confirm("이 견적서를 삭제할까요?")) void runAction(() => api.deleteDraft(draft.id), "견적서를 삭제했습니다.", false).then(reload); }}><Trash2 size={16} /> 삭제</button></div>
            {draft.error_message && <small className="error-text">{draft.error_message}</small>}
          </article>
        ))}
        {!drafts.length && <div className="empty-state wide"><Archive size={38} /><p>생성된 견적서가 없습니다.</p></div>}
      </div>
    </div>
  );
}

function AgentSettingsPanel() {
  const [memories, setMemories] = useState<AgentMemory[]>([]);
  const [knowledge, setKnowledge] = useState<AgentKnowledge[]>([]);
  const [loadingAgentData, setLoadingAgentData] = useState(false);
  const [agentError, setAgentError] = useState("");
  const [knowledgeForm, setKnowledgeForm] = useState({ category: "rule", title: "", content: "", product_name: "", material_name: "", usage_context: "", tags: "" });

  async function reloadAgentData() {
    setLoadingAgentData(true);
    setAgentError("");
    try {
      const [memoryRows, knowledgeRows] = await Promise.all([api.agentMemories(), api.agentKnowledge()]);
      setMemories(memoryRows);
      setKnowledge(knowledgeRows);
    } catch (err) {
      setAgentError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingAgentData(false);
    }
  }

  useEffect(() => { void reloadAgentData(); }, []);

  async function addKnowledge() {
    if (!knowledgeForm.title.trim() || !knowledgeForm.content.trim()) {
      setAgentError("회사 지식은 제목과 내용을 입력해야 합니다.");
      return;
    }
    try {
      await api.createAgentKnowledge({
        category: knowledgeForm.category,
        title: knowledgeForm.title.trim(),
        content: knowledgeForm.content.trim(),
        product_name: knowledgeForm.product_name.trim() || null,
        material_name: knowledgeForm.material_name.trim() || null,
        usage_context: knowledgeForm.usage_context.trim() || null,
        tags: knowledgeForm.tags.trim() || null,
        priority: 0.7
      });
      setKnowledgeForm({ category: "rule", title: "", content: "", product_name: "", material_name: "", usage_context: "", tags: "" });
      await reloadAgentData();
    } catch (err) {
      setAgentError(err instanceof Error ? err.message : String(err));
    }
  }

  async function editKnowledge(row: AgentKnowledge) {
    const title = window.prompt("지식 제목", row.title);
    if (title == null) return;
    const content = window.prompt("회사 기준 내용", row.content);
    if (content == null) return;
    try { await api.updateAgentKnowledge(row.id, { title: title.trim(), content: content.trim() }); await reloadAgentData(); }
    catch (err) { setAgentError(err instanceof Error ? err.message : String(err)); }
  }

  async function removeKnowledge(id: number) {
    if (!window.confirm("이 회사 지식을 삭제할까요?")) return;
    try { await api.deleteAgentKnowledge(id); await reloadAgentData(); }
    catch (err) { setAgentError(err instanceof Error ? err.message : String(err)); }
  }

  async function editMemory(row: AgentMemory) {
    const content = window.prompt("AI가 기억할 내용", row.content);
    if (content == null) return;
    try { await api.updateAgentMemory(row.id, { content: content.trim() }); await reloadAgentData(); }
    catch (err) { setAgentError(err instanceof Error ? err.message : String(err)); }
  }

  async function removeMemory(id: number) {
    if (!window.confirm("이 장기기억을 삭제할까요?")) return;
    try { await api.deleteAgentMemory(id); await reloadAgentData(); }
    catch (err) { setAgentError(err instanceof Error ? err.message : String(err)); }
  }

  return (
    <>
      <section className="page-card agent-settings-card">
        <div className="page-card-header"><div><h2>열린문디자인 회사 지식</h2><p>재질, 표준 규격, 권장 용도, 내부 업무 규칙을 Agent가 우선 참고합니다.</p></div><button className="icon-button" onClick={() => void reloadAgentData()} title="새로고침">{loadingAgentData ? <Loader2 className="spin" size={17} /> : <RefreshCw size={17} />}</button></div>
        <div className="agent-knowledge-form">
          <select value={knowledgeForm.category} onChange={(event) => setKnowledgeForm({ ...knowledgeForm, category: event.target.value })}><option value="rule">업무 규칙</option><option value="material">재질</option><option value="size">표준 규격</option><option value="production">제작 기준</option></select>
          <input placeholder="제목" value={knowledgeForm.title} onChange={(event) => setKnowledgeForm({ ...knowledgeForm, title: event.target.value })} />
          <input placeholder="품목 (선택)" value={knowledgeForm.product_name} onChange={(event) => setKnowledgeForm({ ...knowledgeForm, product_name: event.target.value })} />
          <input placeholder="재질 (선택)" value={knowledgeForm.material_name} onChange={(event) => setKnowledgeForm({ ...knowledgeForm, material_name: event.target.value })} />
          <input placeholder="사용 환경 (예: 실외)" value={knowledgeForm.usage_context} onChange={(event) => setKnowledgeForm({ ...knowledgeForm, usage_context: event.target.value })} />
          <input placeholder="태그 (쉼표 구분)" value={knowledgeForm.tags} onChange={(event) => setKnowledgeForm({ ...knowledgeForm, tags: event.target.value })} />
          <textarea placeholder="열린문디자인에서 실제로 사용하는 기준을 입력하세요." value={knowledgeForm.content} onChange={(event) => setKnowledgeForm({ ...knowledgeForm, content: event.target.value })} />
          <button className="button primary" onClick={() => void addKnowledge()}><Save size={16} /> 회사 지식 저장</button>
        </div>
        <div className="agent-settings-list">{knowledge.map((row) => <div className="agent-settings-row" key={row.id}><div><div className="agent-settings-meta"><span>{row.category}</span>{row.product_name && <span>{row.product_name}</span>}{row.material_name && <span>{row.material_name}</span>}</div><strong>{row.title}</strong><p>{row.content}</p></div><div className="agent-settings-actions"><button className="button secondary compact" onClick={() => void editKnowledge(row)}>수정</button><button className="button danger compact" onClick={() => void removeKnowledge(row.id)}><Trash2 size={14} /> 삭제</button></div></div>)}{!knowledge.length && <p className="muted">아직 등록된 회사 지식이 없습니다.</p>}</div>
      </section>
      <section className="page-card agent-settings-card">
        <div className="page-card-header"><div><h2>AI 장기기억</h2><p>고객별 선호와 대화에서 확정된 지속적인 사실을 확인하고 수정할 수 있습니다.</p></div></div>
        <div className="agent-settings-list memory-list">{memories.map((row) => <div className="agent-settings-row" key={row.id}><div><div className="agent-settings-meta"><span>{row.scope}</span><span>{row.memory_type}</span>{row.customer_name && <span>{row.customer_name}</span>}{row.product_name && <span>{row.product_name}</span>}</div><p>{row.content}</p></div><div className="agent-settings-actions"><button className="button secondary compact" onClick={() => void editMemory(row)}>수정</button><button className="button danger compact" onClick={() => void removeMemory(row.id)}><Trash2 size={14} /> 삭제</button></div></div>)}{!memories.length && <p className="muted">아직 저장된 장기기억이 없습니다.</p>}</div>
      </section>
      {agentError && <div className="chat-error settings-agent-error">{agentError}</div>}
    </>
  );
}

function SettingsView({ runAction }: { runAction: (action: () => Promise<unknown>, success: string, refresh?: boolean) => Promise<void> }) {
  const [status, setStatus] = useState<Record<string, unknown>>({});
  const [paths, setPaths] = useState<Record<string, string>>({});
  useEffect(() => { void api.settingsStatus().then(setStatus); void api.settingsPaths().then(setPaths); }, []);
  return (
    <div className="settings-layout v3-settings-layout">
      <section className="page-card"><h2>연결 상태</h2><div className="status-grid"><StatusTile label="OpenAI" enabled={Boolean(status.openai_configured)} /><StatusTile label="Daum 메일" enabled={Boolean(status.mail_configured)} /><StatusTile label="실제 발송" enabled={Boolean(status.live_send_enabled)} warning /></div><div className="path-list">{Object.entries(paths).map(([key, value]) => <div key={key}><span>{key}</span><code>{value || "미설정"}</code></div>)}</div></section>
      <section className="page-card"><h2>사용자 데이터 연결</h2><div className="settings-block"><h3>현재 단가표 DB</h3><p>price_table.db가 가격 엔진에 정상 연결됐는지 확인합니다.</p><button className="button primary" onClick={() => void runAction(() => api.importPriceTable(), "단가표 DB 연결을 확인했습니다.", false)}><FileSpreadsheet size={17} /> 단가표 DB 확인</button></div><div className="settings-block"><h3>기존 견적 이력 DB</h3><p>quotation_history.db가 가격 엔진에 정상 연결됐는지 확인합니다.</p><button className="button primary" onClick={() => void runAction(() => api.importHistory(""), "견적 이력 DB 연결을 확인했습니다.", false)}><Archive size={17} /> 견적 이력 DB 확인</button></div></section>
      <AgentSettingsPanel />
    </div>
  );
}

function StatusTile({ label, enabled, warning = false }: { label: string; enabled: boolean; warning?: boolean }) {
  return <div className={`status-tile ${enabled ? (warning ? "warning" : "enabled") : "disabled"}`}>{enabled ? <CheckCircle2 size={22} /> : <XCircle size={22} />}<div><strong>{label}</strong><span>{enabled ? "설정됨" : "미설정"}</span></div></div>;
}

function Field({ label, value, onChange }: { label: string; value?: string | null; onChange: (value: string) => void }) {
  return <label className="field"><span>{label}</span><input value={value || ""} onChange={(event) => onChange(event.target.value)} /></label>;
}

function NumberField({ label, value, onChange }: { label: string; value?: number | null; onChange: (value: number | null) => void }) {
  return <label className="field"><span>{label}</span><input type="number" value={value ?? ""} onChange={(event) => onChange(event.target.value === "" ? null : Number(event.target.value))} /></label>;
}

function ReadOnlyField({ label, value }: { label: string; value: string }) {
  return <label className="field"><span>{label}</span><input value={value} readOnly /></label>;
}

function Loading() { return <div className="empty-state"><Loader2 className="spin" size={36} /><p>불러오는 중입니다.</p></div>; }
function EmptySelect() { return <div className="empty-state"><MailCheck size={38} /><p>왼쪽에서 메일을 선택하세요.</p></div>; }

export default App;
