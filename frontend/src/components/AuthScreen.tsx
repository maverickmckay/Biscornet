import React, { useState } from 'react'
import { login, register } from '../api/client'
import { useStore } from '../store/useStore'

type Mode = 'login' | 'register'

interface AuthScreenProps {
  onDone?: () => void
}

export function AuthScreen({ onDone }: AuthScreenProps) {
  const setUser = useStore(s => s.setUser)
  const [mode, setMode] = useState<Mode>('login')
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      if (mode === 'login') {
        const result = await login(email, password)
        setUser(result.user, result.token)
      } else {
        const result = await register(email, name, password)
        setUser(result.user, result.token)
      }
      onDone?.()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Authentication failed'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={s.overlay}>
      <div style={s.card}>
        <div style={s.logoRow}>
          <span style={s.logo}>No Next Move</span>
          <span style={s.version}>v0.3</span>
        </div>

        <div style={s.tabs}>
          <button
            style={{ ...s.tab, ...(mode === 'login' ? s.tabActive : {}) }}
            onClick={() => setMode('login')}
          >
            Sign in
          </button>
          <button
            style={{ ...s.tab, ...(mode === 'register' ? s.tabActive : {}) }}
            onClick={() => setMode('register')}
          >
            Register
          </button>
        </div>

        <form style={s.form} onSubmit={handleSubmit}>
          {mode === 'register' && (
            <>
              <label style={s.label}>Name</label>
              <input
                style={s.input}
                type="text"
                autoComplete="name"
                value={name}
                onChange={e => setName(e.target.value)}
                required
                placeholder="Your name"
              />
            </>
          )}

          <label style={s.label}>Email</label>
          <input
            style={s.input}
            type="email"
            autoComplete="email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            required
            placeholder="you@example.com"
          />

          <label style={s.label}>Password</label>
          <input
            style={s.input}
            type="password"
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            value={password}
            onChange={e => setPassword(e.target.value)}
            required
            placeholder="••••••••"
          />

          {error && <div style={s.error}>{error}</div>}

          <button style={s.btn} type="submit" disabled={loading}>
            {loading ? '...' : mode === 'login' ? 'Sign in' : 'Create account'}
          </button>
        </form>

        <div style={s.skip}>
          <button style={s.skipBtn} onClick={() => { setUser(null, null); onDone?.() }}>
            Continue without account
          </button>
        </div>
      </div>
    </div>
  )
}

const s: Record<string, React.CSSProperties> = {
  overlay: {
    position: 'fixed',
    inset: 0,
    background: '#0d0d0f',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 100,
  },
  card: {
    background: '#111113',
    border: '1px solid #27272a',
    borderRadius: '10px',
    padding: '28px',
    width: '320px',
    display: 'flex',
    flexDirection: 'column',
    gap: '12px',
  },
  logoRow: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'baseline',
    marginBottom: '4px',
  },
  logo: { fontSize: '18px', fontWeight: 700, color: '#e2e2e6' },
  version: { fontSize: '11px', color: '#52525b' },
  tabs: {
    display: 'flex',
    borderBottom: '1px solid #27272a',
    marginBottom: '4px',
  },
  tab: {
    flex: 1,
    padding: '6px',
    background: 'transparent',
    border: 'none',
    color: '#71717a',
    fontSize: '13px',
    cursor: 'pointer',
  },
  tabActive: {
    color: '#e2e2e6',
    borderBottom: '2px solid #3b82f6',
  },
  form: {
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
  },
  label: { fontSize: '11px', color: '#71717a' },
  input: {
    background: '#18181b',
    border: '1px solid #27272a',
    borderRadius: '4px',
    color: '#e2e2e6',
    padding: '7px 10px',
    fontSize: '13px',
    width: '100%',
    boxSizing: 'border-box',
    outline: 'none',
  },
  error: {
    background: '#450a0a',
    color: '#fca5a5',
    fontSize: '11px',
    padding: '6px 8px',
    borderRadius: '4px',
  },
  btn: {
    background: '#1d4ed8',
    color: '#fff',
    border: 'none',
    borderRadius: '4px',
    padding: '9px',
    fontSize: '13px',
    fontWeight: 600,
    cursor: 'pointer',
    marginTop: '4px',
  },
  skip: { textAlign: 'center' },
  skipBtn: {
    background: 'transparent',
    border: 'none',
    color: '#52525b',
    fontSize: '11px',
    cursor: 'pointer',
    textDecoration: 'underline',
  },
}
