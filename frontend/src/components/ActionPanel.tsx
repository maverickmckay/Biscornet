/**
 * ActionPanel — right-side panel showing collapse point details
 * for the selected node (or top-5 if nothing selected).
 */
import React from 'react'
import { useStore } from '../store/useStore'
import type { CollapsePoint, ActionLabel } from '../api/client'
import clsx from 'clsx'

const ACTION_COLOUR: Record<ActionLabel, string> = {
  fix:           '#22c55e',
  monitor:       '#3b82f6',
  avoid:         '#ef4444',
  hedge:         '#f97316',
  escalate:      '#a855f7',
  stress_test:   '#eab308',
  exploit_lawful:'#06b6d4',
}

const ACTION_LABEL: Record<ActionLabel, string> = {
  fix:            'Fix',
  monitor:        'Monitor',
  avoid:          'Avoid',
  hedge:          'Hedge',
  escalate:       'Escalate',
  stress_test:    'Stress-test',
  exploit_lawful: 'Exploit (lawful)',
}

const RISK_BADGE: Record<string, string> = {
  critical: '#ef4444',
  high:     '#f97316',
  medium:   '#eab308',
  low:      '#22c55e',
  none:     '#16a34a',
}

function ScoreBar({ label, value }: { label: string; value: number }) {
  return (
    <div style={s.scoreRow}>
      <span style={s.scoreLabel}>{label}</span>
      <div style={s.barTrack}>
        <div
          style={{
            ...s.barFill,
            width: `${Math.round(value * 100)}%`,
            background: value > 0.65 ? '#ef4444' : value > 0.35 ? '#f97316' : '#22c55e',
          }}
        />
      </div>
      <span style={s.scoreValue}>{(value * 100).toFixed(0)}</span>
    </div>
  )
}

function CollapseCard({ cp, expanded }: { cp: CollapsePoint; expanded: boolean }) {
  const colour = ACTION_COLOUR[cp.action]
  return (
    <div style={{ ...s.card, borderLeft: `3px solid ${colour}` }}>
      <div style={s.cardHeader}>
        <span style={s.nodeLabel}>{cp.node_label}</span>
        <span style={{ ...s.badge, background: RISK_BADGE[cp.collapse_risk] ?? '#6b7280' }}>
          {cp.collapse_risk.toUpperCase()}
        </span>
        <span style={{ ...s.actionBadge, background: colour }}>
          {ACTION_LABEL[cp.action]}
        </span>
      </div>

      <ScoreBar label="NNM"              value={cp.nnm_score} />
      <ScoreBar label="Hidden constraint" value={cp.hidden_constraint_score} />
      <ScoreBar label="False redundancy"  value={cp.false_redundancy_score} />
      <ScoreBar label="Pressure absorb"   value={1 - cp.pressure_absorption_score} />
      <ScoreBar label="Reversion"         value={cp.reversion_potential_score} />

      <p style={s.rationale}>{cp.action_rationale}</p>

      {expanded && (
        <>
          {cp.evidence.length > 0 && (
            <div style={s.section}>
              <div style={s.sectionTitle}>Evidence</div>
              <ul style={s.list}>
                {cp.evidence.map((e, i) => <li key={i} style={s.listItem}>{e}</li>)}
              </ul>
            </div>
          )}
          {cp.downstream_failures.length > 0 && (
            <div style={s.section}>
              <div style={s.sectionTitle}>Downstream failures</div>
              <div style={s.tags}>
                {cp.downstream_failures.map(f => <span key={f} style={s.tag}>{f}</span>)}
              </div>
            </div>
          )}
          {cp.reversion_targets.length > 0 && (
            <div style={s.section}>
              <div style={s.sectionTitle}>Reversion targets</div>
              <div style={s.tags}>
                {cp.reversion_targets.map(t => <span key={t} style={{ ...s.tag, background: '#1e3a5f' }}>{t}</span>)}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

export function ActionPanel() {
  const { analysis, selectedCollapsePoint } = useStore()

  if (!analysis) {
    return (
      <div style={s.empty}>
        <p>Run analysis to see action recommendations.</p>
      </div>
    )
  }

  const displayed = selectedCollapsePoint
    ? [selectedCollapsePoint]
    : analysis.collapse_points.slice(0, 5)

  return (
    <div style={s.panel}>
      <div style={s.header}>
        {selectedCollapsePoint
          ? `Node: ${selectedCollapsePoint.node_label}`
          : 'Top Collapse Points'}
      </div>
      <div style={s.summary}>{analysis.summary}</div>
      <div style={s.cards}>
        {displayed.map(cp => (
          <CollapseCard key={cp.node_id} cp={cp} expanded={!!selectedCollapsePoint} />
        ))}
      </div>

      {analysis.hidden_assumptions.length > 0 && (
        <div style={s.section}>
          <div style={s.sectionTitle}>Hidden Assumptions</div>
          <div style={s.tags}>
            {analysis.hidden_assumptions.map(a => (
              <span key={a} style={{ ...s.tag, background: '#3b1a5e' }}>{a}</span>
            ))}
          </div>
        </div>
      )}

      <div style={s.section}>
        <div style={s.sectionTitle}>Action distribution</div>
        <div style={s.actionDist}>
          {analysis.top_actions.map(({ action, count }) => (
            <div key={action} style={s.actionRow}>
              <span style={{ ...s.actionChip, background: ACTION_COLOUR[action as ActionLabel] ?? '#6b7280' }}>
                {ACTION_LABEL[action as ActionLabel] ?? action}
              </span>
              <span style={s.actionCount}>{count}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

const s: Record<string, React.CSSProperties> = {
  panel: {
    height: '100%',
    overflowY: 'auto',
    padding: '16px',
    display: 'flex',
    flexDirection: 'column',
    gap: '12px',
  },
  header: { fontSize: '13px', fontWeight: 600, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em' },
  summary: { fontSize: '12px', color: '#6b7280', lineHeight: 1.5 },
  empty: { display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#6b7280', fontSize: '13px' },
  cards: { display: 'flex', flexDirection: 'column', gap: '10px' },
  card: { background: '#18181b', borderRadius: '6px', padding: '12px', display: 'flex', flexDirection: 'column', gap: '6px' },
  cardHeader: { display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' },
  nodeLabel: { fontSize: '13px', fontWeight: 600, color: '#e2e2e6', flex: 1 },
  badge: { fontSize: '10px', padding: '2px 6px', borderRadius: '4px', color: '#fff', fontWeight: 700 },
  actionBadge: { fontSize: '10px', padding: '2px 6px', borderRadius: '4px', color: '#fff', fontWeight: 600 },
  scoreRow: { display: 'flex', alignItems: 'center', gap: '6px' },
  scoreLabel: { fontSize: '10px', color: '#6b7280', width: '110px', flexShrink: 0 },
  barTrack: { flex: 1, height: '4px', background: '#27272a', borderRadius: '2px', overflow: 'hidden' },
  barFill: { height: '100%', borderRadius: '2px', transition: 'width 300ms' },
  scoreValue: { fontSize: '10px', color: '#9ca3af', width: '24px', textAlign: 'right' },
  rationale: { fontSize: '11px', color: '#9ca3af', lineHeight: 1.5, marginTop: '4px' },
  section: { display: 'flex', flexDirection: 'column', gap: '6px' },
  sectionTitle: { fontSize: '11px', fontWeight: 600, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.04em' },
  list: { paddingLeft: '16px' },
  listItem: { fontSize: '11px', color: '#9ca3af', lineHeight: 1.6 },
  tags: { display: 'flex', flexWrap: 'wrap', gap: '4px' },
  tag: { fontSize: '10px', background: '#27272a', color: '#d1d5db', padding: '2px 8px', borderRadius: '4px' },
  actionDist: { display: 'flex', flexDirection: 'column', gap: '4px' },
  actionRow: { display: 'flex', alignItems: 'center', gap: '8px' },
  actionChip: { fontSize: '10px', padding: '2px 8px', borderRadius: '4px', color: '#fff', fontWeight: 600 },
  actionCount: { fontSize: '11px', color: '#6b7280' },
}
