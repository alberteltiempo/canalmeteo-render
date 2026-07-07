import React, { useEffect, useRef, useState } from "react";
import {
  AbsoluteFill,
  continueRender,
  delayRender,
  staticFile,
  useVideoConfig,
} from "remotion";
import { loadFont } from "@remotion/google-fonts/Outfit";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import { MAPBOX_TOKEN, CONUS_VIEW } from "../lib/cdn";
import { MAJOR_CITIES } from "../lib/cities";
import { MockupVariant, mockupById } from "../lib/mockups";
import {
  setWaterColor,
  setLandColor,
  addReliefRaster,
  addBathymetry,
  addCoastBorder,
  raiseBorders,
  hideAutoLabels,
} from "../lib/basemap";

const { fontFamily } = loadFont();

// ─── Helpers exclusivos del mockup (hillshade vectorial y halo costero) ───

// Añade relieve sombreado (hillshade) por debajo de los símbolos/fronteras.
function addHillshade(
  map: mapboxgl.Map,
  exaggeration: number,
  shadow = "rgba(10,20,16,0.22)",
  highlight = "rgba(255,255,255,0.3)"
) {
  try {
    if (!map.getSource("cm-dem")) {
      map.addSource("cm-dem", {
        type: "raster-dem",
        url: "mapbox://mapbox.mapbox-terrain-dem-v1",
        tileSize: 512,
        maxzoom: 14,
      });
    }
    // Inserta justo antes de la primera capa de símbolos (rótulos), para que el
    // sombreado quede sobre la tierra pero bajo los textos.
    const firstSymbol = (map.getStyle()?.layers || []).find(
      (l: any) => l.type === "symbol"
    )?.id;
    if (!map.getLayer("cm-hillshade")) {
      map.addLayer(
        {
          id: "cm-hillshade",
          type: "hillshade",
          source: "cm-dem",
          paint: {
            "hillshade-exaggeration": exaggeration,
            // Hillshade como acento: sombra suave para no ennegrecer la tierra
            // plana, de modo que domine el color de tierra y el relieve aparezca
            // como sombreado en las laderas.
            "hillshade-shadow-color": shadow,
            "hillshade-highlight-color": highlight,
            "hillshade-accent-color": "rgba(0,0,0,0.22)",
          },
        },
        firstSymbol
      );
    }
  } catch {
    /* noop */
  }
}

// Halo costero: línea difuminada de color claro sobre el límite del agua, para
// simular el agua somera brillante de los sistemas de TV (Baron/Max).
function addCoastGlow(map: mapboxgl.Map, color: string) {
  if (map.getLayer("cm-coast-glow")) return;
  try {
    // Capa ancha y muy difuminada (resplandor) + una fina nítida encima.
    map.addLayer({
      id: "cm-coast-glow",
      type: "line",
      source: "composite",
      "source-layer": "water",
      paint: {
        "line-color": color,
        "line-width": 5,
        "line-blur": 8,
        "line-opacity": 0.6,
      },
    });
    map.addLayer({
      id: "cm-coast-line",
      type: "line",
      source: "composite",
      "source-layer": "water",
      paint: {
        "line-color": color,
        "line-width": 1.2,
        "line-opacity": 0.5,
      },
    });
  } catch {
    /* noop */
  }
}

function cityMarkerHTML(name: string, dot: string, text: string): string {
  return (
    `<div style="display:flex;align-items:center;gap:8px;transform:translate(-6px,-50%);` +
    `font-family:Outfit,sans-serif;white-space:nowrap;pointer-events:none;">` +
    `<div style="width:12px;height:12px;border-radius:50%;background:${dot};` +
    `border:2px solid rgba(0,0,0,0.55);box-shadow:0 0 6px rgba(0,0,0,0.6);flex:0 0 auto;"></div>` +
    `<div style="font-size:30px;font-weight:800;color:${text};` +
    `text-shadow:0 2px 6px rgba(0,0,0,0.6),0 0 10px rgba(0,0,0,0.4);">${name}</div>` +
    `</div>`
  );
}

// Mockup de base cartográfica (sin satélite): renderiza el encuadre CONUS con el
// estilo/colores de la variante, para comparar looks de broadcast en Studio.
export const MapMockup: React.FC<{ variant?: string }> = ({
  variant = "navy",
}) => {
  const v: MockupVariant = mockupById(variant);
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<mapboxgl.Map | null>(null);
  const [ready, setReady] = useState(false);
  const { width, height } = useVideoConfig();

  useEffect(() => {
    if (!ref.current) return;
    const handle = delayRender(`mockup-${v.id}`);
    mapboxgl.accessToken = MAPBOX_TOKEN;

    const map = new mapboxgl.Map({
      container: ref.current,
      style: v.style,
      center: v.center ?? [-96, 38],
      zoom: v.zoom ?? 3.4,
      interactive: false,
      attributionControl: false,
      preserveDrawingBuffer: true,
      fadeDuration: 0,
      projection: v.projection ?? "mercator",
    });
    mapRef.current = map;

    map.on("load", () => {
      if (v.ocean) setWaterColor(map, v.ocean);
      if (v.landColor) setLandColor(map, v.landColor);
      if (v.reliefRaster) addReliefRaster(map, staticFile(v.reliefRaster));
      if (v.relief)
        addHillshade(
          map,
          v.reliefExaggeration ?? 0.5,
          v.hillshadeShadow,
          v.hillshadeHighlight
        );
      // Batimetría encima del agua plana; el halo costero se añade DESPUÉS para
      // quedar por encima de ella.
      if (v.bathymetry) addBathymetry(map, staticFile(v.bathymetry));
      if (v.coastGlow) addCoastGlow(map, v.coastGlow);
      if (v.coastBorder) addCoastBorder(map, v.coastBorder, v.coastBorderWidth ?? 1.2);
      raiseBorders(map, v.borderColor, v.borderOpacity ?? 0.95);

      // Espacio + atmósfera azul (look de globo de sistema de TV).
      if (v.atmosphere) {
        try {
          map.setFog({
            color: "rgba(30,70,140,0.5)", // bruma cerca del horizonte
            "high-color": "#1f4f8f", // cielo/atmósfera superior
            "horizon-blend": 0.03,
            "space-color": "#01030a", // espacio casi negro
            "star-intensity": 0,
          } as any);
        } catch {
          /* noop */
        }
      }

      // Ocultar rótulos automáticos de Mapbox: solo mostramos los curados.
      hideAutoLabels(map);

      // Encuadre. En globo usamos center/zoom directos (cameraForBounds no encaja
      // con la curvatura). En plano, cameraForBounds + jumpTo es robusto en
      // headless (fitBounds animate:false a veces deja el mundo entero).
      map.resize();
      if ((v.projection ?? "mercator") === "globe") {
        map.jumpTo({ center: v.center ?? [-96, 41], zoom: v.zoom ?? 2.6 });
      } else {
        const cam = map.cameraForBounds(CONUS_VIEW, {
          padding: { top: 150, bottom: 110, left: 70, right: 70 },
        });
        if (cam) map.jumpTo(cam);
        else map.fitBounds(CONUS_VIEW, { animate: false });
      }

      if (v.showCities !== false) {
        MAJOR_CITIES.forEach((c) => {
          const el = document.createElement("div");
          el.innerHTML = cityMarkerHTML(c.name, v.cityDotColor, v.cityTextColor);
          new mapboxgl.Marker({ element: el, anchor: "left" })
            .setLngLat([c.lon, c.lat])
            .addTo(map);
        });
      }

      let done = false;
      const finish = () => {
        if (done) return;
        done = true;
        setReady(true);
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
  }, [v.id, width, height]);

  return (
    <AbsoluteFill style={{ background: "#000", fontFamily }}>
      <style>{`.mapboxgl-ctrl-logo,.mapboxgl-ctrl-attrib,.mapboxgl-ctrl-bottom-left,.mapboxgl-ctrl-bottom-right{display:none !important;}`}</style>
      <div ref={ref} style={{ position: "absolute", inset: 0 }} />

      {/* Etiqueta de la variante (esquina inferior) para identificarla al comparar. */}
      <div
        style={{
          position: "absolute",
          left: 48,
          bottom: 40,
          maxWidth: 760,
          color: v.titleColor,
          opacity: ready ? 1 : 0,
        }}
      >
        <div style={{ fontSize: 44, fontWeight: 800, letterSpacing: 0.5 }}>
          {v.name}
        </div>
        <div style={{ fontSize: 22, fontWeight: 500, opacity: 0.85, marginTop: 6 }}>
          {v.desc}
        </div>
      </div>
    </AbsoluteFill>
  );
};
