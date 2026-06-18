import React from "react";
import { AbsoluteFill } from "remotion";
import { loadFont } from "@remotion/google-fonts/Outfit";
import { ServiceMap, textOn, Geo, Placed } from "./ServicesMockups";
import { SatMap, MapPolygon } from "../components/SatMap";
import { TopicBar } from "../components/Overlay";
import { CONUS_VIEW, CONUS_PAD } from "../lib/cdn";
import { MAJOR_CITIES } from "../lib/cities";
import { tempColor } from "../lib/conditions";
import { SatView } from "../types";

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

// Caja de temperatura más CLARA que las de servicios (azul pizarra), para
// destacar sobre el mapa/relieve. Compartida por máxima y variación.
const TEMP_BOX_BG = "rgba(46,66,88,0.92)";
const TEMP_BOX_BORDER = "1px solid rgba(255,255,255,0.24)";

// Caja de máxima: gran número °F coloreado por temperatura + nombre de ciudad.
const TmaxBox: React.FC<{ c: TempCity }> = ({ c }) => {
  const color = tempColor(c.tmax);
  return (
    <div
      style={{
        background: TEMP_BOX_BG,
        border: TEMP_BOX_BORDER,
        borderLeft: `6px solid ${color}`,
        borderRadius: 11,
        padding: "7px 14px 9px 12px",
        boxShadow: "0 8px 22px rgba(0,0,0,0.5)",
        textAlign: "center",
      }}
    >
      <div
        style={{
          fontSize: 44,
          fontWeight: 900,
          color,
          lineHeight: 1,
          fontFamily: "'JetBrains Mono', monospace",
        }}
      >
        {Math.round(c.tmax)}°
      </div>
      <div style={{ fontSize: 19, fontWeight: 700, color: "#fff", marginTop: 4, whiteSpace: "nowrap" }}>
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

// Caja de variación: flecha ↑/↓ + Δ°F con signo, coloreada por la escala diverging.
const DeltaBox: React.FC<{ c: DeltaCity }> = ({ c }) => {
  const color = deltaColor(c.delta);
  const up = c.delta >= 0;
  const sign = c.delta > 0 ? "+" : "";
  return (
    <div
      style={{
        background: TEMP_BOX_BG,
        border: TEMP_BOX_BORDER,
        borderLeft: `6px solid ${color}`,
        borderRadius: 11,
        padding: "7px 13px 9px 12px",
        boxShadow: "0 8px 22px rgba(0,0,0,0.5)",
        textAlign: "center",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
        <span style={{ fontSize: 30, lineHeight: 1, color }}>{up ? "▲" : "▼"}</span>
        <span
          style={{
            fontSize: 38,
            fontWeight: 900,
            color,
            lineHeight: 1,
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          {sign}
          {Math.round(c.delta)}°
        </span>
      </div>
      <div style={{ fontSize: 19, fontWeight: 700, color: "#fff", marginTop: 4, whiteSpace: "nowrap" }}>
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

// Contenido compartido de máxima (hoy/mañana): solo cambia título/subtítulo/datos.
const TmaxContent: React.FC<{ data: TempCity[]; sub: string; topicColor: string }> = ({
  data,
  sub,
  topicColor,
}) => (
  <ServiceMap
    points={data}
    topPad={150}
    nudge={TEMP_NUDGE}
    boxSize={(c) => ({ w: Math.max(120, c.name.length * 11 + 40), h: 92 })}
    renderChip={(c) => <TmaxBox c={c} />}
  >
    <TopicBar topic="TEMPERATURA MÁXIMA" sub={sub} topicColor={topicColor} opacity={1} />
    <Colorbar title="Máxima (°F)" gradient={TEMP_GRADIENT} labels={["10°", "60°", "110°"]} />
  </ServiceMap>
);

export const TmaxTodayMockup: React.FC = () => (
  <TmaxContent data={TMAX_TODAY} sub="HOY · EE. UU." topicColor="#F39C12" />
);
export const TmaxTomorrowMockup: React.FC = () => (
  <TmaxContent data={TMAX_TOMORROW} sub="MAÑANA · EE. UU." topicColor="#F39C12" />
);

export const TvarMockup: React.FC = () => (
  <ServiceMap
    points={TVAR_TOMORROW}
    topPad={150}
    nudge={TEMP_NUDGE}
    boxSize={(c) => ({ w: Math.max(120, c.name.length * 11 + 40), h: 92 })}
    renderChip={(c) => <DeltaBox c={c} />}
  >
    <TopicBar topic="CAMBIO DE TEMPERATURA" sub="ÚLTIMAS 24 HORAS" topicColor="#F39C12" opacity={1} />
    <Colorbar
      title="Cambio (°F)"
      gradient={DELTA_GRADIENT}
      labels={["−12°", "0°", "+12°"]}
    />
  </ServiceMap>
);

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

export const SpcOutlookMockup: React.FC = () => {
  const colorOf = (lvl: string) => SPC_LEVELS.find((l) => l.key === lvl)?.color || "#c1e9c1";
  const view: SatView = { view: "base", band: "", bounds: null, frames: [] };
  // Más opacos los niveles altos (se dibujan encima por orden del array).
  const polygons: MapPolygon[] = SPC_SAMPLE.map((p) => ({
    data: p.feature,
    fill: colorOf(p.level),
    line: colorOf(p.level),
    fillOpacity: 0.5,
  }));
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
        animatePolygons={false}
        showSatellite={false}
      />
      <AbsoluteFill
        style={{
          pointerEvents: "none",
          background:
            "linear-gradient(180deg, rgba(0,0,0,0.5) 0%, rgba(0,0,0,0) 22%, rgba(0,0,0,0) 78%, rgba(0,0,0,0.5) 100%)",
        }}
      />
      <TopicBar topic="RIESGO DE TIEMPO SEVERO" sub="SPC · HOY · EE. UU." topicColor="#F39C12" opacity={1} />
      {/* Leyenda de niveles SPC */}
      <div style={{ position: "absolute", left: 48, bottom: 40, display: "flex", gap: 18, flexWrap: "wrap", maxWidth: 1100 }}>
        {SPC_LEVELS.map((l) => (
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
            <span style={{ color: "#fff", fontSize: 18, fontWeight: 700 }}>{l.label}</span>
          </div>
        ))}
      </div>
    </AbsoluteFill>
  );
};
