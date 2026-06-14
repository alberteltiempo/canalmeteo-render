import React from "react";
import { Img } from "remotion";
import { MAPBOX_TOKEN } from "../lib/cdn";

// Mini-mapa localizador como IMAGEN ESTÁTICA (Mapbox Static Images API).
// No crea un contexto WebGL (a diferencia de un mapa GL), así evitamos agotar
// el límite de contextos del navegador durante el render con concurrencia alta.
// Estilo "tarjeta con pestaña" igual que la caja de información.
export const LocatorMap: React.FC<{
  lon: number;
  lat: number;
  color?: string; // color de la pestaña (categoría de la tormenta)
  textColor?: string;
  opacity?: number;
}> = ({ lon, lat, color = "#457A99", textColor = "#fff", opacity = 1 }) => {
  const lo = lon.toFixed(2);
  const la = lat.toFixed(2);
  // Coordenadas legibles (N/S · E/O)
  const ns = lat >= 0 ? "N" : "S";
  const ew = lon >= 0 ? "E" : "O";
  const coords = `${Math.abs(lat).toFixed(1)}°${ns}   ${Math.abs(lon).toFixed(1)}°${ew}`;
  // Mapa de "tierra real" (satélite + etiquetas) con marcador naranja, vista amplia.
  const url =
    `https://api.mapbox.com/styles/v1/mapbox/satellite-streets-v12/static/` +
    `pin-l+f39c12(${lo},${la})/${lo},${la},2.8,0/360x224@2x` +
    `?access_token=${MAPBOX_TOKEN}&attribution=false&logo=false`;

  return (
    <div
      style={{
        position: "absolute",
        top: 140,
        right: 56,
        width: 360,
        opacity,
        fontFamily: "Outfit, system-ui, sans-serif",
        borderRadius: 18,
        overflow: "hidden",
        border: "1px solid rgba(255,255,255,0.12)",
        boxShadow: "0 14px 40px rgba(0,0,0,0.55)",
        background: "rgba(13,26,38,0.9)",
      }}
    >
      {/* Pestaña/cabecera coloreada (como la caja de datos) */}
      <div
        style={{
          background: color,
          color: textColor,
          padding: "10px 18px",
          fontSize: 20,
          fontWeight: 800,
          letterSpacing: 0.3,
        }}
      >
        Localización
      </div>
      {/* Cuerpo: mapa */}
      <div style={{ width: "100%", height: 224, background: "#0d1a26" }}>
        <Img src={url} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
      </div>
      {/* Coordenadas */}
      <div
        style={{
          padding: "9px 18px",
          color: "#fff",
          fontSize: 18,
          fontWeight: 700,
          fontFamily: "'JetBrains Mono', monospace",
          letterSpacing: 0.5,
          textAlign: "center",
          background: "rgba(13,26,38,0.95)",
          borderTop: "1px solid rgba(255,255,255,0.1)",
        }}
      >
        {coords}
      </div>
    </div>
  );
};
