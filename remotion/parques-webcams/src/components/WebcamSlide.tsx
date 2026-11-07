import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig, Img} from 'remotion';
import type {CamData, RadarFrame} from '../types';
import {TopBar} from './TopBar';
import {ParkCard} from './ParkCard';
import {MetarCard} from './MetarCard';
import {RadarMini} from './RadarMini';
import {ProgressBar} from './ProgressBar';
import {CamIndicator} from './CamIndicator';

interface Props {
    cam: CamData;
    slideIndex: number;
    totalSlides: number;
    radarFrames: RadarFrame[];
    lang?: string;
}

export const WebcamSlide: React.FC<Props> = ({cam, slideIndex, totalSlides, radarFrames, lang = "es"}) => {
    const frame = useCurrentFrame();
    const {durationInFrames, fps} = useVideoConfig();

    // Fade in al entrar (15 frames = 0.5s)
    const enterOpacity = interpolate(frame, [0, 15], [0, 1], {extrapolateRight: 'clamp'});

    // Fade out al salir (12 frames = 0.4s)
    const exitOpacity = interpolate(
        frame,
        [durationInFrames - 12, durationInFrames],
        [1, 0],
        {extrapolateLeft: 'clamp'}
    );
    const opacity = enterOpacity * exitOpacity;

    // Subtle Ken Burns: zoom in muy ligero durante 12s
    const kenBurnsScale = interpolate(frame, [0, durationInFrames], [1.0, 1.04]);

    // Total progress at this slide point (for progress bar)
    // Each slide takes 25% of total visible bar (4 slides total)
    const slideProgress = interpolate(frame, [0, durationInFrames], [0, 1]);
    const totalProgress = (slideIndex + slideProgress) / totalSlides;

    return (
        <AbsoluteFill
            style={{
                background: 'linear-gradient(135deg, #0a1628 0%, #1a2f4a 50%, #0a1628 100%)',
                fontFamily: 'Outfit, sans-serif',
                color: '#fff',
                opacity,
                padding: 24,
            }}
        >
            {/* === CÁMARA EN CAJA REDONDEADA === */}
            <div
                style={{
                    position: 'absolute',
                    top: 24,
                    left: 24,
                    right: 488, // 24 padding + 440 sidebar + 24 gap
                    bottom: 24,
                    borderRadius: 22,
                    overflow: 'hidden',
                    border: '1px solid rgba(255,255,255,0.08)',
                    boxShadow: '0 24px 60px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.1)',
                    zIndex: 1,
                }}
            >
                {/* Imagen de la cámara con Ken Burns */}
                <Img
                    src={cam.image_url}
                    style={{
                        width: '100%',
                        height: '100%',
                        objectFit: 'cover',
                        filter: 'brightness(0.95) saturate(1.1)',
                        transform: `scale(${kenBurnsScale})`,
                        transformOrigin: 'center center',
                    }}
                />

                {/* Vignette para legibilidad */}
                <div
                    style={{
                        position: 'absolute',
                        inset: 0,
                        background: `
                            linear-gradient(90deg, rgba(10,22,40,0.55) 0%, transparent 28%, transparent 65%, rgba(10,22,40,0.85) 100%),
                            linear-gradient(180deg, rgba(10,22,40,0.45) 0%, transparent 22%, transparent 72%, rgba(10,22,40,0.7) 100%)
                        `,
                        pointerEvents: 'none',
                    }}
                />
            </div>

            {/* Top bar: logo + EN VIVO + título sección */}
            <TopBar lang={lang} />

            {/* 4 dots indicator */}
            <CamIndicator currentIndex={slideIndex} total={totalSlides} />

            {/* Park card (bottom-left) */}
            <ParkCard cam={cam} lang={lang} />

            {/* Sidebar derecho con METAR + Radar */}
            <div
                style={{
                    position: 'absolute',
                    top: 24,
                    right: 24,
                    bottom: 24,
                    width: 440,
                    zIndex: 20,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 22,
                }}
            >
                <MetarCard metar={cam.metar} lang={lang} />
                <RadarMini cam={cam} radarFrames={radarFrames} lang={lang} />
            </div>

            {/* Progress bar abajo */}
            <ProgressBar progress={totalProgress} />
        </AbsoluteFill>
    );
};
