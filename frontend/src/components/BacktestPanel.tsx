import React, { useState } from 'react'
import { runBacktest, listBacktestScenarios } from '../api/client'

type Verdict = 'PASS' | 'PARTIAL' | 'FAIL'

interface ScenarioResult {
  scenario: string
  verdict: Verdict
  composite_score: number
  tags: string[]
  ground_truth: { node: string; hours: number; mechanism: string; is_stable: boolean }
  oracle: {
    predicted_node: string | null
    predicted_hours: number | null
    predicted_mechanism: string
    confidence: number
    threshold_status: string
    lead_time_hours: number | null
    precursor_count: number
    warning_level: number
    top3_nodes: string[]
  }
  scoring: {
    node_hit: boolean
    timing_error_pct: number | null
    timing_within_20pct: boolean
    mechanism_hit: boolean
    false_positive: boolean
  }
  notes: string[]
}

interface BacktestReport {
  run_at: string
  scenario_count: number
  suite_score: number
  node_accuracy: number
  mechanism_accuracy: number
  timing_mae_hours: number | null
  avg_lead_time_hours: number | null
  false_positive_rate: number
  avg_oracle_confidence: number
  confidence_mae: number
  strongest_scenario: string
  weakest_scenario: string
  summary: string
  results: ScenarioResult[]
}

const VERDICT_COLOR: Record<Verdict, string> = {
  PASS: '#22c55e',
  PARTIAL: '#eab308',
  FAIL: '#ef4444',
}

const VERDICT_BG: Record<Verdict, string> = {
  PASS: '#052e16',
  PARTIAL: '#422006',
  FAIL: '#450a0a',
}

const ALL_SCENARIOS = [
  'CASCADE_SPOF',
  'VENDOR_COLLAPSE',
  'AUTHORITY_VACUUM',
  'SILENT_DRIFT',
  'COMPOUND_FAILURE',
  'FALSE_ALARM',
]

function ScoreMeter({ value, label }: { value: number; label: string }) {
  const pct = Math.min(100, value * 100)
  const color = pct >= 70 ? '#22c55e' : pct >= 45 ? '#eab308' : '#ef4444'
  return (
    <div style={{ textAlign: 'center' as const }}>
      <div style={{ fontSize: 20, fontWeight: 700, color, lineHeight: 1 }}>
        {Math.round(pct)}
      </div>
      <div style={{ fontSize: 9, color: '#6b7280', marginTop: 2, textTransform: 'uppercase' as const }}>
        {label}
      </div>
      <div style={{ background: '#27272a', borderRadius: 3, height: 4, marginTop: 4, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 3 }} />
      </div>
    </div>
  )
}

function ResultCard({ r }: { r: ScenarioResult }) {
  const [open, setOpen] = useState(false)
  const v = r.verdict as Verdict
  const color = VERDICT_COLOR[v]
  const bg = VERDICT_BG[v]
  const pct = Math.round(r.composite_score * 100)

  return (
    <div style={{ borderBottom: '1px solid #27272a' }}>
      <button
        style={{ ...s.cardHeader, background: open ? '#18181b' : 'transparent' }}
        onClick={() => setOpen(o => !o)}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1 }}>
          <span style={{
            fontSize: 9, padding: '2px 6px', borderRadius: 3,
            background: bg, color, fontWeight: 700, textTransform: 'uppercase' as const,
            flexShrink: 0,
          }}>{v}</span>
          <span style={{ fontSize: 12, fontWeight: 600, color: '#e2e2e6' }}>{r.scenario}</span>
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' as const }}>
            {r.tags.map(t => (
              <span key={t} style={{ fontSize: 9, color: '#52525b', background: '#1c1c1f', padding: '1px 5px', borderRadius: 3 }}>
                {t}
              </span>
            ))}
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
          <span style={{ fontSize: 12, fontWeight: 700, color }}>
            {pct}<span style={{ fontSize: 9, color: '#6b7280' }}>/100</span>
          </span>
          <span style={{ color: '#6b7280', fontSize: 10 }}>{open ? '▲' : '▼'}</span>
        </div>
      </button>

      {open && (
        <div style={{ padding: '10px 14px 14px', background: '#0f0f11' }}>
          {/* Ground truth vs oracle */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 12 }}>
            <div style={s.infoBox}>
              <div style={s.infoTitle}>Ground Truth</div>
              <div style={s.infoRow}>
                <span style={s.infoLabel}>Node</span>
                <span style={{ color: '#e2e2e6', fontSize: 11 }}>{r.ground_truth.node}</span>
              </div>
              {!r.ground_truth.is_stable && (
                <div style={s.infoRow}>
                  <span style={s.infoLabel}>Fails in</span>
                  <span style={{ color: '#e2e2e6', fontSize: 11 }}>{r.ground_truth.hours}h</span>
                </div>
              )}
              <div style={s.infoRow}>
                <span style={s.infoLabel}>Mechanism</span>
                <span style={{ color: '#a78bfa', fontSize: 10 }}>{r.ground_truth.mechanism}</span>
              </div>
            </div>

            <div style={s.infoBox}>
              <div style={s.infoTitle}>Oracle Prediction</div>
              <div style={s.infoRow}>
                <span style={s.infoLabel}>Node</span>
                <span style={{
                  color: r.scoring.node_hit ? '#22c55e' : '#ef4444', fontSize: 11,
                }}>
                  {r.oracle.predicted_node || '—'}
                </span>
              </div>
              {r.oracle.predicted_hours !== null && (
                <div style={s.infoRow}>
                  <span style={s.infoLabel}>Hours</span>
                  <span style={{ color: '#e2e2e6', fontSize: 11 }}>{r.oracle.predicted_hours}h</span>
                </div>
              )}
              <div style={s.infoRow}>
                <span style={s.infoLabel}>Mechanism</span>
                <span style={{
                  color: r.scoring.mechanism_hit ? '#22c55e' : '#ef4444', fontSize: 10,
                }}>
                  {r.oracle.predicted_mechanism}
                </span>
              </div>
            </div>
          </div>

          {/* Scoring row */}
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' as const, marginBottom: 10 }}>
            {[
              { label: 'Node hit', val: r.scoring.node_hit },
              { label: 'Timing ≤20%', val: r.scoring.timing_within_20pct },
              { label: 'Mechanism', val: r.scoring.mechanism_hit },
              { label: 'No false pos', val: !r.scoring.false_positive },
            ].map(({ label, val }) => (
              <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <span style={{
                  fontSize: 10, color: val ? '#22c55e' : '#ef4444', fontWeight: 700,
                }}>{val ? '✓' : '✗'}</span>
                <span style={{ fontSize: 10, color: '#9ca3af' }}>{label}</span>
              </div>
            ))}
            {r.scoring.timing_error_pct !== null && (
              <span style={{ fontSize: 10, color: '#6b7280' }}>
                timing err: <span style={{ color: '#e2e2e6' }}>{r.scoring.timing_error_pct}%</span>
              </span>
            )}
          </div>

          {/* Oracle metadata */}
          <div style={{ display: 'flex', gap: 12, fontSize: 10, color: '#6b7280', marginBottom: 10, flexWrap: 'wrap' as const }}>
            <span>Status: <span style={{ color: '#e2e2e6' }}>{r.oracle.threshold_status}</span></span>
            <span>Confidence: <span style={{ color: '#e2e2e6' }}>{(r.oracle.confidence * 100).toFixed(0)}%</span></span>
            {r.oracle.lead_time_hours !== null && (
              <span>Lead: <span style={{ color: '#22c55e' }}>{r.oracle.lead_time_hours}h</span></span>
            )}
            {r.oracle.precursor_count > 0 && (
              <span>Precursors: <span style={{ color: '#fbbf24' }}>{r.oracle.precursor_count}</span></span>
            )}
          </div>

          {/* Notes */}
          <div style={{ borderTop: '1px solid #27272a', paddingTop: 8 }}>
            {r.notes.map((n, i) => (
              <div key={i} style={{ fontSize: 10, color: '#9ca3af', lineHeight: 1.5, marginBottom: 2 }}>
                • {n}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export function BacktestPanel() {
  const [report, setReport] = useState<BacktestReport | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set(ALL_SCENARIOS))

  const toggleScenario = (name: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(name)) { next.delete(name) } else { next.add(name) }
      return next
    })
  }

  const run = async () => {
    setLoading(true)
    setError(null)
    try {
      const names = selected.size === ALL_SCENARIOS.length ? undefined : [...selected]
      const data = await runBacktest(names)
      setReport(data)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  const suiteColor = report
    ? report.suite_score >= 0.70 ? '#22c55e' : report.suite_score >= 0.45 ? '#eab308' : '#ef4444'
    : '#6b7280'

  return (
    <div style={s.root}>
      <div style={s.header}>
        <span style={s.title}>Oracle Backtest</span>
        <button style={s.btn} onClick={run} disabled={loading || selected.size === 0}>
          {loading ? 'Running…' : `Run (${selected.size})`}
        </button>
      </div>

      {/* Scenario selector */}
      <div style={s.selectorRow}>
        {ALL_SCENARIOS.map(name => (
          <button
            key={name}
            style={{
              ...s.scenarioBadge,
              background: selected.has(name) ? '#1d3a4a' : '#1c1c1f',
              color: selected.has(name) ? '#38bdf8' : '#52525b',
              border: `1px solid ${selected.has(name) ? '#0ea5e9' : '#27272a'}`,
            }}
            onClick={() => toggleScenario(name)}
          >
            {name.replace('_', ' ')}
          </button>
        ))}
      </div>

      {error && <div style={s.errorBanner}>{error}</div>}

      {report && (
        <>
          {/* Suite score */}
          <div style={s.suiteBox}>
            <div style={{ textAlign: 'center' as const, marginBottom: 12 }}>
              <div style={{ fontSize: 36, fontWeight: 800, color: suiteColor, lineHeight: 1 }}>
                {Math.round(report.suite_score * 100)}
              </div>
              <div style={{ fontSize: 10, color: '#6b7280', textTransform: 'uppercase' as const, letterSpacing: '0.08em', marginTop: 2 }}>
                Suite Score / 100
              </div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 10 }}>
              <ScoreMeter value={report.node_accuracy} label="Node Acc" />
              <ScoreMeter value={report.mechanism_accuracy} label="Mechanism" />
              <ScoreMeter value={1 - report.false_positive_rate} label="Specificity" />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#6b7280', flexWrap: 'wrap' as const, gap: 6 }}>
              {report.timing_mae_hours !== null && (
                <span>Timing MAE: <span style={{ color: '#e2e2e6' }}>{report.timing_mae_hours.toFixed(1)}h</span></span>
              )}
              {report.avg_lead_time_hours !== null && (
                <span>Avg lead: <span style={{ color: '#22c55e' }}>{report.avg_lead_time_hours.toFixed(1)}h</span></span>
              )}
              <span>Confidence: <span style={{ color: '#e2e2e6' }}>{(report.avg_oracle_confidence * 100).toFixed(0)}%</span></span>
              <span>Cal. err: <span style={{ color: '#e2e2e6' }}>{(report.confidence_mae * 100).toFixed(0)}pp</span></span>
            </div>
            <div style={{ marginTop: 8, fontSize: 10, color: '#9ca3af', lineHeight: 1.5, borderTop: '1px solid #27272a', paddingTop: 8 }}>
              {report.summary}
            </div>
          </div>

          {/* Per-scenario results */}
          <div style={s.resultsList}>
            {report.results.map(r => (
              <ResultCard key={r.scenario} r={r} />
            ))}
          </div>
        </>
      )}

      {!report && !loading && (
        <div style={s.empty}>
          <div style={{ fontSize: 12, color: '#6b7280', lineHeight: 1.6 }}>
            Select scenarios and click <strong style={{ color: '#9ca3af' }}>Run</strong> to evaluate
            oracle prediction accuracy against known failure outcomes.
            <br /><br />
            Each scenario has a deterministic ground truth. The oracle is scored on
            node prediction, timing accuracy, mechanism identification, and advance warning.
          </div>
        </div>
      )}
    </div>
  )
}

const s: Record<string, React.CSSProperties> = {
  root: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    overflow: 'hidden',
    background: '#111113',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '10px 12px',
    borderBottom: '1px solid #27272a',
    flexShrink: 0,
  },
  title: {
    fontSize: 13,
    fontWeight: 600,
    color: '#e2e2e6',
  },
  btn: {
    fontSize: 11,
    padding: '4px 12px',
    background: '#1d4ed8',
    color: '#fff',
    border: 'none',
    borderRadius: 4,
    cursor: 'pointer',
  },
  selectorRow: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 5,
    padding: '8px 12px',
    borderBottom: '1px solid #27272a',
    flexShrink: 0,
  },
  scenarioBadge: {
    fontSize: 9,
    padding: '2px 7px',
    borderRadius: 3,
    cursor: 'pointer',
    fontWeight: 600,
    letterSpacing: '0.03em',
  },
  errorBanner: {
    background: '#450a0a',
    color: '#fca5a5',
    fontSize: 11,
    padding: '6px 12px',
    flexShrink: 0,
  },
  suiteBox: {
    padding: '12px 14px',
    borderBottom: '1px solid #27272a',
    flexShrink: 0,
  },
  resultsList: {
    flex: 1,
    overflowY: 'auto',
  },
  cardHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    width: '100%',
    padding: '9px 12px',
    border: 'none',
    cursor: 'pointer',
    textAlign: 'left',
    gap: 8,
  },
  infoBox: {
    background: '#18181b',
    borderRadius: 5,
    padding: '7px 9px',
  },
  infoTitle: {
    fontSize: 9,
    color: '#52525b',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.06em',
    marginBottom: 5,
    fontWeight: 700,
  },
  infoRow: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 3,
  },
  infoLabel: {
    fontSize: 10,
    color: '#6b7280',
  },
  empty: {
    flex: 1,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
  },
}
