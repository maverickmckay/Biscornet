import React, { useState } from 'react'
import { Toolbar } from './components/Toolbar'
import { Legend } from './components/Legend'
import { StressSlider } from './components/StressSlider'
import { CollapseMap } from './components/CollapseMap'
import { ActionPanel } from './components/ActionPanel'
import { MonteCarloPanel } from './components/MonteCarloPanel'
import { ImportPanel } from './components/ImportPanel'
import { useStore } from './store/useStore'

type RightTab = 'action' | 'montecarlo'

export default function App() {
  const { error, showImport, setShowImport } = useStore()
  const [rightTab, setRightTab] = useState<RightTab>('action')

  return (
    <div style={s.root}>
      <Toolbar />
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
            <button
              style={{ ...s.tab, ...(rightTab === 'action' ? s.tabActive : {}) }}
              onClick={() => setRightTab('action')}
            >
              Collapse Points
            </button>
            <button
              style={{ ...s.tab, ...(rightTab === 'montecarlo' ? s.tabActive : {}) }}
              onClick={() => setRightTab('montecarlo')}
            >
              Monte Carlo
            </button>
          </div>
          <div style={s.tabContent}>
            {rightTab === 'action' ? <ActionPanel /> : <MonteCarloPanel />}
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
    width: '340px',
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
  },
  tab: {
    flex: 1,
    padding: '8px',
    fontSize: '12px',
    background: 'transparent',
    border: 'none',
    color: '#6b7280',
    cursor: 'pointer',
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
