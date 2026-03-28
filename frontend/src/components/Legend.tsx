import React from 'react'

const ITEMS = [
  { colour: '#ef4444', label: 'Critical — no reroute' },
  { colour: '#f97316', label: 'High — weak reroute' },
  { colour: '#eab308', label: 'Medium' },
  { colour: '#22c55e', label: 'Low / redundant' },
  { colour: '#a855f7', label: 'Hidden assumption' },
]

export function Legend() {
  return (
    <div style={s.container}>
      {ITEMS.map(({ colour, label }) => (
        <div key={label} style={s.item}>
          <div style={{ ...s.dot, background: colour }} />
          <span style={s.label}>{label}</span>
        </div>
      ))}
    </div>
  )
}

const s: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    gap: '16px',
    padding: '6px 16px',
    background: '#111113',
    borderBottom: '1px solid #27272a',
    flexWrap: 'wrap',
  },
  item: { display: 'flex', alignItems: 'center', gap: '5px' },
  dot: { width: '8px', height: '8px', borderRadius: '50%', flexShrink: 0 },
  label: { fontSize: '11px', color: '#6b7280' },
}
