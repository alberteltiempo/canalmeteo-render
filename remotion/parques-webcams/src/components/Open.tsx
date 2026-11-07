import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig, staticFile, Img} from 'remotion';

export const Open: React.FC = () => {
    const frame = useCurrentFrame();
    const {fps, durationInFrames} = useVideoConfig();

    // Logo entra con spring scale + fade
    const logoScale = spring({
        frame,
        fps,
        config: {damping: 12, stiffness: 100, mass: 0.6},
        from: 0.6,
        to: 1,
    });
    const logoOpacity = interpolate(frame, [0, 12], [0, 1], {extrapolateRight: 'clamp'});

    // Título aparece después del logo
    const titleOpacity = interpolate(frame, [18, 32], [0, 1], {extrapolateRight: 'clamp'});
    const titleY = interpolate(frame, [18, 32], [30, 0], {extrapolateRight: 'clamp'});

    // Underline crece
    const underlineWidth = interpolate(
        frame,
        [25, 50],
        [0, 320],
        {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}
    );

    // Fade out al final
    const exitOpacity = interpolate(
        frame,
        [durationInFrames - 12, durationInFrames],
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
                    width: 1200,
                    height: 1200,
                    borderRadius: '50%',
                    background: 'radial-gradient(circle, rgba(243,156,18,0.10) 0%, transparent 60%)',
                    filter: 'blur(40px)',
                }}
            />

            {/* Logo */}
            <Img
                src="https://dev.canalmeteo.tv/logos/logo-canalmeteo-30.png"
                style={{
                    height: 180,
                    width: 'auto',
                    transform: `scale(${logoScale})`,
                    opacity: logoOpacity,
                    filter: 'drop-shadow(0 8px 30px rgba(0,0,0,0.4))',
                    marginBottom: 40,
                }}
            />

            {/* Título */}
            <div
                style={{
                    opacity: titleOpacity,
                    transform: `translateY(${titleY}px)`,
                    fontSize: 22,
                    fontWeight: 600,
                    letterSpacing: 8,
                    textTransform: 'uppercase',
                    color: '#F39C12',
                    marginBottom: 18,
                }}
            >
                Webcams
            </div>

            <div
                style={{
                    opacity: titleOpacity,
                    transform: `translateY(${titleY}px)`,
                    fontSize: 78,
                    fontWeight: 800,
                    letterSpacing: -1.5,
                    color: '#fff',
                    textShadow: '0 4px 24px rgba(0,0,0,0.5)',
                }}
            >
                Parques Nacionales
            </div>

            {/* Underline */}
            <div
                style={{
                    width: underlineWidth,
                    height: 4,
                    background: 'linear-gradient(90deg, #457a99 0%, #F39C12 100%)',
                    borderRadius: 2,
                    marginTop: 32,
                    boxShadow: '0 0 18px rgba(243,156,18,0.55)',
                }}
            />
        </AbsoluteFill>
    );
};
