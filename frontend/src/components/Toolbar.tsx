import React from 'react'
import { useStore } from '../store/useStore'
import { LiveIndicator } from './LiveIndicator'

interface ToolbarProps {
  onAuthClick?: () => void
}

export function Toolbar({ onAuthClick }: ToolbarProps) {
  const { setShowImport, loading, currentUser, logout } = useStore()

  return (
    <div style={s.bar}>
      <span style={s.brand}>No Next Move</span>
      <div style={s.actions}>
        <button style={s.btn} onClick={() => setShowImport(true)} disabled={loading}>
          {loading ? 'Loading…' : 'Import'}
        </button>
        {currentUser ? (
          <div style={s.userRow}>
            <span style={s.userName}>{currentUser.name}</span>
            <button style={s.logoutBtn} onClick={logout}>Sign out</button>
          </div>
        ) : (
          <button style={s.authBtn} onClick={onAuthClick}>Sign in</button>
        )}
        <LiveIndicator />
      </div>
    </div>
  )
}

const s: Record<string, React.CSSProperties> = {
  bar: {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
    padding: '10px 16px',
    background: '#111113',
    borderBottom: '1px solid #27272a',
  },
  brand: { fontSize: '15px', fontWeight: 700, color: '#e2e2e6', letterSpacing: '-0.02em', flex: 1 },
  actions: { display: 'flex', gap: '8px', alignItems: 'center' },
  btn: {
    fontSize: '12px',
    padding: '5px 12px',
    background: '#27272a',
    color: '#e2e2e6',
    border: '1px solid #3f3f46',
    borderRadius: '5px',
    cursor: 'pointer',
  },
  authBtn: {
    fontSize: '12px',
    padding: '5px 12px',
    background: 'transparent',
    color: '#3b82f6',
    border: '1px solid #3b82f6',
    borderRadius: '5px',
    cursor: 'pointer',
  },
  userRow: { display: 'flex', alignItems: 'center', gap: '6px' },
  userName: { fontSize: '12px', color: '#a1a1aa' },
  logoutBtn: {
    fontSize: '11px',
    background: 'transparent',
    border: 'none',
    color: '#52525b',
    cursor: 'pointer',
    textDecoration: 'underline',
  },
}
