import React from 'react';
import {AbsoluteFill, Audio, Loop, Sequence, staticFile, interpolate, useVideoConfig} from 'remotion';
import {z} from 'zod';
import {Open} from './components/Open';
import {WebcamSlide} from './components/WebcamSlide';
import {Outro} from './components/Outro';
import type {SegmentData} from './types';

// Timing (in seconds)
const OPEN_S = 3;
const SLIDE_S = 12;
const OUTRO_S = 9;
// Total: 3 + 4×12 + 9 = 60s

// Audio config
const AUDIO_FILE = 'parques-music.mp3';
const MASTER_VOLUME = 0.6;       // Master 60% para no competir con voz off futura
const DUCK_VOLUME = 0.3;         // 30% durante el outro
const FADE_IN_FRAMES = 30;       // 1 segundo
const FADE_OUT_FRAMES = 60;      // 2 segundos
const DUCK_TRANSITION_FRAMES = 30; // 1s de transición al ducking

export const parquesSchema = z.object({
    cams: z.array(z.any()),
    radarFrames: z.array(z.any()),
    generatedAt: z.string(),
});

export const ParquesComposition: React.FC<SegmentData> = ({cams, radarFrames}) => {
    const {fps, durationInFrames} = useVideoConfig();

    const openFrames = OPEN_S * fps;     // 90 frames
    const slideFrames = SLIDE_S * fps;   // 360 frames per slide
    const outroFrames = OUTRO_S * fps;   // 270 frames
    const outroStartFrame = openFrames + 4 * slideFrames; // frame 1530

    // Audio file disponible?
    const audioSrc = staticFile(AUDIO_FILE);
    // Si el archivo no existe, Remotion lanzará error en render.
    // Para preview en Studio sin archivo, simplemente removemos <Audio>.
    // Trick: catch via try-catch isn't possible here, así que asumimos
    // que existe; si no, comentar la línea <Audio> abajo.

    // Si no hay cámaras (preview/edit sin data), pantalla de loading
    if (!cams || cams.length === 0) {
        return (
            <AbsoluteFill
                style={{
                    background: '#0a1628',
                    color: '#fff',
                    fontFamily: 'Outfit, sans-serif',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontSize: 48,
                }}
            >
                Cargando datos del segmento...
            </AbsoluteFill>
        );
    }

    return (
        <AbsoluteFill style={{background: '#0a1628'}}>
            {/* === AUDIO === Loop automático para cualquier duración */}
            <Loop durationInFrames={durationInFrames}>
                <Audio
                    src={audioSrc}
                    volume={(f) => {
                        // f = frame relativo dentro del loop (que dura 60s = todo el vídeo)

                        // 1. Fade-in al inicio (0 → 1 en los primeros 30 frames)
                        const fadeIn = interpolate(
                            f,
                            [0, FADE_IN_FRAMES],
                            [0, 1],
                            {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}
                        );

                        // 2. Fade-out al final (1 → 0 en los últimos 60 frames)
                        const fadeOut = interpolate(
                            f,
                            [durationInFrames - FADE_OUT_FRAMES, durationInFrames],
                            [1, 0],
                            {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}
                        );

                        // 3. Ducking al 30% durante el outro
                        // De volumen normal (1) a 0.3 en la transición al outro
                        const duckLevel = interpolate(
                            f,
                            [outroStartFrame, outroStartFrame + DUCK_TRANSITION_FRAMES],
                            [1, DUCK_VOLUME / 1], // ratio para multiplicar
                            {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}
                        );

                        // Combinar: el menor de los 3 envelopes × master volume
                        return Math.min(fadeIn, fadeOut, duckLevel) * MASTER_VOLUME;
                    }}
                />
            </Loop>

            {/* === VIDEO === */}

            {/* Intro 3s */}
            <Sequence from={0} durationInFrames={openFrames} name="Open">
                <Open />
            </Sequence>

            {/* 4 slides de 12s cada uno */}
            {cams.slice(0, 4).map((cam, idx) => {
                const startFrame = openFrames + idx * slideFrames;
                return (
                    <Sequence
                        key={cam.code}
                        from={startFrame}
                        durationInFrames={slideFrames}
                        name={`Slide-${cam.code}`}
                    >
                        <WebcamSlide
                            cam={cam}
                            slideIndex={idx}
                            totalSlides={4}
                            radarFrames={radarFrames}
                        />
                    </Sequence>
                );
            })}

            {/* Outro 9s */}
            <Sequence
                from={outroStartFrame}
                durationInFrames={outroFrames}
                name="Outro"
            >
                <Outro />
            </Sequence>
        </AbsoluteFill>
    );
};
