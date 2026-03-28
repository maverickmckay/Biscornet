/**
 * StressSlider — time-to-failure pressure slider.
 * Moving it right visually stresses the graph.
 */
import React from 'react'
import { useStore } from '../store/useStore'

export function StressSlider() {
  const { stressLevel, setStressLevel } = useStore()

  return (
    <div style={s.container}>
      <span style={s.label}>Pressure</span>
      <input
        type="range"
        min={0}
        max={100}
        value={Math.round(stressLevel * 100)}
        onChange={e => setStressLevel(Number(e.target.value) / 100)}
        style={s.slider}
      />
      <span style={s.value}>
        {stressLevel === 0 ? 'None' : stressLevel < 0.4 ? 'Low' : stressLevel < 0.7 ? 'Moderate' : 'High'}
      </span>
    </div>
  )
}

const s: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
    padding: '6px 16px',
    background: '#18181b',
    borderBottom: '1px solid #27272a',
  },
  label: { fontSize: '12px', color: '#6b7280', whiteSpace: 'nowrap' },
  slider: { flex: 1, accentColor: '#ef4444' },
  value: { fontSize: '11px', color: '#9ca3af', width: '60px', textAlign: 'right' },
}
