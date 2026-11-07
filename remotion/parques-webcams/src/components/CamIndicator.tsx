import React from 'react';

interface Props {
    currentIndex: number;
    total: number;
}

export const CamIndicator: React.FC<Props> = ({currentIndex, total}) => {
    return (
        <div
            style={{
                position: 'absolute',
                top: 146,
                left: 60,
                zIndex: 10,
                display: 'flex',
                gap: 10,
            }}
        >
            {Array.from({length: total}).map((_, i) => {
                const isActive = i === currentIndex;
                const isDone = i < currentIndex;

                return (
                    <div
                        key={i}
                        style={{
                            width: 44,
                            height: 6,
                            borderRadius: 3,
                            background: isActive
                                ? '#F39C12'
                                : isDone
                                ? 'rgba(255,255,255,0.65)'
                                : 'rgba(255,255,255,0.25)',
                            boxShadow: isActive ? '0 0 14px rgba(243,156,18,0.7)' : 'none',
                            transition: 'all 0.3s',
                        }}
                    />
                );
            })}
        </div>
    );
};
