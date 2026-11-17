import { useEffect, useRef, useState } from "react";
import {
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  BarChart3,
  CheckCircle2,
  Download,
  FileText,
  Layers3,
  LoaderCircle,
  Package,
  Printer,
  Search,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
  UploadCloud,
} from "lucide-react";
import {
  Brief,
  ComparableGroup,
  currency,
  downloadFile,
  Intelligence,
  InventoryItem,
  retailNames,
  riskLabels,
  View,
} from "./intelligence";

type Request = <T>(url: string, init?: RequestInit) => Promise<T>;
type Props = {
  campaign: {
    id: string;
    name: string;
    is_demo?: boolean | number;
    products: { sku: string; retailer: string }[];
  };
  view: View;
  request: Request;
  onNavigate: (view: View) => void;
  onAudit: (sku?: string) => void;
};
export function TrendChart({
  values,
  secondary,
  labels,
}: {
  values: number[];
  secondary?: number[];
  labels?: string[];
}) {
  const all = [...values, ...(secondary || [])],
    minimum = Math.min(...all) * 0.94,
    maximum = Math.max(...all) * 1.04;
  const path = (data: number[]) =>
    data
      .map(
        (value, index) =>
          `${index === 0 ? "M" : "L"}${48 + (index * 590) / Math.max(data.length - 1, 1)},${190 - ((value - minimum) / Math.max(maximum - minimum, 1)) * 145}`,
      )
      .join(" ");
  return (
    <div className="trend-chart">
      <svg
        viewBox="0 0 690 235"
        role="img"
        aria-label="Evolución de precios observados"
      >
        <defs>
          <linearGradient id="chart-area" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#6558df" stopOpacity=".16" />
            <stop offset="100%" stopColor="#6558df" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, 1, 2, 3].map((i) => (
          <g key={i}>
            <line
              x1="48"
              x2="640"
              y1={40 + i * 50}
              y2={40 + i * 50}
              stroke="#e8ebf0"
              strokeDasharray="4 5"
            />
            <text x="0" y={44 + i * 50} fill="#8b90a2" fontSize="10">
              {Math.round((maximum - ((maximum - minimum) * i) / 3) / 1000)}k
            </text>
          </g>
        ))}
        {values.length > 1 && (
          <path
            d={`${path(values)} L638,195 L48,195 Z`}
            fill="url(#chart-area)"
          />
        )}
        <path
          d={path(values)}
          fill="none"
          stroke="#6558df"
          strokeWidth="3"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        {secondary && (
          <path
            d={path(secondary)}
            fill="none"
            stroke="#28a49a"
            strokeWidth="2.5"
            strokeDasharray="6 5"
          />
        )}
        {values.map((value, index) => (
          <circle
            key={index}
            cx={48 + (index * 590) / Math.max(values.length - 1, 1)}
            cy={
              190 - ((value - minimum) / Math.max(maximum - minimum, 1)) * 145
            }
            r="3.5"
            fill="white"
            stroke="#6558df"
            strokeWidth="2"
          />
        ))}
        {(labels || values.map((_, i) => `S${i + 1}`)).map((label, index) => (
          <text
            key={index}
            x={48 + (index * 590) / Math.max(values.length - 1, 1)}
            y="222"
            textAnchor="middle"
            fill="#8b90a2"
            fontSize="10"
          >
            {label}
          </text>
        ))}
      </svg>
    </div>
  );
}
export function IntelligenceModule({
  campaign,
  view,
  request,
  onNavigate,
  onAudit,
}: Props) {
  const [intel, setIntel] = useState<Intelligence | null>(null),
    [groups, setGroups] = useState<ComparableGroup[]>([]),
    [inventory, setInventory] = useState<InventoryItem[]>([]),
    [brief, setBrief] = useState<Brief | null>(null),
    [query, setQuery] = useState(""),
    [risk, setRisk] = useState("all"),
    [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState(""),
    [noticeError, setNoticeError] = useState(false),
    [selected, setSelected] = useState(""),
    [selectedOffer, setSelectedOffer] = useState(""),
    [history, setHistory] = useState<
      { observed_at: string; price: number | null }[]
    >([]);
  const input = useRef<HTMLInputElement>(null);
  const isDemo = Boolean(campaign.is_demo);
  async function load() {
    setLoading(true);
    try {
      const [i, c, s, b] = await Promise.all([
        request<Intelligence>(`/api/campaigns/${campaign.id}/intelligence`),
        request<{ groups: ComparableGroup[] }>(
          `/api/campaigns/${campaign.id}/comparables`,
        ),
        request<{ items: InventoryItem[] }>(
          `/api/campaigns/${campaign.id}/inventory`,
        ),
        request<Brief>(`/api/campaigns/${campaign.id}/brief`),
      ]);
      setIntel(i);
      setGroups(c.groups);
      setInventory(s.items);
      setBrief(b);
    } catch (error) {
      setNoticeError(true);
      setNotice(
        error instanceof Error ? error.message : "No pudimos cargar los datos.",
      );
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void load();
    setQuery("");
    setSelected("");
  }, [campaign.id]);
  useEffect(() => {
    setQuery("");
    setRisk("all");
    setNotice("");
  }, [view]);
  useEffect(() => {
    const group = groups.find((g) => g.group_id === selected) || groups[0];
    const product =
      group?.items.find(
        (item) => `${item.sku}:${item.retailer}` === selectedOffer,
      ) ||
      group?.items.find(
        (item) =>
          (group.history?.filter(
            (row) => row.sku === item.sku && row.retailer === item.retailer,
          ).length || 0) > 1,
      ) ||
      group?.items[0] ||
      campaign.products[0];
    if (!product) {
      setHistory([]);
      return;
    }
    const importedHistory = group?.history
      ?.filter(
        (row) => row.sku === product.sku && row.retailer === product.retailer,
      )
      .sort((a, b) => a.observed_at.localeCompare(b.observed_at));
    if (importedHistory && importedHistory.length > 1) {
      setHistory(importedHistory);
      return;
    }
    void request<{
      observations: { observed_at: string; price: number | null }[];
    }>(
      `/api/campaigns/${campaign.id}/price-history?sku=${encodeURIComponent(product.sku)}&retailer=${encodeURIComponent(product.retailer)}`,
    )
      .then((r) =>
        setHistory(
          r.observations
            .filter((o) => o.price !== null)
            .slice(0, 12)
            .reverse(),
        ),
      )
      .catch(() => setHistory([]));
  }, [campaign.id, selected, selectedOffer, groups]);
  async function importFile(file?: File) {
    if (!file) return;
    setBusy(true);
    try {
      const body = new FormData();
      body.append("file", file);
      body.append("replace", "true");
      const result = await request<{ imported: number }>(
        `/api/campaigns/${campaign.id}/${view === "competition" ? "comparables" : "inventory"}/import`,
        { method: "POST", body },
      );
      setNoticeError(false);
      setNotice(`${result.imported} filas importadas. Cálculos actualizados.`);
      await load();
    } catch (error) {
      setNoticeError(true);
      setNotice(
        error instanceof Error ? error.message : "No se pudo importar.",
      );
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }
  function template() {
    const comparable = view === "competition";
    downloadFile(
      comparable ? "plantilla-comparables.csv" : "plantilla-inventario.csv",
      comparable
        ? "grupo_comparable;sku;nombre;retailer;precio;fecha\nMODELO-001;SKU-FALA-001;Producto de ejemplo;falabella_cl;49990;2026-11-16\nMODELO-001;SKU-PARIS-001;Producto equivalente;paris_cl;45990;2026-11-16"
        : "sku;nombre;retailer;stock;ventas_30d;lead_time;stock_seguridad\nSKU-001;Producto de ejemplo;falabella_cl;50;90;14;5",
    );
  }
  const heading: Record<string, [string, string]> = {
    intelligence: [
      "Centro de inteligencia",
      "Tus datos, convertidos en decisiones comerciales.",
    ],
    competition: [
      "Inteligencia competitiva",
      "Detecta brechas de precio en productos asociados explícitamente.",
    ],
    inventory: [
      "Riesgo de quiebres",
      "Anticipa faltantes con stock, ventas y tiempos de reposición.",
    ],
    brief: [
      "Radar Brief",
      "El panorama comercial que tu equipo necesita para actuar.",
    ],
  };
  const title = heading[view] || heading.intelligence;
  const filteredGroups = groups.filter((g) =>
    `${g.name} ${g.group_id}`.toLowerCase().includes(query.toLowerCase()),
  );
  const filteredInventory = inventory.filter(
    (i) =>
      (risk === "all" || i.risk === risk) &&
      `${i.sku} ${i.name} ${retailNames[i.retailer] || i.retailer}`
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  return (
    <div className={`intelligence-module module-${view}`}>
      <div className="page-heading">
        <div>
          <p className="eyebrow">
            RADAR / {view === "brief" ? "EXECUTIVE" : "INTELLIGENCE"}
          </p>
          <h1>{title[0]}</h1>
          <p>{title[1]}</p>
        </div>
        <div className="page-heading-actions">
          {view === "brief" ? (
            <>
              <button
                className="button button-secondary"
                onClick={() => {
                  if (brief)
                    downloadFile(
                      "radar-brief.json",
                      JSON.stringify(brief, null, 2),
                      "application/json",
                    );
                }}
              >
                <Download size={16} /> Exportar
              </button>
              <button
                className="button button-primary"
                onClick={() => window.print()}
              >
                <Printer size={16} /> Imprimir / PDF
              </button>
            </>
          ) : (
            <span className="live-label">
              <span />
              {isDemo ? "Entorno de demostración" : "Datos del workspace"}
            </span>
          )}
        </div>
      </div>
      {notice && (
        <div
          className={`notice notice-${noticeError ? "error" : "success"}`}
          role="status"
        >
          {notice}
          <button onClick={() => setNotice("")} aria-label="Cerrar mensaje">
            ×
          </button>
        </div>
      )}
      {loading ? (
        <div className="page-loader">
          <LoaderCircle className="spin" /> Calculando indicadores…
        </div>
      ) : !intel ? (
        <div className="panel-empty">
          <h2>Datos no disponibles</h2>
          <button className="button button-primary" onClick={() => void load()}>
            Reintentar
          </button>
        </div>
      ) : (
        <>
          {view === "intelligence" && (
            <>
              <div className="intel-metrics">
                <Kpi
                  label="SKU monitoreados"
                  value={String(intel.monitored_skus)}
                  detail={`${new Set(campaign.products.map((p) => p.retailer)).size} retailers en seguimiento`}
                  icon={Layers3}
                />
                <Kpi
                  label="Cumplimiento promocional"
                  value={
                    intel.compliance_percent === null
                      ? "—"
                      : `${intel.compliance_percent.toFixed(1)}%`
                  }
                  detail="Sobre precios con objetivo verificable"
                  icon={ShieldCheck}
                />
                <Kpi
                  label="Alertas prioritarias"
                  value={String(intel.critical_alerts)}
                  detail="Incumplimientos + quiebres críticos"
                  icon={TriangleAlert}
                  tone="danger"
                />
                <Kpi
                  label="Riesgo de quiebre"
                  value={
                    inventory.length
                      ? String(intel.stock_risk.critical || 0)
                      : "—"
                  }
                  detail={
                    inventory.length
                      ? `${intel.stock_risk.high || 0} SKU adicionales en riesgo alto`
                      : "Carga inventario para evaluar el riesgo"
                  }
                  icon={Package}
                  tone="warning"
                />
              </div>
              <div className="intel-grid">
                <section className="chart-panel">
                  <div className="section-title">
                    <div>
                      <span className="eyebrow">PRICE PULSE</span>
                      <h2>Evolución observada</h2>
                      <p>
                        {history.length
                          ? "Serie del primer producto asociado de la campaña"
                          : "Aún no hay observaciones históricas de precio"}
                      </p>
                    </div>
                    <BarChart3 size={20} />
                  </div>
                  {history.length > 1 ? (
                    <TrendChart
                      values={history.map((h) => h.price!)}
                      labels={history.map((h) =>
                        new Date(h.observed_at).toLocaleDateString("es-CL", {
                          day: "numeric",
                          month: "short",
                        }),
                      )}
                    />
                  ) : (
                    <div className="chart-empty">
                      Ejecuta capturas para construir una serie histórica real.
                    </div>
                  )}
                  <div className="chart-legend">
                    <i /> Precio observado{" "}
                    <span>
                      {isDemo
                        ? "Datos ficticios · 7 semanas"
                        : "Fuente: historial de capturas"}
                    </span>
                  </div>
                </section>
                <section className="action-panel">
                  <div className="section-title">
                    <div>
                      <span className="eyebrow">NEXT BEST ACTION</span>
                      <h2>Por dónde empezar</h2>
                    </div>
                    <Sparkles size={19} />
                  </div>
                  <div className="insight-list">
                    {intel.actions.map((a, index) => (
                      <button
                        className="insight-item"
                        key={a.title}
                        onClick={() =>
                          a.view === "audit" ? onAudit() : onNavigate(a.view)
                        }
                      >
                        <span className={`priority-dot ${a.priority}`}>
                          {index + 1}
                        </span>
                        <div>
                          <strong>{a.title}</strong>
                          <p>{a.detail}</p>
                          <small>
                            {a.priority === "critical"
                              ? "Actuar hoy"
                              : a.priority === "high"
                                ? "Prioridad alta"
                                : "Oportunidad comercial"}
                          </small>
                        </div>
                        <ArrowRight size={16} />
                      </button>
                    ))}
                  </div>
                </section>
              </div>
              <div className="intel-grid lower-grid">
                <section className="chart-panel">
                  <div className="section-title">
                    <div>
                      <h2>Promociones fuera de acuerdo</h2>
                      <p>Mayor diferencia absoluta por SKU</p>
                    </div>
                    <button className="text-link" onClick={() => onAudit()}>
                      Ver auditoría <ArrowRight size={14} />
                    </button>
                  </div>
                  <div className="gap-list">
                    {intel.top_gaps.length ? (
                      intel.top_gaps.map((p) => (
                        <button
                          key={p.id}
                          className="gap-item"
                          onClick={() => onAudit(p.sku)}
                        >
                          <div>
                            <strong>{p.name}</strong>
                            <span>
                              {retailNames[p.retailer] || p.retailer} · {p.sku}
                            </span>
                          </div>
                          <strong className="difference-bad">
                            +{currency.format(p.difference)}
                          </strong>
                          <ArrowUpRight size={16} />
                        </button>
                      ))
                    ) : (
                      <div className="chart-empty">
                        No se detectaron incumplimientos con los datos
                        disponibles.
                      </div>
                    )}
                  </div>
                </section>
                <section className="chart-panel">
                  <div className="section-title">
                    <div>
                      <h2>Salud del inventario</h2>
                      <p>Cobertura frente al plazo de reposición</p>
                    </div>
                    <Package size={20} />
                  </div>
                  <div className="retail-bars">
                    {Object.entries(riskLabels).map(([key, label]) => (
                      <button
                        className="retail-bar"
                        key={key}
                        onClick={() => onNavigate("inventory")}
                      >
                        <span>{label}</span>
                        <div>
                          <i
                            className={`bar-fill risk-${key}`}
                            style={{
                              width: `${Math.max(((intel.stock_risk[key] || 0) / Math.max(inventory.length, 1)) * 100, 2)}%`,
                            }}
                          />
                        </div>
                        <strong>{intel.stock_risk[key] || 0}</strong>
                      </button>
                    ))}
                  </div>
                  <p className="panel-note">
                    {inventory.length
                      ? `${inventory.length} registros de inventario evaluados.`
                      : "Importa inventario para calcular cobertura y riesgo."}
                  </p>
                </section>
              </div>
            </>
          )}
          {(view === "competition" || view === "inventory") && (
            <>
              <div className="module-toolbar">
                <label className="module-search">
                  <Search size={17} />
                  <input
                    aria-label={
                      view === "competition"
                        ? "Buscar comparable"
                        : "Buscar inventario"
                    }
                    placeholder={
                      view === "competition"
                        ? "Buscar modelo o grupo comparable…"
                        : "Buscar SKU, producto o retailer…"
                    }
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                </label>
                <div className="import-actions">
                  <button className="button button-quiet" onClick={template}>
                    <Download size={16} /> Plantilla CSV
                  </button>
                  <button
                    className="button button-primary"
                    disabled={busy}
                    onClick={() => input.current?.click()}
                  >
                    {busy ? (
                      <LoaderCircle size={16} className="spin" />
                    ) : (
                      <UploadCloud size={16} />
                    )}{" "}
                    Importar {isDemo ? "CSV" : "Excel / CSV"}
                  </button>
                  <input
                    className="sr-only"
                    type="file"
                    ref={input}
                    accept={isDemo ? ".csv" : ".csv,.xlsx"}
                    onChange={(e) => void importFile(e.target.files?.[0])}
                  />
                </div>
              </div>
            </>
          )}
          {view === "competition" && (
            <>
              <div className="module-note">
                <ShieldCheck size={17} />
                <span>
                  Solo se comparan SKU dentro del mismo{" "}
                  <strong>grupo_comparable</strong>. Cada asociación es
                  explícita; no se infieren equivalencias por nombre.
                </span>
              </div>
              <div className="intel-metrics competition-metrics">
                <Kpi
                  label="Grupos comparables"
                  value={String(groups.length)}
                  detail="Asociaciones explícitas"
                  icon={Layers3}
                />
                <Kpi
                  label="Ofertas asociadas"
                  value={String(groups.reduce((s, g) => s + g.items.length, 0))}
                  detail="Precios por SKU y retailer"
                  icon={BarChart3}
                />
                <Kpi
                  label="Mayor dispersión"
                  value={
                    groups.length
                      ? `${Math.max(...groups.map((g) => g.gap_percent || 0)).toFixed(1)}%`
                      : "—"
                  }
                  detail="Brecha máximo vs mínimo"
                  icon={ArrowUpRight}
                />
              </div>
              <div className="comparison-grid">
                {filteredGroups.map((group) => (
                  <article
                    className={`comparison-card ${selected === group.group_id ? "selected" : ""}`}
                    key={group.group_id}
                  >
                    <header>
                      <div>
                        <span>{group.group_id}</span>
                        <h3>{group.name}</h3>
                      </div>
                      <span className="gap-tag">
                        {group.gap_percent !== null
                          ? `${group.gap_percent}% brecha`
                          : "Falta comparable"}
                      </span>
                    </header>
                    {group.items.map((item, index) => (
                      <div className="comparison-row" key={item.id}>
                        <div>
                          <span>
                            {retailNames[item.retailer] || item.retailer}
                          </span>
                          {index === 0 && group.items.length > 1 && (
                            <small>Menor precio</small>
                          )}
                        </div>
                        <div className="comparison-track">
                          <i
                            className="comparison-fill"
                            style={{
                              width: `${(item.price / group.max_price) * 100}%`,
                            }}
                          />
                        </div>
                        <strong>{currency.format(item.price)}</strong>
                      </div>
                    ))}
                    <footer>
                      <span>
                        Oportunidad{" "}
                        <strong>
                          {group.gap === null
                            ? "Sin dato"
                            : currency.format(group.gap)}
                        </strong>
                      </span>
                      <button
                        className="text-link"
                        onClick={() => {
                          setSelected(group.group_id);
                          setSelectedOffer("");
                        }}
                      >
                        Ver evolución <ArrowRight size={14} />
                      </button>
                    </footer>
                  </article>
                ))}
              </div>
              {!filteredGroups.length && (
                <Empty
                  title="Importa tus comparables"
                  description="Carga un archivo con grupo_comparable, SKU, retailer y precio. Los grupos con al menos dos ofertas muestran su brecha."
                />
              )}
              {selected && (
                <section className="chart-panel comparison-history">
                  <div className="section-title">
                    <div>
                      <h2>
                        Evolución ·{" "}
                        {groups.find((g) => g.group_id === selected)?.name}
                      </h2>
                      <p>Historial de precios por SKU asociado</p>
                    </div>
                    <select
                      className="history-select"
                      aria-label="Serie histórica por retailer"
                      value={selectedOffer}
                      onChange={(event) => setSelectedOffer(event.target.value)}
                    >
                      <option value="">Serie con historial disponible</option>
                      {groups
                        .find((group) => group.group_id === selected)
                        ?.items.map((item) => (
                          <option
                            key={item.id}
                            value={`${item.sku}:${item.retailer}`}
                          >
                            {retailNames[item.retailer] || item.retailer} ·{" "}
                            {item.sku}
                          </option>
                        ))}
                    </select>
                  </div>
                  {history.length > 1 ? (
                    <TrendChart
                      values={history.map((h) => h.price!)}
                      labels={history.map((h) =>
                        new Date(h.observed_at).toLocaleDateString("es-CL", {
                          day: "numeric",
                          month: "short",
                        }),
                      )}
                    />
                  ) : (
                    <div className="chart-empty">
                      Sin historial suficiente para este SKU. Los datos
                      importados no generan una evolución ficticia.
                    </div>
                  )}
                </section>
              )}
            </>
          )}
          {view === "inventory" && (
            <>
              <div className="inventory-summary segmented">
                <button
                  className={risk === "all" ? "active" : ""}
                  onClick={() => setRisk("all")}
                >
                  Todos <b>{inventory.length}</b>
                </button>
                {Object.entries(riskLabels).map(([key, label]) => (
                  <button
                    key={key}
                    className={risk === key ? "active" : ""}
                    onClick={() => setRisk(key)}
                  >
                    {label}{" "}
                    <b>{inventory.filter((i) => i.risk === key).length}</b>
                  </button>
                ))}
              </div>
              <div className="intel-table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>SKU / Producto</th>
                      <th>Retail</th>
                      <th>Stock</th>
                      <th>Venta / día</th>
                      <th>Cobertura</th>
                      <th>Lead time</th>
                      <th>Agotamiento estimado</th>
                      <th>Riesgo</th>
                      <th>Acción sugerida</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredInventory.map((item) => (
                      <tr key={item.id}>
                        <td className="product-cell">
                          <strong>{item.name || item.sku}</strong>
                          <span>{item.sku}</span>
                        </td>
                        <td>{retailNames[item.retailer] || item.retailer}</td>
                        <td>{item.stock ?? "—"}</td>
                        <td>
                          {item.daily_sales === null
                            ? "—"
                            : item.daily_sales.toFixed(1)}
                        </td>
                        <td>
                          <strong>
                            {item.coverage_days === null
                              ? item.daily_sales === 0 && item.stock! > 0
                                ? "Sin consumo"
                                : "—"
                              : `${item.coverage_days} d`}
                          </strong>
                        </td>
                        <td>
                          {item.lead_time_days === null
                            ? "—"
                            : `${item.lead_time_days} d`}
                        </td>
                        <td>
                          {item.stockout_date
                            ? new Date(
                                `${item.stockout_date}T12:00:00`,
                              ).toLocaleDateString("es-CL")
                            : "Sin estimación"}
                        </td>
                        <td>
                          <span className={`risk-pill risk-${item.risk}`}>
                            {riskLabels[item.risk]}
                          </span>
                        </td>
                        <td className="inventory-action">{item.action}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {!filteredInventory.length && (
                <Empty
                  title={
                    inventory.length ? "Sin resultados" : "Carga tu inventario"
                  }
                  description="Importa stock, ventas de los últimos 30 días y lead time. Los campos faltantes se muestran como datos incompletos."
                />
              )}
              <div className="method-note">
                <Package size={17} />
                <p>
                  <strong>Cálculo transparente.</strong> Venta diaria = ventas
                  de 30 días / 30. Cobertura = (stock − seguridad) / venta
                  diaria. Riesgo crítico cuando cobertura ≤ lead time.
                  Agotamiento usa stock total / venta diaria; no incluye pedidos
                  futuros.
                </p>
              </div>
            </>
          )}
          {view === "brief" && brief && (
            <article className="brief-document">
              <header className="brief-header">
                <div className="brief-brand">
                  <BarChart3 size={25} />
                  <strong>Radar Retail</strong>
                  <span>EXECUTIVE BRIEF</span>
                </div>
                <span>
                  {new Date(brief.generated_at).toLocaleDateString("es-CL", {
                    day: "numeric",
                    month: "long",
                    year: "numeric",
                  })}
                </span>
              </header>
              <div className="brief-cover">
                <p className="eyebrow">
                  {isDemo ? "DEMO · DATOS FICTICIOS" : "INTELIGENCIA COMERCIAL"}
                </p>
                <h2>
                  Las decisiones que
                  <br />
                  mueven tu operación.
                </h2>
                <p>{campaign.name}</p>
              </div>
              <p className="brief-summary">{brief.executive_summary}</p>
              <div className="brief-metrics">
                <div>
                  <strong>{brief.metrics.sku}</strong>
                  <span>SKU monitoreados</span>
                </div>
                <div>
                  <strong>
                    {brief.metrics.compliance_percent === null
                      ? "Sin dato"
                      : `${brief.metrics.compliance_percent}%`}
                  </strong>
                  <span>Cumplimiento</span>
                </div>
                <div>
                  <strong>{brief.metrics.non_compliant}</strong>
                  <span>Incumplimientos</span>
                </div>
                <div>
                  <strong>{brief.metrics.critical_stock}</strong>
                  <span>Quiebres críticos</span>
                </div>
              </div>
              <h3>Prioridades & recomendaciones</h3>
              {brief.findings.map((finding, index) => (
                <section className="brief-finding" key={finding.title}>
                  <span className={`priority-dot ${finding.severity}`}>
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <div>
                    <h4>{finding.title}</h4>
                    <p>{finding.detail}</p>
                    <strong>
                      <ArrowDownRight size={14} />
                      {finding.recommendation}
                    </strong>
                  </div>
                </section>
              ))}
              <footer className="brief-method">
                <strong>Metodología y alcance</strong>
                <p>{brief.methodology}</p>
                <span>
                  {isDemo
                    ? "DEMO · Datos sintéticos. Sin pantallazos oficiales."
                    : "Las recomendaciones se basan exclusivamente en los datos disponibles de esta campaña."}
                </span>
              </footer>
            </article>
          )}
        </>
      )}
    </div>
  );
}
function Kpi({
  label,
  value,
  detail,
  icon: Icon,
  tone = "neutral",
}: {
  label: string;
  value: string;
  detail: string;
  icon: typeof Package;
  tone?: string;
}) {
  return (
    <article className={`intel-kpi kpi-${tone}`}>
      <div className="kpi-top">
        <span>{label}</span>
        <Icon size={18} />
      </div>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}
function Empty({ title, description }: { title: string; description: string }) {
  return (
    <div className="panel-empty">
      <div>
        <FileText size={25} />
      </div>
      <h2>{title}</h2>
      <p>{description}</p>
    </div>
  );
}
