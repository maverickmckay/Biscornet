import React from 'react'
import { useStore } from '../store/useStore'

export function LiveIndicator() {
  const { liveConnected, connectLive, disconnectLive } = useStore()

  return (
    <button
      style={s.btn}
      onClick={() => liveConnected ? disconnectLive() : connectLive()}
      title={liveConnected ? 'Disconnect live updates' : 'Connect live updates'}
    >
      <span style={{ ...s.dot, background: liveConnected ? '#22c55e' : '#6b7280',
        boxShadow: liveConnected ? '0 0 0 3px rgba(34,197,94,0.25)' : 'none' }} />
      <span style={s.label}>{liveConnected ? 'Live' : 'Offline'}</span>
    </button>
  )
}

const s: Record<string, React.CSSProperties> = {
  btn: {
    display: 'flex', alignItems: 'center', gap: '5px',
    background: 'transparent', border: '1px solid #3f3f46',
    borderRadius: '5px', padding: '4px 8px', cursor: 'pointer',
  },
  dot: { width: '7px', height: '7px', borderRadius: '50%', transition: 'all 300ms' },
  label: { fontSize: '11px', color: '#9ca3af' },
}
