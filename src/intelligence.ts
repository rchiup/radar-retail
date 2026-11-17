export type View =
  | "intelligence"
  | "audit"
  | "competition"
  | "inventory"
  | "brief";
export type Comparable = {
  id: string;
  group_id: string;
  sku: string;
  name: string;
  retailer: string;
  price: number;
  observed_at: string;
  source: string;
};
export type ComparableGroup = {
  group_id: string;
  name: string;
  items: Comparable[];
  history?: Comparable[];
  min_price: number;
  max_price: number;
  gap: number | null;
  gap_percent: number | null;
};
export type InventoryItem = {
  id: string;
  sku: string;
  name: string;
  retailer: string;
  stock: number | null;
  sales_30d: number | null;
  daily_sales: number | null;
  lead_time_days: number | null;
  safety_stock: number;
  coverage_days: number | null;
  risk: string;
  stockout_date: string | null;
  action: string;
};
export type Intelligence = {
  monitored_skus: number;
  compliance_percent: number | null;
  critical_alerts: number;
  price_gap_total: number;
  stock_risk: Record<string, number>;
  top_gaps: {
    id: string;
    sku: string;
    name: string;
    retailer: string;
    difference: number;
  }[];
  actions: { priority: string; title: string; detail: string; view: View }[];
  comparable_groups: ComparableGroup[];
};
export type Brief = {
  title: string;
  generated_at: string;
  is_demo: boolean;
  executive_summary: string;
  metrics: {
    sku: number;
    compliance_percent: number | null;
    non_compliant: number;
    critical_stock: number;
    comparable_groups: number;
  };
  findings: {
    severity: string;
    title: string;
    detail: string;
    recommendation: string;
  }[];
  methodology: string;
};

export const retailNames: Record<string, string> = {
  falabella_cl: "Falabella",
  paris_cl: "Paris",
  ripley_cl: "Ripley",
  walmart_cl: "Lider",
  abc_cl: "ABC",
  hites_cl: "Hites",
  jumbo_cl: "Jumbo",
  easy_cl: "Easy",
  sodimac_cl: "Sodimac",
  tottus_cl: "Tottus",
  claro_cl: "Claro",
  general: "General",
};
export const currency = new Intl.NumberFormat("es-CL", {
  style: "currency",
  currency: "CLP",
  maximumFractionDigits: 0,
});
export const riskLabels: Record<string, string> = {
  critical: "Crítico",
  high: "Alto",
  medium: "Medio",
  low: "Saludable",
  insufficient: "Datos incompletos",
};
const round = (value: number) => Math.round(value / 10) * 10;
const retail = [
  "falabella_cl",
  "paris_cl",
  "ripley_cl",
  "walmart_cl",
  "abc_cl",
];
const catalogue = [
  ["SONORA-MINI", "Sonora Mini · Parlante portátil", 49990],
  ["SONORA-AIR", "Sonora Air · Audio inalámbrico", 129990],
  ["PULSE-6", "Pulse 6 · Parlante resistente", 189990],
  ["PULSE-MAX", "Pulse Max · Audio outdoor", 329990],
  ["STAGE-120", "Stage 120 · Sistema de fiesta", 429990],
  ["TUNE-520", "Tune 520 · Audífonos on-ear", 44990],
  ["TUNE-770", "Tune 770 · Cancelación de ruido", 109990],
  ["WAVE-2", "Wave 2 · Audífonos in-ear", 59990],
  ["LIVE-3", "Live 3 · Audio premium", 159990],
  ["CINEMA-180", "Cinema 180 · Barra de sonido", 219990],
] as const;
const today = new Date();
const isoDay = (offset = 0) =>
  new Date(today.getTime() + offset * 86400000).toISOString().slice(0, 10);

export function calculateInventory(row: Record<string, string>): InventoryItem {
  const number = (keys: string[]) => {
    const value = keys
      .map((key) => row[key])
      .find((value) => value !== undefined && value !== "");
    if (value === undefined) return null;
    const clean = value
      .replace(/[$\s]/g, "")
      .replace(/\.(?=\d{3}(?:\D|$))/g, "")
      .replace(",", ".");
    return Number.isFinite(Number(clean)) && Number(clean) >= 0
      ? Number(clean)
      : null;
  };
  const stock = number(["stock", "inventario"]),
    sales = number(["ventas_30d", "sales_30d"]),
    daily =
      number(["venta_diaria", "daily_sales"]) ??
      (sales !== null ? sales / 30 : null),
    lead = number(["lead_time", "lead_time_days"]),
    safety = number(["stock_seguridad", "safety_stock"]) ?? 0;
  const coverage =
    stock !== null && daily !== null && daily > 0
      ? Math.max(stock - safety, 0) / daily
      : null;
  const complete = stock !== null && daily !== null && lead !== null;
  const risk = !complete
    ? "insufficient"
    : stock === 0
      ? "critical"
      : daily === 0
        ? "low"
        : coverage! <= lead!
          ? "critical"
          : coverage! <= lead! * 1.5
            ? "high"
            : coverage! <= lead! * 2.5
              ? "medium"
              : "low";
  return {
    id: row.sku,
    sku: row.sku,
    name: row.nombre || row.name || "",
    retailer: row.retailer || "general",
    stock,
    sales_30d: sales,
    daily_sales: daily,
    lead_time_days: lead,
    safety_stock: safety,
    coverage_days: coverage === null ? null : Math.round(coverage * 10) / 10,
    risk,
    stockout_date:
      stock !== null && daily && daily > 0
        ? isoDay(Math.floor(stock / daily))
        : null,
    action:
      risk === "critical"
        ? "Reponer ahora y priorizar traslado de stock disponible."
        : risk === "high"
          ? "Acelerar orden de compra y revisar ventas diariamente."
          : risk === "medium"
            ? "Programar reposición antes de llegar al stock de seguridad."
            : risk === "low"
              ? "Mantener monitoreo semanal de cobertura."
              : "Completar stock, ventas y lead time para evaluar este SKU.",
  };
}

export function makeDemo() {
  const products = catalogue.flatMap(([group, name, base], gi) =>
    retail.map((retailer, ri) => {
      const target = round(base * (0.94 + (ri % 2) * 0.015));
      const observed = round(
        target * (1 + (((gi * 7 + ri * 11) % 19) - 8) / 100),
      );
      return {
        id: `demo-${gi}-${ri}`,
        sku: `DM-${group}-${ri + 1}`,
        name,
        category: "Audio",
        retailer,
        url: "",
        regular_price: round(base * 1.18),
        promo_price: target,
        detected_price: observed,
        difference: observed - target,
        status: observed <= target ? "compliant" : "non_compliant",
        captured_at: today.toISOString(),
        screenshot_url: null,
        evidence_source: "demo",
        evidence_confidence: "demo",
        ip_used: null,
        error: null,
        group,
      };
    }),
  );
  const summary = {
    total: 50,
    pending: 0,
    running: 0,
    processed: 50,
    compliant: products.filter((p) => p.status === "compliant").length,
    non_compliant: products.filter((p) => p.status === "non_compliant").length,
    no_price: 0,
    error: 0,
    blocked: 0,
    needs_review: 0,
    evidence: 0,
    evidence_official: 0,
    evidence_google: 0,
    by_retailer: Object.fromEntries(retail.map((r) => [r, 10])),
  };
  return {
    id: "demo-offline",
    name: "Audio Chile · Operación Noviembre",
    client: "Portafolio de demostración",
    start_date: isoDay(-5),
    end_date: isoDay(5),
    status: "completed_with_errors",
    source_filename: "DEMO · 50 SKU ficticios",
    last_run_at: today.toISOString(),
    last_error: null,
    capture_mode: "demo",
    is_demo: true,
    summary,
    products,
  };
}
const demo = makeDemo();
let comparableRows: Comparable[] = demo.products.map((p) => ({
  id: p.id,
  group_id: p.group,
  sku: p.sku,
  name: p.name,
  retailer: p.retailer,
  price: p.detected_price,
  observed_at: p.captured_at,
  source: "demo",
}));
let inventoryRows = demo.products.map((p, index) =>
  calculateInventory({
    sku: p.sku,
    nombre: p.name,
    retailer: p.retailer,
    stock: String(18 + ((index * 17) % 130)),
    ventas_30d: String(24 + ((index * 29) % 170)),
    lead_time: String(7 + ((index * 3) % 18)),
    stock_seguridad: String(5 + (index % 8)),
  }),
);

function demoGroups() {
  return [...new Set(comparableRows.map((r) => r.group_id))].map((group_id) => {
    const history = comparableRows.filter((r) => r.group_id === group_id);
    const latest = new Map<string, Comparable>();
    history.forEach((row) => {
      const key = `${row.sku}:${row.retailer}`;
      if (!latest.has(key) || row.observed_at >= latest.get(key)!.observed_at)
        latest.set(key, row);
    });
    const items = [...latest.values()].sort((a, b) => a.price - b.price),
      min = items[0].price,
      max = items[items.length - 1].price;
    const comparable = new Set(items.map((item) => item.retailer)).size >= 2;
    return {
      group_id,
      name: items[0].name,
      items,
      history,
      min_price: min,
      max_price: max,
      gap: comparable ? max - min : null,
      gap_percent: comparable ? Math.round((max / min - 1) * 1000) / 10 : null,
    };
  });
}
function demoIntel(): Intelligence {
  const stock = Object.fromEntries(
    Object.keys(riskLabels).map((r) => [
      r,
      inventoryRows.filter((i) => i.risk === r).length,
    ]),
  );
  const groups = demoGroups();
  const actions: Intelligence["actions"] = [
    ...(stock.critical
      ? [
          {
            priority: "critical",
            title: `Reponer ${stock.critical} SKU con cobertura insuficiente`,
            detail: "El stock disponible no alcanza el plazo de reposición.",
            view: "inventory" as View,
          },
        ]
      : []),
    {
      priority: "high",
      title: `Corregir ${demo.summary.non_compliant} promociones incumplidas`,
      detail:
        "Validar precio con el equipo comercial del retail y solicitar corrección.",
      view: "audit",
    },
    {
      priority: "medium",
      title: `Revisar ${groups.filter((g) => (g.gap_percent || 0) >= 12).length} oportunidades competitivas`,
      detail: "Analizar brechas en productos asociados explícitamente.",
      view: "competition",
    },
  ];
  return {
    monitored_skus: 50,
    compliance_percent: (demo.summary.compliant / 50) * 100,
    critical_alerts: stock.critical + demo.summary.non_compliant,
    price_gap_total: demo.products.reduce(
      (sum, p) => sum + Math.max(p.difference, 0),
      0,
    ),
    stock_risk: stock,
    top_gaps: [...demo.products]
      .sort((a, b) => b.difference - a.difference)
      .filter((p) => p.difference > 0)
      .slice(0, 5),
    actions,
    comparable_groups: groups,
  };
}
export function demoHistory(sku: string, retailer: string) {
  const p = demo.products.find((p) => p.sku === sku && p.retailer === retailer);
  if (!p) return [];
  return Array.from({ length: 7 }, (_, week) => {
    const price =
      week === 0
        ? p.detected_price
        : round(
            p.detected_price *
              (1 + (((week * 3 + p.id.length) % 11) - 5) / 100),
          );
    return {
      id: `history-${week}`,
      sku,
      retailer,
      observed_at: new Date(
        today.getTime() - week * 7 * 86400000,
      ).toISOString(),
      price,
      status: price <= p.promo_price ? "compliant" : "non_compliant",
      evidence_source: "demo",
      screenshot_url: null,
    };
  });
}
export async function demoRequest(
  url: string,
  init?: RequestInit,
): Promise<unknown> {
  if (url.endsWith("/run")) {
    demo.last_run_at = new Date().toISOString();
    return demo;
  }
  if (url.includes("price-history")) {
    const params = new URL(url, "http://demo").searchParams;
    return {
      observations: demoHistory(
        params.get("sku") || "",
        params.get("retailer") || "",
      ),
    };
  }
  if (url.endsWith("/intelligence")) return demoIntel();
  if (
    url.includes("/comparables/import") ||
    url.includes("/inventory/import")
  ) {
    const file = (init?.body as FormData).get("file") as File;
    if (!file.name.endsWith(".csv"))
      throw new Error(
        "La demo sin conexión importa CSV. Usa la plantilla; Excel está disponible en el workspace real.",
      );
    const rows = parseCsv(await file.text());
    if (url.includes("comparables")) {
      const items = rows
        .filter(
          (r) =>
            r.grupo_comparable &&
            r.sku &&
            r.retailer &&
            Number.isFinite(Number(r.precio)) &&
            Number(r.precio) > 0 &&
            (!r.fecha || !Number.isNaN(Date.parse(r.fecha))),
        )
        .map((r, index) => ({
          id: String(index),
          group_id: r.grupo_comparable,
          sku: r.sku,
          name: r.nombre || r.grupo_comparable,
          retailer: r.retailer,
          price: Number(r.precio),
          observed_at: r.fecha
            ? new Date(r.fecha).toISOString()
            : today.toISOString(),
          source: "demo_import",
        }));
      if (!items.length)
        throw new Error("Usa grupo_comparable, sku, retailer y precio válido.");
      comparableRows = items;
    } else {
      const items = rows.filter((r) => r.sku).map(calculateInventory);
      if (!items.length) throw new Error("El CSV debe incluir SKU.");
      inventoryRows = items;
    }
    return { imported: rows.length };
  }
  if (url.endsWith("/comparables"))
    return {
      groups: demoGroups(),
      count: comparableRows.length,
      group_count: demoGroups().length,
    };
  if (url.endsWith("/inventory"))
    return {
      items: inventoryRows,
      count: inventoryRows.length,
      summary: demoIntel().stock_risk,
    };
  if (url.endsWith("/brief")) {
    const intel = demoIntel();
    return {
      title: "Radar Brief · Audio Chile",
      generated_at: new Date().toISOString(),
      is_demo: true,
      executive_summary: `Operación de demostración con 50 SKU ficticios. Cumplimiento promocional de ${intel.compliance_percent}%. ${intel.stock_risk.critical} SKU requieren reposición prioritaria y ${demoGroups().length} grupos permiten evaluar posicionamiento competitivo.`,
      metrics: {
        sku: 50,
        compliance_percent: intel.compliance_percent,
        non_compliant: demo.summary.non_compliant,
        critical_stock: intel.stock_risk.critical,
        comparable_groups: demoGroups().length,
      },
      findings: intel.actions.map((a) => ({
        severity: a.priority,
        title: a.title,
        detail: a.detail,
        recommendation:
          a.priority === "critical"
            ? "Priorizar reposición y confirmar fecha de entrega hoy."
            : a.priority === "high"
              ? "Solicitar corrección y respaldar con la evidencia disponible."
              : "Validar margen y definir posicionamiento por retailer.",
      })),
      methodology:
        "DEMO · Cálculos determinísticos sobre datos ficticios. Cobertura = (stock − seguridad) / venta diaria. No constituye evidencia oficial de un retail.",
    } satisfies Brief;
  }
  return demo;
}
function parseCsv(text: string) {
  const lines = text
      .replace(/^\uFEFF/, "")
      .trim()
      .split(/\r?\n/),
    delimiter = lines[0].includes(";") ? ";" : ",";
  const split = (line: string) => {
    const values: string[] = [];
    let value = "",
      quoted = false;
    for (let i = 0; i < line.length; i++) {
      const char = line[i];
      if (char === '"') {
        if (quoted && line[i + 1] === '"') {
          value += '"';
          i++;
        } else quoted = !quoted;
      } else if (char === delimiter && !quoted) {
        values.push(value.trim());
        value = "";
      } else value += char;
    }
    values.push(value.trim());
    return values;
  };
  const headers = split(lines[0]).map((h) =>
    h.toLowerCase().replaceAll(" ", "_"),
  );
  return lines
    .slice(1)
    .map((line) =>
      Object.fromEntries(
        split(line).map((value, index) => [headers[index], value]),
      ),
    );
}
export function downloadFile(
  name: string,
  content: string,
  type = "text/csv;charset=utf-8",
) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function demoReport() {
  downloadFile(
    "radar-DEMO-50-sku.csv",
    "\uFEFFDEMO;SKU;Producto;Retail;Objetivo;Observado;Diferencia;Resultado\n" +
      demo.products
        .map((p) =>
          [
            "DATOS FICTICIOS",
            p.sku,
            p.name,
            retailNames[p.retailer],
            p.promo_price,
            p.detected_price,
            p.difference,
            p.status,
          ].join(";"),
        )
        .join("\n"),
  );
}
export const demoCampaign = () => structuredClone(demo);
