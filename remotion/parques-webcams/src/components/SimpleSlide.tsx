// SimpleSlide.tsx — versión simple de la captura de cámara (12/09/2026).
// Pedida por Albert para la app: foto a pantalla completa, logo de Canal Meteo,
// nombre del parque + estado y la cortesía del NPS. SIN panel lateral (METAR),
// SIN mini-radar, SIN "EN VIVO" y sin indicadores del vídeo.
import React from "react";
import {AbsoluteFill, Img, interpolate, useCurrentFrame, useVideoConfig} from "remotion";
import type {CamData} from "../types";

interface Props {
    cam: CamData;
    lang?: string;
}

const LOGO = "https://dev.canalmeteo.tv/logos/logo-canalmeteo-30.png";

export const SimpleSlide: React.FC<Props> = ({cam, lang = "es"}) => {
    const frame = useCurrentFrame();
    const {durationInFrames} = useVideoConfig();
    const en = lang === "en";

    // Mismo Ken Burns suave que la versión completa (la captura sale a mitad).
    const kenBurnsScale = interpolate(frame, [0, durationInFrames], [1.0, 1.04]);

    return (
        <AbsoluteFill style={{background: "#0a1628", fontFamily: "Outfit, sans-serif", color: "#fff"}}>
            {/* Foto a pantalla completa */}
            <Img
                src={cam.image_url}
                style={{
                    width: "100%",
                    height: "100%",
                    objectFit: "cover",
                    filter: "brightness(0.95) saturate(1.1)",
                    transform: `scale(${kenBurnsScale})`,
                    transformOrigin: "center center",
                }}
            />

            {/* Vignette: sin ella el texto blanco se pierde en fotos claras */}
            <AbsoluteFill
                style={{
                    background:
                        "linear-gradient(180deg, rgba(10,22,40,0.55) 0%, transparent 26%, transparent 58%, rgba(10,22,40,0.88) 100%)",
                    pointerEvents: "none",
                }}
            />

            {/* Logo Canal Meteo (arriba a la izquierda) */}
            <Img
                src={LOGO}
                style={{
                    position: "absolute",
                    top: 54,
                    left: 60,
                    height: 120,
                    width: "auto",
                    filter: "drop-shadow(0 6px 18px rgba(0,0,0,0.55))",
                }}
            />

            {/* Nombre del parque + estado (abajo a la izquierda) */}
            <div style={{position: "absolute", left: 60, bottom: 120, maxWidth: 1400}}>
                <div
                    style={{
                        fontSize: 30,
                        fontWeight: 700,
                        letterSpacing: 3,
                        textTransform: "uppercase",
                        color: "#F39C12",
                        marginBottom: 14,
                        textShadow: "0 2px 10px rgba(0,0,0,0.6)",
                    }}
                >
                    {cam.state}
                </div>
                <div
                    style={{
                        fontSize: 86,
                        fontWeight: 800,
                        lineHeight: 1.02,
                        letterSpacing: -1,
                        textShadow: "0 6px 30px rgba(0,0,0,0.65)",
                    }}
                >
                    {en ? cam.park_name_en : cam.park_name_es}
                </div>
            </div>

            {/* Cortesía del NPS (abajo a la derecha, discreta) */}
            <div
                style={{
                    position: "absolute",
                    right: 60,
                    bottom: 40,
                    fontSize: 20,
                    fontWeight: 500,
                    letterSpacing: 0.3,
                    color: "rgba(255,255,255,0.68)",
                    textShadow: "0 2px 10px rgba(0,0,0,0.7)",
                }}
            >
                {en
                    ? "Camera: courtesy of the National Park Service"
                    : "Cámara: cortesía del Servicio de Parques Nacionales"}
            </div>
        </AbsoluteFill>
    );
};
