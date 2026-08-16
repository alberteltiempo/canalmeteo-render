import React from "react";
import { staticFile } from "remotion";

// Mini-mapa localizador SIN servicios externos: recorte de una imagen
// equirectangular de la Tierra (NASA Blue Marble, dominio público, en
// public/basemap/earth_equirect.jpg) centrado en el sistema. No crea un
// contexto WebGL (igual que la versión anterior con imagen estática de Mapbox):
// así no agotamos el límite de contextos del navegador durante el render.
// Estilo "tarjeta con pestaña" igual que la caja de información.

// Equivalencia con el zoom del Static API que sustituye: a zoom z el mundo mide
// 512·2^z px. Con z=1.5 en una vista de 360 px siempre entra tierra de
// referencia (continentes/islas) aunque el sistema esté en mar abierto.
const ZOOM = 1.5;
const WORLD_W = 512 * Math.pow(2, ZOOM); // ≈1448 px
const WORLD_H = WORLD_W / 2;
const VIEW_W = 360;
const VIEW_H = 224;

export const LocatorMap: React.FC<{
  lon: number;
  lat: number;
  color?: string; // color de la pestaña (categoría de la tormenta)
  textColor?: string;
  opacity?: number;
}> = ({ lon, lat, color = "#457A99", textColor = "#fff", opacity = 1 }) => {
  // Coordenadas legibles (N/S · E/O)
  const ns = lat >= 0 ? "N" : "S";
  const ew = lon >= 0 ? "E" : "O";
  const coords = `${Math.abs(lat).toFixed(1)}°${ns}   ${Math.abs(lon).toFixed(1)}°${ew}`;

  // Posición del fondo: el punto (lon,lat) queda en el centro de la vista.
  // repeat-x resuelve el cruce del antimeridiano (Pacífico central).
  const bgX = VIEW_W / 2 - ((lon + 180) / 360) * WORLD_W;
  const bgY = VIEW_H / 2 - ((90 - lat) / 180) * WORLD_H;

  return (
    <div
      style={{
        position: "absolute",
        top: 140,
        right: 56,
        width: VIEW_W,
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
      {/* Cuerpo: mapa (recorte local de la Tierra) + marcador centrado */}
      <div
        style={{
          position: "relative",
          width: "100%",
          height: VIEW_H,
          background: "#0d1a26",
          backgroundImage: `url(${staticFile("basemap/earth_equirect.jpg")})`,
          backgroundSize: `${WORLD_W}px ${WORLD_H}px`,
          backgroundPosition: `${bgX}px ${bgY}px`,
          backgroundRepeat: "repeat-x",
        }}
      >
        <div
          style={{
            position: "absolute",
            left: "50%",
            top: "50%",
            transform: "translate(-50%, -50%)",
            width: 22,
            height: 22,
            borderRadius: "50%",
            background: "#f39c12",
            border: "3px solid #fff",
            boxShadow: "0 0 0 5px rgba(243,156,18,0.35), 0 2px 8px rgba(0,0,0,0.6)",
          }}
        />
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
