import React, { useEffect, useState } from 'react'
import { useStore } from '../store/useStore'
import { submitOutcome, getWeights, type OutcomeRecord } from '../api/client'

const OUTCOMES = ['resolved', 'worsened', 'unchanged', 'collapsed', 'avoided']
const ACTIONS_MAP: Record<string, string> = {
  'Fix': 'Fix',
  'Monitor': 'Monitor',
  'Avoid': 'Avoid',
  'Hedge': 'Hedge',
  'Escalate': 'Escalate',
  'Stress-test': 'Stress-test',
  'Exploit (lawful)': 'Exploit (lawful)',
}

const WEIGHT_KEYS = [
  'reroute_failure',
  'time_to_failure',
  'dependency_concentration',
  'return_loop_absence',
  'hidden_constraint',
]

export function FeedbackPanel() {
  const { analysis, selectedCollapsePoint, graphData } = useStore()
  const graphId = analysis?.graph_id ?? graphData?.id ?? ''
  const cp = selectedCollapsePoint

  const [outcome, setOutcome] = useState('resolved')
  const [notes, setNotes] = useState('')
  const [loading, setLoading] = useState(false)
  const [success, setSuccess] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [weights, setWeights] = useState<Record<string, number> | null>(null)

  useEffect(() => {
    getWeights().then(w => setWeights(w)).catch(() => {})
  }, [])

  async function handleSubmit() {
    if (!cp || !graphId) return
    setLoading(true)
    setError(null)
    setSuccess(null)
    try {
      const result = await submitOutcome({
        graph_id: graphId,
        node_id: cp.node_id,
        node_label: cp.node_label,
        action_taken: ACTIONS_MAP[cp.action] ?? cp.action,
        outcome,
        nnm_score: cp.nnm_score,
        notes: notes || undefined,
      })
      setSuccess('Outcome recorded. Weights updated.')
      setWeights(result.current_weights)
      setNotes('')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Submit failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={s.wrap}>
      <div style={s.title}>Outcome Feedback</div>
      <div style={s.sub}>
        Record what actually happened. The NNM scoring weights update via exponential
        moving average to improve future recommendations.
      </div>

      {!cp && (
        <div style={s.empty}>Select a collapse point to record an outcome.</div>
      )}

      {cp && (
        <>
          <div style={s.node}>
            <span style={s.nodeLabel}>{cp.node_label}</span>
            <span style={s.nodeMeta}>Recommended: {cp.action} · NNM {cp.nnm_score.toFixed(2)}</span>
          </div>

          <label style={s.label}>What actually happened?</label>
          <div style={s.outcomeRow}>
            {OUTCOMES.map(o => (
              <button
                key={o}
                style={{ ...s.outcomeBtn, ...(outcome === o ? s.outcomeBtnActive : {}) }}
                onClick={() => setOutcome(o)}
              >
                {o}
              </button>
            ))}
          </div>

          <label style={s.label}>Notes (optional)</label>
          <textarea
            style={s.textarea}
            value={notes}
            onChange={e => setNotes(e.target.value)}
            placeholder="What was the context? What intervention was used?"
            rows={3}
          />

          <button style={s.btn} onClick={handleSubmit} disabled={loading}>
            {loading ? 'Recording...' : 'Submit Outcome'}
          </button>

          {success && <div style={s.success}>{success}</div>}
          {error && <div style={s.error}>{error}</div>}
        </>
      )}

      {weights && (
        <>
          <div style={s.sectionTitle}>Current NNM Weights</div>
          {WEIGHT_KEYS.map(k => (
            <div key={k} style={s.weightRow}>
              <span style={s.weightKey}>{k.replace(/_/g, ' ')}</span>
              <div style={s.barWrap}>
                <div style={{ ...s.bar, width: `${weights[k] * 100}%` }} />
              </div>
              <span style={s.weightVal}>{(weights[k] * 100).toFixed(1)}%</span>
            </div>
          ))}
        </>
      )}
    </div>
  )
}

const s: Record<string, React.CSSProperties> = {
  wrap: {
    padding: '12px',
    overflowY: 'auto',
    height: '100%',
    boxSizing: 'border-box',
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
  },
  title: {
    fontSize: '12px',
    color: '#a1a1aa',
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
  },
  sub: { fontSize: '11px', color: '#52525b', lineHeight: 1.5 },
  empty: { fontSize: '12px', color: '#52525b', padding: '8px 0' },
  node: {
    background: '#18181b',
    border: '1px solid #27272a',
    borderRadius: '4px',
    padding: '8px 10px',
    display: 'flex',
    flexDirection: 'column',
    gap: '2px',
  },
  nodeLabel: { fontSize: '13px', color: '#e2e2e6', fontWeight: 600 },
  nodeMeta: { fontSize: '11px', color: '#71717a' },
  label: { fontSize: '11px', color: '#71717a', display: 'block' },
  outcomeRow: { display: 'flex', flexWrap: 'wrap', gap: '4px' },
  outcomeBtn: {
    fontSize: '11px',
    padding: '3px 8px',
    borderRadius: '4px',
    border: '1px solid #27272a',
    background: 'transparent',
    color: '#71717a',
    cursor: 'pointer',
  },
  outcomeBtnActive: {
    background: '#1d4ed8',
    color: '#fff',
    border: '1px solid #1d4ed8',
  },
  textarea: {
    background: '#18181b',
    border: '1px solid #27272a',
    borderRadius: '4px',
    color: '#d4d4d8',
    padding: '6px 8px',
    fontSize: '12px',
    width: '100%',
    boxSizing: 'border-box',
    resize: 'vertical',
    fontFamily: 'inherit',
  },
  btn: {
    background: '#1d4ed8',
    color: '#fff',
    border: 'none',
    borderRadius: '4px',
    padding: '7px',
    fontSize: '12px',
    cursor: 'pointer',
    fontWeight: 600,
  },
  success: {
    background: '#052e16',
    color: '#86efac',
    fontSize: '11px',
    padding: '6px 8px',
    borderRadius: '4px',
  },
  error: {
    background: '#450a0a',
    color: '#fca5a5',
    fontSize: '11px',
    padding: '6px 8px',
    borderRadius: '4px',
  },
  sectionTitle: {
    fontSize: '11px',
    color: '#52525b',
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
    marginTop: '4px',
  },
  weightRow: { display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11px' },
  weightKey: { color: '#71717a', width: '145px', flexShrink: 0, textTransform: 'capitalize' },
  barWrap: {
    flex: 1,
    height: '6px',
    background: '#27272a',
    borderRadius: '3px',
    overflow: 'hidden',
  },
  bar: { height: '100%', background: '#3b82f6', borderRadius: '3px', transition: 'width 0.4s' },
  weightVal: { color: '#d4d4d8', width: '36px', textAlign: 'right' },
}
