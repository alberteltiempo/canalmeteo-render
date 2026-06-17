import React, { useEffect, useRef, useState } from "react";
import {
  AbsoluteFill,
  continueRender,
  delayRender,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { loadFont } from "@remotion/google-fonts/Outfit";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import { MAPBOX_TOKEN, MAPBOX_STYLE, CONUS_VIEW, CONUS_PAD } from "../lib/cdn";
import { applyBaseMap } from "../lib/basemap";
import { TopicBar } from "../components/Overlay";
import { palette } from "../lib/theme";
import type { Airport, AirStatus, UvCity, AqiCity, ThemeMode } from "../types";

const { fontFamily } = loadFont();

// ─────────────────────────────────────────────────────────────────────────────
// MOCKUPS de servicios CONUS (Still → PNG, para pulir el LOOK antes de cablear
// los feeds reales): demoras de aeropuertos (FAA), índice UV (EPA) y calidad del
// aire / AQI (AirNow). Las tres son DATOS PUNTUALES por ciudad/aeropuerto →
// iconos coloreados sobre la base "sistema TV" con colocación anti-solape.
// Datos de muestra: NO son reales, solo para juzgar el diseño.
// ─────────────────────────────────────────────────────────────────────────────

// ── Colocador anti-solape genérico (chips pequeños) ──────────────────────────
type Rect = { x0: number; y0: number; x1: number; y1: number };
type Geo = { id: string; lon: number; lat: number };
type Placed<T> = T & { x: number; y: number; bx: number; by: number };

function overlap(a: Rect, b: Rect, pad = 6): number {
  const ix = Math.min(a.x1, b.x1 + pad) - Math.max(a.x0, b.x0 - pad);
  const iy = Math.min(a.y1, b.y1 + pad) - Math.max(a.y0, b.y0 - pad);
  return ix > 0 && iy > 0 ? ix * iy : 0;
}

// Coloca cada chip junto a su punto eligiendo el primer hueco sin solape
// (arriba/abajo/lados/diagonales). El array entra por orden de PRIORIDAD.
function placeChips<T extends Geo>(
  items: (T & { x: number; y: number; w: number; h: number })[],
  W: number,
  H: number,
  top: number,
  bottom: number
): Placed<T>[] {
  const margin = 20;
  const gap = 12;
  const taken: Rect[] = [];
  const out: Placed<T>[] = [];
  for (const c of items) {
    const { w, h } = c;
    // Anillo cercano (8) + anillo lejano (8, doble distancia) para deshacer
    // aglomeraciones densas (p. ej. el corredor NE: EWR/LGA/JFK/PHL/BWI).
    const dx = gap + w / 2;
    const dy = gap + h / 2;
    const cands: [number, number][] = [
      [c.x, c.y - dy],
      [c.x, c.y + dy],
      [c.x + dx, c.y],
      [c.x - dx, c.y],
      [c.x + dx, c.y - dy],
      [c.x - dx, c.y - dy],
      [c.x + dx, c.y + dy],
      [c.x - dx, c.y + dy],
      [c.x, c.y - dy * 2],
      [c.x, c.y + dy * 2],
      [c.x + dx * 1.8, c.y],
      [c.x - dx * 1.8, c.y],
      [c.x + dx * 1.8, c.y - dy * 1.6],
      [c.x - dx * 1.8, c.y - dy * 1.6],
      [c.x + dx * 1.8, c.y + dy * 1.6],
      [c.x - dx * 1.8, c.y + dy * 1.6],
    ];
    let best: { cx: number; cy: number; rect: Rect } | null = null;
    let bestScore = Infinity;
    for (const [cx0, cy0] of cands) {
      const cx = Math.max(margin + w / 2, Math.min(W - margin - w / 2, cx0));
      const cy = Math.max(top + h / 2, Math.min(bottom - h / 2, cy0));
      const rect: Rect = { x0: cx - w / 2, y0: cy - h / 2, x1: cx + w / 2, y1: cy + h / 2 };
      let ov = 0;
      for (const t of taken) ov += overlap(rect, t);
      const drift = Math.abs(cx - cx0) + Math.abs(cy - cy0);
      const score = ov * 4 + drift;
      if (score < bestScore) {
        bestScore = score;
        best = { cx, cy, rect };
      }
      if (score === 0) break;
    }
    if (best) {
      taken.push(best.rect);
      out.push({ ...c, bx: best.cx, by: best.cy });
    }
  }
  return out;
}

// ── Base "sistema TV" + proyección de puntos + colocación de chips ───────────
// Componente reutilizable: monta el mapa, proyecta los puntos, coloca los chips
// y los pinta con renderChip. Los overlays (título/leyenda) van como children.
function ServiceMap<T extends Geo>({
  points,
  boxSize,
  renderChip,
  topPad = 110,
  animate = false,
  nudge,
  children,
}: {
  points: T[];
  boxSize: (p: T) => { w: number; h: number };
  renderChip: (p: Placed<T>) => React.ReactNode;
  topPad?: number;
  // En escena (vídeo) hace fade-in de los chips; en mockup (Still) queda fijo.
  animate?: boolean;
  // Empujones manuales (px) por id, tras el auto-placement (zonas densas).
  nudge?: Record<string, [number, number]>;
  children?: React.ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<mapboxgl.Map | null>(null);
  const [placed, setPlaced] = useState<Placed<T>[]>([]);
  const { width, height } = useVideoConfig();
  const frame = useCurrentFrame();
  const op = animate ? interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" }) : 1;

  useEffect(() => {
    if (!ref.current) return;
    const handle = delayRender("service-mockup");
    mapboxgl.accessToken = MAPBOX_TOKEN;
    const map = new mapboxgl.Map({
      container: ref.current,
      style: MAPBOX_STYLE,
      center: [-96, 38],
      zoom: 3.4,
      interactive: false,
      attributionControl: false,
      preserveDrawingBuffer: true,
      fadeDuration: 0,
      projection: "mercator",
    });
    mapRef.current = map;

    map.on("load", () => {
      applyBaseMap(map);
      map.resize();
      const cam = map.cameraForBounds(CONUS_VIEW, { padding: CONUS_PAD });
      if (cam) map.jumpTo(cam);
      else map.fitBounds(CONUS_VIEW, { animate: false });

      let done = false;
      const finish = () => {
        if (done) return;
        done = true;
        const projected = points.map((c) => {
          const p = map.project([c.lon, c.lat]);
          const { w, h } = boxSize(c);
          return { ...c, x: p.x, y: p.y, w, h };
        });
        const boxes = placeChips(projected, width, height, topPad, height - 56).map((b) => {
          const d = nudge?.[b.id];
          return d ? { ...b, bx: b.bx + d[0], by: b.by + d[1] } : b;
        });
        setPlaced(boxes);
        map.off("idle", finish);
        clearTimeout(fb);
        continueRender(handle);
      };
      map.on("idle", finish);
      const fb = setTimeout(finish, 90000);
    });

    return () => {
      try {
        continueRender(handle);
      } catch {
        /* noop */
      }
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [width, height]);

  return (
    <AbsoluteFill style={{ background: "#000", fontFamily }}>
      <style>{`.mapboxgl-ctrl-logo,.mapboxgl-ctrl-attrib,.mapboxgl-ctrl-bottom-left,.mapboxgl-ctrl-bottom-right{display:none !important;}`}</style>
      <div ref={ref} style={{ position: "absolute", inset: 0 }} />
      <AbsoluteFill
        style={{
          pointerEvents: "none",
          background:
            "linear-gradient(180deg, rgba(0,0,0,0.45) 0%, rgba(0,0,0,0) 18%, rgba(0,0,0,0) 82%, rgba(0,0,0,0.5) 100%)",
        }}
      />
      <div style={{ opacity: op }}>
        {placed.map((c) => (
          <React.Fragment key={c.id}>
            <div style={{ position: "absolute", left: c.bx, top: c.by, transform: "translate(-50%, -50%)" }}>
              {renderChip(c)}
            </div>
            <div
              style={{
                position: "absolute",
                left: c.x,
                top: c.y,
                width: 10,
                height: 10,
                borderRadius: "50%",
                background: "#fff",
                border: "2px solid rgba(0,0,0,0.6)",
                boxShadow: "0 0 6px rgba(0,0,0,0.6)",
                transform: "translate(-50%, -50%)",
              }}
            />
          </React.Fragment>
        ))}
        {children}
      </div>
    </AbsoluteFill>
  );
}

// Texto legible sobre un color de fondo: oscuro sobre claros (verde/amarillo),
// blanco sobre oscuros (rojo/morado/granate). Luminancia relativa sRGB.
function textOn(bg: string): string {
  const m = bg.replace("#", "");
  const r = parseInt(m.slice(0, 2), 16) / 255;
  const g = parseInt(m.slice(2, 4), 16) / 255;
  const b = parseInt(m.slice(4, 6), 16) / 255;
  const lum = 0.299 * r + 0.587 * g + 0.114 * b;
  return lum < 0.55 ? "#fff" : "#10202c";
}

// Disco/badge coloreado con un valor numérico dentro + nombre de ciudad debajo.
// Reutilizado por UV y AQI (mismo look, distinta escala/color).
const ValueBadge: React.FC<{
  value: number | string;
  name: string;
  color: string;
  sub?: string;
}> = ({ value, name, color, sub }) => (
  <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 5 }}>
    <div
      style={{
        width: 74,
        height: 74,
        borderRadius: "50%",
        background: color,
        border: "3px solid rgba(255,255,255,0.95)",
        boxShadow: "0 6px 18px rgba(0,0,0,0.6)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: textOn(color),
        fontWeight: 900,
        fontSize: 34,
        lineHeight: 1,
        fontFamily: "'JetBrains Mono', monospace",
      }}
    >
      {value}
    </div>
    <div
      style={{
        color: "#fff",
        fontSize: 23,
        fontWeight: 800,
        whiteSpace: "nowrap",
        textShadow: "0 2px 6px rgba(0,0,0,0.95),0 0 12px rgba(0,0,0,0.9)",
      }}
    >
      {name}
    </div>
    {sub ? (
      // Categoría como pastilla con el color del tramo de fondo y texto oscuro:
      // legible sobre el mapa (antes el texto coloreado se perdía).
      <div
        style={{
          background: color,
          color: textOn(color),
          fontSize: 14,
          fontWeight: 800,
          letterSpacing: 0.2,
          padding: "2px 10px",
          borderRadius: 999,
          boxShadow: "0 2px 8px rgba(0,0,0,0.5)",
          marginTop: 1,
        }}
      >
        {sub}
      </div>
    ) : null}
  </div>
);

// Leyenda horizontal de "stops" coloreados (UV/AQI).
const ScaleLegend: React.FC<{ title: string; stops: { c: string; label: string }[] }> = ({
  title,
  stops,
}) => (
  <div style={{ position: "absolute", left: 48, bottom: 36 }}>
    <div style={{ color: "#fff", fontSize: 17, fontWeight: 700, opacity: 0.9, marginBottom: 7 }}>
      {title}
    </div>
    <div style={{ display: "flex", gap: 0, borderRadius: 7, overflow: "hidden", border: "1px solid rgba(255,255,255,0.3)" }}>
      {stops.map((s) => (
        <div key={s.label} style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
          <div style={{ width: 92, height: 13, background: s.c }} />
        </div>
      ))}
    </div>
    <div style={{ display: "flex", gap: 0 }}>
      {stops.map((s) => (
        <div key={s.label} style={{ width: 92, textAlign: "center", color: "#dfe8f0", fontSize: 12, marginTop: 4 }}>
          {s.label}
        </div>
      ))}
    </div>
  </div>
);

// ═════════════════════════════════════════════════════════════════════════════
// 1) DEMORAS DE AEROPUERTOS (FAA Airport Status). Tipos en ../types.
// ═════════════════════════════════════════════════════════════════════════════
const AIRPORT_COLOR: Record<AirStatus, string> = {
  open: "#2ecc71",
  delay: "#f4a020",
  closed: "#e74c3c",
};
const airportLabel = (a: Airport): string =>
  a.status === "closed" ? "Cerrado" : a.status === "delay" ? `${a.delayMin} min` : "Normal";

const PlaneIcon: React.FC<{ size?: number; color?: string }> = ({ size = 26, color = "#fff" }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" style={{ display: "block" }}>
    <path
      d="M21 16v-2l-8-5V3.5a1.5 1.5 0 0 0-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L11 19v-5.5z"
      fill={color}
    />
  </svg>
);

const AirportChip: React.FC<{ a: Airport }> = ({ a }) => {
  const color = AIRPORT_COLOR[a.status];
  return (
    <div
      style={{
        background: "rgba(13,24,34,0.88)",
        border: "1px solid rgba(255,255,255,0.16)",
        borderLeft: `6px solid ${color}`,
        borderRadius: 11,
        padding: "7px 12px 8px 10px",
        boxShadow: "0 8px 22px rgba(0,0,0,0.5)",
        minWidth: 104,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <PlaneIcon size={24} color={color} />
        <span style={{ fontSize: 28, fontWeight: 900, color: "#fff", lineHeight: 1, letterSpacing: 1 }}>
          {a.iata}
        </span>
      </div>
      <div style={{ fontSize: 17, fontWeight: 700, color: "#fff", marginTop: 4, whiteSpace: "nowrap" }}>
        {a.city}
      </div>
      {/* Estado como pastilla rellena del color: el código de color es inequívoco
          (antes la línea fina del borde era casi imperceptible). */}
      <div
        style={{
          display: "inline-block",
          background: color,
          color: textOn(color),
          fontSize: 15,
          fontWeight: 800,
          letterSpacing: 0.2,
          padding: "2px 10px",
          borderRadius: 999,
          marginTop: 6,
          boxShadow: "0 2px 8px rgba(0,0,0,0.45)",
        }}
      >
        {airportLabel(a)}
      </div>
    </div>
  );
};

// Muestra (no real): ground stops/demoras típicas de un día con mal tiempo en el NE.
const AIRPORTS: Airport[] = [
  { id: "JFK", iata: "JFK", city: "Nueva York", lon: -73.78, lat: 40.64, status: "closed", delayMin: 0 },
  { id: "SFO", iata: "SFO", city: "San Francisco", lon: -122.38, lat: 37.62, status: "delay", delayMin: 62 },
  { id: "ORD", iata: "ORD", city: "Chicago", lon: -87.9, lat: 41.97, status: "delay", delayMin: 48 },
  { id: "ATL", iata: "ATL", city: "Atlanta", lon: -84.43, lat: 33.64, status: "delay", delayMin: 35 },
  { id: "EWR", iata: "EWR", city: "Newark", lon: -74.17, lat: 40.69, status: "closed", delayMin: 0 },
  { id: "MIA", iata: "MIA", city: "Miami", lon: -80.29, lat: 25.79, status: "delay", delayMin: 40 },
  { id: "LAX", iata: "LAX", city: "Los Ángeles", lon: -118.41, lat: 33.94, status: "delay", delayMin: 25 },
  { id: "BOS", iata: "BOS", city: "Boston", lon: -71.01, lat: 42.37, status: "delay", delayMin: 30 },
  { id: "DFW", iata: "DFW", city: "Dallas", lon: -97.04, lat: 32.9, status: "open", delayMin: 0 },
  { id: "DEN", iata: "DEN", city: "Denver", lon: -104.67, lat: 39.86, status: "open", delayMin: 0 },
  { id: "SEA", iata: "SEA", city: "Seattle", lon: -122.31, lat: 47.45, status: "open", delayMin: 0 },
  { id: "PHX", iata: "PHX", city: "Phoenix", lon: -112.01, lat: 33.43, status: "open", delayMin: 0 },
  { id: "MCO", iata: "MCO", city: "Orlando", lon: -81.31, lat: 28.43, status: "delay", delayMin: 20 },
  { id: "IAH", iata: "IAH", city: "Houston", lon: -95.34, lat: 29.99, status: "open", delayMin: 0 },
  { id: "MSP", iata: "MSP", city: "Mineápolis", lon: -93.22, lat: 44.88, status: "open", delayMin: 0 },
  { id: "SLC", iata: "SLC", city: "Salt Lake City", lon: -111.98, lat: 40.79, status: "open", delayMin: 0 },
  { id: "DTW", iata: "DTW", city: "Detroit", lon: -83.35, lat: 42.21, status: "open", delayMin: 0 },
  { id: "CLT", iata: "CLT", city: "Charlotte", lon: -80.94, lat: 35.21, status: "delay", delayMin: 15 },
];

// Empujones (px) para el corredor NE, muy denso (EWR/LGA/JFK junto a PHL/BWI), y
// para separar Portland por debajo de Seattle (costa NW).
const AIRPORT_NUDGE: Record<string, [number, number]> = {
  JFK: [70, -28],
  LGA: [86, 18],
  EWR: [-66, 30],
  PHL: [22, 70],
  BWI: [-60, 64],
  SEA: [0, -10],
  PDX: [0, 80],
};

// Contenido compartido por el mockup (Still) y la escena real (vídeo).
const AirportsContent: React.FC<{ data: Airport[]; animate?: boolean; topicColor: string }> = ({
  data,
  animate,
  topicColor,
}) => (
  <ServiceMap
    points={data}
    animate={animate}
    boxSize={(a) => ({ w: 23 + Math.max(112, a.city.length * 11 + 30), h: 108 })}
    renderChip={(a) => <AirportChip a={a} />}
    nudge={AIRPORT_NUDGE}
  >
    <TopicBar topic="DEMORAS EN AEROPUERTOS" sub="EE. UU." topicColor={topicColor} opacity={1} />
    <div style={{ position: "absolute", left: 48, bottom: 40, display: "flex", gap: 26 }}>
      {(
        [
          ["#2ecc71", "Normal"],
          ["#f4a020", "Demoras"],
          ["#e74c3c", "Cerrado / parada en tierra"],
        ] as [string, string][]
      ).map(([c, l]) => (
        <div key={l} style={{ display: "flex", alignItems: "center", gap: 9 }}>
          <PlaneIcon size={22} color={c} />
          <span style={{ color: "#fff", fontSize: 17, fontWeight: 700 }}>{l}</span>
        </div>
      ))}
    </div>
  </ServiceMap>
);

export const AirportsMockup: React.FC = () => (
  <AirportsContent data={AIRPORTS} topicColor="#F39C12" />
);

// Escena real (datos FAA del feed data/airports/delays.json).
export const AirportsScene: React.FC<{ airports?: Airport[]; mode?: ThemeMode }> = ({
  airports = [],
  mode = "normal",
}) => <AirportsContent data={airports} animate topicColor={palette(mode).topicColor} />;

// ═════════════════════════════════════════════════════════════════════════════
// 2) ÍNDICE UV (EPA). Tipo UvCity en ../types.
// ═════════════════════════════════════════════════════════════════════════════
// Escala estándar EPA.
function uvColor(uv: number): string {
  if (uv <= 2) return "#2ecc71";
  if (uv <= 5) return "#f4d03f";
  if (uv <= 7) return "#ef8e2d";
  if (uv <= 10) return "#e74c3c";
  return "#8e44ad";
}
function uvCat(uv: number): string {
  if (uv <= 2) return "Bajo";
  if (uv <= 5) return "Moderado";
  if (uv <= 7) return "Alto";
  if (uv <= 10) return "Muy alto";
  return "Extremo";
}

const UV_CITIES: UvCity[] = [
  { id: "MIA", name: "Miami", lon: -80.19, lat: 25.76, uv: 11 },
  { id: "PHX", name: "Phoenix", lon: -112.07, lat: 33.45, uv: 11 },
  { id: "LAX", name: "Los Ángeles", lon: -118.24, lat: 34.05, uv: 9 },
  { id: "HOU", name: "Houston", lon: -95.37, lat: 29.76, uv: 10 },
  { id: "DAL", name: "Dallas", lon: -96.8, lat: 32.78, uv: 10 },
  { id: "ATL", name: "Atlanta", lon: -84.39, lat: 33.75, uv: 9 },
  { id: "DEN", name: "Denver", lon: -104.99, lat: 39.74, uv: 8 },
  { id: "NYC", name: "Nueva York", lon: -74.01, lat: 40.71, uv: 7 },
  { id: "CHI", name: "Chicago", lon: -87.63, lat: 41.88, uv: 7 },
  { id: "SEA", name: "Seattle", lon: -122.33, lat: 47.61, uv: 5 },
  { id: "SFO", name: "San Francisco", lon: -122.42, lat: 37.77, uv: 8 },
  { id: "MSP", name: "Mineápolis", lon: -93.27, lat: 44.98, uv: 6 },
  { id: "SLC", name: "Salt Lake City", lon: -111.89, lat: 40.76, uv: 9 },
  { id: "ABQ", name: "Albuquerque", lon: -106.65, lat: 35.08, uv: 11 },
  { id: "MCO", name: "Orlando", lon: -81.38, lat: 28.54, uv: 11 },
  { id: "BIS", name: "Bismarck", lon: -100.78, lat: 46.81, uv: 6 },
  // Centro del país (relleno del hueco).
  { id: "KC", name: "Kansas City", lon: -94.58, lat: 39.1, uv: 9 },
  { id: "OKC", name: "Oklahoma City", lon: -97.52, lat: 35.47, uv: 10 },
  { id: "STL", name: "San Luis", lon: -90.2, lat: 38.63, uv: 9 },
  { id: "OMA", name: "Omaha", lon: -95.94, lat: 41.26, uv: 8 },
  { id: "MEM", name: "Memphis", lon: -90.05, lat: 35.15, uv: 10 },
  { id: "BNA", name: "Nashville", lon: -86.78, lat: 36.16, uv: 9 },
  { id: "LAS", name: "Las Vegas", lon: -115.14, lat: 36.17, uv: 11 },
];

const UvContent: React.FC<{ data: UvCity[]; animate?: boolean; topicColor: string }> = ({
  data,
  animate,
  topicColor,
}) => (
  <ServiceMap
    points={data}
    animate={animate}
    topPad={140}
    boxSize={(c) => ({ w: Math.max(82, c.name.length * 11 + 20), h: 128 })}
    renderChip={(c) => (
      <ValueBadge value={c.uv} name={c.name} color={uvColor(c.uv)} sub={uvCat(c.uv)} />
    )}
  >
    <TopicBar topic="ÍNDICE UV" sub="MÁXIMO" topicColor={topicColor} opacity={1} />
    <ScaleLegend
      title="Índice UV"
      stops={[
        { c: "#2ecc71", label: "0-2 Bajo" },
        { c: "#f4d03f", label: "3-5 Mod." },
        { c: "#ef8e2d", label: "6-7 Alto" },
        { c: "#e74c3c", label: "8-10 M.alto" },
        { c: "#8e44ad", label: "11+ Extremo" },
      ]}
    />
  </ServiceMap>
);

export const UvMockup: React.FC = () => <UvContent data={UV_CITIES} topicColor="#F39C12" />;

// Escena real (índice UV del feed data/uv/cities.json).
export const UvScene: React.FC<{ uv?: UvCity[]; mode?: ThemeMode }> = ({
  uv = [],
  mode = "normal",
}) => <UvContent data={uv} animate topicColor={palette(mode).topicColor} />;

// ═════════════════════════════════════════════════════════════════════════════
// 3) CALIDAD DEL AIRE / AQI (AirNow). Tipo AqiCity en ../types.
// ═════════════════════════════════════════════════════════════════════════════
// Escala estándar EPA AQI.
function aqiColor(aqi: number): string {
  if (aqi <= 50) return "#2ecc71";
  if (aqi <= 100) return "#f4d03f";
  if (aqi <= 150) return "#ef8e2d";
  if (aqi <= 200) return "#e74c3c";
  if (aqi <= 300) return "#8e44ad";
  return "#7e0023";
}
function aqiCat(aqi: number): string {
  if (aqi <= 50) return "Buena";
  if (aqi <= 100) return "Moderada";
  if (aqi <= 150) return "Sensibles";
  if (aqi <= 200) return "Dañina";
  if (aqi <= 300) return "Muy dañina";
  return "Peligrosa";
}

const AQI_CITIES: AqiCity[] = [
  { id: "SAC", name: "Sacramento", lon: -121.49, lat: 38.58, aqi: 175 },
  { id: "PDX", name: "Portland", lon: -122.68, lat: 45.52, aqi: 158 },
  { id: "LAX", name: "Los Ángeles", lon: -118.24, lat: 34.05, aqi: 142 },
  { id: "SLC", name: "Salt Lake City", lon: -111.89, lat: 40.76, aqi: 120 },
  { id: "HOU", name: "Houston", lon: -95.37, lat: 29.76, aqi: 96 },
  { id: "PHX", name: "Phoenix", lon: -112.07, lat: 33.45, aqi: 88 },
  { id: "DEN", name: "Denver", lon: -104.99, lat: 39.74, aqi: 78 },
  { id: "ATL", name: "Atlanta", lon: -84.39, lat: 33.75, aqi: 70 },
  { id: "CHI", name: "Chicago", lon: -87.63, lat: 41.88, aqi: 61 },
  { id: "DAL", name: "Dallas", lon: -96.8, lat: 32.78, aqi: 58 },
  { id: "NYC", name: "Nueva York", lon: -74.01, lat: 40.71, aqi: 54 },
  { id: "SFO", name: "San Francisco", lon: -122.42, lat: 37.77, aqi: 49 },
  { id: "SEA", name: "Seattle", lon: -122.33, lat: 47.61, aqi: 45 },
  { id: "MIA", name: "Miami", lon: -80.19, lat: 25.76, aqi: 38 },
  { id: "MSP", name: "Mineápolis", lon: -93.27, lat: 44.98, aqi: 42 },
  { id: "BOS", name: "Boston", lon: -71.06, lat: 42.36, aqi: 47 },
  // Centro del país (relleno del hueco).
  { id: "KC", name: "Kansas City", lon: -94.58, lat: 39.1, aqi: 55 },
  { id: "OKC", name: "Oklahoma City", lon: -97.52, lat: 35.47, aqi: 62 },
  { id: "STL", name: "San Luis", lon: -90.2, lat: 38.63, aqi: 68 },
  { id: "OMA", name: "Omaha", lon: -95.94, lat: 41.26, aqi: 48 },
  { id: "MEM", name: "Memphis", lon: -90.05, lat: 35.15, aqi: 72 },
  { id: "BNA", name: "Nashville", lon: -86.78, lat: 36.16, aqi: 64 },
  { id: "LAS", name: "Las Vegas", lon: -115.14, lat: 36.17, aqi: 90 },
];

const AqiContent: React.FC<{ data: AqiCity[]; animate?: boolean; topicColor: string }> = ({
  data,
  animate,
  topicColor,
}) => (
  <ServiceMap
    points={data}
    animate={animate}
    topPad={140}
    boxSize={(c) => ({ w: Math.max(82, c.name.length * 11 + 20), h: 128 })}
    renderChip={(c) => (
      <ValueBadge value={c.aqi} name={c.name} color={aqiColor(c.aqi)} sub={aqiCat(c.aqi)} />
    )}
  >
    <TopicBar topic="CALIDAD DEL AIRE" sub="ÍNDICE AQI · EE. UU." topicColor={topicColor} opacity={1} />
    <ScaleLegend
      title="Índice AQI"
      stops={[
        { c: "#2ecc71", label: "0-50 Buena" },
        { c: "#f4d03f", label: "51-100 Mod." },
        { c: "#ef8e2d", label: "101-150 Sens." },
        { c: "#e74c3c", label: "151-200 Dañina" },
        { c: "#8e44ad", label: "201+ M.dañina" },
      ]}
    />
  </ServiceMap>
);

export const AqiMockup: React.FC = () => <AqiContent data={AQI_CITIES} topicColor="#F39C12" />;

// Escena real (calidad del aire del feed data/aqi/cities.json).
export const AqiScene: React.FC<{ aqi?: AqiCity[]; mode?: ThemeMode }> = ({
  aqi = [],
  mode = "normal",
}) => <AqiContent data={aqi} animate topicColor={palette(mode).topicColor} />;
