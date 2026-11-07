import React from 'react';

interface Props {
    progress: number; // 0..1
}

export const ProgressBar: React.FC<Props> = ({progress}) => {
    return (
        <div
            style={{
                position: 'absolute',
                bottom: 24,
                left: 24,
                right: 488,
                height: 5,
                background: 'rgba(255,255,255,0.10)',
                borderRadius: '0 0 22px 22px',
                zIndex: 30,
                overflow: 'hidden',
            }}
        >
            <div
                style={{
                    height: '100%',
                    width: `${Math.max(0, Math.min(1, progress)) * 100}%`,
                    background: 'linear-gradient(90deg, #457a99 0%, #F39C12 100%)',
                    boxShadow: '0 0 18px rgba(243,156,18,0.55)',
                }}
            />
        </div>
    );
};
