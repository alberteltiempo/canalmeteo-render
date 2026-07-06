import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { loadFont } from "@remotion/google-fonts/Outfit";
import { SatMap, MapPolygon } from "../components/SatMap";
import { TopicBar } from "../components/Overlay";
import { CONUS_VIEW, CONUS_PAD, REGION_STATES } from "../lib/cdn";
import { MAJOR_CITIES } from "../lib/cities";
import { SatView, AlertsData, AlertItem, ThemeMode } from "../types";
import { alertCategoryMeta, ALERT_CATEGORIES, palette } from "../lib/theme";

const { fontFamily } = loadFont();

type Group = {
  tipo: string;
  label: string;
  color: string;
  icon: string;
  count: number;
  states: string[];
  poblacion: number;
};

function groupWatches(watches: AlertItem[], only?: string[]): Group[] {
  const allow = only && only.length ? new Set(only) : null;
  const map = new Map<string, Group>();
  for (const w of watches) {
    if (allow && !allow.has(w.tipo)) continue;
    // Sin "Otras vigilancias": solo categorías conocidas (con etiqueta/color/icono).
    if (!(w.tipo in ALERT_CATEGORIES)) continue;
    const meta = alertCategoryMeta(w.tipo);
    const g =
      map.get(w.tipo) ||
      ({ tipo: w.tipo, label: meta.label, color: meta.color, icon: meta.icon, count: 0, states: [], poblacion: 0 } as Group);
    g.count += 1;
    g.poblacion += w.poblacion || 0;
    if (w.estado && !g.states.includes(w.estado)) g.states.push(w.estado);
    map.set(w.tipo, g);
  }
  // Orden por severidad relativa (tornado/severo primero) y luego por nº.
  const rank: Record<string, number> = { tornado: 5, tormenta: 4, inundacion: 3, calor: 2, invierno: 1 };
  return [...map.values()].sort(
    (a, b) => (rank[b.tipo] || 0) - (rank[a.tipo] || 0) || b.count - a.count
  );
}

// Escena de vigilancias (watches) del NWS sobre el GEOCOLOR de CONUS.
//  - dibuja los polígonos de cada vigilancia coloreados por categoría
//  - una caja de información por categoría presente (icono, nombre, nº, estados)
//  - si no hay vigilancias activas → tarjeta de estado
// `categories` permite limitar las categorías a destacar (se especifica por render).
export const Alerts: React.FC<{
  alerts?: AlertsData;
  mode?: ThemeMode;
  categories?: string[];
}> = ({ alerts, mode = "normal", categories }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pal = palette(mode);
  // Solo el mapa base (sin satélite); polígonos de alerta encima.
  const view: SatView = { view: "base", band: "", bounds: null, frames: [] };

  // Mapa NACIONAL: alertas de ZONA GRANDE → vigilancias/avisos agrupados del feed
  // (is_grouped) MÁS la bandera roja de incendios (tipo=fuego, aunque sea warning,
  // cubre zonas amplias). Quedan fuera los warnings de condado (p. ej. flash flood).
  const esZonaGrande = (tipo?: string, grouped?: boolean) => !!grouped || tipo === "fuego";
  // Solo alertas de los estados de la REGIÓN: el feed es nacional y las tarjetas
  // salían con incendios de ID·OR en un segmento regional. Sin estado → fuera
  // (no podemos atribuirla). Los polígonos sí se pintan todos: el mapa recorta.
  const allWatches = (alerts?.watches || []).filter(
    (a) => esZonaGrande(a.tipo, a.is_grouped) && !!a.estado && REGION_STATES.has(a.estado)
  );
  const groups = groupWatches(allWatches, categories);
  const hasWatches = groups.length > 0;

  // Polígonos: pintamos TODAS las alertas activas con geometría (vigilancias,
  // avisos y warnings) para máxima cobertura, como el mapa del NWS. Las CAJAS
  // de abajo siguen resumiendo solo las zonas grandes (groups).
  const allow = categories && categories.length ? new Set(categories) : null;
  const feats: any[] = (alerts?.geojson?.features || []).filter((f: any) => {
    const p = f?.properties || {};
    return !allow || (p.tipo && allow.has(p.tipo));
  });
  const polygons: MapPolygon[] = feats.map((f) => {
    const meta = alertCategoryMeta(f?.properties?.tipo || "");
    return { data: f, fill: meta.color, line: meta.color, fillOpacity: 0.6 };
  });

  const op = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const cardIn = spring({ frame: frame - 6, fps, config: { damping: 16 } });
  const cardScale = interpolate(cardIn, [0, 1], [0.9, 1]);

  return (
    <AbsoluteFill style={{ fontFamily, background: "#000" }}>
      <SatMap
        sat={view}
        center={[-96, 38]}
        zoom={3.4}
        fitBounds={CONUS_VIEW}
        fitPadding={CONUS_PAD}
        cityMarkers={MAJOR_CITIES}
        polygons={polygons}
        showSatellite={false}
      />

      <AbsoluteFill
        style={{
          background:
            "linear-gradient(180deg, rgba(0,0,0,0.5) 0%, rgba(0,0,0,0) 22%, rgba(0,0,0,0) 58%, rgba(0,0,0,0.6) 100%)",
          pointerEvents: "none",
        }}
      />

      <TopicBar topic="ALERTAS ACTIVAS" topicColor={pal.topicColor} opacity={op} />

      {hasWatches && groups.length > 4 ? (
        // Muchas categorías: la fila de cajas satura → leyenda compacta (nombre,
        // color y, si hay, personas afectadas), una entrada por categoría.
        <AbsoluteFill style={{ alignItems: "center", justifyContent: "flex-end", paddingBottom: 40 }}>
          <div style={{ opacity: op, transform: `scale(${cardScale})`, maxWidth: 1720 }}>
            <AlertsLegend groups={groups} />
          </div>
        </AbsoluteFill>
      ) : hasWatches ? (
        // Fila de cajas por categoría, abajo (≤ 4 categorías)
        <AbsoluteFill style={{ alignItems: "center", justifyContent: "flex-end", paddingBottom: 36 }}>
          <div
            style={{
              opacity: op,
              transform: `scale(${cardScale})`,
              display: "flex",
              gap: 22,
              flexWrap: "wrap",
              justifyContent: "center",
              maxWidth: 1700,
            }}
          >
            {groups.map((g) => (
              <CategoryBox key={g.tipo} g={g} />
            ))}
          </div>
        </AbsoluteFill>
      ) : (
        // Sin vigilancias: tarjeta de estado
        <AbsoluteFill style={{ alignItems: "center", justifyContent: "flex-end", paddingBottom: 90 }}>
          <div
            style={{
              opacity: op,
              transform: `scale(${cardScale})`,
              background: "rgba(13,26,38,0.9)",
              border: "1px solid rgba(255,255,255,0.14)",
              borderRadius: 22,
              padding: "34px 60px",
              textAlign: "center",
              boxShadow: "0 20px 60px rgba(0,0,0,0.55)",
            }}
          >
            <div style={{ width: 120, height: 8, borderRadius: 4, background: "#2ecc71", margin: "0 auto 22px" }} />
            <div style={{ fontSize: 58, fontWeight: 800, color: "#fff", lineHeight: 1.05 }}>
              No hay alertas activas
            </div>
            <div style={{ fontSize: 30, color: "rgba(255,255,255,0.85)", marginTop: 14 }}>
              Sureste · sin alertas del NWS
            </div>
          </div>
        </AbsoluteFill>
      )}
    </AbsoluteFill>
  );
};

// Población afectada → texto compacto (millones / miles de personas).
function formatPob(n: number): string {
  if (n >= 1e6) return `${(n / 1e6).toFixed(1).replace(".", ",")} M`;
  if (n >= 1e3) return `${Math.round(n / 1e3)} mil`;
  return `${n}`;
}

// Leyenda compacta (cuando hay > 4 categorías): píldora por categoría con icono,
// nombre y, si la hay, la población afectada al lado.
const AlertsLegend: React.FC<{ groups: Group[] }> = ({ groups }) => (
  <div
    style={{
      display: "flex",
      flexWrap: "wrap",
      gap: 14,
      justifyContent: "center",
      background: "rgba(13,26,38,0.82)",
      border: "1px solid rgba(255,255,255,0.12)",
      borderRadius: 16,
      padding: "16px 22px",
      boxShadow: "0 16px 48px rgba(0,0,0,0.5)",
    }}
  >
    {groups.map((g) => (
      <div key={g.tipo} style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span
          style={{
            width: 16,
            height: 16,
            borderRadius: 4,
            background: g.color,
            boxShadow: "0 0 0 2px rgba(255,255,255,0.15)",
            flex: "0 0 auto",
          }}
        />
        <span style={{ fontSize: 26, fontWeight: 800, color: "#fff" }}>{g.label}</span>
        {g.poblacion > 0 ? (
          <span style={{ fontSize: 24, fontWeight: 700, color: "rgba(255,255,255,0.78)" }}>
            · {formatPob(g.poblacion)}
          </span>
        ) : null}
      </div>
    ))}
  </div>
);

const CategoryBox: React.FC<{ g: Group }> = ({ g }) => {
  const statesStr =
    g.states.length > 6 ? `${g.states.slice(0, 6).join(" · ")} +${g.states.length - 6}` : g.states.join(" · ");
  return (
    <div
      style={{
        background: "rgba(13,26,38,0.92)",
        border: `1px solid ${g.color}`,
        borderRadius: 18,
        overflow: "hidden",
        minWidth: 300,
        boxShadow: "0 16px 48px rgba(0,0,0,0.5)",
      }}
    >
      <div
        style={{
          background: g.color,
          color: "#fff",
          padding: "14px 22px",
          display: "flex",
          alignItems: "center",
          gap: 12,
          fontWeight: 800,
          fontSize: 30,
        }}
      >
        <span style={{ fontSize: 34 }}>{g.icon}</span>
        <span>{g.label}</span>
      </div>
      <div style={{ padding: "16px 22px 18px", color: "#fff" }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
          <span style={{ fontSize: 56, fontWeight: 800, lineHeight: 1, fontFamily: "'JetBrains Mono', monospace" }}>
            {g.count}
          </span>
          <span style={{ fontSize: 24, color: "rgba(255,255,255,0.8)" }}>
            {g.count === 1 ? "alerta" : "alertas"}
          </span>
        </div>
        {g.poblacion > 0 ? (
          <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginTop: 6 }}>
            <span style={{ fontSize: 34, fontWeight: 800, color: g.color, fontFamily: "'JetBrains Mono', monospace" }}>
              {formatPob(g.poblacion)}
            </span>
            <span style={{ fontSize: 22, color: "rgba(255,255,255,0.85)" }}>personas</span>
          </div>
        ) : null}
        {statesStr ? (
          <div style={{ fontSize: 22, color: "rgba(255,255,255,0.6)", marginTop: 8 }}>{statesStr}</div>
        ) : null}
      </div>
    </div>
  );
};
