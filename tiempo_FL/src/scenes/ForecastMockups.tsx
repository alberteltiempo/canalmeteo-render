import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { loadFont } from "@remotion/google-fonts/Outfit";
import { ServiceMap, textOn, Geo } from "./ServicesMockups";
import { SatMap, MapPolygon } from "../components/SatMap";
import { TopicBar } from "../components/Overlay";
import { CONUS_VIEW, CONUS_PAD } from "../lib/cdn";
import { MAJOR_CITIES } from "../lib/cities";
import { tempColor } from "../lib/conditions";
import { palette } from "../lib/theme";
import { SatView, SpcOutlook, TmaxCity, TmaxPop, ThemeMode } from "../types";

const { fontFamily } = loadFont();

// ─────────────────────────────────────────────────────────────────────────────
// MOCKUPS del cierre del segmento nacional (Still → PNG, para pulir el LOOK antes
// de cablear los feeds reales de nimbus):
//   1) Riesgo de tiempo severo (SPC, outlook categórico día 1) → polígonos.
//   2) Temperatura máxima HOY              → cajas por ciudad coloreadas por °F.
//   3) Variación de temperatura MAÑANA     → mapa diverging + Δ°F por ciudad.
//   4) Temperatura máxima MAÑANA           → igual que (2), otro día.
// Datos de MUESTRA: NO son reales, solo para juzgar el diseño.
// ─────────────────────────────────────────────────────────────────────────────

// ═════════════════════════════════════════════════════════════════════════════
// Cajas de temperatura (reutilizan el motor anti-solape ServiceMap)
// ═════════════════════════════════════════════════════════════════════════════
type TempCity = Geo & { name: string; tmax: number };
type DeltaCity = Geo & { name: string; delta: number };

// Caja tintada por su propia temperatura (como los discos de UV/AQI): el fondo es
// el color de la temperatura y el texto se auto-contrasta (textOn). Compartido el
// borde/sombra entre máxima y variación.
const TEMP_BOX_BORDER = "1px solid rgba(255,255,255,0.55)";
const TEMP_BOX_SHADOW = "0 8px 22px rgba(0,0,0,0.45)";

// Caja de máxima: gran número °F sobre fondo del color de su temperatura.
const TmaxBox: React.FC<{ c: TempCity }> = ({ c }) => {
  const color = tempColor(c.tmax);
  const fg = textOn(color);
  return (
    <div
      style={{
        background: color,
        border: TEMP_BOX_BORDER,
        borderRadius: 14,
        padding: "10px 22px 12px",
        boxShadow: TEMP_BOX_SHADOW,
        textAlign: "center",
      }}
    >
      <div
        style={{
          fontSize: 62,
          fontWeight: 900,
          color: fg,
          lineHeight: 1,
          fontFamily: "'JetBrains Mono', monospace",
        }}
      >
        {Math.round(c.tmax)}°
      </div>
      <div style={{ fontSize: 27, fontWeight: 800, color: fg, marginTop: 4, whiteSpace: "nowrap", opacity: 0.95 }}>
        {c.name}
      </div>
    </div>
  );
};

// Escala diverging ESCALONADA para el CAMBIO de temperatura: un color sólido por
// grado (saturación creciente, clamp en ±8°) — los deltas típicos son pequeños y
// un degradado suave no se distingue en pantalla. La leyenda se genera de esta
// misma tabla (cortes duros) para que nunca divirjan.
const DELTA_SCALE: [number, string][] = [
  [-8, "#123f8f"],
  [-7, "#1a52ad"],
  [-6, "#2767c4"],
  [-5, "#3a7ed8"],
  [-4, "#5497e6"],
  [-3, "#74b1ef"],
  [-2, "#9acaf5"],
  [-1, "#c4e0fa"],
  [0, "#c9ced4"],
  [1, "#ffe0a8"],
  [2, "#ffc873"],
  [3, "#ffab42"],
  [4, "#ff8c1a"],
  [5, "#f76b00"],
  [6, "#e64f00"],
  [7, "#cf3600"],
  [8, "#b32000"],
];
function deltaColor(d: number): string {
  const i = Math.max(-8, Math.min(8, Math.round(d)));
  return DELTA_SCALE[i + 8][1];
}

// Caja de variación: fondo del color diverging (Δ°F); flecha ↑/↓ + Δ°F con signo
// y ciudad, todo auto-contrastado sobre ese fondo.
const DeltaBox: React.FC<{ c: DeltaCity }> = ({ c }) => {
  const color = deltaColor(c.delta);
  const fg = textOn(color);
  const up = c.delta >= 0;
  const sign = c.delta > 0 ? "+" : "";
  return (
    <div
      style={{
        background: color,
        border: TEMP_BOX_BORDER,
        borderRadius: 14,
        padding: "10px 21px 12px",
        boxShadow: TEMP_BOX_SHADOW,
        textAlign: "center",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 7 }}>
        <span style={{ fontSize: 43, lineHeight: 1, color: fg }}>{up ? "▲" : "▼"}</span>
        <span
          style={{
            fontSize: 54,
            fontWeight: 900,
            color: fg,
            lineHeight: 1,
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          {sign}
          {Math.round(c.delta)}°
        </span>
      </div>
      <div style={{ fontSize: 27, fontWeight: 800, color: fg, marginTop: 4, whiteSpace: "nowrap", opacity: 0.95 }}>
        {c.name}
      </div>
    </div>
  );
};

// Colorbar horizontal (leyenda de temperatura/variación) abajo a la derecha.
const Colorbar: React.FC<{ title: string; gradient: string; labels: string[] }> = ({
  title,
  gradient,
  labels,
}) => (
  <div
    style={{
      position: "absolute",
      right: 48,
      bottom: 40,
      display: "flex",
      flexDirection: "column",
      alignItems: "flex-end",
      gap: 6,
    }}
  >
    <div style={{ color: "#fff", fontSize: 22, fontWeight: 700, opacity: 0.9 }}>{title}</div>
    <div
      style={{
        width: 420,
        height: 18,
        borderRadius: 7,
        border: "1px solid rgba(255,255,255,0.3)",
        background: gradient,
      }}
    />
    <div style={{ width: 420, display: "flex", justifyContent: "space-between", color: "#dfe8f0", fontSize: 17 }}>
      {labels.map((l) => (
        <span key={l}>{l}</span>
      ))}
    </div>
  </div>
);

// Ciudades de muestra (coords reales; valores inventados para juzgar el diseño).
const TMAX_TODAY: TempCity[] = [
  { id: "SEA", name: "Seattle", lon: -122.33, lat: 47.61, tmax: 71 },
  { id: "PDX", name: "Portland", lon: -122.68, lat: 45.52, tmax: 78 },
  { id: "SFO", name: "San Francisco", lon: -122.42, lat: 37.77, tmax: 68 },
  { id: "LAX", name: "Los Ángeles", lon: -118.24, lat: 34.05, tmax: 84 },
  { id: "LAS", name: "Las Vegas", lon: -115.14, lat: 36.17, tmax: 104 },
  { id: "PHX", name: "Phoenix", lon: -112.07, lat: 33.45, tmax: 109 },
  { id: "SLC", name: "Salt Lake City", lon: -111.89, lat: 40.76, tmax: 92 },
  { id: "DEN", name: "Denver", lon: -104.99, lat: 39.74, tmax: 88 },
  { id: "ABQ", name: "Albuquerque", lon: -106.65, lat: 35.08, tmax: 95 },
  { id: "BIS", name: "Bismarck", lon: -100.78, lat: 46.81, tmax: 80 },
  { id: "OKC", name: "Oklahoma City", lon: -97.52, lat: 35.47, tmax: 96 },
  { id: "DAL", name: "Dallas", lon: -96.8, lat: 32.78, tmax: 99 },
  { id: "HOU", name: "Houston", lon: -95.37, lat: 29.76, tmax: 95 },
  { id: "KC", name: "Kansas City", lon: -94.58, lat: 39.1, tmax: 90 },
  { id: "MSP", name: "Mineápolis", lon: -93.27, lat: 44.98, tmax: 82 },
  { id: "CHI", name: "Chicago", lon: -87.63, lat: 41.88, tmax: 84 },
  { id: "ATL", name: "Atlanta", lon: -84.39, lat: 33.75, tmax: 90 },
  { id: "MIA", name: "Miami", lon: -80.19, lat: 25.76, tmax: 91 },
  { id: "DC", name: "Washington", lon: -77.04, lat: 38.91, tmax: 88 },
  { id: "NYC", name: "Nueva York", lon: -74.01, lat: 40.71, tmax: 86 },
  { id: "BOS", name: "Boston", lon: -71.06, lat: 42.36, tmax: 79 },
  { id: "BOI", name: "Boise", lon: -116.2, lat: 43.62, tmax: 94 },
  { id: "MSY", name: "New Orleans", lon: -90.07, lat: 29.95, tmax: 93 },
  { id: "CLE", name: "Cleveland", lon: -81.69, lat: 41.5, tmax: 84 },
  { id: "RDU", name: "Raleigh", lon: -78.64, lat: 35.78, tmax: 91 },
];

const TMAX_TOMORROW: TempCity[] = TMAX_TODAY.map((c) => ({
  ...c,
  tmax:
    c.tmax +
    [3, -6, 2, 4, -2, 1, -5, 6, 0, 7, -8, -10, 1, -7, 5, 6, -3, 0, 2, 4, 5, 2, -3, 4, -1][
      TMAX_TODAY.indexOf(c)
    ],
}));

// Población expuesta de MUESTRA (día caluroso de finales de junio). No real.
const SAMPLE_POP_TODAY: TmaxPop = { heat90: 78_400_000, heat100: 11_200_000 };
const SAMPLE_POP_TOMORROW: TmaxPop = { heat90: 71_900_000, heat100: 7_600_000 };

const TVAR_TOMORROW: DeltaCity[] = TMAX_TODAY.map((c, i) => ({
  id: c.id,
  name: c.name,
  lon: c.lon,
  lat: c.lat,
  delta: TMAX_TOMORROW[i].tmax - c.tmax,
}));

const TEMP_GRADIENT =
  "linear-gradient(90deg,#7c4dff 0%,#3d7bff 18%,#21b6c9 32%,#2ecc71 46%,#f4d03f 60%,#ef8e2d 74%,#e74c3c 88%,#c0298a 100%)";
const DELTA_GRADIENT = `linear-gradient(90deg,${DELTA_SCALE.map(
  ([, c], i) => `${c} ${((i / DELTA_SCALE.length) * 100).toFixed(1)}%,${c} ${(((i + 1) / DELTA_SCALE.length) * 100).toFixed(1)}%`
).join(",")})`;

// Sin empujones manuales: el colocador con sesgo al interior coloca Houston/Dallas
// tierra adentro (antes HOU caía en el Golfo y DAL bajaba hasta San Antonio).
const TEMP_NUDGE: Record<string, [number, number]> = {};
// Lado fijo por ciudad (revisión de Albert sobre el render): Miami al SUR de
// Fort Lauderdale, Fort Myers/Orlando/Daytona abajo, Jacksonville arriba,
// panhandle (TLH/ECP/PNS) pegado al continente y Sarasota junto a su punto.
const TEMP_FORCE: Record<string, "left" | "right" | "up" | "down"> = {
  MIA: "down",
  FLL: "right",
  RSW: "down",
  SRQ: "left",
  MCO: "down",
  DAB: "right", // "down" chocaba con Orlando (los forzados no se esquivan entre sí)
  JAX: "up",
  TLH: "right", // "up" clampaba al margen superior y pisaba a Panama City
  ECP: "up",
  PNS: "up",
};

// Tarjeta de población expuesta por umbral (calor: ≥90/≥100 °F; frío: ≤32 °F).
// Solo pinta los umbrales que traiga el feed. Estilo coherente con el titular de
// población del SPC. Va arriba a la derecha.
const PopBadge: React.FC<{ pop: TmaxPop }> = ({ pop }) => {
  const rows: { n: number; label: string; color: string }[] = [];
  if (pop.heat90 != null) rows.push({ n: pop.heat90, label: "por encima de 90°F", color: "#ef8e2d" });
  if (pop.heat100 != null) rows.push({ n: pop.heat100, label: "por encima de 100°F", color: "#e74c3c" });
  if (pop.cold32 != null) rows.push({ n: pop.cold32, label: "por debajo de 32°F", color: "#3d7bff" });
  if (!rows.length) return null;
  return (
    <div
      style={{
        position: "absolute",
        right: 48,
        top: 120,
        background: "rgba(8,20,30,0.85)",
        border: "1.5px solid rgba(255,255,255,0.28)",
        borderRadius: 16,
        padding: "14px 22px 16px",
        boxShadow: "0 6px 22px rgba(0,0,0,0.55)",
        minWidth: 270,
      }}
    >
      <div
        style={{
          fontSize: 17,
          fontWeight: 800,
          letterSpacing: 2,
          textTransform: "uppercase",
          color: "rgba(255,255,255,0.7)",
          marginBottom: 12,
          textAlign: "right",
        }}
      >
        Población expuesta
      </div>
      {rows.map((r, i) => (
        <div
          key={i}
          style={{
            display: "flex",
            alignItems: "baseline",
            justifyContent: "flex-end",
            gap: 14,
            marginTop: i ? 12 : 0,
          }}
        >
          <span style={{ fontSize: 18, fontWeight: 700, color: "rgba(255,255,255,0.88)" }}>
            {r.label}
          </span>
          <span
            style={{
              fontSize: 48,
              fontWeight: 900,
              color: "#fff",
              lineHeight: 1,
              minWidth: 118,
              textAlign: "right",
              fontFamily: "'JetBrains Mono', monospace",
              borderBottom: `3px solid ${r.color}`,
              paddingBottom: 3,
            }}
          >
            {formatPob(r.n)}
          </span>
        </div>
      ))}
    </div>
  );
};

// Contenido compartido de máxima (hoy/mañana): cambia título/subtítulo/datos y,
// en escena real, el ráster NBM drapeado bajo las cajas. `pop` (opcional) =
// población expuesta por umbral, mostrada arriba a la derecha.
const TmaxContent: React.FC<{
  data: TempCity[];
  sub: string;
  topicColor: string;
  raster?: SatView;
  pop?: TmaxPop;
  animate?: boolean;
}> = ({ data, sub, topicColor, raster, pop, animate }) => (
  <ServiceMap
    points={data}
    topPad={175}
    nudge={TEMP_NUDGE}
    force={TEMP_FORCE}
    animate={animate}
    raster={raster}
    boxSize={(c) => ({ w: Math.max(170, c.name.length * 16 + 56), h: 130 })}
    renderChip={(c) => <TmaxBox c={c} />}
  >
    <TopicBar topic="TEMPERATURA MÁXIMA" sub={sub} topicColor={topicColor} opacity={1} />
    {pop ? <PopBadge pop={pop} /> : null}
    <Colorbar title="Máxima (°F)" gradient={TEMP_GRADIENT} labels={["10°", "60°", "110°"]} />
  </ServiceMap>
);

const TvarContent: React.FC<{
  data: DeltaCity[];
  topicColor: string;
  raster?: SatView;
  animate?: boolean;
}> = ({ data, topicColor, raster, animate }) => (
  <ServiceMap
    points={data}
    topPad={175}
    nudge={TEMP_NUDGE}
    force={TEMP_FORCE}
    animate={animate}
    raster={raster}
    boxSize={(c) => ({ w: Math.max(170, c.name.length * 16 + 56), h: 130 })}
    renderChip={(c) => <DeltaBox c={c} />}
  >
    <TopicBar topic="CAMBIO DE TEMPERATURA" sub="PRÓXIMAS 24 HORAS" topicColor={topicColor} opacity={1} />
    <Colorbar title="Cambio (°F)" gradient={DELTA_GRADIENT} labels={["−8°", "0°", "+8°"]} />
  </ServiceMap>
);

// ── Mockups (Still, datos de muestra) ──
export const TmaxTodayMockup: React.FC = () => (
  <TmaxContent data={TMAX_TODAY} sub="HOY" pop={SAMPLE_POP_TODAY} topicColor="#F39C12" />
);
export const TmaxTomorrowMockup: React.FC = () => (
  <TmaxContent data={TMAX_TOMORROW} sub="MAÑANA" pop={SAMPLE_POP_TOMORROW} topicColor="#F39C12" />
);
export const TvarMockup: React.FC = () => (
  <TvarContent data={TVAR_TOMORROW} topicColor="#F39C12" />
);

// ── Escenas reales (feeds NBM) ──
export const TmaxScene: React.FC<{
  cities?: TmaxCity[];
  raster?: SatView;
  pop?: TmaxPop;
  sub: string;
  mode?: ThemeMode;
}> = ({ cities = [], raster, pop, sub, mode = "normal" }) => (
  <TmaxContent
    data={cities.map((c) => ({ ...c }))}
    sub={sub}
    raster={raster}
    pop={pop}
    animate
    topicColor={palette(mode).topicColor}
  />
);

// Variación = mañana − hoy (emparejado por id). Necesita ambos días.
export const TvarScene: React.FC<{
  today?: TmaxCity[];
  tomorrow?: TmaxCity[];
  raster?: SatView;
  mode?: ThemeMode;
}> = ({ today = [], tomorrow = [], raster, mode = "normal" }) => {
  const byId = new Map(today.map((c) => [c.id, c.tmax]));
  const data: DeltaCity[] = tomorrow
    .filter((c) => byId.has(c.id))
    .map((c) => ({ id: c.id, name: c.name, lon: c.lon, lat: c.lat, delta: c.tmax - (byId.get(c.id) as number) }));
  return <TvarContent data={data} raster={raster} animate topicColor={palette(mode).topicColor} />;
};

// ═════════════════════════════════════════════════════════════════════════════
// Riesgo de tiempo severo (SPC, outlook categórico día 1)
// ═════════════════════════════════════════════════════════════════════════════
// Niveles SPC con sus colores estándar. "general" = solo tormentas (TSTM).
const SPC_LEVELS: { key: string; label: string; color: string }[] = [
  { key: "tstm", label: "Tormentas", color: "#c1e9c1" },
  { key: "mrgl", label: "Marginal", color: "#7fc57f" },
  { key: "slgt", label: "Ligero", color: "#f6f67f" },
  { key: "enh", label: "Realzado", color: "#e6c27a" },
  { key: "mdt", label: "Moderado", color: "#e67f7f" },
  { key: "high", label: "Alto", color: "#ff80ff" },
];

// Polígonos de MUESTRA (anidados sobre las llanuras centrales): general → realzado.
function ring(coords: [number, number][]): any {
  return { type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [coords] } };
}
const SPC_SAMPLE: { level: string; feature: any }[] = [
  {
    level: "tstm",
    feature: ring([
      [-106, 30], [-106, 46], [-80, 46], [-80, 30], [-106, 30],
    ]),
  },
  {
    level: "mrgl",
    feature: ring([
      [-103, 32], [-103, 44], [-86, 44], [-86, 32], [-103, 32],
    ]),
  },
  {
    level: "slgt",
    feature: ring([
      [-101, 34], [-101, 42], [-90, 42], [-90, 34], [-101, 34],
    ]),
  },
  {
    level: "enh",
    feature: ring([
      [-99, 36], [-99, 41], [-93, 41], [-93, 36], [-99, 36],
    ]),
  },
];

const colorOfLevel = (lvl: string) =>
  SPC_LEVELS.find((l) => l.key === lvl)?.color || "#c1e9c1";

// Población compacta para la leyenda ("1,2 M" / "850 mil").
function formatPob(n: number): string {
  if (n >= 1e6) return `${(n / 1e6).toFixed(1).replace(".", ",")} M`;
  if (n >= 1e3) return `${Math.round(n / 1e3)} mil`;
  return `${n}`;
}

// Contenido compartido SPC (mockup y escena). `items` = polígonos con su nivel.
// `pop` (opcional) = población acumulada bajo ≥cada nivel (feed v2). Si no hay
// items → tarjeta "sin riesgo significativo".
const SpcContent: React.FC<{
  items: { feature: any; level: string }[];
  pop?: Record<string, number>;
  topicColor: string;
  animate?: boolean;
}> = ({ items, pop, topicColor, animate }) => {
  const frame = useCurrentFrame();
  const op = animate ? interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" }) : 1;
  const view: SatView = { view: "base", band: "", bounds: null, frames: [] };
  // El outlook del SPC es nacional: para la leyenda y el titular solo cuentan las
  // bandas que TOCAN el encuadre (test de bbox, aproximado pero barato). Los
  // polígonos se pintan todos: el mapa ya recorta por el viewport.
  const inView = (f: any): boolean => {
    const g = f?.geometry?.coordinates;
    if (!g) return true; // sin geometría medible: no descartar
    let w = Infinity, s = Infinity, e = -Infinity, n = -Infinity;
    const walk = (c: any) => {
      if (typeof c[0] === "number") {
        w = Math.min(w, c[0]); e = Math.max(e, c[0]);
        s = Math.min(s, c[1]); n = Math.max(n, c[1]);
      } else for (const x of c) walk(x);
    };
    walk(g);
    const [[vw, vs], [ve, vn]] = CONUS_VIEW;
    return w <= ve && e >= vw && s <= vn && n >= vs;
  };
  const regionItems = items.filter((p) => inView(p.feature));
  const polygons: MapPolygon[] = items.map((p) => ({
    data: p.feature,
    fill: colorOfLevel(p.level),
    line: colorOfLevel(p.level),
    fillOpacity: 0.5,
  }));
  // Población por nivel: SOLO la regional del feed (population_by_level_fl). Sin
  // fallback a la población nacional por feature — en un segmento regional esos
  // números son de otro sitio y salen titulares imposibles (marginal > tormentas).
  // Población "bajo riesgo" = banda más amplia SIN contar tormentas generales.
  const popByLevel: Record<string, number> = { ...(pop || {}) };
  const popUnderRisk = Math.max(
    0,
    ...regionItems.filter((p) => p.level !== "tstm").map((p) => popByLevel[p.level] || 0)
  );
  // Solo los niveles presentes EN EL ENCUADRE (en orden de severidad).
  const present = new Set(regionItems.map((p) => p.level));
  const legend = SPC_LEVELS.filter((l) => present.has(l.key));
  return (
    <AbsoluteFill style={{ background: "#000", fontFamily }}>
      <SatMap
        sat={view}
        center={[-96, 38]}
        zoom={3.4}
        fitBounds={CONUS_VIEW}
        fitPadding={CONUS_PAD}
        cityMarkers={MAJOR_CITIES}
        polygons={polygons}
        animatePolygons={animate}
        showSatellite={false}
      />
      <AbsoluteFill
        style={{
          pointerEvents: "none",
          background:
            "linear-gradient(180deg, rgba(0,0,0,0.5) 0%, rgba(0,0,0,0) 22%, rgba(0,0,0,0) 78%, rgba(0,0,0,0.5) 100%)",
        }}
      />
      <TopicBar topic="RIESGO DE TIEMPO SEVERO" sub="SPC · HOY" topicColor={topicColor} opacity={op} />
      {/* Caja: gente bajo riesgo de tiempo severo (banda más amplia sin tstm). */}
      {regionItems.length > 0 && popUnderRisk > 0 ? (
        <div
          style={{
            position: "absolute",
            right: 48,
            top: 60,
            opacity: op,
            background: "rgba(8,12,18,0.85)",
            border: "1.5px solid rgba(255,255,255,0.22)",
            borderRadius: 16,
            padding: "16px 28px",
            textAlign: "center",
            boxShadow: "0 8px 28px rgba(0,0,0,0.5)",
          }}
        >
          <div
            style={{
              fontSize: 18,
              fontWeight: 800,
              letterSpacing: 2,
              textTransform: "uppercase",
              color: "rgba(255,255,255,0.7)",
              marginBottom: 6,
            }}
          >
            Población bajo riesgo
          </div>
          <div
            style={{
              fontSize: 70,
              fontWeight: 900,
              color: "#fff",
              lineHeight: 1,
              fontFamily: "'JetBrains Mono', monospace",
              textShadow: "0 2px 10px rgba(0,0,0,0.6)",
            }}
          >
            {formatPob(popUnderRisk)}
          </div>
          <div style={{ fontSize: 21, fontWeight: 700, color: "rgba(255,255,255,0.85)", marginTop: 4 }}>
            personas
          </div>
        </div>
      ) : null}
      {regionItems.length === 0 ? (
        // Sin riesgo: tarjeta de estado (igual que "sin alertas").
        <AbsoluteFill style={{ alignItems: "center", justifyContent: "flex-end", paddingBottom: 90 }}>
          <div
            style={{
              opacity: op,
              background: "rgba(13,26,38,0.9)",
              border: "1px solid rgba(255,255,255,0.14)",
              borderRadius: 22,
              padding: "30px 56px",
              textAlign: "center",
              boxShadow: "0 20px 60px rgba(0,0,0,0.55)",
            }}
          >
            <div style={{ width: 120, height: 8, borderRadius: 4, background: "#2ecc71", margin: "0 auto 20px" }} />
            <div style={{ fontSize: 50, fontWeight: 800, color: "#fff", lineHeight: 1.05 }}>
              Sin riesgo significativo
            </div>
            <div style={{ fontSize: 28, color: "rgba(255,255,255,0.85)", marginTop: 12 }}>
              Florida · tiempo severo
            </div>
          </div>
        </AbsoluteFill>
      ) : (
        <div style={{ position: "absolute", left: 48, bottom: 40, display: "flex", gap: 18, flexWrap: "wrap", maxWidth: 1240, opacity: op }}>
          {legend.map((l) => {
            const p = popByLevel[l.key];
            return (
              <div key={l.key} style={{ display: "flex", alignItems: "center", gap: 9 }}>
                <span
                  style={{
                    width: 26,
                    height: 17,
                    borderRadius: 3,
                    background: l.color,
                    border: "1px solid rgba(255,255,255,0.5)",
                    flex: "0 0 auto",
                  }}
                />
                <span style={{ color: "#fff", fontSize: 22, fontWeight: 700 }}>
                  {l.label}
                  {p && p > 0 ? (
                    <span style={{ color: "rgba(255,255,255,0.7)", fontWeight: 600 }}>
                      {" "}
                      · {formatPob(p)}
                    </span>
                  ) : null}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </AbsoluteFill>
  );
};

// Población de MUESTRA bajo cada nivel (acumulada, contrato v2). No real.
const SPC_SAMPLE_POP: Record<string, number> = {
  mrgl: 24_600_000,
  slgt: 9_800_000,
  enh: 3_100_000,
};

export const SpcOutlookMockup: React.FC = () => (
  <SpcContent
    items={SPC_SAMPLE.map((p) => ({ feature: p.feature, level: p.level }))}
    pop={SPC_SAMPLE_POP}
    topicColor="#F39C12"
  />
);

// Escena real (feed data/spc/outlook_day1.json, v2). Solo el categórico ("el
// general"); las bandas son disjuntas, así que las ordenamos por severidad
// ascendente para que los niveles altos queden ENCIMA al pintarse.
export const SpcScene: React.FC<{ spc?: SpcOutlook | null; mode?: ThemeMode }> = ({
  spc,
  mode = "normal",
}) => {
  const order = SPC_LEVELS.map((l) => l.key);
  const items = (spc?.categorical || [])
    .map((f: any) => ({
      feature: f,
      level: String(f?.properties?.level || "tstm").toLowerCase(),
    }))
    .sort((a, b) => order.indexOf(a.level) - order.indexOf(b.level));
  return (
    <SpcContent
      items={items}
      pop={spc?.populationByLevel}
      animate
      topicColor={palette(mode).topicColor}
    />
  );
};
