import React, { useEffect, useState } from 'react'
import { Toolbar } from './components/Toolbar'
import { Legend } from './components/Legend'
import { StressSlider } from './components/StressSlider'
import { CollapseMap } from './components/CollapseMap'
import { ActionPanel } from './components/ActionPanel'
import { MonteCarloPanel } from './components/MonteCarloPanel'
import { MarketPanel } from './components/MarketPanel'
import { AgentSimPanel } from './components/AgentSimPanel'
import { FeedbackPanel } from './components/FeedbackPanel'
import { OraclePanel } from './components/OraclePanel'
import { ThresholdPanel } from './components/ThresholdPanel'
import { BacktestPanel } from './components/BacktestPanel'
import { LiminosityPanel } from './components/LiminosityPanel'
import { ImportPanel } from './components/ImportPanel'
import { AuthScreen } from './components/AuthScreen'
import { useStore } from './store/useStore'
import { getMe } from './api/client'

type RightTab = 'action' | 'montecarlo' | 'market' | 'agents' | 'feedback' | 'oracle' | 'threshold' | 'backtest' | 'liminosity'

const TABS: { id: RightTab; label: string }[] = [
  { id: 'action', label: 'Collapse' },
  { id: 'montecarlo', label: 'Monte Carlo' },
  { id: 'market', label: 'Market' },
  { id: 'agents', label: 'Agents' },
  { id: 'feedback', label: 'Feedback' },
  { id: 'oracle', label: 'Oracle' },
  { id: 'threshold', label: 'Threshold' },
  { id: 'backtest', label: 'Backtest' },
  { id: 'liminosity', label: 'Liminosity' },
]

export default function App() {
  const { error, showImport, setShowImport, token, currentUser, setUser, authChecked } = useStore()
  const [rightTab, setRightTab] = useState<RightTab>('action')
  const [showAuth, setShowAuth] = useState(false)

  // On mount: validate stored token and fetch user profile
  useEffect(() => {
    if (token && !currentUser) {
      getMe()
        .then(user => setUser(user, token))
        .catch(() => setUser(null, null))
    }
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  if (showAuth) {
    return <AuthScreen onDone={() => setShowAuth(false)} />
  }

  return (
    <div style={s.root}>
      <Toolbar onAuthClick={() => setShowAuth(true)} />
      <Legend />
      <StressSlider />

      {error && <div style={s.error}>{error}</div>}

      <div style={s.body}>
        {/* Left: collapse map */}
        <div style={s.mapArea}>
          <CollapseMap />
        </div>

        {/* Right: tabbed panel */}
        <div style={s.sidePanel}>
          <div style={s.tabs}>
            {TABS.map(t => (
              <button
                key={t.id}
                style={{ ...s.tab, ...(rightTab === t.id ? s.tabActive : {}) }}
                onClick={() => setRightTab(t.id)}
              >
                {t.label}
              </button>
            ))}
          </div>
          <div style={s.tabContent}>
            {rightTab === 'action' && <ActionPanel />}
            {rightTab === 'montecarlo' && <MonteCarloPanel />}
            {rightTab === 'market' && <MarketPanel />}
            {rightTab === 'agents' && <AgentSimPanel />}
            {rightTab === 'feedback' && <FeedbackPanel />}
            {rightTab === 'oracle' && <OraclePanel />}
            {rightTab === 'threshold' && <ThresholdPanel />}
            {rightTab === 'backtest' && <BacktestPanel />}
            {rightTab === 'liminosity' && <LiminosityPanel />}
          </div>
        </div>
      </div>

      {showImport && <ImportPanel onClose={() => setShowImport(false)} />}
    </div>
  )
}

const s: Record<string, React.CSSProperties> = {
  root: {
    display: 'flex',
    flexDirection: 'column',
    height: '100vh',
    overflow: 'hidden',
    background: '#0d0d0f',
  },
  error: {
    background: '#450a0a',
    color: '#fca5a5',
    fontSize: '12px',
    padding: '6px 16px',
  },
  body: {
    flex: 1,
    display: 'flex',
    overflow: 'hidden',
  },
  mapArea: {
    flex: 1,
    overflow: 'hidden',
    position: 'relative',
  },
  sidePanel: {
    width: '360px',
    borderLeft: '1px solid #27272a',
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column',
    background: '#111113',
  },
  tabs: {
    display: 'flex',
    borderBottom: '1px solid #27272a',
    flexShrink: 0,
    overflowX: 'auto',
  },
  tab: {
    flex: 1,
    padding: '7px 4px',
    fontSize: '11px',
    background: 'transparent',
    border: 'none',
    color: '#6b7280',
    cursor: 'pointer',
    whiteSpace: 'nowrap',
  },
  tabActive: {
    color: '#e2e2e6',
    borderBottom: '2px solid #3b82f6',
  },
  tabContent: {
    flex: 1,
    overflow: 'hidden',
  },
}
