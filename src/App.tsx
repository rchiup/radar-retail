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
  | "error";

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

type CampaignSummary = {
  total: number;
  pending: number;
  running: number;
  processed: number;
  compliant: number;
  non_compliant: number;
  no_price: number;
  error: number;
  evidence: number;
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
  summary: CampaignSummary;
  products: Product[];
  import?: {
    filename: string;
    count: number;
    unsupported_retailers: string[];
  };
};

type ApiMessage = { detail?: string };
type Tab = "products" | "evidence";

const retailerLabels: Record<string, string> = {
  easy_cl: "Easy",
  falabella_cl: "Falabella",
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
};

const campaignStatusLabels: Record<Campaign["status"], string> = {
  draft: "Sin productos",
  ready: "Lista para ejecutar",
  running: "Capturando evidencias",
  completed: "Completada",
  completed_with_errors: "Completada con alertas",
};

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
  const response = await fetch(url, init);
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
          : status === "error" || status === "no_price"
            ? CircleAlert
            : Clock3;
  return (
    <span className={`status-badge status-${status}`}>
      <Icon size={14} className={status === "running" ? "spin" : ""} aria-hidden="true" />
      {statusLabels[status]}
    </span>
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
  const [actionBusy, setActionBusy] = useState<"create" | "import" | "run" | "retry" | null>(null);
  const [notice, setNotice] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const [tab, setTab] = useState<Tab>("products");
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | ProductStatus>("all");
  const [showCreate, setShowCreate] = useState(false);
  const [preview, setPreview] = useState<Product | null>(null);
  const [form, setForm] = useState({
    name: "",
    client: "",
    start_date: localIsoDate(),
    end_date: localIsoDate(7),
  });
  const fileInput = useRef<HTMLInputElement>(null);

  async function loadCampaigns(preferredId?: string) {
    const payload = await api<{ campaigns: Campaign[] }>("/api/campaigns");
    setCampaigns(payload.campaigns);
    const selectedId = preferredId ?? activeId ?? payload.campaigns[0]?.id ?? null;
    setActiveId(selectedId);
    setActive(payload.campaigns.find((campaign) => campaign.id === selectedId) ?? payload.campaigns[0] ?? null);
    return payload.campaigns;
  }

  async function refreshCampaign(campaignId: string) {
    const payload = await api<Campaign>(`/api/campaigns/${campaignId}`);
    setActive(payload);
    setCampaigns((current) => current.map((campaign) => (campaign.id === payload.id ? payload : campaign)));
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
    if (!activeId || active?.status !== "running") return;
    const timer = window.setInterval(() => {
      void refreshCampaign(activeId).catch(() => {
        setNotice({ tone: "error", text: "Perdimos la actualización de progreso. Intentaremos nuevamente." });
      });
    }, 1800);
    return () => window.clearInterval(timer);
  }, [activeId, active?.status]);

  useEffect(() => {
    if (active?.status === "completed") {
      setNotice({ tone: "success", text: "Campaña completada. Las evidencias y el reporte están listos." });
    }
  }, [active?.status]);

  async function selectCampaign(campaign: Campaign) {
    setActiveId(campaign.id);
    setActive(campaign);
    setTab("products");
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
      const unsupported = imported.import?.unsupported_retailers.length
        ? ` Revisa retailers no soportados: ${imported.import.unsupported_retailers.join(", ")}.`
        : "";
      setNotice({ tone: unsupported ? "error" : "success", text: `${imported.summary.total} productos cargados.${unsupported}` });
    } catch (error) {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : "No pudimos leer el archivo." });
    } finally {
      if (fileInput.current) fileInput.current.value = "";
      setActionBusy(null);
    }
  }

  async function executeCampaign(onlyFailed = false) {
    if (!active) return;
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

  const filteredProducts = useMemo(() => {
    if (!active) return [];
    const normalized = query.trim().toLowerCase();
    return active.products.filter((product) => {
      const matchesText = !normalized || [product.sku, product.name, product.retailer]
        .some((value) => value.toLowerCase().includes(normalized));
      return matchesText && (statusFilter === "all" || product.status === statusFilter);
    });
  }, [active, query, statusFilter]);

  const evidenceProducts = active?.products.filter((product) => product.screenshot_url) ?? [];
  const progress = active?.summary.total ? Math.round((active.summary.processed / active.summary.total) * 100) : 0;
  const issueCount = (active?.summary.error ?? 0) + (active?.summary.no_price ?? 0);
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
                </div>
              </section>

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
                    <button className={tab === "products" ? "active" : ""} onClick={() => setTab("products")} type="button" role="tab">
                      <FileSpreadsheet size={17} /> Productos <span>{active.summary.total}</span>
                    </button>
                    <button className={tab === "evidence" ? "active" : ""} onClick={() => setTab("evidence")} type="button" role="tab">
                      <ImageIcon size={17} /> Evidencias <span>{active.summary.evidence}</span>
                    </button>
                  </div>
                  <div className="export-actions">
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

                {tab === "products" ? (
                  <>
                    <div className="table-toolbar">
                      <label className="search-box">
                        <Search size={17} />
                        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Buscar por SKU, producto o retail" aria-label="Buscar productos" />
                      </label>
                      <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as "all" | ProductStatus)} aria-label="Filtrar por estado">
                        <option value="all">Todos los estados</option>
                        {Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                      </select>
                    </div>
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
                      <div className="table-wrap">
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
                                <td><span className="retailer-chip">{retailerLabels[product.retailer] ?? product.retailer}</span></td>
                                <td>{money.format(product.regular_price)}</td>
                                <td><strong>{money.format(product.promo_price)}</strong></td>
                                <td>{product.detected_price === null ? <span className="muted">—</span> : <strong>{money.format(product.detected_price)}</strong>}</td>
                                <td className={product.difference === null ? "" : product.difference <= 0 ? "difference-good" : "difference-bad"}>
                                  {product.difference === null ? "—" : `${product.difference > 0 ? "+" : ""}${money.format(product.difference)}`}
                                </td>
                                <td><StatusBadge status={product.status} /></td>
                                <td>
                                  {product.screenshot_url ? (
                                    <button className="evidence-button" type="button" onClick={() => setPreview(product)}><Eye size={16} /> Ver</button>
                                  ) : product.error ? (
                                    <span className="error-hint" title={product.error}>Ver error</span>
                                  ) : <span className="muted">Pendiente</span>}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                        {filteredProducts.length === 0 && <div className="no-results">No encontramos productos con esos filtros.</div>}
                      </div>
                    )}
                  </>
                ) : evidenceProducts.length ? (
                  <div className="evidence-grid">
                    {evidenceProducts.map((product) => (
                      <button className="evidence-card" key={product.id} type="button" onClick={() => setPreview(product)}>
                        <div className="evidence-image"><img src={product.screenshot_url ?? ""} alt={`Evidencia SKU ${product.sku}`} loading="lazy" /></div>
                        <div><span>{product.evidence_source === "google_reference" ? "Referencia Google · baja confianza" : (retailerLabels[product.retailer] ?? product.retailer)}</span><strong>SKU {product.sku}</strong><small>{formatDateTime(product.captured_at)}</small></div>
                        <ExternalLink size={16} />
                      </button>
                    ))}
                  </div>
                ) : (
                  <div className="panel-empty compact-empty"><div><ImageIcon size={27} /></div><h2>Aún no hay evidencias</h2><p>Ejecuta la campaña en modo Browser para generar un pantallazo verificable por SKU.</p></div>
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

      {preview && preview.screenshot_url && (
        <div className="modal-backdrop preview-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && setPreview(null)}>
          <section className="preview-modal" role="dialog" aria-modal="true" aria-label={`Evidencia SKU ${preview.sku}`}>
            <header>
              <div><span>{retailerLabels[preview.retailer] ?? preview.retailer}</span><strong>SKU {preview.sku}</strong><small>{formatDateTime(preview.captured_at)}</small></div>
              <div>
                <a className="button button-secondary" href={preview.screenshot_url} download><Download size={16} /> Descargar</a>
                <button className="modal-close inline" type="button" onClick={() => setPreview(null)} aria-label="Cerrar"><X size={19} /></button>
              </div>
            </header>
            <div className="preview-scroll"><img src={preview.screenshot_url} alt={`Pantallazo completo del SKU ${preview.sku}`} /></div>
          </section>
        </div>
      )}
    </div>
  );
}

export { App };
