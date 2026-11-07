import React from 'react';
import {Img, useCurrentFrame, interpolate} from 'remotion';

export const TopBar: React.FC<{lang?: string}> = ({lang = "es"}) => {
    const en = lang === "en";
    const frame = useCurrentFrame();

    // Pulse del punto rojo "EN VIVO" - sin parar
    const livePulse = Math.abs(Math.sin(frame * 0.08));
    const pulseScale = interpolate(livePulse, [0, 1], [1, 1.3]);
    const pulseOpacity = interpolate(livePulse, [0, 1], [1, 0.4]);

    return (
        <div
            style={{
                position: 'absolute',
                top: 56,
                left: 60,
                right: 548, // 24 + 440 + 24 + 60
                zIndex: 10,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 20,
            }}
        >
            {/* Brand pill: logo + dot + EN VIVO */}
            <div
                style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 16,
                    background: 'rgba(34, 69, 91, 0.55)',
                    backdropFilter: 'blur(20px) saturate(1.4)',
                    padding: '12px 22px 12px 14px',
                    borderRadius: 14,
                    border: '1px solid rgba(255,255,255,0.10)',
                    boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
                }}
            >
                <Img
                    src="https://dev.canalmeteo.tv/logos/logo-canalmeteo-30.png"
                    style={{height: 44, width: 'auto'}}
                />

                {/* Pulse dot */}
                <div
                    style={{
                        width: 10,
                        height: 10,
                        borderRadius: '50%',
                        background: '#ff3b3b',
                        boxShadow: '0 0 14px rgba(255,59,59,0.8)',
                        transform: `scale(${pulseScale})`,
                        opacity: pulseOpacity,
                    }}
                />

                <div
                    style={{
                        fontSize: 17,
                        fontWeight: 800,
                        letterSpacing: 2.5,
                        textTransform: 'uppercase',
                        color: '#fff',
                        lineHeight: 1,
                    }}
                >
                    {en ? "LIVE" : "EN VIVO"}
                </div>
            </div>

            {/* Section title */}
            <div
                style={{
                    background: 'rgba(34, 69, 91, 0.55)',
                    backdropFilter: 'blur(20px) saturate(1.4)',
                    padding: '16px 28px',
                    borderRadius: 12,
                    border: '1px solid rgba(255,255,255,0.10)',
                    boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
                    fontSize: 17,
                    fontWeight: 700,
                    letterSpacing: 2.5,
                    textTransform: 'uppercase',
                    color: 'rgba(255,255,255,0.95)',
                }}
            >
                {en ? "Webcams · National Parks" : "Webcams · Parques Nacionales"}
            </div>
        </div>
    );
};
