import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig, Img} from 'remotion';

export const Outro: React.FC = () => {
    const frame = useCurrentFrame();
    const {fps, durationInFrames} = useVideoConfig();

    // Logo entra con spring
    const logoScale = spring({
        frame,
        fps,
        config: {damping: 12, stiffness: 90, mass: 0.7},
        from: 0.7,
        to: 1,
    });
    const logoOpacity = interpolate(frame, [0, 18], [0, 1], {extrapolateRight: 'clamp'});

    // "Síguenos en" aparece
    const followOpacity = interpolate(frame, [22, 38], [0, 1], {extrapolateRight: 'clamp'});
    const followY = interpolate(frame, [22, 38], [20, 0], {extrapolateRight: 'clamp'});

    // URL grande
    const urlOpacity = interpolate(frame, [40, 60], [0, 1], {extrapolateRight: 'clamp'});
    const urlScale = spring({
        frame: Math.max(0, frame - 40),
        fps,
        config: {damping: 14, stiffness: 100, mass: 0.6},
        from: 0.85,
        to: 1,
    });

    // Social handles entran al final
    const socialOpacity = interpolate(frame, [80, 110], [0, 1], {extrapolateRight: 'clamp'});
    const socialY = interpolate(frame, [80, 110], [25, 0], {extrapolateRight: 'clamp'});

    // Fade out al final
    const exitOpacity = interpolate(
        frame,
        [durationInFrames - 15, durationInFrames],
        [1, 0],
        {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}
    );

    return (
        <AbsoluteFill
            style={{
                background: 'linear-gradient(135deg, #0a1628 0%, #1a2f4a 50%, #0a1628 100%)',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                fontFamily: 'Outfit, sans-serif',
                color: '#fff',
                opacity: exitOpacity,
            }}
        >
            {/* Background glow */}
            <div
                style={{
                    position: 'absolute',
                    width: 1400,
                    height: 1400,
                    borderRadius: '50%',
                    background: 'radial-gradient(circle, rgba(69,122,153,0.18) 0%, transparent 65%)',
                    filter: 'blur(50px)',
                }}
            />

            {/* Logo */}
            <Img
                src="https://dev.canalmeteo.tv/logos/logo-canalmeteo-30.png"
                style={{
                    height: 200,
                    width: 'auto',
                    transform: `scale(${logoScale})`,
                    opacity: logoOpacity,
                    filter: 'drop-shadow(0 8px 30px rgba(0,0,0,0.5))',
                    marginBottom: 50,
                }}
            />

            {/* Síguenos en */}
            <div
                style={{
                    opacity: followOpacity,
                    transform: `translateY(${followY}px)`,
                    fontSize: 26,
                    fontWeight: 500,
                    letterSpacing: 4,
                    textTransform: 'uppercase',
                    color: 'rgba(255,255,255,0.75)',
                    marginBottom: 24,
                }}
            >
                Síguenos en
            </div>

            {/* URL */}
            <div
                style={{
                    opacity: urlOpacity,
                    transform: `scale(${urlScale})`,
                    fontSize: 96,
                    fontWeight: 800,
                    letterSpacing: -2,
                    color: '#F39C12',
                    textShadow: '0 4px 30px rgba(243,156,18,0.4)',
                }}
            >
                canalmeteo.tv
            </div>

            {/* Social handles */}
            <div
                style={{
                    opacity: socialOpacity,
                    transform: `translateY(${socialY}px)`,
                    fontSize: 24,
                    fontWeight: 600,
                    letterSpacing: 3,
                    color: 'rgba(255,255,255,0.85)',
                    marginTop: 60,
                    display: 'flex',
                    gap: 36,
                }}
            >
                <span>@alberteltiempo</span>
                <span style={{opacity: 0.4}}>·</span>
                <span>Instagram</span>
                <span style={{opacity: 0.4}}>·</span>
                <span>X</span>
                <span style={{opacity: 0.4}}>·</span>
                <span>YouTube</span>
                <span style={{opacity: 0.4}}>·</span>
                <span>TikTok</span>
            </div>
        </AbsoluteFill>
    );
};
