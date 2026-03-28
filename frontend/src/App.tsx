import React from 'react'
import { Toolbar } from './components/Toolbar'
import { Legend } from './components/Legend'
import { StressSlider } from './components/StressSlider'
import { CollapseMap } from './components/CollapseMap'
import { ActionPanel } from './components/ActionPanel'
import { useStore } from './store/useStore'

export default function App() {
  const { error } = useStore()

  return (
    <div style={s.root}>
      <Toolbar />
      <Legend />
      <StressSlider />

      {error && (
        <div style={s.error}>
          {error}
        </div>
      )}

      <div style={s.body}>
        {/* Left: collapse map */}
        <div style={s.mapArea}>
          <CollapseMap />
        </div>

        {/* Right: action panel */}
        <div style={s.sidePanel}>
          <ActionPanel />
        </div>
      </div>
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
    width: '320px',
    borderLeft: '1px solid #27272a',
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column',
    background: '#111113',
  },
}
