import React, {useLayoutEffect, useState} from 'react';
import {continueRender, delayRender, Img, interpolate, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import type {CamData, RadarFrame} from '../types';

// Tesela del radar mundial propio. El pipeline no sube las teselas vacías (sin eco → 404), y
// <Img> de Remotion cancela el render ante un 404 (o lo deja esperando con onError): aquí se
// espera a cada tesela y, si no existe, simplemente no se pinta (16/10/2026).
const TeselaRadar: React.FC<{src: string; style: React.CSSProperties}> = ({src, style}) => {
    const [ok, setOk] = useState(false);
    useLayoutEffect(() => {
        const h = delayRender('tesela radar ' + src);
        let vivo = true;
        let hecho = false;
        const fin = (bien: boolean) => {
            if (hecho) return;
            hecho = true;
            if (vivo) setOk(bien);
            continueRender(h);
        };
        const im = new Image();
        im.onload = () => fin(true);
        im.onerror = () => fin(false);
        im.src = src;
        return () => {
            vivo = false;
            im.onload = null;
            im.onerror = null;
            fin(false);
        };
    }, [src]);
    return ok ? <img src={src} style={style} alt="" /> : null;
};

interface Props {
    cam: CamData;
    radarFrames: RadarFrame[];
    lang?: string;
}

// Fondo del mini-radar: imágenes propias (MapLibre + estilo tormenta sobre OpenFreeMap)
// generadas en nimbus-01 con scripts/parques_basemaps.js → public/basemaps/<code>.png.
// Sustituye a la Static API de Mapbox (token revocado: el render fallaba desde mayo; 11/09/2026).
// Cada PNG cubre MAP_W×MAP_H px CSS a zoom ZOOM (base 512 px) @2x y se pinta centrado en la
// cámara SIN escalar, igual que las teselas del radar: todo casa sea cual sea el alto del card.
const BASEMAP_CODES = new Set([
    'jotr', 'yose', 'seki', 'brca', 'grte', 'mora', 'olym', 'noca', 'grsm', 'grcd',
    'maca', 'shen', 'acad', 'dena', 'havo', 'wash', 'pore', 'bibe', 'dino',
]);
const MAP_W = 720;
const MAP_H = 900;
const ZOOM = 5.5;
// RainViewer sirve teselas de 256 px: ZOOM en base 512 = ZOOM+1 en base 256. Se piden a
// RADAR_Z y se dibujan a 256·2^(ZOOM+1−RADAR_Z) px para que casen con el mapa.
const RADAR_Z = 6;

// Convertir lat/lon + zoom a tile coords (ESRI/Slippy/Web Mercator)
function lonLatToTile(lon: number, lat: number, z: number) {
    const n = Math.pow(2, z);
    const xtile = ((lon + 180) / 360) * n;
    const latRad = (lat * Math.PI) / 180;
    const ytile = ((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2) * n;
    return {x: xtile, y: ytile};
}

// Calcula los tiles que cubren el área visible del mapa
function getCoveringTiles(centerLon: number, centerLat: number, z: number, w: number, h: number) {
    // Tamaño en pantalla de una tesela de 256 px de zoom z a la escala del mapa.
    const tileSize = 256 * Math.pow(2, ZOOM + 1 - z);
    const center = lonLatToTile(centerLon, centerLat, z);

    // Cuántos tiles caben en cada dirección desde el centro
    const halfTilesX = w / 2 / tileSize;
    const halfTilesY = h / 2 / tileSize;

    const minTileX = Math.floor(center.x - halfTilesX);
    const maxTileX = Math.ceil(center.x + halfTilesX);
    const minTileY = Math.floor(center.y - halfTilesY);
    const maxTileY = Math.ceil(center.y + halfTilesY);

    const tiles = [];
    for (let tx = minTileX; tx <= maxTileX; tx++) {
        for (let ty = minTileY; ty <= maxTileY; ty++) {
            // Posición en px relativa al CENTRO del card (se pinta con calc(50% + …))
            const offsetX = (tx - center.x) * tileSize;
            const offsetY = (ty - center.y) * tileSize;
            tiles.push({x: tx, y: ty, z, left: offsetX, top: offsetY, size: tileSize});
        }
    }
    return tiles;
}

export const RadarMini: React.FC<Props> = ({cam, radarFrames, lang = "es"}) => {
    const en = lang === "en";
    const frame = useCurrentFrame();
    const {durationInFrames} = useVideoConfig();

    // Slide in from right (un poquito más tarde que MetarCard)
    const enterX = interpolate(frame, [6, 32], [60, 0], {
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp',
    });
    const enterOpacity = interpolate(frame, [6, 32], [0, 1], {
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp',
    });

    // Pulse del pin (oscilación continua)
    const pinPulseScale = 1 + Math.abs(Math.sin(frame * 0.1)) * 0.4;
    const pinPulseOpacity = 1 - Math.abs(Math.sin(frame * 0.1)) * 0.6;

    // === Fondo propio (fichero local, sin peticiones externas) ===
    const basemapSrc = BASEMAP_CODES.has(cam.code) ? staticFile(`basemaps/${cam.code}.png`) : null;

    // === Tiles de RainViewer ===
    // Calculamos qué tiles cubren la vista actual y por cada frame del radar
    // mostramos su versión correspondiente
    const tiles = getCoveringTiles(cam.lon, cam.lat, RADAR_Z, MAP_W, MAP_H);

    // Frame actual del radar (loop por los 6 frames durante 12s)
    const radarFrameIdx =
        radarFrames.length > 0
            ? Math.floor((frame / durationInFrames) * radarFrames.length) %
              radarFrames.length
            : 0;

    const currentRadar = radarFrames[radarFrameIdx];

    // Timestamp formateado en hora local del parque
    const timestampStr = formatRadarTimestamp(currentRadar, cam.tz, cam.tz_abbr, en);

    return (
        <div
            style={{
                flex: 1,
                display: 'flex',
                flexDirection: 'column',
                borderRadius: 18,
                overflow: 'hidden',
                background: 'rgba(34, 69, 91, 0.55)',
                border: '1px solid rgba(255,255,255,0.10)',
                boxShadow:
                    '0 12px 40px rgba(0,0,0,0.35), inset 0 1px 0 rgba(255,255,255,0.08)',
                backdropFilter: 'blur(20px)',
                transform: `translateX(${enterX}px)`,
                opacity: enterOpacity,
            }}
        >
            {/* Header (ch-amber) */}
            <div
                style={{
                    padding: '18px 24px',
                    display: 'flex',
                    alignItems: 'center',
                    fontSize: 19,
                    fontWeight: 700,
                    letterSpacing: 2.2,
                    textTransform: 'uppercase',
                    color: '#fff',
                    borderBottom: '1px solid rgba(255,255,255,0.08)',
                    background: 'linear-gradient(90deg, #c0660b 0%, #F39C12 100%)',
                }}
            >
                {en ? "Last Hour of Radar" : "Última Hora de Radar"}
            </div>

            {/* Map container */}
            <div
                style={{
                    flex: 1,
                    position: 'relative',
                    minHeight: 260,
                    overflow: 'hidden',
                }}
            >
                {/* === Fondo propio centrado en la cámara, a tamaño natural === */}
                {basemapSrc && (
                    <Img
                        src={basemapSrc}
                        style={{
                            position: 'absolute',
                            left: '50%',
                            top: '50%',
                            width: MAP_W,
                            height: MAP_H,
                            transform: 'translate(-50%, -50%)',
                        }}
                    />
                )}

                {/* === Teselas del radar mundial propio encima === */}
                {currentRadar && (
                    <div
                        style={{
                            position: 'absolute',
                            inset: 0,
                            overflow: 'hidden',
                            pointerEvents: 'none',
                        }}
                    >
                        {tiles.map((tile) => (
                            <TeselaRadar
                                key={`${tile.z}-${tile.x}-${tile.y}-${currentRadar.time}`}
                                src={`${currentRadar.host}${currentRadar.path}/256/${tile.z}/${tile.x}/${tile.y}/2/1_1.png`}
                                style={{
                                    position: 'absolute',
                                    left: `calc(50% + ${tile.left}px)`,
                                    top: `calc(50% + ${tile.top}px)`,
                                    width: tile.size,
                                    height: tile.size,
                                    opacity: 0.85,
                                    imageRendering: 'auto',
                                }}
                            />
                        ))}
                    </div>
                )}

                {/* Pin pulsante centrado (parque) */}
                <div
                    style={{
                        position: 'absolute',
                        top: '50%',
                        left: '50%',
                        transform: 'translate(-50%, -50%)',
                        zIndex: 50,
                        width: 24,
                        height: 24,
                        pointerEvents: 'none',
                    }}
                >
                    {/* Outer pulse */}
                    <div
                        style={{
                            position: 'absolute',
                            inset: 0,
                            borderRadius: '50%',
                            background: '#F39C12',
                            transform: `scale(${pinPulseScale})`,
                            opacity: pinPulseOpacity,
                        }}
                    />
                    {/* Inner solid pin */}
                    <div
                        style={{
                            position: 'absolute',
                            inset: 0,
                            borderRadius: '50%',
                            background: '#F39C12',
                            border: '3px solid #fff',
                        }}
                    />
                </div>

                {/* Timestamp */}
                <div
                    style={{
                        position: 'absolute',
                        bottom: 14,
                        left: 14,
                        fontFamily: 'JetBrains Mono, monospace',
                        fontSize: 13,
                        fontWeight: 600,
                        color: 'rgba(255,255,255,0.92)',
                        background: 'rgba(0,0,0,0.65)',
                        padding: '8px 12px',
                        borderRadius: 8,
                        zIndex: 10,
                        backdropFilter: 'blur(8px)',
                        letterSpacing: 0.5,
                    }}
                >
                    {timestampStr}
                </div>

                {/* Precipitation legend */}
                <div
                    style={{
                        position: 'absolute',
                        bottom: 14,
                        right: 14,
                        zIndex: 10,
                        background: 'rgba(0,0,0,0.65)',
                        backdropFilter: 'blur(8px)',
                        padding: '8px 10px',
                        borderRadius: 8,
                        display: 'flex',
                        flexDirection: 'column',
                        gap: 4,
                        fontFamily: 'JetBrains Mono, monospace',
                        fontWeight: 600,
                        color: 'rgba(255,255,255,0.85)',
                    }}
                >
                    <div
                        style={{
                            fontSize: 10,
                            color: 'rgba(255,255,255,0.75)',
                            textTransform: 'uppercase',
                            letterSpacing: 1,
                            marginBottom: 2,
                        }}
                    >
                        {en ? "Precipitation" : "Precipitación"}
                    </div>
                    <div
                        style={{
                            display: 'flex',
                            height: 8,
                            borderRadius: 2,
                            overflow: 'hidden',
                            width: 130,
                        }}
                    >
                        {[
                            '#01a4ec',
                            '#00ff00',
                            '#fffe00',
                            '#fb9d04',
                            '#fb0000',
                            '#fb00fc',
                        ].map((color, i) => (
                            <div
                                key={i}
                                style={{
                                    flex: 1,
                                    height: '100%',
                                    background: color,
                                }}
                            />
                        ))}
                    </div>
                    <div
                        style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            fontSize: 8,
                            color: 'rgba(255,255,255,0.6)',
                            marginTop: 2,
                        }}
                    >
                        <span>{en ? "Low" : "Bajo"}</span>
                        <span>{en ? "High" : "Alto"}</span>
                    </div>
                </div>
            </div>
        </div>
    );
};

function formatRadarTimestamp(
    rFrame: RadarFrame | undefined,
    tz: string,
    tzAbbr: string,
    en = false,
): string {
    if (!rFrame) return '— · —';
    const date = new Date(rFrame.time * 1000);
    const minsAgo = Math.round((Date.now() - date.getTime()) / 60000);
    try {
        const timeStr = date.toLocaleTimeString(en ? 'en-US' : 'es-ES', {
            hour: '2-digit',
            minute: '2-digit',
            timeZone: tz,
        });
        return en ? `${minsAgo} min ago · ${timeStr} ${tzAbbr}` : `Hace ${minsAgo} min · ${timeStr} ${tzAbbr}`;
    } catch {
        return en ? `${minsAgo} min ago` : `Hace ${minsAgo} min`;
    }
}
