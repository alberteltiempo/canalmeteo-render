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
import { SatView, SpcOutlook, TmaxCity, ThemeMode } from "../types";

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
        borderRadius: 12,
        padding: "6px 15px 8px",
        boxShadow: TEMP_BOX_SHADOW,
        textAlign: "center",
      }}
    >
      <div
        style={{
          fontSize: 44,
          fontWeight: 900,
          color: fg,
          lineHeight: 1,
          fontFamily: "'JetBrains Mono', monospace",
        }}
      >
        {Math.round(c.tmax)}°
      </div>
      <div style={{ fontSize: 19, fontWeight: 800, color: fg, marginTop: 3, whiteSpace: "nowrap", opacity: 0.95 }}>
        {c.name}
      </div>
    </div>
  );
};

// Escala diverging para el CAMBIO de temperatura (°F respecto a hoy).
function deltaColor(d: number): string {
  if (d <= -12) return "#3b6fb5";
  if (d <= -7) return "#5b96d6";
  if (d <= -3) return "#9ec4e6";
  if (d < 3) return "#b9c2c9"; // sin cambios apreciables (gris)
  if (d < 7) return "#f0a06a";
  if (d < 12) return "#ec7a4e";
  return "#d6402c";
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
        borderRadius: 12,
        padding: "6px 14px 8px",
        boxShadow: TEMP_BOX_SHADOW,
        textAlign: "center",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
        <span style={{ fontSize: 30, lineHeight: 1, color: fg }}>{up ? "▲" : "▼"}</span>
        <span
          style={{
            fontSize: 38,
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
      <div style={{ fontSize: 19, fontWeight: 800, color: fg, marginTop: 3, whiteSpace: "nowrap", opacity: 0.95 }}>
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
    <div style={{ color: "#fff", fontSize: 18, fontWeight: 700, opacity: 0.9 }}>{title}</div>
    <div
      style={{
        width: 360,
        height: 14,
        borderRadius: 7,
        border: "1px solid rgba(255,255,255,0.3)",
        background: gradient,
      }}
    />
    <div style={{ width: 360, display: "flex", justifyContent: "space-between", color: "#dfe8f0", fontSize: 14 }}>
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
  { id: "NYC", name: "Nueva York", lon: -74.01, lat: 40.71, tmax: 86 },
  { id: "BOS", name: "Boston", lon: -71.06, lat: 42.36, tmax: 79 },
];

const TMAX_TOMORROW: TempCity[] = TMAX_TODAY.map((c) => ({
  ...c,
  tmax: c.tmax + [3, -6, 2, 4, -2, 1, -5, 6, 0, 7, -8, -10, 1, -7, 5, 6, -3, 0, 4, 5][
    TMAX_TODAY.indexOf(c)
  ],
}));

const TVAR_TOMORROW: DeltaCity[] = TMAX_TODAY.map((c, i) => ({
  id: c.id,
  name: c.name,
  lon: c.lon,
  lat: c.lat,
  delta: TMAX_TOMORROW[i].tmax - c.tmax,
}));

const TEMP_GRADIENT =
  "linear-gradient(90deg,#7c4dff 0%,#3d7bff 18%,#21b6c9 32%,#2ecc71 46%,#f4d03f 60%,#ef8e2d 74%,#e74c3c 88%,#c0298a 100%)";
const DELTA_GRADIENT =
  "linear-gradient(90deg,#3b6fb5 0%,#9ec4e6 35%,#b9c2c9 50%,#f0a06a 65%,#d6402c 100%)";

// Empujones (px) por id: Bismarck cae bajo el banner (bajarla) y el par
// Dallas/Houston se solapa en vertical → una caja a la izquierda y otra a la
// derecha de su punto.
const TEMP_NUDGE: Record<string, [number, number]> = {
  BIS: [0, 60],
  DAL: [-96, -6],
  HOU: [70, 22],
};

// Contenido compartido de máxima (hoy/mañana): cambia título/subtítulo/datos y,
// en escena real, el ráster NBM drapeado bajo las cajas.
const TmaxContent: React.FC<{
  data: TempCity[];
  sub: string;
  topicColor: string;
  raster?: SatView;
  animate?: boolean;
}> = ({ data, sub, topicColor, raster, animate }) => (
  <ServiceMap
    points={data}
    topPad={150}
    nudge={TEMP_NUDGE}
    animate={animate}
    raster={raster}
    boxSize={(c) => ({ w: Math.max(120, c.name.length * 11 + 40), h: 92 })}
    renderChip={(c) => <TmaxBox c={c} />}
  >
    <TopicBar topic="TEMPERATURA MÁXIMA" sub={sub} topicColor={topicColor} opacity={1} />
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
    topPad={150}
    nudge={TEMP_NUDGE}
    animate={animate}
    raster={raster}
    boxSize={(c) => ({ w: Math.max(120, c.name.length * 11 + 40), h: 92 })}
    renderChip={(c) => <DeltaBox c={c} />}
  >
    <TopicBar topic="CAMBIO DE TEMPERATURA" sub="PRÓXIMAS 24 HORAS" topicColor={topicColor} opacity={1} />
    <Colorbar title="Cambio (°F)" gradient={DELTA_GRADIENT} labels={["−12°", "0°", "+12°"]} />
  </ServiceMap>
);

// ── Mockups (Still, datos de muestra) ──
export const TmaxTodayMockup: React.FC = () => (
  <TmaxContent data={TMAX_TODAY} sub="HOY" topicColor="#F39C12" />
);
export const TmaxTomorrowMockup: React.FC = () => (
  <TmaxContent data={TMAX_TOMORROW} sub="MAÑANA" topicColor="#F39C12" />
);
export const TvarMockup: React.FC = () => (
  <TvarContent data={TVAR_TOMORROW} topicColor="#F39C12" />
);

// ── Escenas reales (feeds NBM) ──
export const TmaxScene: React.FC<{
  cities?: TmaxCity[];
  raster?: SatView;
  sub: string;
  mode?: ThemeMode;
}> = ({ cities = [], raster, sub, mode = "normal" }) => (
  <TmaxContent
    data={cities.map((c) => ({ ...c }))}
    sub={sub}
    raster={raster}
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
  const polygons: MapPolygon[] = items.map((p) => ({
    data: p.feature,
    fill: colorOfLevel(p.level),
    line: colorOfLevel(p.level),
    fillOpacity: 0.5,
  }));
  // Solo los niveles presentes en la leyenda (en orden de severidad).
  const present = new Set(items.map((p) => p.level));
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
      <TopicBar topic="RIESGO DE TIEMPO SEVERO" sub="SPC · HOY · EE. UU." topicColor={topicColor} opacity={op} />
      {items.length === 0 ? (
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
              Estados Unidos · tiempo severo
            </div>
          </div>
        </AbsoluteFill>
      ) : (
        <div style={{ position: "absolute", left: 48, bottom: 40, display: "flex", gap: 18, flexWrap: "wrap", maxWidth: 1100, opacity: op }}>
          {legend.map((l) => {
            const p = pop?.[l.key];
            return (
              <div key={l.key} style={{ display: "flex", alignItems: "center", gap: 9 }}>
                <span
                  style={{
                    width: 22,
                    height: 14,
                    borderRadius: 3,
                    background: l.color,
                    border: "1px solid rgba(255,255,255,0.5)",
                    flex: "0 0 auto",
                  }}
                />
                <span style={{ color: "#fff", fontSize: 18, fontWeight: 700 }}>
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

export const SpcOutlookMockup: React.FC = () => (
  <SpcContent
    items={SPC_SAMPLE.map((p) => ({ feature: p.feature, level: p.level }))}
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
