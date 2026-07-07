import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { loadFont } from "@remotion/google-fonts/Outfit";
import { SatMap, MapPolygon, MapLine, MapMarker, MapDot } from "../components/SatMap";
import { TopicBar } from "../components/Overlay";
import { CONUS_VIEW, CONUS_PAD } from "../lib/cdn";
import { MAJOR_CITIES } from "../lib/cities";
import { palette } from "../lib/theme";
import { FrontsData, StormReportsData, DroughtData, SatView, ThemeMode } from "../types";

const { fontFamily } = loadFont();

// Vista "base" (sin satélite): solo la cartografía sistema + overlays propios.
const BASE_VIEW: SatView = { view: "base", band: "", bounds: null, frames: [] };

// Shell común de las escenas de mapa nacional: base + viñeta + barra de tópico +
// leyenda (children). Replica el encuadre único de todo el segmento.
const MapScene: React.FC<{
  topic: string;
  sub: string;
  topicColor: string;
  op: number;
  polygons?: MapPolygon[];
  lines?: MapLine[];
  markers?: MapMarker[];
  dots?: MapDot[];
  dotRadius?: number;
  animate?: boolean;
  children?: React.ReactNode;
}> = ({ topic, sub, topicColor, op, polygons, lines, markers, dots, dotRadius, animate, children }) => (
  <AbsoluteFill style={{ background: "#000", fontFamily }}>
    <SatMap
      sat={BASE_VIEW}
      center={[-96, 38]}
      zoom={3.4}
      fitBounds={CONUS_VIEW}
      fitPadding={CONUS_PAD}
      cityMarkers={MAJOR_CITIES}
      polygons={polygons}
      lines={lines}
      markers={markers}
      dots={dots}
      dotRadius={dotRadius}
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
    <TopicBar topic={topic} sub={sub} topicColor={topicColor} opacity={op} />
    {children}
  </AbsoluteFill>
);

// Leyenda inferior-izquierda compartida (fila de ítems con swatch + texto).
const Legend: React.FC<{ op: number; children: React.ReactNode }> = ({ op, children }) => (
  <div
    style={{
      position: "absolute",
      left: 48,
      bottom: 40,
      display: "flex",
      gap: 20,
      flexWrap: "wrap",
      maxWidth: 1280,
      opacity: op,
      alignItems: "center",
    }}
  >
    {children}
  </div>
);

// ═════════════════════════════════════════════════════════════════════════════
// 1) Mapa de superficie: frentes + centros de presión (A/B)
// ═════════════════════════════════════════════════════════════════════════════
const FRONT_STYLE: Record<string, { color: string; label: string; dash?: number[] }> = {
  cold: { color: "#3a8ff0", label: "Frente frío" },
  warm: { color: "#e64a3b", label: "Frente cálido" },
  occluded: { color: "#b06bd6", label: "Frente ocluido" },
  stationary: { color: "#23b3a0", label: "Estacionario" },
  trough: { color: "#e0913a", label: "Vaguada", dash: [2, 2] },
};
const FRONT_ORDER = ["cold", "warm", "occluded", "stationary", "trough"];

// Marcador de centro de presión: gran "A" (alta, azul) o "B" (baja, roja) con
// halo blanco para leerse sobre el relieve, y la presión (hPa) debajo.
function pressureHTML(kind: "H" | "L", pressure?: number): string {
  const isHigh = kind === "H";
  const letter = isHigh ? "A" : "B";
  const color = isHigh ? "#1f63c8" : "#e0392b";
  const halo =
    "text-shadow:0 0 5px #fff,0 0 5px #fff,0 0 5px #fff,0 0 9px #fff,0 2px 4px rgba(0,0,0,0.45);";
  const pres =
    pressure != null
      ? `<div style="font-size:18px;font-weight:800;color:#10202c;background:rgba(255,255,255,0.82);` +
        `border-radius:4px;padding:0 5px;margin-top:-2px;font-family:'JetBrains Mono',monospace;">${pressure}</div>`
      : "";
  return (
    `<div style="display:flex;flex-direction:column;align-items:center;pointer-events:none;` +
    `font-family:Outfit,sans-serif;transform:translateY(-2px);">` +
    `<div style="font-size:56px;font-weight:900;line-height:0.85;color:${color};${halo}">${letter}</div>` +
    pres +
    `</div>`
  );
}

// Centros de presión muy alejados (Alaska, Pacífico, Atlántico medio) ensucian el
// encuadre CONUS → solo dibujamos los que caen dentro/junto a los 48 estados.
const inConus = (lon: number, lat: number) =>
  lon >= -127 && lon <= -66 && lat >= 22 && lat <= 51;

const FrontsContent: React.FC<{ data: FrontsData; topicColor: string; animate?: boolean }> = ({
  data,
  topicColor,
  animate,
}) => {
  const frame = useCurrentFrame();
  const op = animate ? interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" }) : 1;

  // Agrupamos las líneas por tipo en un FeatureCollection por estilo (menos capas).
  const byType = new Map<string, any[]>();
  for (const ln of data.lines) {
    const key = FRONT_STYLE[ln.ftype] ? ln.ftype : "trough";
    const arr = byType.get(key) || [];
    arr.push({ type: "Feature", properties: {}, geometry: ln.geometry });
    byType.set(key, arr);
  }
  const lines: MapLine[] = FRONT_ORDER.filter((t) => byType.has(t)).map((t) => {
    const st = FRONT_STYLE[t];
    return {
      data: { type: "FeatureCollection", features: byType.get(t) },
      color: st.color,
      width: 4.5,
      dash: st.dash,
      casing: !st.dash, // sólido lleva casing oscuro; la vaguada discontinua no
    };
  });

  const markers: MapMarker[] = data.points
    .filter((p) => inConus(p.lon, p.lat))
    .map((p) => ({ lon: p.lon, lat: p.lat, html: pressureHTML(p.kind, p.pressure) }));

  const present = FRONT_ORDER.filter((t) => byType.has(t));

  return (
    <MapScene
      topic="MAPA DE SUPERFICIE"
      sub="FRENTES Y PRESIÓN · HOY"
      topicColor={topicColor}
      op={op}
      lines={lines}
      markers={markers}
      animate={animate}
    >
      <Legend op={op}>
        {present.map((t) => {
          const st = FRONT_STYLE[t];
          return (
            <div key={t} style={{ display: "flex", alignItems: "center", gap: 9 }}>
              <span
                style={{
                  width: 30,
                  height: 0,
                  borderTop: `${st.dash ? "4px dashed" : "5px solid"} ${st.color}`,
                  flex: "0 0 auto",
                }}
              />
              <span style={{ color: "#fff", fontSize: 22, fontWeight: 700 }}>{st.label}</span>
            </div>
          );
        })}
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ color: "#1f63c8", fontSize: 28, fontWeight: 900 }}>A</span>
          <span style={{ color: "#fff", fontSize: 22, fontWeight: 700 }}>Alta presión</span>
          <span style={{ color: "#e0392b", fontSize: 28, fontWeight: 900, marginLeft: 10 }}>B</span>
          <span style={{ color: "#fff", fontSize: 22, fontWeight: 700 }}>Baja presión</span>
        </div>
      </Legend>
    </MapScene>
  );
};

export const FrontsScene: React.FC<{
  fronts?: FrontsData | null;
  mode?: ThemeMode;
  animate?: boolean;
}> = ({ fronts, mode = "normal", animate = true }) => {
  if (!fronts) return <AbsoluteFill style={{ background: "#000" }} />;
  return <FrontsContent data={fronts} animate={animate} topicColor={palette(mode).topicColor} />;
};

// ═════════════════════════════════════════════════════════════════════════════
// 2) Reportes de tormenta últimas 24 h ("lo que pasó")
// ═════════════════════════════════════════════════════════════════════════════
const REPORT_CAT: Record<string, { color: string; label: string }> = {
  tornado: { color: "#e53935", label: "Tornado" },
  wind: { color: "#3d7bff", label: "Viento" },
  hail: { color: "#2ecc71", label: "Granizo" },
  rain: { color: "#26c6da", label: "Lluvia / inund." },
  winter: { color: "#7fb6e8", label: "Invierno" }, // azulado: blanco se perdía en el mapa
};

// Iconos SVG por categoría (más grandes y legibles que los puntos). Halo blanco
// (drop-shadow) para destacar sobre el relieve gris. viewBox 0 0 32 32.
const REPORT_ICON: Record<string, string> = {
  // Embudo de tornado.
  tornado:
    '<path d="M4 5h24l-7 6H11z" /><path d="M11 13h10l-4 6h-2z" /><path d="M15 21h4l-3 7z" />',
  // Ráfagas de viento.
  wind:
    '<g fill="none" stroke="CLR" stroke-width="3" stroke-linecap="round"><path d="M3 11h15a3.2 3.2 0 1 0-3.2-3.2"/><path d="M3 17h21a3.2 3.2 0 1 1-3.2 3.2"/><path d="M3 23h12a2.8 2.8 0 1 1-2.8 2.8"/></g>',
  // Nube + bolas de granizo.
  hail:
    '<path d="M9 15a5 5 0 0 1 .6-10 6 6 0 0 1 11.3 1.7A4.6 4.6 0 0 1 22 15z"/><circle cx="11" cy="23" r="2.6"/><circle cx="17" cy="25" r="2.6"/><circle cx="22" cy="22" r="2.6"/>',
  // Gota de lluvia.
  rain: '<path d="M16 4s-9 11-9 17a9 9 0 0 0 18 0c0-6-9-17-9-17z"/>',
  // Copo de nieve.
  winter:
    '<g fill="none" stroke="CLR" stroke-width="2.6" stroke-linecap="round"><path d="M16 4v24M5.6 10l20.8 12M26.4 10 5.6 22"/><path d="M16 4l-3 3M16 4l3 3M16 28l-3-3M16 28l3-3"/></g>',
};

function reportIconHTML(cat: string): string {
  const color = REPORT_CAT[cat]?.color || "#9aa7b2";
  // Placa de color con el icono en BLANCO dentro → máximo contraste sobre el
  // relieve gris (mejor que el icono de color suelto con halo). El icono se
  // pinta blanco: los de relleno via fill del <svg>, los de trazo via CLR→#fff.
  const body = (REPORT_ICON[cat] || '<circle cx="16" cy="16" r="7"/>').replace(/CLR/g, "#fff");
  const D = 48; // diámetro de la placa
  const IS = 32; // tamaño del icono dentro
  // Para cuadrado en vez de círculo: borderRadius "20%" en lugar de "50%".
  return (
    `<div style="width:${D}px;height:${D}px;border-radius:50%;box-sizing:border-box;` +
    `background:${color};border:2px solid #fff;` +
    `display:flex;align-items:center;justify-content:center;pointer-events:none;` +
    `box-shadow:0 1px 3px rgba(0,0,0,0.55),0 0 0 1px rgba(0,0,0,0.25);">` +
    `<svg width="${IS}" height="${IS}" viewBox="0 0 32 32" fill="#fff">${body}</svg></div>`
  );
}

const ReportsContent: React.FC<{
  data: StormReportsData;
  topicColor: string;
  animate?: boolean;
}> = ({ data, topicColor, animate }) => {
  const frame = useCurrentFrame();
  const op = animate ? interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" }) : 1;

  const markers: MapMarker[] = data.reports.map((r) => ({
    lon: r.lon,
    lat: r.lat,
    html: reportIconHTML(r.cat),
  }));

  // Conteos para la leyenda (del summary = total real 24 h, no solo la muestra).
  const s = data.summary;
  const counts: { key: string; n: number }[] = [
    { key: "tornado", n: s.tornado },
    { key: "wind", n: s.wind },
    { key: "hail", n: s.hail },
    { key: "rain", n: s.rain },
    { key: "winter", n: s.snow + s.ice },
  ].filter((c) => c.n > 0);

  return (
    <MapScene
      topic="REPORTES DE TORMENTA"
      sub="ÚLTIMAS 24 HORAS"
      topicColor={topicColor}
      op={op}
      markers={markers}
      animate={animate}
    >
      {/* Total grande arriba a la derecha, dentro de una caja. */}
      <div
        style={{
          position: "absolute",
          right: 48,
          top: 56,
          opacity: op,
          textAlign: "center",
          background: "rgba(8,20,30,0.82)",
          border: "1.5px solid rgba(255,255,255,0.28)",
          borderRadius: 14,
          padding: "14px 26px",
          boxShadow: "0 4px 18px rgba(0,0,0,0.5)",
        }}
      >
        <div
          style={{
            fontSize: 82,
            fontWeight: 900,
            color: "#fff",
            lineHeight: 1,
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          {data.total}
        </div>
        <div
          style={{
            fontSize: 20,
            fontWeight: 800,
            letterSpacing: 2,
            textTransform: "uppercase",
            color: "rgba(255,255,255,0.85)",
            marginTop: 5,
          }}
        >
          reportes
        </div>
      </div>
      <Legend op={op}>
        {counts.map((c) => {
          const cat = REPORT_CAT[c.key];
          return (
            <div key={c.key} style={{ display: "flex", alignItems: "center", gap: 11 }}>
              <span
                style={{
                  width: 24,
                  height: 24,
                  borderRadius: "50%",
                  background: cat.color,
                  border: "2px solid rgba(255,255,255,0.85)",
                  flex: "0 0 auto",
                }}
              />
              <span style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                <span style={{ color: "#fff", fontSize: 24, fontWeight: 700 }}>{cat.label}</span>
                <span
                  style={{
                    color: "#fff",
                    fontWeight: 900,
                    fontSize: 38,
                    lineHeight: 1,
                    fontFamily: "'JetBrains Mono', monospace",
                    textShadow: "0 2px 8px rgba(0,0,0,0.6)",
                  }}
                >
                  {c.n}
                </span>
              </span>
            </div>
          );
        })}
      </Legend>
    </MapScene>
  );
};

export const ReportsScene: React.FC<{
  reports?: StormReportsData | null;
  mode?: ThemeMode;
  animate?: boolean;
}> = ({ reports, mode = "normal", animate = true }) => {
  if (!reports) return <AbsoluteFill style={{ background: "#000" }} />;
  return <ReportsContent data={reports} animate={animate} topicColor={palette(mode).topicColor} />;
};

// ═════════════════════════════════════════════════════════════════════════════
// 3) Monitor de sequía (USDM)
// ═════════════════════════════════════════════════════════════════════════════
// Colores estándar USDM por nivel D0..D4.
const DM_COLOR = ["#ffff00", "#fcd37f", "#ffaa00", "#e60000", "#730000"];
const DM_LABEL = [
  "D0 · Anormalmente seco",
  "D1 · Moderada",
  "D2 · Severa",
  "D3 · Extrema",
  "D4 · Excepcional",
];

const DroughtContent: React.FC<{ data: DroughtData; topicColor: string; animate?: boolean }> = ({
  data,
  topicColor,
  animate,
}) => {
  const frame = useCurrentFrame();
  const op = animate ? interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" }) : 1;

  // Un polígono por feature, de menor a mayor severidad (D4 queda encima).
  const feats = [...(data.geojson?.features || [])].sort(
    (a, b) => Number(a?.properties?.DM) - Number(b?.properties?.DM)
  );
  const polygons: MapPolygon[] = feats.map((f) => {
    const dm = Number(f?.properties?.DM) || 0;
    const c = DM_COLOR[dm] || DM_COLOR[0];
    return { data: f, fill: c, line: c, fillOpacity: 0.62 };
  });

  return (
    <MapScene
      topic="MONITOR DE SEQUÍA"
      sub="NOROESTE"
      topicColor={topicColor}
      op={op}
      polygons={polygons}
      animate={animate}
    >
      <Legend op={op}>
        {data.levels.map((dm) => (
          <div key={dm} style={{ display: "flex", alignItems: "center", gap: 9 }}>
            <span
              style={{
                width: 26,
                height: 17,
                borderRadius: 3,
                background: DM_COLOR[dm],
                border: "1px solid rgba(255,255,255,0.5)",
                flex: "0 0 auto",
              }}
            />
            <span style={{ color: "#fff", fontSize: 22, fontWeight: 700 }}>{DM_LABEL[dm]}</span>
          </div>
        ))}
      </Legend>
    </MapScene>
  );
};

export const DroughtScene: React.FC<{
  drought?: DroughtData | null;
  mode?: ThemeMode;
  animate?: boolean;
}> = ({ drought, mode = "normal", animate = true }) => {
  if (!drought) return <AbsoluteFill style={{ background: "#000" }} />;
  return <DroughtContent data={drought} animate={animate} topicColor={palette(mode).topicColor} />;
};
