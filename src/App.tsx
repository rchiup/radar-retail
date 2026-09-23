import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  Archive,
  ArrowRight,
  CalendarRange,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Clock3,
  Download,
  ExternalLink,
  Eye,
  FileDown,
  FileSpreadsheet,
  Image as ImageIcon,
  LoaderCircle,
  PackageCheck,
  Play,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Store,
  UploadCloud,
  X,
  XCircle,
} from "lucide-react";

type ProductStatus =
  | "pending"
  | "running"
  | "compliant"
  | "non_compliant"
  | "captured_unverified"
  | "no_price"
  | "error"
  | "blocked"
  | "needs_review";

type Product = {
  id: string;
  sku: string;
  name: string;
  category: string;
  retailer: string;
  url: string;
  regular_price: number;
  promo_price: number;
  detected_price: number | null;
  difference: number | null;
  status: ProductStatus;
  captured_at: string | null;
  screenshot_url: string | null;
  fallback_screenshot_url?: string | null;
  evidence_source?: "retailer" | "google_reference" | string;
  evidence_confidence?: "official" | "low" | string;
  ip_used: string | null;
  error: string | null;
};

type PriceObservation = {
  id: string;
  sku: string;
  retailer: string;
  observed_at: string;
  price: number | null;
  status: ProductStatus;
  evidence_source: string;
  screenshot_url: string | null;
};

type CampaignSummary = {
  total: number;
  pending: number;
  running: number;
  processed: number;
  compliant: number;
  non_compliant: number;
  no_price: number;
  error: number;
  blocked?: number;
  needs_review?: number;
  evidence: number;
  evidence_official?: number;
  evidence_google?: number;
  by_retailer?: Record<string, number>;
};

type Campaign = {
  id: string;
  name: string;
  client: string;
  start_date: string;
  end_date: string;
  status: "draft" | "ready" | "running" | "completed" | "completed_with_errors";
  source_filename: string | null;
  last_run_at: string | null;
  last_error: string | null;
  run_started_at?: string | null;
  run_ended_at?: string | null;
  capture_mode?: "local" | "cloud" | string | null;
  summary: CampaignSummary;
  products: Product[];
  import?: {
    filename: string;
    count: number;
    unsupported_retailers: string[];
    retailers_found?: string[];
    retailers_count?: number;
    by_retailer?: Record<string, number>;
    empty_sku?: number;
    empty_url?: number;
    invalid_links_count?: number;
    claimed_retails_in_filename?: number | null;
    filename_retail_mismatch?: boolean;
    summary_message?: string;
  };
};

type ApiMessage = { detail?: string };
type Tab = "products" | "review" | "evidence";
type EvidenceFilter = "all" | "official" | "structured" | "google" | "missing";
type IssueFilter = "all" | "actionable" | "blocked" | "no_price" | "bad_url" | "missing_evidence";

const retailerLabels: Record<string, string> = {
  abc_cl: "ABC",
  claro_cl: "Claro",
  easy_cl: "Easy",
  falabella_cl: "Falabella",
  hites_cl: "Hites",
  jumbo_cl: "Jumbo",
  paris_cl: "Paris",
  ripley_cl: "Ripley",
  sodimac_cl: "Sodimac",
  tottus_cl: "Tottus",
  walmart_cl: "Lider",
};

const statusLabels: Record<ProductStatus, string> = {
  pending: "Pendiente",
  running: "Capturando",
  compliant: "Cumple",
  non_compliant: "No cumple",
  captured_unverified: "Sin objetivo",
  no_price: "Sin precio",
  error: "Error",
  blocked: "Bloqueado",
  needs_review: "Requiere revisión",
};

const campaignStatusLabels: Record<Campaign["status"], string> = {
  draft: "Sin productos",
  ready: "Lista para ejecutar",
  running: "Capturando evidencias",
  completed: "Completada",
  completed_with_errors: "Completada con alertas",
};

const reviewStatuses = new Set<ProductStatus>([
  "non_compliant",
  "no_price",
  "error",
  "blocked",
  "needs_review",
]);

function hasEvidence(product: Product) {
  return Boolean(product.screenshot_url || product.fallback_screenshot_url);
}

function evidenceKind(product: Product): Exclude<EvidenceFilter, "all"> {
  if (product.evidence_source === "google_reference" || (!product.screenshot_url && product.fallback_screenshot_url)) return "google";
  if (product.evidence_source === "retailer_structured") return "structured";
  if (product.screenshot_url) return "official";
  return "missing";
}

function isBadUrl(product: Product) {
  const error = (product.error ?? "").toLocaleLowerCase("es");
  return ["url", "link", "búsqueda", "busqueda", "categoría", "categoria", "no pertenece", "404"]
    .some((token) => error.includes(token));
}

function isBlocked(product: Product) {
  const error = (product.error ?? "").toLocaleLowerCase("es");
  return product.status === "blocked" || ["captcha", "cloudflare", "403", "bloque", "access denied"]
    .some((token) => error.includes(token));
}

function needsReview(product: Product) {
  const finishedWithoutEvidence = !["pending", "running"].includes(product.status) && !hasEvidence(product);
  return reviewStatuses.has(product.status) || finishedWithoutEvidence;
}

function evidenceLabel(product: Product) {
  const kind = evidenceKind(product);
  if (kind === "google") return "Referencia Google · baja confianza";
  if (kind === "structured") return "Datos estructurados retail · confianza media";
  if (kind === "official") return `${retailerLabels[product.retailer] ?? product.retailer} · evidencia oficial`;
  return "Sin evidencia";
}

function reviewReason(product: Product) {
  if (isBadUrl(product)) return "El link necesita corrección antes de volver a ejecutar.";
  if (isBlocked(product)) return "El sitio bloqueó o desafió la captura automática.";
  if (product.status === "non_compliant") return "El precio observado es mayor al precio acordado.";
  if (product.status === "no_price") return "Se abrió el producto, pero no se pudo leer el precio.";
  if (!hasEvidence(product)) return "La corrida terminó sin generar una evidencia visual.";
  if (product.status === "needs_review") return "La captura existe, pero requiere validación manual.";
  return product.error || "Revisa este resultado antes de cerrar la campaña.";
}

const money = new Intl.NumberFormat("es-CL", {
  style: "currency",
  currency: "CLP",
  maximumFractionDigits: 0,
});

const dateFormatter = new Intl.DateTimeFormat("es-CL", {
  day: "2-digit",
  month: "short",
  year: "numeric",
});

const dateTimeFormatter = new Intl.DateTimeFormat("es-CL", {
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

function localIsoDate(offsetDays = 0) {
  const value = new Date();
  value.setDate(value.getDate() + offsetDays);
  return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}

function formatDate(value: string) {
  return dateFormatter.format(new Date(`${value}T12:00:00`));
}

function formatDateTime(value: string | null) {
  return value ? dateTimeFormatter.format(new Date(value)) : "Aún no ejecutada";
}

async function api<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch {
    throw new Error("El backend no responde. ¿Está corriendo en http://127.0.0.1:8001?");
  }
  const contentType = response.headers.get("content-type") ?? "";
  const payload = contentType.includes("application/json") ? await response.json() : null;
  if (!response.ok) {
    throw new Error((payload as ApiMessage | null)?.detail ?? "No pudimos completar la operación.");
  }
  return payload as T;
}

function Logo() {
  return (
    <div className="brand">
      <div className="brand-symbol" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
      <div>
        <strong>Radar Retail</strong>
        <small>Evidencia comercial</small>
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: ProductStatus }) {
  const Icon =
    status === "compliant"
      ? CheckCircle2
      : status === "non_compliant"
        ? XCircle
        : status === "running"
          ? LoaderCircle
          : status === "error" || status === "no_price" || status === "blocked" || status === "needs_review"
            ? CircleAlert
            : Clock3;
  return (
    <span className={`status-badge status-${status}`}>
      <Icon size={14} className={status === "running" ? "spin" : ""} aria-hidden="true" />
      {statusLabels[status]}
    </span>
  );
}

function ProductMobileCard({
  product,
  onPreview,
  onRetailClick,
}: {
  product: Product;
  onPreview: (product: Product) => void;
  onRetailClick: (retailer: string) => void;
}) {
  return (
    <article className="product-mobile-card">
      <div className="mobile-card-head">
        <div>
          <strong>{product.sku || "Sin SKU"}</strong>
          <span>{product.name}</span>
        </div>
        <button className="retailer-chip retailer-chip-button" type="button" onClick={() => onRetailClick(product.retailer)}>
          {retailerLabels[product.retailer] ?? product.retailer}
        </button>
      </div>
      <div className="mobile-price-grid">
        <div><span>PVP</span><strong>{money.format(product.regular_price)}</strong></div>
        <div><span>Campaña</span><strong>{money.format(product.promo_price)}</strong></div>
        <div><span>Observado</span><strong>{product.detected_price === null ? "—" : money.format(product.detected_price)}</strong></div>
      </div>
      <div className="mobile-card-result">
        <StatusBadge status={product.status} />
        {product.difference !== null && (
          <strong className={product.difference <= 0 ? "difference-good" : "difference-bad"}>
            {product.difference > 0 ? "+" : ""}{money.format(product.difference)}
          </strong>
        )}
      </div>
      {product.error && <p className="mobile-card-error">{product.error}</p>}
      <div className="mobile-card-actions">
        {hasEvidence(product) ? (
          <button className="button button-secondary" type="button" onClick={() => onPreview(product)}>
            <Eye size={16} /> Ver evidencia
          </button>
        ) : (
          <a className="button button-secondary" href={product.url} target="_blank" rel="noreferrer">
            <ExternalLink size={16} /> Abrir producto
          </a>
        )}
      </div>
    </article>
  );
}

function Metric({ icon: Icon, label, value, helper, tone = "neutral" }: {
  icon: typeof Store;
  label: string;
  value: string;
  helper: string;
  tone?: "neutral" | "success" | "danger";
}) {
  return (
    <article className={`metric metric-${tone}`}>
      <div className="metric-icon"><Icon size={19} aria-hidden="true" /></div>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{helper}</small>
      </div>
    </article>
  );
}

function EmptyCampaign({ onCreate }: { onCreate: () => void }) {
  return (
    <section className="empty-campaign">
      <div className="empty-visual" aria-hidden="true">
        <FileSpreadsheet size={34} />
        <span><Check size={16} /></span>
      </div>
      <p className="eyebrow">Tu centro de evidencias</p>
      <h1>Crea tu primera campaña</h1>
      <p>Sube el maestro de aportes, captura cada SKU y entrega un respaldo verificable en un solo flujo.</p>
      <button className="button button-primary" onClick={onCreate} type="button">
        <Plus size={18} /> Nueva campaña
      </button>
      <div className="empty-steps">
        <span><b>1</b> Crea la campaña</span>
        <ChevronRight size={16} />
        <span><b>2</b> Sube el Excel</span>
        <ChevronRight size={16} />
        <span><b>3</b> Descarga evidencias</span>
      </div>
    </section>
  );
}

function App() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [active, setActive] = useState<Campaign | null>(null);
  const [apiStatus, setApiStatus] = useState<"checking" | "online" | "offline">("checking");
  const [browserAvailable, setBrowserAvailable] = useState(false);
  const [pageLoading, setPageLoading] = useState(true);
  const [actionBusy, setActionBusy] = useState<"create" | "import" | "run" | "retry" | "cancel" | null>(null);
  const [notice, setNotice] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const [tab, setTab] = useState<Tab>("products");
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | ProductStatus>("all");
  const [retailerFilter, setRetailerFilter] = useState("all");
  const [evidenceFilter, setEvidenceFilter] = useState<EvidenceFilter>("all");
  const [issueFilter, setIssueFilter] = useState<IssueFilter>("all");
  const [refreshing, setRefreshing] = useState(false);
  const [lastRefreshedAt, setLastRefreshedAt] = useState<Date | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [preview, setPreview] = useState<Product | null>(null);
  const [history, setHistory] = useState<PriceObservation[]>([]);
  const [form, setForm] = useState({
    name: "",
    client: "",
    start_date: localIsoDate(),
    end_date: localIsoDate(7),
  });
  const fileInput = useRef<HTMLInputElement>(null);
  const activeIdRef = useRef<string | null>(null);
  const refreshInFlight = useRef(false);

  useEffect(() => {
    activeIdRef.current = activeId;
  }, [activeId]);

  useEffect(() => {
    if (!preview || !active) {
      setHistory([]);
      return;
    }
    void api<{ observations: PriceObservation[] }>(
      `/api/campaigns/${active.id}/price-history?sku=${encodeURIComponent(preview.sku)}&retailer=${encodeURIComponent(preview.retailer)}`,
    ).then((payload) => setHistory(payload.observations)).catch(() => setHistory([]));
  }, [preview?.id, active?.id]);

  async function loadCampaigns(preferredId?: string) {
    const payload = await api<{ campaigns: Campaign[] }>("/api/campaigns");
    setCampaigns(payload.campaigns);
    const selectedId = preferredId ?? activeId ?? payload.campaigns[0]?.id ?? null;
    activeIdRef.current = selectedId;
    setActiveId(selectedId);
    setActive(payload.campaigns.find((campaign) => campaign.id === selectedId) ?? payload.campaigns[0] ?? null);
    return payload.campaigns;
  }

  async function refreshCampaign(campaignId: string) {
    const payload = await api<Campaign>(`/api/campaigns/${campaignId}`);
    if (activeIdRef.current === payload.id) setActive(payload);
    setCampaigns((current) => current.map((campaign) => (campaign.id === payload.id ? payload : campaign)));
    setLastRefreshedAt(new Date());
    return payload;
  }

  useEffect(() => {
    async function bootstrap() {
      try {
        const [health] = await Promise.all([
          api<{ browser_available: boolean }>("/api/health"),
          loadCampaigns(),
        ]);
        setBrowserAvailable(health.browser_available);
        setApiStatus("online");
      } catch (error) {
        setApiStatus("offline");
        setNotice({ tone: "error", text: error instanceof Error ? error.message : "La API no está disponible." });
      } finally {
        setPageLoading(false);
      }
    }
    void bootstrap();
    // The initial bootstrap intentionally runs once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!activeId) return;
    let stopped = false;
    let timer: number | undefined;

    const schedule = (delay: number) => {
      timer = window.setTimeout(() => void poll(), delay);
    };
    const poll = async () => {
      if (stopped) return;
      if (document.visibilityState === "hidden" || refreshInFlight.current) {
        schedule(active?.status === "running" ? 2000 : 30000);
        return;
      }
      refreshInFlight.current = true;
      try {
        await refreshCampaign(activeId);
      } catch {
        // El siguiente ciclo vuelve a intentar sin interrumpir el trabajo del usuario.
      } finally {
        refreshInFlight.current = false;
        if (!stopped) schedule(active?.status === "running" ? 2000 : 30000);
      }
    };
    const refreshVisible = () => {
      if (document.visibilityState === "visible" && !refreshInFlight.current) {
        if (timer) window.clearTimeout(timer);
        void poll();
      }
    };

    schedule(active?.status === "running" ? 1200 : 30000);
    window.addEventListener("focus", refreshVisible);
    document.addEventListener("visibilitychange", refreshVisible);
    return () => {
      stopped = true;
      if (timer) window.clearTimeout(timer);
      window.removeEventListener("focus", refreshVisible);
      document.removeEventListener("visibilitychange", refreshVisible);
    };
  }, [activeId, active?.status]);

  useEffect(() => {
    if (active?.status === "completed" || active?.status === "completed_with_errors") {
      setNotice({
        tone: "success",
        text: active.status === "completed"
          ? "Campaña completada. Las evidencias y el reporte están listos."
          : "Campaña terminada con alertas. Revisa la cola antes de descargar la entrega.",
      });
    }
  }, [active?.status]);

  function clearFilters() {
    setQuery("");
    setStatusFilter("all");
    setRetailerFilter("all");
    setEvidenceFilter("all");
    setIssueFilter("all");
  }

  function selectRetailer(retailer: string) {
    setRetailerFilter((current) => current === retailer ? "all" : retailer);
  }

  async function manualRefresh() {
    if (!activeId || refreshInFlight.current) return;
    setRefreshing(true);
    refreshInFlight.current = true;
    try {
      await refreshCampaign(activeId);
    } catch (error) {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : "No pudimos actualizar los resultados." });
    } finally {
      refreshInFlight.current = false;
      setRefreshing(false);
    }
  }

  async function selectCampaign(campaign: Campaign) {
    activeIdRef.current = campaign.id;
    setActiveId(campaign.id);
    setActive(campaign);
    setTab("products");
    clearFilters();
    setNotice(null);
    try {
      await refreshCampaign(campaign.id);
    } catch (error) {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : "No pudimos abrir la campaña." });
    }
  }

  async function createCampaign(event: FormEvent) {
    event.preventDefault();
    setActionBusy("create");
    setNotice(null);
    try {
      const created = await api<Campaign>("/api/campaigns", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      await loadCampaigns(created.id);
      setActive(created);
      setShowCreate(false);
      setForm({ name: "", client: "", start_date: localIsoDate(), end_date: localIsoDate(7) });
      setNotice({ tone: "success", text: "Campaña creada. Ahora carga el maestro de aportes." });
    } catch (error) {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : "No pudimos crear la campaña." });
    } finally {
      setActionBusy(null);
    }
  }

  async function importFile(file?: File) {
    if (!file || !active) return;
    setActionBusy("import");
    setNotice(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("replace", "true");
      const imported = await api<Campaign>(`/api/campaigns/${active.id}/import`, {
        method: "POST",
        body: formData,
      });
      setActive(imported);
      setCampaigns((current) => current.map((campaign) => (campaign.id === imported.id ? imported : campaign)));
      clearFilters();
      const unsupported = imported.import?.unsupported_retailers.length
        ? ` Revisa retailers no soportados: ${imported.import.unsupported_retailers.join(", ")}.`
        : "";
      const mismatch = imported.import?.filename_retail_mismatch
        ? ` Ojo: el archivo se llama como si tuviera ${imported.import.claimed_retails_in_filename} retails, pero detectamos ${imported.import.retailers_count}.`
        : "";
      const empties = [
        imported.import?.empty_sku ? `${imported.import.empty_sku} sin SKU` : null,
        imported.import?.empty_url ? `${imported.import.empty_url} sin URL` : null,
        imported.import?.invalid_links_count ? `${imported.import.invalid_links_count} links inválidos` : null,
      ].filter(Boolean).join(", ");
      const detail = empties ? ` Detalle: ${empties}.` : "";
      const tone = unsupported || mismatch || imported.import?.invalid_links_count ? "error" : "success";
      setNotice({
        tone,
        text: `${imported.import?.summary_message ?? `${imported.summary.total} productos cargados.`}${mismatch}${unsupported}${detail}`,
      });
    } catch (error) {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : "No pudimos leer el archivo." });
    } finally {
      if (fileInput.current) fileInput.current.value = "";
      setActionBusy(null);
    }
  }

  async function executeCampaign(onlyFailed = false) {
    if (!active) return;
    if (active.status === "running" || actionBusy === "run" || actionBusy === "retry") {
      setNotice({ tone: "error", text: "La campaña ya está en curso. Evita el doble clic." });
      return;
    }
    setActionBusy(onlyFailed ? "retry" : "run");
    setNotice(null);
    try {
      const started = await api<Campaign>(`/api/campaigns/${active.id}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          method: browserAvailable ? "playwright" : "curl",
          screenshot: browserAvailable,
          only_failed: onlyFailed,
          capture_mode: "local",
          google_fallback: true,
        }),
      });
      setActive(started);
      setCampaigns((current) => current.map((campaign) => (campaign.id === started.id ? started : campaign)));
      setNotice({ tone: "success", text: onlyFailed ? "Reintentando productos con problemas." : "Captura iniciada. Puedes seguir el progreso aquí." });
    } catch (error) {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : "No pudimos iniciar la captura." });
    } finally {
      setActionBusy(null);
    }
  }


  async function cancelCampaign() {
    if (!active || active.status !== "running") return;
    setActionBusy("cancel");
    setNotice(null);
    try {
      const stopped = await api<Campaign>(`/api/campaigns/${active.id}/cancel`, { method: "POST" });
      setActive(stopped);
      setCampaigns((current) => current.map((campaign) => (campaign.id === stopped.id ? stopped : campaign)));
      setNotice({ tone: "success", text: "Cancelación pedida. Se detiene al terminar el lote actual." });
    } catch (error) {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : "No pudimos cancelar la campaña." });
    } finally {
      setActionBusy(null);
    }
  }

  const filteredProducts = useMemo(() => {
    if (!active) return [];
    const normalized = query.trim().toLocaleLowerCase("es");
    return active.products.filter((product) => {
      const matchesText = !normalized || [product.sku, product.name, product.retailer, retailerLabels[product.retailer] ?? ""]
        .some((value) => value.toLocaleLowerCase("es").includes(normalized));
      const matchesStatus = statusFilter === "all" || product.status === statusFilter;
      const matchesRetailer = retailerFilter === "all" || product.retailer === retailerFilter;
      const matchesEvidence = evidenceFilter === "all" || evidenceKind(product) === evidenceFilter;
      const matchesIssue = issueFilter === "all"
        || (issueFilter === "actionable" && needsReview(product))
        || (issueFilter === "blocked" && isBlocked(product))
        || (issueFilter === "no_price" && (product.status === "no_price" || (product.detected_price === null && !["pending", "running"].includes(product.status))))
        || (issueFilter === "bad_url" && isBadUrl(product))
        || (issueFilter === "missing_evidence" && !hasEvidence(product));
      return matchesText && matchesStatus && matchesRetailer && matchesEvidence && matchesIssue;
    });
  }, [active, query, statusFilter, retailerFilter, evidenceFilter, issueFilter]);

  const reviewProducts = filteredProducts.filter(needsReview);
  const allReviewProducts = active?.products.filter(needsReview) ?? [];
  const evidenceProducts = filteredProducts.filter(hasEvidence);
  const retailerStats = useMemo(() => {
    if (!active) return [];
    const stats = new Map<string, { total: number; evidence: number; issues: number }>();
    active.products.forEach((product) => {
      const current = stats.get(product.retailer) ?? { total: 0, evidence: 0, issues: 0 };
      current.total += 1;
      if (hasEvidence(product)) current.evidence += 1;
      if (needsReview(product)) current.issues += 1;
      stats.set(product.retailer, current);
    });
    return [...stats.entries()].sort(([a], [b]) => (retailerLabels[a] ?? a).localeCompare(retailerLabels[b] ?? b, "es"));
  }, [active]);
  const reviewStats = {
    blocked: allReviewProducts.filter(isBlocked).length,
    noPrice: allReviewProducts.filter((product) => product.status === "no_price").length,
    badUrl: allReviewProducts.filter(isBadUrl).length,
    missing: allReviewProducts.filter((product) => !hasEvidence(product)).length,
  };
  const hasActiveFilters = Boolean(query.trim()) || statusFilter !== "all" || retailerFilter !== "all" || evidenceFilter !== "all" || issueFilter !== "all";
  const progress = active?.summary.total ? Math.round((active.summary.processed / active.summary.total) * 100) : 0;
  const issueCount = (active?.summary.error ?? 0) + (active?.summary.no_price ?? 0) + (active?.summary.blocked ?? 0) + (active?.summary.needs_review ?? 0);
  const runningProduct = active?.products.find((product) => product.status === "running");

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Logo />

        <button className="button button-lime sidebar-new" type="button" onClick={() => setShowCreate(true)}>
          <Plus size={17} /> Nueva campaña
        </button>

        <div className="sidebar-label">Campañas</div>
        <nav className="campaign-nav" aria-label="Campañas">
          {campaigns.length === 0 && <p className="sidebar-empty">Todavía no hay campañas.</p>}
          {campaigns.map((campaign) => (
            <button
              className={campaign.id === activeId ? "campaign-link active" : "campaign-link"}
              key={campaign.id}
              onClick={() => void selectCampaign(campaign)}
              type="button"
            >
              <span className="campaign-link-icon"><Archive size={16} /></span>
              <span>
                <strong>{campaign.name}</strong>
                <small>{campaign.summary.total} SKU · {campaignStatusLabels[campaign.status]}</small>
              </span>
              <ChevronRight size={15} />
            </button>
          ))}
        </nav>

        <div className="sidebar-foot">
          <div className={`service-state ${apiStatus}`}><span /> Motor {apiStatus === "online" ? "conectado" : apiStatus === "offline" ? "desconectado" : "revisando"}</div>
          <small>Capturas con sello de fecha, precio, URL e IP.</small>
        </div>
      </aside>

      <main className="main-area">
        <header className="topbar">
          <div className="mobile-brand"><Logo /></div>
          <div>
            <span className="topbar-kicker">Workspace</span>
            <strong>Operaciones comerciales</strong>
          </div>
          <div className="operator">
            <span>RC</span>
            <div><strong>Raimundo</strong><small>Administrador</small></div>
          </div>
        </header>

        <div className="workspace">
          {notice && (
            <div className={`notice notice-${notice.tone}`} role="status" aria-live="polite">
              {notice.tone === "success" ? <CheckCircle2 size={18} /> : <CircleAlert size={18} />}
              <span>{notice.text}</span>
              <button type="button" aria-label="Cerrar mensaje" onClick={() => setNotice(null)}><X size={16} /></button>
            </div>
          )}

          {pageLoading ? (
            <div className="page-loader"><LoaderCircle className="spin" /> Preparando tu workspace…</div>
          ) : !active ? (
            <EmptyCampaign onCreate={() => setShowCreate(true)} />
          ) : (
            <>
              <section className="campaign-head">
                <div className="campaign-copy">
                  <div className="headline-meta">
                    <span className={`campaign-state campaign-state-${active.status}`}><span />{campaignStatusLabels[active.status]}</span>
                    {active.client && <span className="client-label">{active.client}</span>}
                  </div>
                  <h1>{active.name}</h1>
                  <div className="campaign-dates">
                    <CalendarRange size={17} />
                    <span>{formatDate(active.start_date)} — {formatDate(active.end_date)}</span>
                    <i />
                    <span>Última ejecución: {formatDateTime(active.last_run_at)}</span>
                    {active.run_started_at && <><i /><span>Inicio corrida: {formatDateTime(active.run_started_at)}</span></>}
                    {active.run_ended_at && <><i /><span>Fin corrida: {formatDateTime(active.run_ended_at)}</span></>}
                    <i /><span>Modo: {active.capture_mode === "cloud" ? "Cloud" : "Local"}</span>
                  </div>
                </div>
                <div className="head-actions">
                  <input
                    ref={fileInput}
                    type="file"
                    className="sr-only"
                    accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    onChange={(event) => void importFile(event.target.files?.[0])}
                  />
                  <button className="button button-secondary" onClick={() => fileInput.current?.click()} disabled={actionBusy === "import" || active.status === "running"} type="button">
                    {actionBusy === "import" ? <LoaderCircle className="spin" size={17} /> : <UploadCloud size={17} />}
                    {active.summary.total ? "Cambiar archivo" : "Cargar Excel"}
                  </button>
                  <button className="button button-primary" onClick={() => void executeCampaign(false)} disabled={!active.summary.total || active.status === "running" || actionBusy !== null} type="button">
                    {active.status === "running" || actionBusy === "run" ? <LoaderCircle className="spin" size={17} /> : <Play size={17} />}
                    {active.status === "running" ? "Capturando…" : "Ejecutar campaña"}
                  </button>
                  {active.status === "running" && (
                    <button className="button button-secondary" onClick={() => void cancelCampaign()} disabled={actionBusy === "cancel"} type="button">
                      {actionBusy === "cancel" ? <LoaderCircle className="spin" size={17} /> : <X size={17} />}
                      Cancelar
                    </button>
                  )}
                </div>
              </section>

              {retailerStats.length > 0 && (
                <section className="retailer-summary" aria-label="Resumen por retail">
                  <button
                    type="button"
                    className={`retailer-pill ${retailerFilter === "all" ? "active" : ""}`}
                    onClick={() => setRetailerFilter("all")}
                    aria-pressed={retailerFilter === "all"}
                  >
                    <Store size={15} />
                    <strong>Todos</strong>
                    <span>{active.summary.total} SKU</span>
                  </button>
                  {retailerStats.map(([retailer, stats]) => (
                    <button
                      key={retailer}
                      type="button"
                      className={`retailer-pill ${retailerFilter === retailer ? "active" : ""}`}
                      onClick={() => selectRetailer(retailer)}
                      aria-pressed={retailerFilter === retailer}
                    >
                      <Store size={15} />
                      <strong>{retailerLabels[retailer] ?? retailer}</strong>
                      <span>{stats.evidence}/{stats.total} evid.</span>
                      {stats.issues > 0 && <small>{stats.issues} alerta{stats.issues === 1 ? "" : "s"}</small>}
                    </button>
                  ))}
                  {active.import?.filename_retail_mismatch && (
                    <article className="retailer-pill warn">
                      <CircleAlert size={15} />
                      <strong>Nombre vs contenido</strong>
                      <span>Archivo sugiere {active.import.claimed_retails_in_filename}, hay {active.import.retailers_count}</span>
                    </article>
                  )}
                </section>
              )}

              <section className="workflow-card" aria-label="Flujo de campaña">
                <div className={active.summary.total ? "workflow-step done" : "workflow-step current"}>
                  <span>{active.summary.total ? <Check size={15} /> : "1"}</span>
                  <div><strong>Maestro cargado</strong><small>{active.source_filename ?? "Carga el formato de Experto Retail"}</small></div>
                </div>
                <ArrowRight size={17} />
                <div className={active.status === "running" ? "workflow-step current" : active.summary.processed ? "workflow-step done" : "workflow-step"}>
                  <span>{active.summary.processed ? <Check size={15} /> : "2"}</span>
                  <div><strong>Captura automática</strong><small>{active.status === "running" ? `Procesando ${runningProduct?.sku ?? "siguiente SKU"}` : "Screenshots por SKU y retail"}</small></div>
                </div>
                <ArrowRight size={17} />
                <div className={active.summary.evidence ? "workflow-step done" : "workflow-step"}>
                  <span>{active.summary.evidence ? <Check size={15} /> : "3"}</span>
                  <div><strong>Entrega auditable</strong><small>ZIP de imágenes + reporte CSV</small></div>
                </div>
              </section>

              <section className="metrics-grid" aria-label="Resumen de campaña">
                <Metric icon={Store} label="SKU cargados" value={String(active.summary.total)} helper={active.source_filename ?? "Sin archivo"} />
                <Metric icon={PackageCheck} label="Capturados" value={`${active.summary.processed}/${active.summary.total}`} helper={`${progress}% del maestro`} />
                <Metric icon={ShieldCheck} label="Cumplen" value={String(active.summary.compliant)} helper="Precio observado ≤ acordado" tone="success" />
                <Metric icon={CircleAlert} label="Revisar" value={String(active.summary.non_compliant + issueCount)} helper={`${issueCount} errores o sin precio`} tone={active.summary.non_compliant + issueCount ? "danger" : "neutral"} />
              </section>

              {(active.status === "running" || active.summary.processed > 0) && (
                <section className="progress-card">
                  <div>
                    <span>{active.status === "running" ? "Captura en curso" : "Resultado de la última corrida"}</span>
                    <strong>{progress}%</strong>
                  </div>
                  <div className="progress-track"><span style={{ width: `${progress}%` }} /></div>
                  <div className="progress-detail">
                    <span>{active.summary.processed} procesados</span>
                    <span className="dot-separator" />
                    <span>{active.summary.evidence} evidencias</span>
                    {runningProduct && <><span className="dot-separator" /><span>Ahora: {runningProduct.sku}</span></>}
                  </div>
                </section>
              )}

              <section className="data-panel">
                <div className="panel-tabs">
                  <div role="tablist" aria-label="Contenido de campaña">
                    <button className={tab === "products" ? "active" : ""} onClick={() => setTab("products")} type="button" role="tab" aria-selected={tab === "products"}>
                      <FileSpreadsheet size={17} /> Productos <span>{active.summary.total}</span>
                    </button>
                    <button className={tab === "review" ? "active" : ""} onClick={() => setTab("review")} type="button" role="tab" aria-selected={tab === "review"}>
                      <CircleAlert size={17} /> Por revisar <span>{allReviewProducts.length}</span>
                    </button>
                    <button className={tab === "evidence" ? "active" : ""} onClick={() => setTab("evidence")} type="button" role="tab" aria-selected={tab === "evidence"}>
                      <ImageIcon size={17} /> Evidencias <span>{active.summary.evidence}</span>
                    </button>
                  </div>
                  <div className="export-actions">
                    <button className="button button-quiet refresh-button" type="button" onClick={() => void manualRefresh()} disabled={refreshing} title="Actualizar resultados ahora">
                      <RefreshCw className={refreshing ? "spin" : ""} size={16} /> Actualizar
                    </button>
                    {issueCount > 0 && active.status !== "running" && (
                      <button className="button button-quiet" type="button" onClick={() => void executeCampaign(true)} disabled={actionBusy !== null}>
                        {actionBusy === "retry" ? <LoaderCircle className="spin" size={16} /> : <RefreshCw size={16} />} Reintentar {issueCount}
                      </button>
                    )}
                    <a className={`button button-quiet ${!active.summary.total ? "disabled" : ""}`} href={`/api/campaigns/${active.id}/report.csv`} download aria-disabled={!active.summary.total}>
                      <FileDown size={16} /> Reporte
                    </a>
                    <a className={`button button-dark ${!active.summary.evidence ? "disabled" : ""}`} href={`/api/campaigns/${active.id}/evidence.zip`} download aria-disabled={!active.summary.evidence}>
                      <Download size={16} /> Descargar ZIP
                    </a>
                  </div>
                </div>

                {active.products.length > 0 && (
                  <>
                    <div className="table-toolbar">
                      <label className="search-box">
                        <Search size={17} />
                        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Buscar SKU, producto o retail" aria-label="Buscar productos" />
                      </label>
                      <div className="filter-controls">
                        <select value={retailerFilter} onChange={(event) => setRetailerFilter(event.target.value)} aria-label="Filtrar por retail">
                          <option value="all">Todos los retail</option>
                          {retailerStats.map(([retailer]) => <option key={retailer} value={retailer}>{retailerLabels[retailer] ?? retailer}</option>)}
                        </select>
                        <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as "all" | ProductStatus)} aria-label="Filtrar por estado">
                        <option value="all">Todos los estados</option>
                        {Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                        </select>
                        <select value={evidenceFilter} onChange={(event) => setEvidenceFilter(event.target.value as EvidenceFilter)} aria-label="Filtrar por tipo de evidencia">
                          <option value="all">Toda evidencia</option>
                          <option value="official">Pantallazo oficial</option>
                          <option value="structured">Datos del retail</option>
                          <option value="google">Referencia Google</option>
                          <option value="missing">Sin evidencia</option>
                        </select>
                        <select value={issueFilter} onChange={(event) => setIssueFilter(event.target.value as IssueFilter)} aria-label="Filtrar por problema">
                          <option value="all">Todos los problemas</option>
                          <option value="actionable">Requiere acción</option>
                          <option value="blocked">Bloqueado / CAPTCHA</option>
                          <option value="no_price">Sin precio</option>
                          <option value="bad_url">Link incorrecto</option>
                          <option value="missing_evidence">Sin pantallazo</option>
                        </select>
                        {hasActiveFilters && <button className="clear-filters" type="button" onClick={clearFilters}>Limpiar</button>}
                      </div>
                    </div>
                    <div className="filter-summary" aria-live="polite">
                      <span><strong>{filteredProducts.length}</strong> de {active.products.length} productos</span>
                      <span>{lastRefreshedAt ? `Actualizado ${lastRefreshedAt.toLocaleTimeString("es-CL", { hour: "2-digit", minute: "2-digit" })}` : "Actualización automática activa"}</span>
                    </div>
                  </>
                )}

                {tab === "products" ? (
                  <>
                    {active.products.length === 0 ? (
                      <div className="panel-empty">
                        <div><UploadCloud size={27} /></div>
                        <h2>Carga el maestro de aportes</h2>
                        <p>Aceptamos Excel o CSV con las columnas SKU, Link, PVP y PVP Descuento. El nombre de cada hoja define el retail.</p>
                        <button className="button button-primary" type="button" onClick={() => fileInput.current?.click()}>
                          <UploadCloud size={17} /> Seleccionar archivo
                        </button>
                      </div>
                    ) : (
                      <>
                        <div className="table-wrap product-table-view">
                          <table>
                            <thead>
                              <tr>
                                <th>SKU / producto</th><th>Retail</th><th>PVP</th><th>Precio campaña</th>
                                <th>Observado</th><th>Diferencia</th><th>Resultado</th><th>Evidencia</th>
                              </tr>
                            </thead>
                            <tbody>
                              {filteredProducts.map((product) => (
                                <tr key={product.id}>
                                  <td className="product-cell"><strong>{product.sku || "Sin SKU"}</strong><span>{product.name}</span></td>
                                  <td><button className="retailer-chip retailer-chip-button" type="button" onClick={() => selectRetailer(product.retailer)}>{retailerLabels[product.retailer] ?? product.retailer}</button></td>
                                  <td>{money.format(product.regular_price)}</td>
                                  <td><strong>{money.format(product.promo_price)}</strong></td>
                                  <td>{product.detected_price === null ? <span className="muted">—</span> : <strong>{money.format(product.detected_price)}</strong>}</td>
                                  <td className={product.difference === null ? "" : product.difference <= 0 ? "difference-good" : "difference-bad"}>
                                    {product.difference === null ? "—" : `${product.difference > 0 ? "+" : ""}${money.format(product.difference)}`}
                                  </td>
                                  <td><StatusBadge status={product.status} /></td>
                                  <td>
                                    {hasEvidence(product) ? (
                                      <button className="evidence-button" type="button" onClick={() => setPreview(product)}>
                                        <Eye size={16} /> {evidenceKind(product) === "google" ? "Google" : evidenceKind(product) === "structured" ? "Datos retail" : "Ver"}
                                      </button>
                                    ) : product.error ? (
                                      <span className="error-hint" title={product.error}>Ver error</span>
                                    ) : <span className="muted">Pendiente</span>}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                        <div className="product-card-list">
                          {filteredProducts.map((product) => <ProductMobileCard key={product.id} product={product} onPreview={setPreview} onRetailClick={selectRetailer} />)}
                        </div>
                        {filteredProducts.length === 0 && <div className="no-results">No encontramos productos con esos filtros. <button type="button" onClick={clearFilters}>Limpiar filtros</button></div>}
                      </>
                    )}
                  </>
                ) : tab === "review" ? (
                  allReviewProducts.length ? (
                    <div className="review-layout">
                      <div className="review-overview" aria-label="Resumen de alertas">
                        <button type="button" onClick={() => setIssueFilter("actionable")} className={issueFilter === "actionable" ? "active" : ""}><strong>{allReviewProducts.length}</strong><span>Total por revisar</span></button>
                        <button type="button" onClick={() => setIssueFilter("blocked")} className={issueFilter === "blocked" ? "active" : ""}><strong>{reviewStats.blocked}</strong><span>Bloqueados</span></button>
                        <button type="button" onClick={() => setIssueFilter("no_price")} className={issueFilter === "no_price" ? "active" : ""}><strong>{reviewStats.noPrice}</strong><span>Sin precio</span></button>
                        <button type="button" onClick={() => setIssueFilter("bad_url")} className={issueFilter === "bad_url" ? "active" : ""}><strong>{reviewStats.badUrl}</strong><span>Links malos</span></button>
                        <button type="button" onClick={() => setIssueFilter("missing_evidence")} className={issueFilter === "missing_evidence" ? "active" : ""}><strong>{reviewStats.missing}</strong><span>Sin evidencia</span></button>
                      </div>
                      <div className="review-list">
                        {reviewProducts.map((product) => (
                          <article className="review-card" key={product.id}>
                            <div className="review-card-main">
                              <div className="review-card-title">
                                <button className="retailer-chip retailer-chip-button" type="button" onClick={() => selectRetailer(product.retailer)}>{retailerLabels[product.retailer] ?? product.retailer}</button>
                                <StatusBadge status={product.status} />
                              </div>
                              <strong>SKU {product.sku || "sin identificar"}</strong>
                              <span>{product.name}</span>
                              <p>{reviewReason(product)}</p>
                              {product.error && <code>{product.error}</code>}
                            </div>
                            <div className="review-prices">
                              <span>Objetivo <strong>{money.format(product.promo_price)}</strong></span>
                              <span>Observado <strong>{product.detected_price === null ? "—" : money.format(product.detected_price)}</strong></span>
                            </div>
                            <div className="review-actions">
                              {hasEvidence(product) && <button className="button button-secondary" type="button" onClick={() => setPreview(product)}><Eye size={16} /> Ver evidencia</button>}
                              <a className="button button-quiet" href={product.url} target="_blank" rel="noreferrer"><ExternalLink size={16} /> Abrir producto</a>
                            </div>
                          </article>
                        ))}
                        {reviewProducts.length === 0 && <div className="no-results">No hay alertas con estos filtros. <button type="button" onClick={clearFilters}>Ver todas</button></div>}
                      </div>
                    </div>
                  ) : (
                    <div className="panel-empty compact-empty review-clear"><div><CheckCircle2 size={27} /></div><h2>Todo está listo</h2><p>No hay productos que necesiten revisión manual.</p></div>
                  )
                ) : evidenceProducts.length ? (
                  <div className="evidence-grid">
                    {evidenceProducts.map((product) => (
                      <button className="evidence-card" key={product.id} type="button" onClick={() => setPreview(product)}>
                        <div className="evidence-image"><img src={product.screenshot_url || product.fallback_screenshot_url || ""} alt={`Evidencia SKU ${product.sku}`} loading="lazy" /></div>
                        <div><span>{evidenceLabel(product)}</span><strong>SKU {product.sku}</strong><small>{formatDateTime(product.captured_at)}</small></div>
                        <ExternalLink size={16} />
                      </button>
                    ))}
                  </div>
                ) : (
                  <div className="panel-empty compact-empty"><div><ImageIcon size={27} /></div><h2>{hasActiveFilters ? "No hay evidencias con esos filtros" : "Aún no hay evidencias"}</h2><p>{hasActiveFilters ? "Prueba limpiando los filtros para ver el resto de la campaña." : "Ejecuta la campaña para generar pantallazos y respaldos auditables por SKU."}</p>{hasActiveFilters && <button className="button button-secondary" type="button" onClick={clearFilters}>Limpiar filtros</button>}</div>
                )}
              </section>
            </>
          )}
        </div>
      </main>

      {showCreate && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && setShowCreate(false)}>
          <section className="modal" role="dialog" aria-modal="true" aria-labelledby="create-title">
            <button className="modal-close" type="button" onClick={() => setShowCreate(false)} aria-label="Cerrar"><X size={19} /></button>
            <div className="modal-icon"><CalendarRange size={22} /></div>
            <p className="eyebrow">Nueva operación</p>
            <h2 id="create-title">Crear campaña</h2>
            <p className="modal-copy">Define la vigencia comercial. Después podrás cargar el maestro de SKU.</p>
            <form onSubmit={(event) => void createCampaign(event)}>
              <label>Nombre de campaña<input required minLength={2} autoFocus value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="Ej. Cyber Septiembre" /></label>
              <label>Cliente o marca <span>Opcional</span><input value={form.client} onChange={(event) => setForm({ ...form, client: event.target.value })} placeholder="Ej. Macrotel" /></label>
              <div className="form-grid">
                <label>Fecha de inicio<input required type="date" value={form.start_date} onChange={(event) => setForm({ ...form, start_date: event.target.value })} /></label>
                <label>Fecha de término<input required type="date" min={form.start_date} value={form.end_date} onChange={(event) => setForm({ ...form, end_date: event.target.value })} /></label>
              </div>
              <div className="modal-actions">
                <button className="button button-secondary" type="button" onClick={() => setShowCreate(false)}>Cancelar</button>
                <button className="button button-primary" type="submit" disabled={actionBusy === "create"}>
                  {actionBusy === "create" ? <LoaderCircle className="spin" size={17} /> : <Plus size={17} />} Crear campaña
                </button>
              </div>
            </form>
          </section>
        </div>
      )}

      {preview && hasEvidence(preview) && (
        <div className="modal-backdrop preview-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && setPreview(null)}>
          <section className="preview-modal" role="dialog" aria-modal="true" aria-label={`Evidencia SKU ${preview.sku}`}>
            <header>
              <div><span>{evidenceLabel(preview)}</span><strong>SKU {preview.sku}</strong><small>{formatDateTime(preview.captured_at)}</small></div>
              <div>
                <a className="button button-secondary" href={preview.screenshot_url || preview.fallback_screenshot_url || ""} download><Download size={16} /> Descargar</a>
                <button className="modal-close inline" type="button" onClick={() => setPreview(null)} aria-label="Cerrar"><X size={19} /></button>
              </div>
            </header>
            <div className="preview-scroll"><img src={preview.screenshot_url || preview.fallback_screenshot_url || ""} alt={`Pantallazo completo del SKU ${preview.sku}`} /></div>
            <section className="price-history" aria-label="Historial de precios">
              <div className="price-history-heading"><strong>Historial de este SKU</strong><span>{history.length} observaciones</span></div>
              {history.length === 0 ? <p className="muted">Todavía no hay observaciones históricas.</p> : (
                <div className="price-history-list">
                  {history.slice(0, 8).map((observation) => (
                    <div className="price-history-row" key={observation.id}>
                      <span>{formatDateTime(observation.observed_at)}</span>
                      <strong>{observation.price === null ? "Sin precio" : money.format(observation.price)}</strong>
                      <small>{observation.evidence_source === "google_reference" ? "Referencia Google" : observation.evidence_source === "retailer_structured" ? "Datos estructurados retail" : "Retail"}</small>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </section>
        </div>
      )}
    </div>
  );
}

export { App };
