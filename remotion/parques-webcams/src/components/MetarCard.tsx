import React from 'react';
import {interpolate, useCurrentFrame} from 'remotion';
import type {MetarData} from '../types';

interface Props {
    metar: MetarData;
    lang?: string;
}

export const MetarCard: React.FC<Props> = ({metar, lang = "es"}) => {
    const en = lang === "en";
    const frame = useCurrentFrame();

    // Slide in from right
    const enterX = interpolate(frame, [3, 28], [60, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
    const enterOpacity = interpolate(frame, [3, 28], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});

    // Parse wind: "12 mph NO" → ["12", "mph NO"]
    const windParts = ((en ? metar.wind_en : metar.wind) || '— mph').split(' ');
    const windSpeed = windParts[0];
    const windRest = windParts.slice(1).join(' ');

    return (
        <div
            style={{
                borderRadius: 18,
                overflow: 'hidden',
                background: 'rgba(34, 69, 91, 0.55)',
                border: '1px solid rgba(255,255,255,0.10)',
                boxShadow: '0 12px 40px rgba(0,0,0,0.35), inset 0 1px 0 rgba(255,255,255,0.08)',
                backdropFilter: 'blur(20px)',
                transform: `translateX(${enterX}px)`,
                opacity: enterOpacity,
            }}
        >
            {/* Header (ch-blue gradient) */}
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
                    background: 'linear-gradient(90deg, #457a99 0%, #5a9bc4 100%)',
                }}
            >
                {en ? "Current Conditions" : "Condiciones Actuales"}
            </div>

            {/* Body */}
            <div style={{padding: 24}}>
                {/* Station info */}
                <div
                    style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'flex-end',
                        marginBottom: 22,
                        paddingBottom: 18,
                        borderBottom: '1px dashed rgba(255,255,255,0.14)',
                    }}
                >
                    <div>
                        <div
                            style={{
                                fontFamily: 'JetBrains Mono, monospace',
                                fontSize: 30,
                                fontWeight: 700,
                                color: '#5a9bc4',
                                letterSpacing: 1,
                                lineHeight: 1,
                            }}
                        >
                            {metar.id}
                        </div>
                        <div
                            style={{
                                fontSize: 14,
                                color: 'rgba(255,255,255,0.65)',
                                textTransform: 'uppercase',
                                letterSpacing: 1.2,
                                marginTop: 6,
                                fontWeight: 500,
                            }}
                        >
                            {metar.name}
                        </div>
                    </div>
                    <div
                        style={{
                            fontSize: 13,
                            color: 'rgba(255,255,255,0.55)',
                            textAlign: 'right',
                            textTransform: 'uppercase',
                            letterSpacing: 1.5,
                            fontWeight: 600,
                        }}
                    >
                        a
                        <div
                            style={{
                                fontFamily: 'JetBrains Mono, monospace',
                                fontSize: 22,
                                color: 'rgba(255,255,255,0.95)',
                                marginTop: 4,
                                fontWeight: 700,
                                letterSpacing: 0,
                            }}
                        >
                            {metar.distance_mi} mi
                        </div>
                    </div>
                </div>

                {/* Hero temp */}
                <div style={{textAlign: 'center', marginBottom: 26}}>
                    <div
                        style={{
                            fontFamily: 'JetBrains Mono, monospace',
                            fontSize: 110,
                            fontWeight: 700,
                            lineHeight: 1,
                            color: '#fff',
                            letterSpacing: -4,
                            textShadow: '0 6px 24px rgba(0,0,0,0.4)',
                        }}
                    >
                        {metar.temp_f ?? '—'}
                        <span
                            style={{
                                fontSize: 42,
                                color: '#5a9bc4',
                                verticalAlign: 'top',
                                marginLeft: 6,
                                letterSpacing: 0,
                            }}
                        >
                            °F
                        </span>
                    </div>
                    <div
                        style={{
                            fontSize: 28,
                            fontWeight: 600,
                            color: 'rgba(255,255,255,0.95)',
                            marginTop: 14,
                            letterSpacing: 0.5,
                        }}
                    >
                        {(en ? metar.conditions_en : metar.conditions) || '—'}
                    </div>
                    <div
                        style={{
                            fontSize: 17,
                            color: 'rgba(255,255,255,0.65)',
                            marginTop: 12,
                            fontFamily: 'JetBrains Mono, monospace',
                            fontWeight: 500,
                        }}
                    >
                        {en ? "Feels like" : "Sensación"}: {metar.feels_f ?? '—'} °F
                    </div>
                </div>

                {/* Stats grid 2x2 */}
                <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12}}>
                    <Stat label={en ? "Wind" : "Viento"} value={windSpeed} unit={windRest} />
                    <Stat label={en ? "Humidity" : "Humedad"} value={`${metar.humidity ?? '—'}`} unit="%" />
                    <Stat label={en ? "Dew point" : "Punto rocío"} value={`${metar.dewpoint_f ?? '—'}`} unit="°F" />
                    <Stat label={en ? "Visibility" : "Visibilidad"} value={`${metar.visibility_mi ?? '—'}`} unit="mi" />
                </div>
            </div>
        </div>
    );
};

const Stat: React.FC<{label: string; value: string; unit: string}> = ({label, value, unit}) => (
    <div
        style={{
            background: 'rgba(0,0,0,0.28)',
            borderRadius: 12,
            padding: '18px 16px',
            border: '1px solid rgba(255,255,255,0.06)',
        }}
    >
        <div
            style={{
                fontSize: 13,
                fontWeight: 600,
                color: 'rgba(255,255,255,0.65)',
                textTransform: 'uppercase',
                letterSpacing: 1.5,
                marginBottom: 10,
            }}
        >
            {label}
        </div>
        <div
            style={{
                fontFamily: 'JetBrains Mono, monospace',
                fontSize: 36,
                fontWeight: 700,
                color: '#fff',
                lineHeight: 1,
            }}
        >
            {value}
            <span
                style={{
                    fontSize: 18,
                    color: 'rgba(255,255,255,0.6)',
                    marginLeft: 6,
                    fontWeight: 500,
                    letterSpacing: 0,
                }}
            >
                {unit}
            </span>
        </div>
    </div>
);
