import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import type {CamData} from '../types';

interface Props {
    cam: CamData;
    lang?: string;
}

export const ParkCard: React.FC<Props> = ({cam, lang = "es"}) => {
    const en = lang === "en";
    const frame = useCurrentFrame();

    // Slide in from left
    const enterX = interpolate(frame, [0, 25], [-60, 0], {extrapolateRight: 'clamp'});
    const enterOpacity = interpolate(frame, [0, 25], [0, 1], {extrapolateRight: 'clamp'});

    return (
        <div
            style={{
                position: 'absolute',
                bottom: 80,
                left: 60,
                zIndex: 10,
                background: 'rgba(34, 69, 91, 0.55)',
                backdropFilter: 'blur(28px) saturate(1.5)',
                borderRadius: 20,
                padding: '26px 36px',
                border: '1px solid rgba(255,255,255,0.10)',
                boxShadow: '0 20px 60px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.12)',
                maxWidth: 880,
                transform: `translateX(${enterX}px)`,
                opacity: enterOpacity,
            }}
        >
            {/* State eyebrow */}
            <div
                style={{
                    fontSize: 18,
                    fontWeight: 700,
                    letterSpacing: 4,
                    textTransform: 'uppercase',
                    color: '#F39C12',
                    marginBottom: 12,
                    textShadow: '0 2px 8px rgba(243,156,18,0.3)',
                }}
            >
                {cam.state}
            </div>

            {/* Park name */}
            <div
                style={{
                    fontSize: 64,
                    fontWeight: 800,
                    color: '#fff',
                    letterSpacing: -0.8,
                    lineHeight: 1.02,
                    textShadow: '0 4px 24px rgba(0,0,0,0.5)',
                }}
            >
                {en ? cam.park_name_en : cam.park_name_es}
            </div>

            {/* Park meta: view + elevation */}
            <div
                style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 20,
                    marginTop: 16,
                    fontSize: 20,
                    fontWeight: 500,
                    color: 'rgba(255,255,255,0.82)',
                }}
            >
                <span>{en ? cam.view_en : cam.view_es}</span>
                <span
                    style={{
                        width: 5,
                        height: 5,
                        borderRadius: '50%',
                        background: 'rgba(255,255,255,0.5)',
                        flexShrink: 0,
                    }}
                />
                <span>{en ? `${cam.elevation_ft.toLocaleString('en-US')} ft elevation` : `${cam.elevation_ft.toLocaleString('de-DE')} pies de elevación`}</span>
            </div>
        </div>
    );
};
