import { useEffect, useMemo, useRef, useState, type DragEvent as ReactDragEvent, type PointerEvent as ReactPointerEvent } from "react";
import {
  AlertTriangle,
  Archive,
  CheckCircle2,
  ChevronRight,
  FileDown,
  FileSpreadsheet,
  Inbox,
  Heart,
  GripVertical,
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
import { api, syncEventsUrl } from "./api";
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
  ProductCatalog,
  ProductCatalogProduct,
  QuotationStorageCandidate,
  QuotationStorageMode,
  QuotationStorageOptions,
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

type WorkbenchPanelKey = "mail" | "original" | "analysis" | "chat";

const WORKBENCH_PANEL_TITLES: Record<WorkbenchPanelKey, string> = {
  mail: "메일 목록",
  original: "원본 메일",
  analysis: "AI 분석",
  chat: "Agent"
};

const WORKBENCH_LAYOUT_STORAGE_KEY = "openmoon.workbench.layout.v1";

const DEFAULT_PANEL_WIDTHS: Record<WorkbenchPanelKey, number> = {
  mail: 270,
  original: 380,
  analysis: 460,
  chat: 360
};

const DEFAULT_PANEL_ORDER: WorkbenchPanelKey[] = [
  "mail",
  "original",
  "analysis",
  "chat"
];

const DEFAULT_BOTTOM_PANEL_HEIGHT = 258;

type StoredWorkbenchLayout = {
  widths?: Partial<Record<WorkbenchPanelKey, number>>;
  order?: WorkbenchPanelKey[];
  collapsed?: WorkbenchPanelKey[];
  bottomHeight?: number;
};

function loadStoredWorkbenchLayout(): StoredWorkbenchLayout {
  try {
    const raw = window.localStorage.getItem(
      WORKBENCH_LAYOUT_STORAGE_KEY
    );

    if (!raw) return {};

    const parsed = JSON.parse(raw) as StoredWorkbenchLayout;

    return parsed && typeof parsed === "object"
      ? parsed
      : {};
  } catch {
    return {};
  }
}

function validPanelOrder(value: unknown): WorkbenchPanelKey[] {
  if (!Array.isArray(value)) {
    return [...DEFAULT_PANEL_ORDER];
  }

  const allowed = new Set<WorkbenchPanelKey>(
    DEFAULT_PANEL_ORDER
  );

  const filtered = value.filter(
    (panel): panel is WorkbenchPanelKey =>
      typeof panel === "string"
      && allowed.has(panel as WorkbenchPanelKey)
  );

  if (
    filtered.length !== DEFAULT_PANEL_ORDER.length
    || new Set(filtered).size !== DEFAULT_PANEL_ORDER.length
  ) {
    return [...DEFAULT_PANEL_ORDER];
  }

  return filtered;
}

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

function quoteValuePresent(value: unknown) {
  if (value == null) return false;
  if (Array.isArray(value)) {
    return value.some((part) => String(part ?? "").trim());
  }
  if (typeof value === "number") {
    return Number.isFinite(value);
  }
  return String(value).trim().length > 0;
}

function normalizedQuoteProductKey(value?: string | null) {
  return String(value || "")
    .replace(/\s+/g, "")
    .toLocaleLowerCase("ko-KR");
}

function requiredCatalogProduct(
  item: MailItem,
  catalog: ProductCatalog | null
) {
  if (!catalog) return null;

  const targets = [item.normalized_product, item.product_name]
    .map(normalizedQuoteProductKey)
    .filter(Boolean);

  if (!targets.length) return null;

  const products = catalog.categories.flatMap(
    (category) => category.products
  );

  for (const product of products) {
    const names = [product.name, ...(product.aliases || [])]
      .map(normalizedQuoteProductKey);

    if (targets.some((target) => names.includes(target))) {
      return product;
    }
  }

  return null;
}

function requiredCatalogFieldValue(
  item: MailItem,
  field: ProductCatalogProduct["fields"][number]
) {
  const legacy = field.legacy_field;

  if (legacy === "quantity") return item.quantity;
  if (legacy === "specification") return item.specification;
  if (legacy === "paper") return item.paper;
  if (legacy === "print_sides") return item.print_sides;
  if (legacy === "material") return item.material;

  return item.spec_attributes?.[field.key];
}

function missingQuoteFields(
  items: MailItem[],
  catalog: ProductCatalog | null
) {
  if (!items.length) {
    return ["견적서에 입력할 품목이 없습니다."];
  }

  return items.flatMap((item, index) => {
    const number = index + 1;
    const errors: string[] = [];

    if (!item.product_name?.trim()) {
      errors.push(`${number}번째 품목명이 비어 있습니다.`);
      return errors;
    }

    if (
      item.quantity == null
      || !Number.isFinite(Number(item.quantity))
      || Number(item.quantity) <= 0
    ) {
      errors.push(`${number}번째 품목의 수량을 입력해주세요.`);
    }

    if (
      item.unit_price == null
      || !Number.isFinite(Number(item.unit_price))
      || Number(item.unit_price) <= 0
    ) {
      errors.push(`${number}번째 품목의 확정 단가를 입력해주세요.`);
    }

    const product = requiredCatalogProduct(item, catalog);

    if (product) {
      for (const field of product.fields) {
        const value = requiredCatalogFieldValue(item, field);

        if (!quoteValuePresent(value)) {
          const duplicate =
            field.legacy_field === "quantity"
            && errors.some((message) => message.includes("수량"));

          if (!duplicate) {
            errors.push(
              `${number}번째 품목의 ${field.label}을(를) 입력해주세요.`
            );
          }
        }
      }
    } else if (!String(item.specification || "").trim()) {
      errors.push(`${number}번째 품목의 규격/사양을 입력해주세요.`);
    }

    return errors;
  });
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
  const [bulkStopRequested, setBulkStopRequested] = useState(false);
  const [analyzingIds, setAnalyzingIds] = useState<Set<number>>(new Set());
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [storageMail, setStorageMail] = useState<MailDetail | null>(null);
  const [syncRefreshToken, setSyncRefreshToken] = useState(0);
  const fileRef = useRef<HTMLInputElement>(null);
  const autoSyncingRef = useRef(false);
  const bulkStopRequestedRef = useRef(false);
  const syncRevisionRef = useRef<number | null>(null);
  const eventSyncingRef = useRef(false);
  const sseConnectedRef = useRef(false);
  const pendingRevisionRef = useRef<number | null>(null);
  const selectedIdRef = useRef<number | null>(null);
  const viewRef = useRef<ViewKey>("mail");

  const initialWorkbenchLayoutRef = useRef<StoredWorkbenchLayout | null>(null);

  if (initialWorkbenchLayoutRef.current === null) {
    initialWorkbenchLayoutRef.current = loadStoredWorkbenchLayout();
  }

  const initialWorkbenchLayout = initialWorkbenchLayoutRef.current;

  const [panelWidths, setPanelWidths] = useState<Record<WorkbenchPanelKey, number>>(
    () => ({
      ...DEFAULT_PANEL_WIDTHS,
      ...(initialWorkbenchLayout.widths || {})
    })
  );

  const [panelOrder, setPanelOrder] = useState<WorkbenchPanelKey[]>(
    () => validPanelOrder(initialWorkbenchLayout.order)
  );

  const [collapsedPanels, setCollapsedPanels] = useState<Set<WorkbenchPanelKey>>(
    () => new Set(
      (initialWorkbenchLayout.collapsed || []).filter(
        (panel): panel is WorkbenchPanelKey =>
          DEFAULT_PANEL_ORDER.includes(
            panel as WorkbenchPanelKey
          )
      )
    )
  );

  const [bottomPanelHeight, setBottomPanelHeight] = useState(
    () => {
      const stored = Number(
        initialWorkbenchLayout.bottomHeight
      );

      return Number.isFinite(stored)
        ? Math.min(520, Math.max(150, stored))
        : DEFAULT_BOTTOM_PANEL_HEIGHT;
    }
  );

  const [dragOverPanel, setDragOverPanel] = useState<WorkbenchPanelKey | null>(null);
  const draggedPanelRef = useRef<WorkbenchPanelKey | null>(null);

  const statusFilter = view === "review" ? "REVIEW_REQUIRED" : undefined;

  useEffect(() => {
    const payload: StoredWorkbenchLayout = {
      widths: panelWidths,
      order: panelOrder,
      collapsed: [...collapsedPanels],
      bottomHeight: bottomPanelHeight
    };

    try {
      window.localStorage.setItem(
        WORKBENCH_LAYOUT_STORAGE_KEY,
        JSON.stringify(payload)
      );
    } catch {
      // 저장 공간 접근이 불가능한 환경에서는 현재 세션만 유지한다.
    }
  }, [
    panelWidths,
    panelOrder,
    collapsedPanels,
    bottomPanelHeight
  ]);

  async function loadMails(keepSelection = true) {
    try {
      const data = await api.listMails(statusFilter, search || undefined);
      setMails(data);
      const currentSelectedId = selectedIdRef.current;
      if (!keepSelection || !currentSelectedId || !data.some((item) => item.id === currentSelectedId)) {
        setSelectedId(data[0]?.id ?? null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function loadMail(id: number, silent = false) {
    if (!silent) {
      setLoading(true);
      setError("");
    }
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
      if (!silent) setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (!silent) setLoading(false);
    }
  }

  async function deleteMailFromList(
    item: MailListItem
  ) {
    const subject = (
      item.original_subject
      || item.outer_subject
      || "제목 없음"
    );

    const confirmed = window.confirm(
      `"${subject}" 메일을 프로그램 목록에서 삭제할까요?\n\n`
      + "실제 Daum 받은편지함의 원본 메일은 삭제되지 않습니다."
    );

    if (!confirmed) return;

    setError("");

    try {
      await api.deleteMail(item.id);

      const data = await api.listMails(
        statusFilter,
        search || undefined
      );

      setMails(data);

      if (selectedId === item.id) {
        const nextId = data[0]?.id ?? null;

        setSelectedId(nextId);

        if (nextId) {
          await loadMail(nextId);
        } else {
          setMail(null);
          setPrices([]);
          setHistory([]);
          setCompanyHistory([]);
        }
      }

      showNotice(
        "메일을 프로그램 목록에서 삭제했습니다."
      );
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : String(err)
      );
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

  async function toggleMailHeart(item: MailListItem) {
    const hearted = !item.hearted;
    setMails((current) => current.map((row) => row.id === item.id ? { ...row, hearted } : row));
    setMail((current) => current?.id === item.id ? { ...current, hearted } : current);
    try {
      const updated = await api.setMailHeart(item.heart_key, hearted);
      setMails((current) => current.map((row) => row.id === item.id ? { ...row, hearted: updated.hearted } : row));
      setMail((current) => current?.id === item.id ? { ...current, hearted: updated.hearted } : current);
    } catch (err) {
      setMails((current) => current.map((row) => row.id === item.id ? { ...row, hearted: item.hearted } : row));
      setMail((current) => current?.id === item.id ? { ...current, hearted: item.hearted } : current);
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
    selectedIdRef.current = selectedId;
    viewRef.current = view;
  }, [selectedId, view]);

  useEffect(() => {
    let stopped = false;

    async function refreshAfterServerChange(incomingState?: { revision: number }) {
      if (eventSyncingRef.current) {
        if (incomingState) {
          pendingRevisionRef.current = Math.max(
            pendingRevisionRef.current ?? 0,
            incomingState.revision
          );
        }
        return;
      }
      if (document.visibilityState === "hidden") return;
      eventSyncingRef.current = true;

      try {
        const state = incomingState ?? await api.syncState();
        if (stopped) return;

        if (syncRevisionRef.current === null) {
          syncRevisionRef.current = state.revision;
          return;
        }
        if (state.revision === syncRevisionRef.current) return;

        syncRevisionRef.current = state.revision;
        const currentId = selectedIdRef.current;
        const currentView = viewRef.current;

        await loadMails();
        if (currentId && currentView !== "draft" && currentView !== "settings") {
          await loadMail(currentId, true);
        }
        if (currentView === "draft") await loadDrafts();

        const states = await api.mailHearts();
        if (stopped) return;
        setMails((current) => current.map((row) => ({
          ...row,
          hearted: Boolean(states[row.heart_key])
        })));
        setMail((current) => current ? {
          ...current,
          hearted: Boolean(states[current.heart_key])
        } : current);
        setSyncRefreshToken((current) => current + 1);
      } catch {
        // LAN 연결이 복구되면 최신 revision을 기준으로 전체 상태를 다시 맞춘다.
      } finally {
        eventSyncingRef.current = false;
        const pendingRevision = pendingRevisionRef.current;
        pendingRevisionRef.current = null;
        if (pendingRevision != null && pendingRevision !== syncRevisionRef.current) {
          void refreshAfterServerChange({ revision: pendingRevision });
        }
      }
    }

    const events = new EventSource(syncEventsUrl);
    events.onopen = () => {
      sseConnectedRef.current = true;
    };
    events.onmessage = (event) => {
      try {
        const state = JSON.parse(event.data) as { revision: number };
        void refreshAfterServerChange(state);
      } catch {
        // 잘못된 단일 이벤트는 무시하고 다음 이벤트를 기다린다.
      }
    };
    events.onerror = () => {
      sseConnectedRef.current = false;
    };

    void refreshAfterServerChange();
    const timer = window.setInterval(() => {
      if (!sseConnectedRef.current) void refreshAfterServerChange();
    }, 10000);
    const onVisible = () => {
      if (document.visibilityState === "visible") void refreshAfterServerChange();
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      stopped = true;
      events.close();
      sseConnectedRef.current = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [search, statusFilter]);

  useEffect(() => {
    if (view === "draft") void loadDrafts();
    else if (view !== "settings") void loadMails(false);
  }, [view]);

  useEffect(() => {
    if (view === "draft" || view === "settings") return;
    let stopped = false;

    const syncHearts = async () => {
      if (document.visibilityState === "hidden") return;
      try {
        const [states, latestMail] = await Promise.all([
          api.mailHearts(),
          selectedId ? api.getMail(selectedId) : Promise.resolve(null)
        ]);
        if (stopped) return;
        setMails((current) => current.map((row) => ({
          ...row,
          hearted: Boolean(states[row.heart_key])
        })));
        setMail((current) => {
          if (!latestMail || !current || current.id !== latestMail.id) return current;
          return {
            ...latestMail,
            hearted: Boolean(states[latestMail.heart_key])
          };
        });
      } catch {
        // LAN 연결이 잠시 끊겨도 메인 프로그램은 계속 사용한다.
      }
    };

    void syncHearts();
    const timer = window.setInterval(() => void syncHearts(), 5000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [view, selectedId]);

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

  function startPanelResize(
    panel: WorkbenchPanelKey,
    event: ReactPointerEvent<HTMLDivElement>
  ) {
    event.preventDefault();

    if (collapsedPanels.has(panel)) return;

    const startX = event.clientX;
    const startWidth = panelWidths[panel];

    const limits: Record<WorkbenchPanelKey, { min: number; max: number }> = {
      mail: { min: 220, max: 430 },
      original: { min: 300, max: 680 },
      analysis: { min: 340, max: 760 },
      chat: { min: 300, max: 680 }
    };

    document.body.classList.add("is-resizing-panels");

    function onPointerMove(moveEvent: PointerEvent) {
      const delta = moveEvent.clientX - startX;
      const { min, max } = limits[panel];
      const nextWidth = Math.min(max, Math.max(min, startWidth + delta));

      setPanelWidths((current) => ({
        ...current,
        [panel]: Math.round(nextWidth)
      }));
    }

    function stopResize() {
      document.body.classList.remove("is-resizing-panels");
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", stopResize);
      window.removeEventListener("pointercancel", stopResize);
    }

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", stopResize);
    window.addEventListener("pointercancel", stopResize);
  }

  function resetPanelWidth(panel: WorkbenchPanelKey) {
    setPanelWidths((current) => ({
      ...current,
      [panel]: DEFAULT_PANEL_WIDTHS[panel]
    }));
  }

  function isPanelCollapsed(panel: WorkbenchPanelKey) {
    return collapsedPanels.has(panel);
  }

  function togglePanelCollapsed(panel: WorkbenchPanelKey) {
    setCollapsedPanels((current) => {
      const next = new Set(current);
      if (next.has(panel)) next.delete(panel);
      else next.add(panel);
      return next;
    });
  }

  function workbenchColumns() {
    const columns: string[] = [];
    const expandedPanels = panelOrder.filter(
      (panel) => !collapsedPanels.has(panel)
    );
    const flexPanel = expandedPanels.at(-1) ?? null;

    panelOrder.forEach((panel, index) => {
      if (collapsedPanels.has(panel)) {
        columns.push("52px");
      } else if (panel === flexPanel) {
        columns.push(`minmax(${panelWidths[panel]}px, 1fr)`);
      } else {
        columns.push(`${panelWidths[panel]}px`);
      }

      if (index < panelOrder.length - 1) {
        columns.push("10px");
      }
    });

    return columns.join(" ");
  }

  function panelGridStyle(panel: WorkbenchPanelKey) {
    const slot = panelOrder.indexOf(panel);

    return {
      gridColumn: slot * 2 + 1,
      gridRow: slot === 0 ? "1 / 4" : "1"
    };
  }

  function isLastWorkbenchPanel(panel: WorkbenchPanelKey) {
    return panelOrder[panelOrder.length - 1] === panel;
  }

  function panelWindowClass(panel: WorkbenchPanelKey, base: string) {
    return [
      base,
      "panel",
      "panel-window",
      isPanelCollapsed(panel) ? "panel-collapsed" : "",
      dragOverPanel === panel ? "panel-drop-target" : ""
    ].filter(Boolean).join(" ");
  }

  function startPanelDrag(
    panel: WorkbenchPanelKey,
    event: ReactDragEvent<HTMLDivElement>
  ) {
    draggedPanelRef.current = panel;
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", panel);
    document.body.classList.add("is-dragging-panel");
  }

  function swapPanels(target: WorkbenchPanelKey) {
    const source = draggedPanelRef.current;
    if (!source || source === target) return;

    setPanelOrder((current) => {
      const sourceIndex = current.indexOf(source);
      const targetIndex = current.indexOf(target);

      if (sourceIndex < 0 || targetIndex < 0) {
        return current;
      }

      const next = [...current];
      [next[sourceIndex], next[targetIndex]] = [
        next[targetIndex],
        next[sourceIndex]
      ];

      return next;
    });
  }

  function finishPanelDrag() {
    draggedPanelRef.current = null;
    setDragOverPanel(null);
    document.body.classList.remove("is-dragging-panel");
  }

  function startBottomPanelResize(
    event: ReactPointerEvent<HTMLDivElement>
  ) {
    event.preventDefault();

    const startY = event.clientY;
    const startHeight = bottomPanelHeight;

    document.body.classList.add("is-resizing-bottom-panel");

    function onPointerMove(moveEvent: PointerEvent) {
      // 경계선을 위로 끌면 하단 패널이 커진다.
      const delta = startY - moveEvent.clientY;
      const nextHeight = Math.min(
        520,
        Math.max(150, startHeight + delta)
      );

      setBottomPanelHeight(
        Math.round(nextHeight)
      );
    }

    function stopResize() {
      document.body.classList.remove(
        "is-resizing-bottom-panel"
      );

      window.removeEventListener(
        "pointermove",
        onPointerMove
      );

      window.removeEventListener(
        "pointerup",
        stopResize
      );

      window.removeEventListener(
        "pointercancel",
        stopResize
      );
    }

    window.addEventListener(
      "pointermove",
      onPointerMove
    );

    window.addEventListener(
      "pointerup",
      stopResize
    );

    window.addEventListener(
      "pointercancel",
      stopResize
    );
  }

  function resetWorkbenchLayout() {
    setPanelWidths({
      ...DEFAULT_PANEL_WIDTHS
    });

    setPanelOrder([
      ...DEFAULT_PANEL_ORDER
    ]);

    setCollapsedPanels(
      new Set()
    );

    setBottomPanelHeight(
      DEFAULT_BOTTOM_PANEL_HEIGHT
    );
  }

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

  function requestStopBulkAnalysis() {
    if (!bulkAnalyzing || bulkStopRequestedRef.current) return;

    bulkStopRequestedRef.current = true;
    setBulkStopRequested(true);
    showNotice("현재 메일 분석이 끝나면 전체 분석을 중지합니다.");
  }

  async function analyzeAllNewMails() {
    if (bulkAnalyzing) return;

    bulkStopRequestedRef.current = false;
    setBulkStopRequested(false);
    setBulkAnalyzing(true);
    setError("");

    let completed = 0;
    let failed = 0;
    let total = 0;
    let stopped = false;

    try {
      const allMails = await api.listMails();
      const pending = allMails.filter(
        (item) => item.status === "NEW"
      );

      total = pending.length;

      if (!pending.length) {
        showNotice("분석할 신규 메일이 없습니다.");
        return;
      }

      for (const item of pending) {
        if (bulkStopRequestedRef.current) {
          stopped = true;
          break;
        }

        setAnalyzingIds((current) =>
          new Set(current).add(item.id)
        );

        try {
          const analyzed = await api.analyzeMail(item.id);
          completed += 1;

          setMails((current) =>
            current.map((row) =>
              row.id === item.id
                ? analyzed
                : row
            )
          );

          if (selectedId === item.id) {
            setMail(analyzed);
          }
        } catch {
          failed += 1;
        } finally {
          setAnalyzingIds((current) => {
            const next = new Set(current);
            next.delete(item.id);
            return next;
          });
        }

        if (bulkStopRequestedRef.current) {
          stopped = true;
          break;
        }
      }

      await loadMails();

      if (selectedId) {
        await loadMail(selectedId);
      }

      if (stopped) {
        const processed = completed + failed;
        const remaining = Math.max(
          0,
          total - processed
        );

        showNotice(
          `전체 분석 중지 · 완료 ${completed}건`
          + `${failed ? ` · 실패 ${failed}건` : ""}`
          + ` · 남은 신규 ${remaining}건`
        );
      } else {
        showNotice(
          `신규 메일 ${completed}건 분석 완료`
          + `${failed ? ` · 실패 ${failed}건` : ""}`
        );
      }
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : String(err)
      );
    } finally {
      bulkStopRequestedRef.current = false;
      setBulkStopRequested(false);
      setAnalyzingIds(new Set());
      setBulkAnalyzing(false);
    }
  }

  return (
    <div className="app-shell sidebar-is-collapsed">
      <aside className="sidebar collapsed">
        <div className="brand">
          <img className="brand-logo" src="/yullinmoon-logo.png" alt="열린문디자인 DESIGN Corp." />
        </div>
        <nav>
          {NAV_ITEMS.map(({ key, label, icon: Icon }) => (
            <button key={key} className={view === key ? "nav-item active" : "nav-item"} onClick={() => setView(key)} title={label} aria-label={label}>
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
                <button
                  className="button secondary"
                  onClick={resetWorkbenchLayout}
                  title="창 순서·너비·최소화·하단 높이를 기본값으로 되돌립니다."
                >
                  <Maximize2 size={16} />
                  화면 초기화
                </button>
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
          <div
            className="workbench resizable-workbench"
            style={{
              gridTemplateColumns: workbenchColumns(),
              gridTemplateRows:
                `minmax(0, 1fr) 10px ${bottomPanelHeight}px`
            }}
          >
            <section
              className={panelWindowClass("mail", "mail-column")}
              style={panelGridStyle("mail")}
              onDragOver={(event) => {
                event.preventDefault();
                setDragOverPanel("mail");
              }}
              onDrop={(event) => {
                event.preventDefault();
                swapPanels("mail");
                finishPanelDrag();
              }}
            >
              <div
                className="panel-window-bar"
                draggable
                onDragStart={(event) => startPanelDrag("mail", event)}
                onDragEnd={finishPanelDrag}
                title="드래그해서 창 위치 변경"
              >
                <span className="panel-drag-grip" aria-hidden="true">⠿</span>
                <strong className="panel-window-title">{WORKBENCH_PANEL_TITLES.mail}</strong>
                <button
                  type="button"
                  className="panel-minimize-button"
                  draggable={false}
                  onClick={() => togglePanelCollapsed("mail")}
                  title={isPanelCollapsed("mail") ? "창 펼치기" : "창 최소화"}
                >
                  {isPanelCollapsed("mail") ? <Maximize2 size={13} /> : <Minimize2 size={13} />}
                </button>
              </div>

              <div className="panel-header">
                <div><strong>{view === "review" ? "검토 대기 메일" : "받은 메일"}</strong><span>{mails.length}건</span></div>
                <div className="panel-actions">
                  {view === "mail" && (
                    <button
                      className={
                        bulkAnalyzing
                          ? "button danger compact bulk-analyze-button"
                          : "button secondary compact bulk-analyze-button"
                      }
                      disabled={bulkAnalyzing && bulkStopRequested}
                      onClick={() => {
                        if (bulkAnalyzing) {
                          requestStopBulkAnalysis();
                        } else {
                          void analyzeAllNewMails();
                        }
                      }}
                      title={
                        bulkAnalyzing
                          ? "현재 분석 중인 메일까지 완료한 뒤 중지합니다."
                          : "신규 메일을 순서대로 분석합니다."
                      }
                    >
                      {bulkAnalyzing ? (
                        bulkStopRequested ? (
                          <Loader2 className="spin" size={14} />
                        ) : (
                          <XCircle size={14} />
                        )
                      ) : (
                        <Sparkles size={14} />
                      )}
                      {bulkAnalyzing
                        ? bulkStopRequested
                          ? "중지 대기"
                          : "분석 중지"
                        : "전체 분석"}
                    </button>
                  )}
                  <button className="icon-button" onClick={() => void loadMails()} title="새로고침"><RefreshCw size={17} /></button>
                </div>
              </div>
              <div className="search-box"><Search size={16} /><input value={search} onChange={(event) => setSearch(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void loadMails(false); }} placeholder="기관, 담당자, 제목 검색" /></div>
              {isLastWorkbenchPanel("mail") && !isPanelCollapsed("mail") && (
                <div
                  className="panel-edge-resizer"
                  role="separator"
                  aria-orientation="vertical"
                  aria-label="메일 목록 오른쪽 너비 조절"
                  title="드래그하여 창 너비 조절"
                  onPointerDown={(event) => startPanelResize("mail", event)}
                  onDoubleClick={() => resetPanelWidth("mail")}
                />
              )}

              <div className="mail-list">
                {mails.map((item) => (
                  <div key={item.id} className={selectedId === item.id ? "mail-card selected" : "mail-card"} role="button" tabIndex={0} onClick={() => setSelectedId(item.id)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") setSelectedId(item.id); }}>
                    <div className="mail-card-top">
                      <span className="mail-status-wrap">
                        <button className={item.starred ? "mail-star starred" : "mail-star"} onClick={(event) => { event.stopPropagation(); void toggleMailStar(item); }} aria-label={item.starred ? "별표 해제" : "별표 표시"}><Star size={16} fill={item.starred ? "currentColor" : "none"} /></button>
                        <button className={item.hearted ? "mail-heart hearted" : "mail-heart"} onClick={(event) => { event.stopPropagation(); void toggleMailHeart(item); }} aria-label={item.hearted ? "공용 하트 끄기" : "공용 하트 켜기"} title="사내 공유 하트"><Heart size={16} fill={item.hearted ? "currentColor" : "none"} /></button>
                        <span className={statusClass(item.status)}>{STATUS_LABELS[item.status]}</span>
                        {(item.status === "ANALYZING" || analyzingIds.has(item.id)) && <Loader2 className="spin mail-loading" size={14} />}
                      </span>
                      <span className="mail-card-right-actions">
                        <time>{formatDate(item.outer_sent_at || item.original_sent_at)}</time>
                        <button
                          type="button"
                          className="mail-delete-button"
                          title="프로그램 목록에서 삭제"
                          aria-label="메일 삭제"
                          onClick={(event) => {
                            event.stopPropagation();
                            void deleteMailFromList(item);
                          }}
                        >
                          <Trash2 size={14} />
                        </button>
                      </span>
                    </div>
                    <strong>{item.original_subject || item.outer_subject || "제목 없음"}</strong>
                    <p>{item.customer_organization || item.original_sender_name || item.original_sender_email || "고객 미확인"}</p>
                    <small>{item.summary || "아직 분석되지 않은 메일입니다."}</small>
                  </div>
                ))}
                {!mails.length && <div className="empty-state"><Inbox size={32} /><p>표시할 메일이 없습니다.</p></div>}
              </div>
            </section>

            <div
              className="panel-resizer panel-resizer-mail"
              role="separator"
              aria-orientation="vertical"
              aria-label="메일 목록 너비 조절"
              title="드래그하여 너비 조절 · 더블클릭하여 초기화"
              onPointerDown={(event) => startPanelResize(panelOrder[0], event)}
              onDoubleClick={() => resetPanelWidth(panelOrder[0])}
            />

            <section
              className={panelWindowClass("original", "mail-view")}
              style={panelGridStyle("original")}
              onDragOver={(event) => {
                event.preventDefault();
                setDragOverPanel("original");
              }}
              onDrop={(event) => {
                event.preventDefault();
                swapPanels("original");
                finishPanelDrag();
              }}
            >
              <div
                className="panel-window-bar"
                draggable
                onDragStart={(event) => startPanelDrag("original", event)}
                onDragEnd={finishPanelDrag}
                title="드래그해서 창 위치 변경"
              >
                <span className="panel-drag-grip" aria-hidden="true">⠿</span>
                <strong className="panel-window-title">{WORKBENCH_PANEL_TITLES.original}</strong>
                <button
                  type="button"
                  className="panel-minimize-button"
                  draggable={false}
                  onClick={() => togglePanelCollapsed("original")}
                  title={isPanelCollapsed("original") ? "창 펼치기" : "창 최소화"}
                >
                  {isPanelCollapsed("original") ? <Maximize2 size={13} /> : <Minimize2 size={13} />}
                </button>
              </div>

              {isLastWorkbenchPanel("original") && !isPanelCollapsed("original") && (
                <div
                  className="panel-edge-resizer"
                  role="separator"
                  aria-orientation="vertical"
                  aria-label="원본 메일 오른쪽 너비 조절"
                  title="드래그하여 창 너비 조절"
                  onPointerDown={(event) => startPanelResize("original", event)}
                  onDoubleClick={() => resetPanelWidth("original")}
                />
              )}

              {loading && !mail ? <Loading /> : mail ? <OriginalMail mail={mail} /> : <EmptySelect />}
            </section>

            <div
              className="panel-resizer panel-resizer-original"
              role="separator"
              aria-orientation="vertical"
              aria-label="원본 메일 너비 조절"
              title="드래그하여 너비 조절 · 더블클릭하여 초기화"
              onPointerDown={(event) => startPanelResize(panelOrder[1], event)}
              onDoubleClick={() => resetPanelWidth(panelOrder[1])}
            />

            <section
              className={panelWindowClass("analysis", "analysis-view")}
              style={panelGridStyle("analysis")}
              onDragOver={(event) => {
                event.preventDefault();
                setDragOverPanel("analysis");
              }}
              onDrop={(event) => {
                event.preventDefault();
                swapPanels("analysis");
                finishPanelDrag();
              }}
            >
              <div
                className="panel-window-bar"
                draggable
                onDragStart={(event) => startPanelDrag("analysis", event)}
                onDragEnd={finishPanelDrag}
                title="드래그해서 창 위치 변경"
              >
                <span className="panel-drag-grip" aria-hidden="true">⠿</span>
                <strong className="panel-window-title">{WORKBENCH_PANEL_TITLES.analysis}</strong>
                <button
                  type="button"
                  className="panel-minimize-button"
                  draggable={false}
                  onClick={() => togglePanelCollapsed("analysis")}
                  title={isPanelCollapsed("analysis") ? "창 펼치기" : "창 최소화"}
                >
                  {isPanelCollapsed("analysis") ? <Maximize2 size={13} /> : <Minimize2 size={13} />}
                </button>
              </div>

              {isLastWorkbenchPanel("analysis") && !isPanelCollapsed("analysis") && (
                <div
                  className="panel-edge-resizer"
                  role="separator"
                  aria-orientation="vertical"
                  aria-label="AI 분석 오른쪽 너비 조절"
                  title="드래그하여 창 너비 조절"
                  onPointerDown={(event) => startPanelResize("analysis", event)}
                  onDoubleClick={() => resetPanelWidth("analysis")}
                />
              )}

              {mail ? <AnalysisPanel mail={mail} onAnalyze={() => void runAction(() => api.analyzeMail(mail.id), "AI 분석이 완료되었습니다.")} onSave={(payload) => void runAction(() => api.saveAnalysis(mail.id, payload), "분석 내용을 저장했습니다.")} onCreate={(payload) => void runAction(async () => { const updated = await api.saveAnalysis(mail.id, payload); setStorageMail(updated); }, "견적서 저장 위치를 선택해주세요.", false)} loading={loading} /> : <EmptySelect />}
            </section>

            <div
              className="panel-resizer panel-resizer-analysis"
              role="separator"
              aria-orientation="vertical"
              aria-label="AI 분석 너비 조절"
              title="드래그하여 너비 조절 · 더블클릭하여 초기화"
              onPointerDown={(event) => startPanelResize(panelOrder[2], event)}
              onDoubleClick={() => resetPanelWidth(panelOrder[2])}
            />

            <section
              className={panelWindowClass("chat", "chat-view")}
              style={panelGridStyle("chat")}
              onDragOver={(event) => {
                event.preventDefault();
                setDragOverPanel("chat");
              }}
              onDrop={(event) => {
                event.preventDefault();
                swapPanels("chat");
                finishPanelDrag();
              }}
            >
              <div
                className="panel-window-bar"
                draggable
                onDragStart={(event) => startPanelDrag("chat", event)}
                onDragEnd={finishPanelDrag}
                title="드래그해서 창 위치 변경"
              >
                <span className="panel-drag-grip" aria-hidden="true">⠿</span>
                <strong className="panel-window-title">{WORKBENCH_PANEL_TITLES.chat}</strong>
                <button
                  type="button"
                  className="panel-minimize-button"
                  draggable={false}
                  onClick={() => togglePanelCollapsed("chat")}
                  title={isPanelCollapsed("chat") ? "창 펼치기" : "창 최소화"}
                >
                  {isPanelCollapsed("chat") ? <Maximize2 size={13} /> : <Minimize2 size={13} />}
                </button>
              </div>

              {isLastWorkbenchPanel("chat") && !isPanelCollapsed("chat") && (
                <div
                  className="panel-edge-resizer"
                  role="separator"
                  aria-orientation="vertical"
                  aria-label="Agent 오른쪽 너비 조절"
                  title="드래그하여 창 너비 조절"
                  onPointerDown={(event) => startPanelResize("chat", event)}
                  onDoubleClick={() => resetPanelWidth("chat")}
                />
              )}

              {mail ? <ChatPanel mail={mail} refreshToken={syncRefreshToken} onMailChanged={(updated) => { setMail(updated); void loadMails(); }} onRequestQuotation={(updated) => setStorageMail(updated)} /> : <EmptySelect />}
            </section>
            <div
              className="bottom-panel-resizer"
              role="separator"
              aria-orientation="horizontal"
              aria-label="과거 견적 및 가격 영역 높이 조절"
              title="위아래로 드래그하여 높이 조절 · 더블클릭하여 초기화"
              onPointerDown={startBottomPanelResize}
              onDoubleClick={() => setBottomPanelHeight(DEFAULT_BOTTOM_PANEL_HEIGHT)}
            >
              <span />
            </div>

            <section className="bottom-panel panel">
              <HistoryAndPricing
                companyHistory={companyHistory}
                history={history}
                prices={prices}
              />
            </section>
          </div>
        )}
        {storageMail && (
          <QuotationStorageModal
            mail={storageMail}
            onClose={() => setStorageMail(null)}
            onCreated={async () => {
              setStorageMail(null);
              showNotice("견적서 시트를 생성했습니다.");
              await loadMails();
              if (selectedId) await loadMail(selectedId);
            }}
          />
        )}
      </main>
    </div>
  );
}

function QuotationStorageModal({ mail, onClose, onCreated }: {
  mail: MailDetail;
  onClose: () => void;
  onCreated: () => Promise<void>;
}) {
  const [options, setOptions] = useState<QuotationStorageOptions | null>(null);
  const [selected, setSelected] = useState<QuotationStorageCandidate | null>(null);
  const [mode, setMode] = useState<QuotationStorageMode>("existing");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.quotationStorageOptions(mail.id)
      .then((data) => {
        setOptions(data);
        const previous = data.selected_file
          ? [...data.existing_files, ...data.new_files].find((row) => row.path === data.selected_file)
          : undefined;
        const first = previous || data.existing_files[0] || data.new_files[0] || null;
        if (first) {
          setSelected(first);
          setMode(first.mode);
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  }, [mail.id]);

  useEffect(() => {
    function keydown(event: KeyboardEvent) {
      if (event.key === "Escape" && !saving) onClose();
    }
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [onClose, saving]);

  function chooseMode(nextMode: QuotationStorageMode) {
    setMode(nextMode);
    const rows = nextMode === "existing" ? options?.existing_files : options?.new_files;
    setSelected(rows?.find((row) => row.mode === nextMode) || null);
  }

  async function create() {
    if (!selected || saving) return;
    setSaving(true);
    setError("");
    try {
      await api.createDraft(mail.id, selected.mode, selected.path);
      await onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  const modes: Array<{ key: QuotationStorageMode; label: string }> = [
    { key: "existing", label: "기존 견적 엑셀에 새 시트 추가" },
    { key: "department", label: "부서 공용 파일 사용 또는 생성" },
    { key: "person", label: "담당자별 파일 사용 또는 생성" },
    { key: "separate", label: "별도의 새 견적 파일 생성" }
  ];
  const rows = mode === "existing"
    ? options?.existing_files || []
    : (options?.new_files || []).filter((row) => row.mode === mode);

  return (
    <div className="quote-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !saving) onClose(); }}>
      <section className="quote-modal" role="dialog" aria-modal="true" aria-labelledby="quote-storage-title">
        <header><div><h2 id="quote-storage-title">견적서 저장 방식 선택</h2><p>{mail.customer_organization || "고객"} · {mail.customer_department || "부서 미확인"} · {mail.customer_name || "담당자 미확인"}</p></div><button className="icon-button" onClick={onClose} disabled={saving}>×</button></header>
        {loading ? <div className="quote-modal-loading"><Loader2 className="spin" size={22} /> 저장 후보를 찾고 있습니다.</div> : (
          <>
            <div className="storage-mode-grid">
              {modes.map((row) => <button key={row.key} className={mode === row.key ? "storage-mode active" : "storage-mode"} onClick={() => chooseMode(row.key)}>{row.label}</button>)}
            </div>
            <div className="storage-root"><span>견적 폴더</span><strong>{options?.root_path}</strong></div>
            <div className="storage-files">
              {rows.map((row) => (
                <button key={`${row.mode}-${row.path}`} className={selected?.path === row.path ? "storage-file selected" : "storage-file"} onClick={() => setSelected(row)}>
                  <span className="storage-radio">{selected?.path === row.path ? "●" : "○"}</span>
                  <span className="storage-file-main"><strong>{row.filename}</strong><small>{row.path}</small></span>
                  <span className="storage-file-meta"><b>{row.file_type}</b><em>{row.exists ? "기존 파일" : "새로 생성"}</em></span>
                </button>
              ))}
              {!rows.length && <div className="storage-empty">관련 기존 파일이 없습니다. 부서 공용, 담당자별 또는 별도 파일 방식을 선택할 수 있습니다.</div>}
            </div>
            <div className="selected-storage"><span>선택된 파일</span><strong>{selected?.filename || "선택되지 않음"}</strong><small>{selected?.path || ""}</small></div>
          </>
        )}
        {error && <div className="quote-modal-error"><XCircle size={16} />{error}</div>}
        <footer><button className="button secondary" onClick={onClose} disabled={saving}>취소</button><button className="button primary" onClick={() => void create()} disabled={!selected || saving}>{saving ? <Loader2 className="spin" size={16} /> : <FileSpreadsheet size={16} />} 선택한 파일에 견적 생성</button></footer>
      </section>
    </div>
  );
}

function ChatPanel({ mail, refreshToken, onMailChanged, onRequestQuotation }: { mail: MailDetail; refreshToken: number; onMailChanged: (mail: MailDetail) => void; onRequestQuotation: (mail: MailDetail) => void }) {
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
  }, [mail.id]);

  useEffect(() => {
    api.chatMessages(mail.id).then(setMessages).catch((err) => setChatError(err instanceof Error ? err.message : String(err)));
  }, [mail.id, refreshToken]);

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
      const actions = Array.isArray(result.assistant_message.action_payload?.actions)
        ? result.assistant_message.action_payload.actions as Array<Record<string, unknown>>
        : [];
      if (actions.some((action) => action.type === "open_storage_modal")) {
        onRequestQuotation(result.mail);
      }
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
    if (type === "history_excel_opened") return "과거 견적 Excel";
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


function ProductPickerModal({
  catalog,
  loading,
  error,
  onSelect,
  onBlank,
  onClose
}: {
  catalog: ProductCatalog | null;
  loading: boolean;
  error: string;
  onSelect: (product: ProductCatalogProduct) => void;
  onBlank: () => void;
  onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("전체");

  const categories = catalog?.categories ?? [];
  const normalizedQuery = query.trim().toLocaleLowerCase("ko-KR");
  const products = categories.flatMap((group) =>
    group.products.map((product) => ({
      ...product,
      categoryCode: group.code,
      categoryName: group.name
    }))
  );
  const filtered = products.filter((product) => {
    if (category !== "전체" && product.categoryName !== category) return false;
    if (!normalizedQuery) return true;
    const haystack = [product.name, ...(product.aliases || [])]
      .join(" ")
      .toLocaleLowerCase("ko-KR");
    return haystack.includes(normalizedQuery);
  });

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div
      className="product-picker-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section className="product-picker-modal" role="dialog" aria-modal="true" aria-labelledby="product-picker-title">
        <header className="product-picker-header">
          <div>
            <h2 id="product-picker-title">품목 추가</h2>
            <p>회사 품목을 검색하거나 목록에 없는 품목을 직접 추가할 수 있습니다.</p>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="닫기">X</button>
        </header>

        <div className="product-picker-search">
          <Search size={17} />
          <input
            autoFocus
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="품목명 검색 (예: 현수막, 명함, 간판)"
          />
        </div>

        <div className="product-picker-categories">
          {["전체", ...categories.map((group) => group.name)].map((name) => (
            <button
              type="button"
              key={name}
              className={category === name ? "active" : ""}
              onClick={() => setCategory(name)}
            >
              {name}
            </button>
          ))}
        </div>

        <div className="product-picker-list">
          {loading && (
            <div className="product-picker-state">
              <Loader2 className="spin" size={22} />
              <span>품목 목록을 불러오고 있습니다.</span>
            </div>
          )}

          {!loading && error && (
            <div className="product-picker-state error">
              <XCircle size={20} />
              <span>{error}</span>
            </div>
          )}

          {!loading && !error && filtered.map((product) => (
            <button
              type="button"
              className="product-picker-row"
              key={product.code}
              onClick={() => onSelect(product)}
            >
              <span className="product-picker-row-main">
                <strong>{product.name}</strong>
                <small>{product.categoryName}</small>
              </span>
              <span className="product-picker-row-meta">사양 {product.fields.length}개</span>
              <ChevronRight size={17} />
            </button>
          ))}

          {!loading && !error && !filtered.length && (
            <div className="product-picker-state">
              <Search size={20} />
              <span>검색 결과가 없습니다.</span>
            </div>
          )}
        </div>

        <footer className="product-picker-footer">
          <button type="button" className="button secondary product-blank-button" onClick={onBlank}>
            + 목록에 없는 품목 직접 추가
          </button>
          <span>등록 품목 {products.length}개</span>
        </footer>
      </section>
    </div>
  );
}


function CatalogSpecField({
  field,
  value,
  onChange
}: {
  field: ProductCatalogProduct["fields"][number];
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const options = field.options || [];
  const isMulti = field.input_type === "multi_select_or_input";
  const isNumber = field.input_type === "number_input" || field.input_type === "number_select_or_input";
  const textValue = value == null ? "" : String(value);
  const matchedOption = options.find((option) => option === textValue) || "";
  const [customMode, setCustomMode] = useState(
    Boolean(options.length && textValue && !matchedOption)
  );

  useEffect(() => {
    if (!options.length) {
      setCustomMode(true);
      return;
    }
    if (matchedOption) {
      setCustomMode(false);
    } else if (textValue) {
      setCustomMode(true);
    }
  }, [matchedOption, textValue, options.length]);

  if (isMulti) {
    const selected = Array.isArray(value)
      ? value.map(String)
      : String(value ?? "")
          .split(",")
          .map((part) => part.trim())
          .filter(Boolean);

    function toggle(option: string) {
      const next = selected.includes(option)
        ? selected.filter((item) => item !== option)
        : [...selected, option];
      onChange(next);
    }

    return (
      <div className="catalog-spec-field full">
        <span className="catalog-spec-label">{field.label}</span>
        {!!options.length && (
          <div className="catalog-option-chips">
            {options.map((option) => (
              <button
                type="button"
                key={option}
                className={selected.includes(option) ? "selected" : ""}
                onClick={() => toggle(option)}
              >
                {option}
              </button>
            ))}
          </div>
        )}
        <input
          value={selected.filter((item) => !options.includes(item)).join(", ")}
          onChange={(event) => {
            const customValues = event.target.value
              .split(",")
              .map((part) => part.trim())
              .filter(Boolean);
            const optionValues = selected.filter((item) => options.includes(item));
            onChange([...optionValues, ...customValues]);
          }}
          placeholder="목록에 없으면 직접 입력 (여러 항목은 쉼표로 구분)"
        />
      </div>
    );
  }

  if (!options.length) {
    return (
      <label className="catalog-spec-field">
        <span className="catalog-spec-label">{field.label}</span>
        <input
          type={isNumber ? "number" : "text"}
          value={textValue}
          onChange={(event) => onChange(event.target.value)}
          placeholder="직접 입력"
        />
      </label>
    );
  }

  return (
    <label className="catalog-spec-field">
      <span className="catalog-spec-label">{field.label}</span>
      <select
        value={customMode ? "__custom__" : matchedOption}
        onChange={(event) => {
          if (event.target.value === "__custom__") {
            setCustomMode(true);
            if (matchedOption) onChange("");
            return;
          }
          setCustomMode(false);
          onChange(event.target.value);
        }}
      >
        <option value="">선택</option>
        {options.map((option) => (
          <option value={option} key={option}>{option}</option>
        ))}
        <option value="__custom__">직접 입력</option>
      </select>

      {customMode && (
        <input
          type={isNumber ? "number" : "text"}
          value={matchedOption ? "" : textValue}
          autoFocus={!textValue}
          onChange={(event) => onChange(event.target.value)}
          placeholder="직접 입력"
        />
      )}
    </label>
  );
}

function AnalysisPanel({ mail, onAnalyze, onSave, onCreate, loading }: {
  mail: MailDetail;
  onAnalyze: () => void;
  onSave: (payload: unknown) => void;
  onCreate: (payload: unknown) => void;
  loading: boolean;
}) {
  const [form, setForm] = useState<MailDetail>(mail);
  const formRef = useRef<MailDetail>(mail);
  const sourceMailRef = useRef<MailDetail>(mail);
  const lastItemRef = useRef<HTMLDivElement | null>(null);
  const pendingItemScrollRef = useRef(false);
  const [productCatalog, setProductCatalog] = useState<ProductCatalog | null>(null);
  const draggedItemIndexRef = useRef<number | null>(null);
  const [productPickerOpen, setProductPickerOpen] = useState(false);
  const [productCatalogLoading, setProductCatalogLoading] = useState(false);
  const [productCatalogError, setProductCatalogError] = useState("");
  const [editingOrder, setEditingOrder] = useState<Record<number, string>>({});

  formRef.current = form;

  useEffect(() => {
    const previousSource = sourceMailRef.current;
    const currentForm = formRef.current;
    const switchedMail = previousSource.id !== mail.id;
    const hasUnsavedChanges = JSON.stringify(currentForm) !== JSON.stringify(previousSource);

    sourceMailRef.current = mail;
    if (switchedMail || !hasUnsavedChanges) {
      formRef.current = mail;
      setForm(mail);
    }
  }, [mail]);

  useEffect(() => {
    if (!pendingItemScrollRef.current) return;
    pendingItemScrollRef.current = false;
    window.requestAnimationFrame(() => {
      lastItemRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  }, [form.items.length]);

  useEffect(() => {
    let active = true;
    setProductCatalogLoading(true);
    setProductCatalogError("");
    api.productCatalog()
      .then((catalog) => {
        if (active) setProductCatalog(catalog);
      })
      .catch((error) => {
        if (active) setProductCatalogError(error instanceof Error ? error.message : String(error));
      })
      .finally(() => {
        if (active) setProductCatalogLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const missingFields = missingQuoteFields(form.items, productCatalog);

  function addCatalogProduct(product: ProductCatalogProduct) {
    const newItem: MailItem = {
      product_name: product.name,
      normalized_product: product.name,
      specification: null,
      spec_attributes: {},
      cost_price: null,
      evidence: {}
    };
    pendingItemScrollRef.current = true;
    setForm((current) => ({ ...current, items: [...current.items, newItem] }));
    setProductPickerOpen(false);
  }

  function addBlankProduct() {
    const newItem: MailItem = {
      product_name: "",
      normalized_product: null,
      specification: null,
      spec_attributes: {},
      cost_price: null,
      evidence: {}
    };
    pendingItemScrollRef.current = true;
    setForm((current) => ({ ...current, items: [...current.items, newItem] }));
    setProductPickerOpen(false);
  }

  function patchItem(index: number, patch: Partial<MailItem>) {
    const items = [...form.items];
    const current = items[index];
    items[index] = { ...current, ...patch };
    const updated = items[index];
    if (updated.quantity != null && updated.unit_price != null) {
      updated.amount = Math.round(Number(updated.quantity) * Number(updated.unit_price));
    } else if (updated.quantity == null || updated.unit_price == null) {
      updated.amount = null;
    }
    setForm({ ...form, items });
  }

  function removeItem(index: number) {
    setForm((current) => ({
      ...current,
      items: current.items.filter((_, itemIndex) => itemIndex !== index)
    }));
  }
  function startItemDrag(index: number) {
  draggedItemIndexRef.current = index;
}

function swapItems(targetIndex: number) {
  const sourceIndex = draggedItemIndexRef.current;

  if (
    sourceIndex == null ||
    sourceIndex === targetIndex
  ) {
    return;
  }

  setForm((current) => {
    const items = [...current.items];

    if (
      sourceIndex < 0 ||
      targetIndex < 0 ||
      sourceIndex >= items.length ||
      targetIndex >= items.length
    ) {
      return current;
    }

    // 드래그는 서로 위치 교환
    [items[sourceIndex], items[targetIndex]] = [
      items[targetIndex],
      items[sourceIndex],
    ];

    return {
      ...current,
      items,
    };
  });

  draggedItemIndexRef.current = null;
}

function finishItemDrag() {
  draggedItemIndexRef.current = null;
}

/**
 * 품목 번호를 변경했을 때 사용하는 함수
 *
 * 예:
 * 8번 → 1번
 *
 * 기존:
 * 1 A
 * 2 B
 * 3 C
 * ...
 * 8 H
 *
 * 변경:
 * 1 H
 * 2 A
 * 3 B
 * ...
 * 8 G
 */
function moveItemToPosition(
  sourceIndex: number,
  targetPosition: number
) {
  setForm((current) => {
    const items = [...current.items];

    if (
      targetPosition < 0 ||
      targetPosition >= items.length ||
      sourceIndex < 0 ||
      sourceIndex >= items.length
    ) {
      return current;
    }

    // 같은 위치라면 아무것도 하지 않음
    if (sourceIndex === targetPosition) {
      return current;
    }

    // 기존 위치에서 품목 제거
    const [movedItem] = items.splice(sourceIndex, 1);

    // 새로운 위치에 삽입
    items.splice(targetPosition, 0, movedItem);

    return {
      ...current,
      items,
    };
  });
}



  function normalizedProductKey(value?: string | null) {
    return String(value || "")
      .replace(/\s+/g, "")
      .toLocaleLowerCase("ko-KR");
  }

  function catalogProductFor(item: MailItem) {
    if (!productCatalog) return null;

    const targets = [item.normalized_product, item.product_name]
      .map((value) => normalizedProductKey(value))
      .filter(Boolean);

    if (!targets.length) return null;

    const products = productCatalog.categories.flatMap((group) => group.products);

    // 1순위: 정확히 같은 표준명/별칭
    for (const product of products) {
      const candidates = [product.name, ...(product.aliases || [])]
        .map((value) => normalizedProductKey(value))
        .filter(Boolean);

      if (targets.some((target) => candidates.includes(target))) {
        return product;
      }
    }

    // 2순위: AI가 "친환경 현수막", "고급 명함"처럼 수식어를 붙인 경우.
    // 배너/미니배너처럼 이름이 겹칠 수 있으므로 가장 긴 일치명을 선택한다.
    let best: { product: ProductCatalogProduct; score: number } | null = null;

    for (const product of products) {
      const candidates = [product.name, ...(product.aliases || [])]
        .map((value) => normalizedProductKey(value))
        .filter(Boolean);

      for (const target of targets) {
        for (const candidate of candidates) {
          if (candidate.length < 2) continue;
          if (target.includes(candidate) || candidate.includes(target)) {
            const score = Math.min(target.length, candidate.length);
            if (!best || score > best.score) {
              best = { product, score };
            }
          }
        }
      }
    }

    return best?.product ?? null;
  }

  function catalogFieldValue(
    item: MailItem,
    field: ProductCatalogProduct["fields"][number]
  ) {
    const legacyField = field.legacy_field as keyof MailItem | null | undefined;
    if (legacyField) {
      const legacyValue = item[legacyField];
      if (
        legacyValue != null
        && !(typeof legacyValue === "string" && !legacyValue.trim())
      ) {
        return legacyValue;
      }
    }
    return item.spec_attributes?.[field.key] ?? "";
  }

  function patchCatalogField(
    index: number,
    field: ProductCatalogProduct["fields"][number],
    rawValue: unknown
  ) {
    const item = form.items[index];
    const specAttributes = {
      ...(item.spec_attributes || {}),
      [field.key]: rawValue
    };

    const patch: Partial<MailItem> = {
      spec_attributes: specAttributes
    };

    const legacyField = field.legacy_field;
    if (legacyField === "quantity") {
      const text = Array.isArray(rawValue) ? rawValue.join(",") : String(rawValue ?? "").trim();
      const numeric = text === "" ? null : Number(text);
      patch.quantity = numeric == null || Number.isNaN(numeric) ? null : numeric;
    } else if (legacyField === "specification") {
      patch.specification = Array.isArray(rawValue)
        ? rawValue.join(", ")
        : String(rawValue ?? "").trim() || null;
    } else if (legacyField === "paper") {
      patch.paper = Array.isArray(rawValue)
        ? rawValue.join(", ")
        : String(rawValue ?? "").trim() || null;
    } else if (legacyField === "print_sides") {
      patch.print_sides = Array.isArray(rawValue)
        ? rawValue.join(", ")
        : String(rawValue ?? "").trim() || null;
    } else if (legacyField === "material") {
      patch.material = Array.isArray(rawValue)
        ? rawValue.join(", ")
        : String(rawValue ?? "").trim() || null;
    }

    patchItem(index, patch);
  }

  function analysisPayload() {
    return {
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
    };
  }

  function save() {
    onSave(analysisPayload());
  }

  return (
    <>
      {productPickerOpen && (
        <ProductPickerModal
          catalog={productCatalog}
          loading={productCatalogLoading}
          error={productCatalogError}
          onSelect={addCatalogProduct}
          onBlank={addBlankProduct}
          onClose={() => setProductPickerOpen(false)}
        />
      )}
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

      <div className="form-section"><h3>고객 정보</h3><div className="form-grid two"><Field label="기관명" value={form.customer_organization} onChange={(value) => setForm({ ...form, customer_organization: value })} /><Field label="담당자" value={form.customer_name} onChange={(value) => setForm({ ...form, customer_name: value })} /><Field label="이메일" value={form.customer_email} onChange={(value) => setForm({ ...form, customer_email: value })} /><Field label="전화번호" value={form.customer_phone} onChange={(value) => setForm({ ...form, customer_phone: value })} /><Field label="납품 장소" value={form.delivery_place} onChange={(value) => setForm({ ...form, delivery_place: value })} /><Field label="희망 일정" value={form.requested_date} onChange={(value) => setForm({ ...form, requested_date: value })} /></div></div>

      <div className="form-section">
        <div className="section-title"><h3>주문 품목</h3></div>
        {form.items.map((item, index) => {
          const catalogProduct = catalogProductFor(item);
          return (
            <div
  className="item-editor"
  ref={index === form.items.length - 1 ? lastItemRef : undefined}
  key={item.id ?? `new-${index}`}
  onDragOver={(event) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }}
  onDrop={(event) => {
    event.preventDefault();
    swapItems(index);
  }}
>
              <div className="item-editor-head">
  <div className="item-number-wrap">
  {/* 드래그 핸들 */}
  <div
    className="item-drag-handle"
    draggable
    onDragStart={(event) => {
      event.stopPropagation();

      startItemDrag(index);

      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData(
        "text/plain",
        String(index)
      );
    }}
    onDragEnd={(event) => {
      event.stopPropagation();
      finishItemDrag();
    }}
    title="드래그해서 품목 순서 변경"
  >
    <GripVertical size={14} />
  </div>

  {/* 품목 순서 */}
  <input
    type="number"
    min={1}
    max={form.items.length}
    value={
      editingOrder[index] ??
      String(index + 1)
    }
    className="item-order-input"
    aria-label={`${index + 1}번 품목 순서`}
    onFocus={() => {
      setEditingOrder((current) => ({
        ...current,
        [index]: String(index + 1),
      }));
    }}
    onChange={(event) => {
      setEditingOrder((current) => ({
        ...current,
        [index]: event.target.value,
      }));
    }}
    onKeyDown={(event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        event.currentTarget.blur();
      }
    }}
    onBlur={(event) => {
      const value = Number(event.currentTarget.value);

      // 빈 값 또는 잘못된 값이면 원래 번호로 복구
      if (
        !Number.isInteger(value) ||
        value < 1 ||
        value > form.items.length
      ) {
        setEditingOrder((current) => {
          const next = { ...current };
          delete next[index];
          return next;
        });

        return;
      }

      const targetPosition = value - 1;

      // 실제 품목 이동
      moveItemToPosition(
        index,
        targetPosition
      );

      setEditingOrder({});
    }}
  />
</div>
                <button
                  type="button"
                  className="item-delete-button"
                  onClick={() => {
                    const name = item.product_name?.trim() || `${index + 1}번째 품목`;
                    if (window.confirm(`'${name}' 품목을 삭제할까요?`)) {
                      removeItem(index);
                    }
                  }}
                  title="품목 삭제"
                >
                  <Trash2 size={14} />
                  삭제
                </button>
              </div>

              <div className="catalog-item-head">
                <Field
                  label="품목"
                  value={item.product_name}
                  onChange={(value) => patchItem(index, {
                    product_name: value,
                    normalized_product: value || null
                  })}
                />
                <span className={catalogProduct ? "catalog-match-badge matched" : "catalog-match-badge manual"}>
                  {catalogProduct ? "품목 카탈로그 적용" : "직접 입력 품목"}
                </span>
              </div>

              {catalogProduct ? (
                <div className="catalog-spec-section">
                  <div className="catalog-spec-title">
                    <strong>{catalogProduct.name} 사양</strong>
                    <span>선택하거나 직접 입력할 수 있습니다.</span>
                  </div>
                  <div className="catalog-spec-grid">
                    {catalogProduct.fields.map((field) => (
                      <CatalogSpecField
                        key={field.key}
                        field={field}
                        value={catalogFieldValue(item, field)}
                        onChange={(value) => patchCatalogField(index, field, value)}
                      />
                    ))}
                  </div>
                </div>
              ) : (
                <div className="manual-spec-section">
                  <div className="catalog-spec-title">
                    <strong>직접 입력 사양</strong>
                    <span>목록에 없는 품목은 필요한 내용을 자유롭게 입력하세요.</span>
                  </div>
                  <div className="form-grid two">
                    <Field label="규격 설명" value={item.specification} onChange={(value) => patchItem(index, { specification: value })} />
                    <NumberField label="수량" value={item.quantity} onChange={(value) => patchItem(index, { quantity: value })} />
                    <Field label="용지" value={item.paper} onChange={(value) => patchItem(index, { paper: value })} />
                    <Field label="단면·양면" value={item.print_sides} onChange={(value) => patchItem(index, { print_sides: value })} />
                    <Field label="재질" value={item.material} onChange={(value) => patchItem(index, { material: value })} />
                  </div>
                </div>
              )}

              <div className="catalog-price-section">
                <div className="form-grid two">
                  <NumberField
                    label="확정 단가"
                    value={item.unit_price}
                    onChange={(value) => patchItem(index, {
                      unit_price: value == null ? null : Math.round(value),
                      confirmed: value != null,
                      evidence: value == null
                        ? item.evidence
                        : {
                            ...item.evidence,
                            price: {
                              source: "manual",
                              type: "MANUAL",
                              reason: "담당자가 직접 입력한 단가"
                            }
                          }
                    })}
                  />
                  <ReadOnlyField label="공급금액" value={money(supplyAmount(item))} />
                </div>
              </div>

              {priceEvidence(item) && (
                <div className="price-evidence">
                  <span>단가 출처</span>
                  <strong>{priceEvidence(item)?.label}</strong>
                  {priceEvidence(item)?.score != null && <em>점수 {priceEvidence(item)?.score?.toFixed(1)}</em>}
                  <small title={priceEvidence(item)?.reference || priceEvidence(item)?.reason}>
                    {priceEvidence(item)?.reference || priceEvidence(item)?.reason}
                  </small>
                </div>
              )}

              <label className="field full">
                <span>디자인·문구 요청</span>
                <textarea
                  value={item.design_request || item.detail_text || ""}
                  onChange={(event) => patchItem(index, { design_request: event.target.value })}
                />
              </label>

              <div className="production-cost-section">
                <div className="production-cost-title">
                  <div>
                    <strong>제작 원가</strong>
                    <span>선택 입력 · 내부 관리용</span>
                  </div>
                  <small>고객 견적 금액에는 포함되지 않습니다.</small>
                </div>
                <NumberField
                  label="제작 원가(원)"
                  value={item.cost_price}
                  onChange={(value) => patchItem(index, {
                    cost_price: value == null ? null : Math.round(value)
                  })}
                />
              </div>
            </div>
          );
        })}
        {!form.items.length && <p className="muted">추출된 품목이 없습니다. AI 분석을 실행하거나 품목을 추가하세요.</p>}
        {!!form.items.length && <div className="analysis-quote-total"><span>분석 견적 합계</span><strong>{money(quoteTotal(form.items))}</strong></div>}
      </div>

      <div className="form-section"><h3>분석 요약</h3><textarea className="summary-input" value={form.summary || ""} onChange={(event) => setForm({ ...form, summary: event.target.value })} /></div>
      {missingFields.length > 0 && <p className="blocking-note">견적서 생성 전 필수 항목을 확인해 주세요: {missingFields.join(" / ")}</p>}
      <div className="action-bar">
  <button
    className="button secondary"
    onClick={() => setProductPickerOpen(true)}
  >
    <span>＋</span> 품목 추가
  </button>

  <button
    className="button secondary"
    onClick={save}
  >
    <Save size={17} /> 수정 저장
  </button>

  <button
    className="button primary"
    disabled={!form.items.length || missingFields.length > 0}
    onClick={() => onCreate(analysisPayload())}
  >
    <FileSpreadsheet size={17} /> 견적서 생성
  </button>
</div>
      </div>
    </>
  );
}

function ReviewRow({ issue, onResolve }: { issue: ReviewIssue; onResolve: (issue: ReviewIssue, value: unknown) => void }) {
  const [value, setValue] = useState("");
  const suggestion = issue.suggestions[0] as Record<string, unknown> | undefined;
  const suggestedValue = suggestion && typeof suggestion === "object" ? suggestion.value : suggestion;
  const suggestionMessage = suggestion && typeof suggestion === "object" && suggestion.message ? String(suggestion.message) : "";
  return (
    <div className={`review-row ${issue.severity}`}>
      <div><strong>{issue.message}</strong><small>{issue.code}</small></div>
      <div className="review-resolve">
        {suggestedValue != null && <button className="suggestion-chip" title={suggestionMessage} onClick={() => onResolve(issue, suggestedValue)}>{suggestion?.source === "quotation_history_db" ? "최근 주문 기준 예상" : "추천"} {String(suggestedValue)}</button>}
        <input placeholder="직접 입력" value={value} onChange={(event) => setValue(event.target.value)} />
        <button className="icon-button" disabled={!value} onClick={() => onResolve(issue, Number.isNaN(Number(value)) ? value : Number(value))}><CheckCircle2 size={17} /></button>
      </div>
    </div>
  );
}

function HistoryAndPricing({ companyHistory, history, prices }: { companyHistory: HistoryCandidate[]; history: HistoryCandidate[]; prices: PriceCandidate[] }) {
  const [tab, setTab] = useState<"company" | "history" | "price">("company");
  const [openingKey, setOpeningKey] = useState("");
  const [openNotice, setOpenNotice] = useState("");
  const [openError, setOpenError] = useState("");
  const historyRows = tab === "company" ? companyHistory : history;

  async function openHistoryRow(row: HistoryCandidate, index: number) {
    if (openingKey) return;
    const key = `${row.quotation_id}-${index}`;
    setOpeningKey(key);
    setOpenNotice("");
    setOpenError("");
    try {
      const result = await api.openHistorySource(row.source_file, row.source_sheet);
      setOpenNotice(result.navigation_supported && result.sheet
        ? `Excel에서 '${result.sheet}' 시트를 열었습니다.`
        : result.warning || "과거 견적 Excel 파일을 열었습니다.");
    } catch (err) {
      setOpenError(err instanceof Error ? err.message : String(err));
    } finally {
      setOpeningKey("");
    }
  }
  return (
    <div className="bottom-content">
      <div className="bottom-tabs"><button className={tab === "company" ? "active" : ""} onClick={() => setTab("company")}>동일 회사 견적 <span>{companyHistory.length}</span></button><button className={tab === "history" ? "active" : ""} onClick={() => setTab("history")}>동일 고객 과거 견적 <span>{history.length}</span></button><button className={tab === "price" ? "active" : ""} onClick={() => setTab("price")}>현재 단가 후보 <span>{prices.length}</span></button></div>
      {openNotice && <div className="history-open-message success"><CheckCircle2 size={13} />{openNotice}</div>}
      {openError && <div className="history-open-message error"><XCircle size={13} />{openError}</div>}
      <div className="table-wrap">
        {tab !== "price" ? (
          <table><thead><tr><th>견적일</th><th>고객</th><th>품목</th><th>규격</th><th>수량</th><th>단가</th><th>근거</th></tr></thead><tbody>{historyRows.map((row, index) => { const key = `${row.quotation_id}-${index}`; return <tr className="history-clickable-row" key={key} role="button" tabIndex={0} title={`${row.source_file} · ${row.source_sheet} 시트 열기`} onClick={() => void openHistoryRow(row, index)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); void openHistoryRow(row, index); } }}><td>{openingKey === key ? <Loader2 className="spin" size={13} /> : row.quotation_date || "-"}</td><td>{row.customer_name || "-"}</td><td>{row.product_name}</td><td>{row.specification || "-"}</td><td>{row.quantity ?? "-"}</td><td>{money(row.unit_price)}</td><td title={row.source_file}><span className="history-source-link"><FileSpreadsheet size={13} />{row.source_sheet}</span></td></tr>; })}{!historyRows.length && <tr><td colSpan={7} className="empty-cell">{tab === "company" ? "동일 회사의 과거 견적이 없습니다." : "동일 고객의 과거 견적이 없습니다."}</td></tr>}</tbody></table>
        ) : (
          <table><thead><tr><th>품목</th><th>단가</th><th>총금액</th><th>출처</th><th>점수</th><th>판정</th><th>근거</th></tr></thead><tbody>{prices.map((row, index) => { const sourceLabels: Record<string, string> = { history: "기존 견적", price_table: "단가표", mail: "메일", unresolved: "미확정" }; return <tr key={`${row.item_id}-${index}`}><td>{row.product_name}</td><td>{money(row.unit_price)}</td><td>{money(row.amount)}</td><td>{sourceLabels[row.source] ?? row.source}</td><td>{row.score.toFixed(1)}</td><td><span className={row.needs_review ? "match candidate" : "match exact"}>{row.unit_price == null ? "미확정" : row.needs_review ? "검토 필요" : "자동 적용"}</span></td><td title={row.reference || row.reason}>{row.reference || row.reason}</td></tr>; })}{!prices.length && <tr><td colSpan={7} className="empty-cell">가격 후보가 없습니다.</td></tr>}</tbody></table>
        )}
      </div>
    </div>
  );
}

function DraftView({ drafts, reload, runAction }: { drafts: Draft[]; reload: () => Promise<void>; runAction: (action: () => Promise<unknown>, success: string, refresh?: boolean) => Promise<void> }) {
  const [employees, setEmployees] = useState<Record<number, string>>({});
  const [subjects, setSubjects] = useState<Record<number, string>>({});
  const [savingSubjectIds, setSavingSubjectIds] = useState<Set<number>>(new Set());
  const [sendingIds, setSendingIds] = useState<Set<number>>(new Set());

  const employeeFor = (draftId: number) => employees[draftId] || "kim_heejung";

  const subjectFor = (draft: Draft) =>
    subjects[draft.id]
    ?? draft.email_subject
    ?? `[열린문디자인] 요청하신 견적서를 보내드립니다 - ${draft.customer_name}`;

  const MANUAL_SUBJECT_VALUE = "__manual__";

  function subjectPresets(draft: Draft) {
    return [
      {
        label: "요청하신 견적서",
        value: `[열린문디자인] 요청하신 견적서를 보내드립니다 - ${draft.customer_name}`
      },
      {
        label: "견적서 전달",
        value: `[열린문디자인] 견적서 전달드립니다 - ${draft.customer_name}`
      },
      {
        label: "견적 관련 회신",
        value: `[열린문디자인] 견적 관련 회신드립니다 - ${draft.customer_name}`
      }
    ];
  }

  async function saveDraftSubject(draft: Draft) {
    const subject = subjectFor(draft).trim();

    if (!subject) {
      window.alert("발송 제목을 입력해주세요.");
      return false;
    }

    if (savingSubjectIds.has(draft.id)) {
      return false;
    }

    setSavingSubjectIds((current) =>
      new Set(current).add(draft.id)
    );

    try {
      await runAction(
        () => api.updateDraftEmail(
          draft.id,
          { email_subject: subject }
        ),
        "발송 제목을 저장했습니다.",
        false
      );

      setSubjects((current) => ({
        ...current,
        [draft.id]: subject
      }));

      await reload();
      return true;
    } finally {
      setSavingSubjectIds((current) => {
        const next = new Set(current);
        next.delete(draft.id);
        return next;
      });
    }
  }

  async function persistSubjectBeforeSend(draft: Draft) {
    const subject = subjectFor(draft).trim();

    if (!subject) {
      throw new Error("발송 제목을 입력해주세요.");
    }

    await api.updateDraftEmail(
      draft.id,
      { email_subject: subject }
    );
  }
  async function runDraftSend(draftId: number, action: () => Promise<unknown>) {
    if (sendingIds.has(draftId)) return;
    setSendingIds((current) => new Set(current).add(draftId));
    try {
      await runAction(action, "견적서를 승인하고 답장을 발송했습니다.", false);
      await reload();
    } finally {
      setSendingIds((current) => {
        const next = new Set(current);
        next.delete(draftId);
        return next;
      });
    }
  }
  return (
    <div className="page-card">
      <div className="page-card-header"><div><h2>견적서 목록</h2><p>같은 메일에서 다시 생성하면 기존 견적서가 업데이트됩니다.</p></div><button className="icon-button" onClick={() => void reload()}><RefreshCw size={18} /></button></div>
      <div className="draft-grid">
        {drafts.map((draft) => (
          <article className={`draft-card ${sendingIds.has(draft.id) ? "is-sending" : ""}`} key={draft.id}>
            {sendingIds.has(draft.id) && <div className="draft-sending-overlay" role="status" aria-live="polite"><Loader2 className="spin" size={34} /><strong>메일 발송 중...</strong><span>견적서 첨부와 보낸메일함 저장을 처리하고 있습니다.</span></div>}
            <div className="draft-top"><span className={`status status-${draft.status.toLowerCase()}`}>{draft.status}</span><small>#{draft.id}</small></div>
            <h3>{draft.customer_name}</h3><p>{draft.items.map((item) => item.product_name).join(", ") || "품목 없음"}</p><strong>{money(draft.total_amount)}</strong>

            <div className="draft-email-subject">
              <div className="draft-email-subject-head">
                <span>고객 발송 제목</span>
                <small>
                  {draft.status === "SENT"
                    ? "발송 완료 후에는 수정할 수 없습니다."
                    : "예시를 선택하거나 직접 수정할 수 있습니다."}
                </small>
              </div>

              <div className="draft-email-subject-controls">
                <select
                  value=""
                  disabled={draft.status === "SENT"}
                  onChange={(event) => {
                    const selected = event.target.value;
                    if (!selected) return;

                    setSubjects((current) => ({
                      ...current,
                      [draft.id]: selected === MANUAL_SUBJECT_VALUE ? "" : selected
                    }));
                  }}
                  aria-label="발송 제목 예시 선택"
                >
                  <option value="">제목 예시 선택</option>
                  {subjectPresets(draft).map((preset) => (
                    <option key={preset.label} value={preset.value}>
                      {preset.label}
                    </option>
                  ))}
                  <option value={MANUAL_SUBJECT_VALUE}>직접입력</option>
                </select>

                <input
                  value={subjectFor(draft)}
                  disabled={draft.status === "SENT"}
                  maxLength={300}
                  onChange={(event) =>
                    setSubjects((current) => ({
                      ...current,
                      [draft.id]: event.target.value
                    }))
                  }
                  placeholder="고객에게 보낼 메일 제목"
                />

                <button
                  type="button"
                  className="button secondary compact"
                  disabled={
                    draft.status === "SENT"
                    || savingSubjectIds.has(draft.id)
                    || !subjectFor(draft).trim()
                  }
                  onClick={() => void saveDraftSubject(draft)}
                >
                  {savingSubjectIds.has(draft.id)
                    ? <Loader2 className="spin" size={14} />
                    : <Save size={14} />}
                  제목 저장
                </button>
              </div>
            </div>

            <div className="draft-actions"><a className="button secondary compact" href={`/api/quotations/${draft.id}/file`}><FileDown size={16} /> Excel</a><a className="button secondary compact" href={`/api/quotations/${draft.id}/customer-pdf`} target="_blank" rel="noreferrer"><FileDown size={16} /> PDF</a>{(draft.status === "DRAFT" || draft.status === "FAILED") && <><select value={employeeFor(draft.id)} onChange={(event) => setEmployees({ ...employees, [draft.id]: event.target.value })} aria-label="답장 담당 직원"><option value="moon_jeongseon">업무총괄 문정선 대표이사</option><option value="shin_woohyun">관리부서 신우현 주임</option><option value="kwon_jihye">회계담당 권지혜 대리</option><option value="kim_heejung">관리부 김희정 과장</option></select><button className="button primary compact" onClick={() => { const employee = employeeFor(draft.id); const label = ({ moon_jeongseon: "문정선 대표이사", shin_woohyun: "신우현 주임", kwon_jihye: "권지혜 대리", kim_heejung: "김희정 과장" } as Record<string, string>)[employee]; const warning = draft.status === "FAILED" ? "먼저 고객 수신함을 확인해 주세요. 서버 응답 전에 연결이 끊겼다면 이미 전송됐을 수 있습니다. 그래도 다시 발송할까요?" : `${label} 명의로 견적서를 승인하고 고객에게 답장할까요?`; if (window.confirm(warning)) void runDraftSend(draft.id, async () => {
                    await persistSubjectBeforeSend(draft);
                    return api.approveDraft(draft.id, employee);
                  }); }}><Send size={16} /> {draft.status === "FAILED" ? "발송 재시도" : "승인 및 답장"}</button></>}{draft.status === "APPROVED" && <button className="button danger compact" onClick={() => void runDraftSend(draft.id, async () => {
              await persistSubjectBeforeSend(draft);
              return api.sendDraft(draft.id);
            })}><Send size={16} /> 발송 재시도</button>}<button className="button danger compact" onClick={() => { if (window.confirm("이 견적서를 삭제할까요?")) void runAction(() => api.deleteDraft(draft.id), "견적서를 삭제했습니다.", false).then(reload); }}><Trash2 size={16} /> 삭제</button></div>
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
      <section className="page-card"><h2>연결 상태</h2><div className="status-grid"><StatusTile label={status.ai_provider === "anthropic" ? "Claude" : "OpenAI"} enabled={Boolean(status.ai_configured)} /><StatusTile label="Daum 메일" enabled={Boolean(status.mail_configured)} /><StatusTile label="실제 발송" enabled={Boolean(status.live_send_enabled)} warning /></div><div className="path-list">{Object.entries(paths).map(([key, value]) => <div key={key}><span>{key}</span><code>{value || "미설정"}</code></div>)}</div></section>
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
