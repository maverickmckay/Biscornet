import React, { useState } from 'react'
import { useStore } from '../store/useStore'
import { runOracle, type OraclePrediction } from '../api/client'

const STATUS_COLORS: Record<string, string> = {
  threshold: '#ef4444',
  cascade:   '#f97316',
  precursor: '#eab308',
  ensemble:  '#6366f1',
}

const SEVERITY_COLORS: Record<string, string> = {
  critical: '#ef4444',
  high:     '#f97316',
  medium:   '#eab308',
  low:      '#6366f1',
}

function ConfidenceMeter({ value, label }: { value: number; label: string }) {
  const color = value >= 0.7 ? '#22c55e' : value >= 0.4 ? '#eab308' : '#ef4444'
  return (
    <div style={s.confRow}>
      <span style={s.confLabel}>{label}</span>
      <div style={s.confBar}>
        <div style={{ ...s.confFill, width: `${value * 100}%`, background: color }} />
      </div>
      <span style={{ ...s.confVal, color }}>{(value * 100).toFixed(0)}%</span>
    </div>
  )
}

export function OraclePanel() {
  const { analysis, graphData } = useStore()
  const graphId = analysis?.graph_id ?? graphData?.id

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [prediction, setPrediction] = useState<OraclePrediction | null>(null)
  const [expandedSection, setExpandedSection] = useState<string | null>('sequence')

  async function handleRun() {
    if (!graphId) return
    setLoading(true)
    setError(null)
    try {
      const result = await runOracle(graphId)
      setPrediction(result)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Oracle prediction failed')
    } finally {
      setLoading(false)
    }
  }

  function toggle(section: string) {
    setExpandedSection(s => s === section ? null : section)
  }

  return (
    <div style={s.wrap}>
      <div style={s.header}>
        <div>
          <div style={s.title}>Oracle Prediction</div>
          <div style={s.sub}>Causal · Threshold · Precursor · Analog · Adversarial · Ensemble</div>
        </div>
        <button style={s.btn} onClick={handleRun} disabled={loading || !graphId}>
          {loading ? 'Running...' : 'Predict'}
        </button>
      </div>

      {error && <div style={s.error}>{error}</div>}

      {!prediction && !loading && (
        <div style={s.empty}>
          Runs 6 analysis engines and integrates them into a single forward prediction
          with confidence decomposition and uncertainty mapping.
        </div>
      )}

      {prediction && (
        <>
          {/* Overall confidence */}
          <div style={overallStyle(prediction.overall_confidence)}>
            <span style={s.overallLabel}>Overall Confidence</span>
            <span style={s.overallVal}>{(prediction.overall_confidence * 100).toFixed(0)}%</span>
          </div>

          {/* Narrative */}
          <div style={s.narrative}>{prediction.narrative}</div>

          {/* Earliest failure */}
          {prediction.earliest_failure_label && (
            <div style={s.earlyCard}>
              <div style={s.earlyLabel}>Earliest predicted failure</div>
              <div style={s.earlyNode}>{prediction.earliest_failure_label}</div>
              {prediction.earliest_failure_hours != null && (
                <div style={s.earlyTime}>
                  ~{formatHours(prediction.earliest_failure_hours)}
                </div>
              )}
            </div>
          )}

          {/* Confidence breakdown */}
          <div style={s.sectionCard}>
            <button style={s.sectionBtn} onClick={() => toggle('confidence')}>
              <span>Confidence Breakdown</span>
              <span>{expandedSection === 'confidence' ? '▲' : '▼'}</span>
            </button>
            {expandedSection === 'confidence' && (
              <div style={s.sectionBody}>
                <ConfidenceMeter value={prediction.ensemble_confidence} label="Ensemble agreement" />
                <ConfidenceMeter value={prediction.uncertainty.graph_completeness} label="Graph completeness" />
                <ConfidenceMeter value={prediction.uncertainty.timing_confidence} label="Timing confidence" />
                <ConfidenceMeter value={prediction.uncertainty.mechanism_confidence} label="Mechanism confidence" />
                <ConfidenceMeter value={1 - prediction.uncertainty.novel_situation_risk} label="Analog coverage" />
              </div>
            )}
          </div>

          {/* Failure sequence */}
          {prediction.primary_sequence.length > 0 && (
            <div style={s.sectionCard}>
              <button style={s.sectionBtn} onClick={() => toggle('sequence')}>
                <span>Failure Sequence ({prediction.primary_sequence.length})</span>
                <span>{expandedSection === 'sequence' ? '▲' : '▼'}</span>
              </button>
              {expandedSection === 'sequence' && (
                <div style={s.sectionBody}>
                  {prediction.primary_sequence.slice(0, 8).map((event, i) => (
                    <div key={i} style={s.seqItem}>
                      <div style={s.seqHeader}>
                        <span style={{ ...s.seqDot, background: STATUS_COLORS[event.trigger_type] ?? '#6b7280' }} />
                        <span style={s.seqLabel}>{event.node_label}</span>
                        {event.estimated_hours_to_failure != null && (
                          <span style={s.seqTime}>{formatHours(event.estimated_hours_to_failure)}</span>
                        )}
                      </div>
                      <div style={s.seqMech}>{event.failure_mechanism}</div>
                      {event.supporting_evidence[0] && (
                        <div style={s.seqEvidence}>{event.supporting_evidence[0]}</div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Precursors */}
          {prediction.active_precursors.length > 0 && (
            <div style={s.sectionCard}>
              <button style={s.sectionBtn} onClick={() => toggle('precursors')}>
                <span>Active Precursors ({prediction.active_precursors.length})</span>
                <span style={{ color: SEVERITY_COLORS[prediction.active_precursors[0]?.severity] ?? '#6b7280' }}>
                  {prediction.active_precursors[0]?.severity.toUpperCase()}
                </span>
              </button>
              {expandedSection === 'precursors' && (
                <div style={s.sectionBody}>
                  {prediction.active_precursors.map((sig, i) => (
                    <div key={i} style={s.precursorCard}>
                      <div style={s.precursorHeader}>
                        <span style={{ ...s.sevBadge, background: SEVERITY_COLORS[sig.severity] + '22', color: SEVERITY_COLORS[sig.severity] }}>
                          {sig.severity}
                        </span>
                        <span style={s.precursorNode}>{sig.node_label}</span>
                        <span style={s.precursorLead}>~{sig.lead_time_hours}h lead</span>
                      </div>
                      <div style={s.precursorSig}>{sig.signature.replace(/_/g, ' ')}</div>
                      <div style={s.precursorMode}>{sig.failure_mode}</div>
                      {sig.evidence.map((ev, j) => (
                        <div key={j} style={s.precursorEvidence}>{ev}</div>
                      ))}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Analog */}
          <div style={s.sectionCard}>
            <button style={s.sectionBtn} onClick={() => toggle('analog')}>
              <span>Structural Analog</span>
              <span style={s.analogName}>{prediction.analog_archetype}</span>
            </button>
            {expandedSection === 'analog' && (
              <div style={s.sectionBody}>
                <div style={s.analogRate}>
                  Historical failure rate:&nbsp;
                  <span style={{ color: rateColor(prediction.analog_failure_rate) }}>
                    {(prediction.analog_failure_rate * 100).toFixed(0)}%
                  </span>
                </div>
                <div style={s.analogNarrative}>{prediction.analog_narrative}</div>
              </div>
            )}
          </div>

          {/* Adversarial */}
          {prediction.top_adversarial_scenarios.length > 0 && (
            <div style={s.sectionCard}>
              <button style={s.sectionBtn} onClick={() => toggle('adversarial')}>
                <span>Adversarial Scenarios</span>
                <span style={s.dangerBadge}>{prediction.top_adversarial_scenarios.length}</span>
              </button>
              {expandedSection === 'adversarial' && (
                <div style={s.sectionBody}>
                  {prediction.mitigation_gaps.length > 0 && (
                    <div style={s.gapWarning}>
                      {prediction.mitigation_gaps.length} mitigation gap(s) detected
                    </div>
                  )}
                  {prediction.top_adversarial_scenarios.map((sc, i) => (
                    <div key={i} style={s.advCard}>
                      <div style={s.advCategory}>{sc.category.replace(/_/g, ' ')}</div>
                      <div style={s.advDanger}>{sc.why_dangerous}</div>
                      <div style={s.advMissed}>{sc.why_missed}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Ensemble */}
          <div style={s.sectionCard}>
            <button style={s.sectionBtn} onClick={() => toggle('ensemble')}>
              <span>Ensemble Agreement</span>
              <span style={s.confSmall}>{(prediction.ensemble_confidence * 100).toFixed(0)}%</span>
            </button>
            {expandedSection === 'ensemble' && (
              <div style={s.sectionBody}>
                {prediction.robust_nodes.length > 0 && (
                  <div style={s.ensRow}>
                    <span style={s.ensLabel}>Robust (all agree)</span>
                    <span style={s.ensGreen}>{prediction.robust_nodes.length} node(s)</span>
                  </div>
                )}
                {prediction.contested_nodes.length > 0 && (
                  <div style={s.ensRow}>
                    <span style={s.ensLabel}>Contested</span>
                    <span style={s.ensYellow}>{prediction.contested_nodes.length} node(s)</span>
                  </div>
                )}
                {prediction.hidden_nodes.length > 0 && (
                  <div style={s.ensRow}>
                    <span style={s.ensLabel}>Hidden by base weights</span>
                    <span style={s.ensOrange}>{prediction.hidden_nodes.length} node(s)</span>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Uncertainty */}
          <div style={s.sectionCard}>
            <button style={s.sectionBtn} onClick={() => toggle('uncertainty')}>
              <span>Irreducible Uncertainty</span>
              <span style={s.riskBadge}>{(prediction.uncertainty.novel_situation_risk * 100).toFixed(0)}% novel</span>
            </button>
            {expandedSection === 'uncertainty' && (
              <div style={s.sectionBody}>
                {prediction.uncertainty.irreducible_unknowns.map((u, i) => (
                  <div key={i} style={s.unknownItem}>{u}</div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}

function formatHours(hours: number): string {
  if (hours < 1) return `${Math.round(hours * 60)}m`
  if (hours < 24) return `${hours.toFixed(1)}h`
  return `${(hours / 24).toFixed(1)}d`
}

function rateColor(rate: number): string {
  if (rate >= 0.7) return '#ef4444'
  if (rate >= 0.5) return '#f97316'
  return '#eab308'
}

function overallStyle(confidence: number): React.CSSProperties {
  const bg = confidence >= 0.7 ? 'rgba(34,197,94,0.08)' : confidence >= 0.4 ? 'rgba(234,179,8,0.08)' : 'rgba(239,68,68,0.08)'
  const border = confidence >= 0.7 ? '#22c55e' : confidence >= 0.4 ? '#eab308' : '#ef4444'
  return { ...s.overallCard, background: bg, borderColor: border }
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
  header: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexShrink: 0 },
  title: { fontSize: '12px', color: '#a1a1aa', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em' },
  sub: { fontSize: '10px', color: '#52525b', marginTop: '2px' },
  btn: {
    background: '#7c3aed', color: '#fff', border: 'none', borderRadius: '4px',
    padding: '6px 14px', fontSize: '12px', cursor: 'pointer', fontWeight: 600, flexShrink: 0,
  },
  error: { background: '#450a0a', color: '#fca5a5', fontSize: '11px', padding: '6px 8px', borderRadius: '4px' },
  empty: { color: '#52525b', fontSize: '11px', lineHeight: 1.6 },
  overallCard: {
    border: '1px solid', borderRadius: '6px', padding: '10px 12px',
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
  },
  overallLabel: { fontSize: '11px', color: '#a1a1aa', textTransform: 'uppercase', letterSpacing: '0.06em' },
  overallVal: { fontSize: '22px', fontWeight: 700, color: '#e2e2e6' },
  narrative: { fontSize: '11px', color: '#a1a1aa', lineHeight: 1.6 },
  earlyCard: {
    background: 'rgba(239,68,68,0.06)', border: '1px solid rgba(239,68,68,0.3)',
    borderRadius: '6px', padding: '10px 12px',
  },
  earlyLabel: { fontSize: '10px', color: '#ef4444', textTransform: 'uppercase', letterSpacing: '0.08em' },
  earlyNode: { fontSize: '14px', color: '#e2e2e6', fontWeight: 600, marginTop: '2px' },
  earlyTime: { fontSize: '11px', color: '#fca5a5', marginTop: '2px' },
  sectionCard: { background: '#18181b', border: '1px solid #27272a', borderRadius: '4px', overflow: 'hidden' },
  sectionBtn: {
    width: '100%', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    padding: '8px 10px', background: 'transparent', border: 'none', color: '#d4d4d8',
    fontSize: '12px', cursor: 'pointer', fontWeight: 500,
  },
  sectionBody: { padding: '8px 10px', borderTop: '1px solid #27272a', display: 'flex', flexDirection: 'column', gap: '6px' },
  confRow: { display: 'flex', alignItems: 'center', gap: '8px', fontSize: '11px' },
  confLabel: { color: '#71717a', width: '130px', flexShrink: 0 },
  confBar: { flex: 1, height: '5px', background: '#27272a', borderRadius: '3px', overflow: 'hidden' },
  confFill: { height: '100%', borderRadius: '3px', transition: 'width 0.4s' },
  confVal: { width: '32px', textAlign: 'right', fontWeight: 600 },
  seqItem: { paddingBottom: '8px', borderBottom: '1px solid #27272a' },
  seqHeader: { display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '2px' },
  seqDot: { width: '7px', height: '7px', borderRadius: '50%', flexShrink: 0 },
  seqLabel: { fontSize: '12px', color: '#e2e2e6', fontWeight: 500 },
  seqTime: { fontSize: '11px', color: '#fca5a5', marginLeft: 'auto' },
  seqMech: { fontSize: '11px', color: '#71717a', paddingLeft: '13px' },
  seqEvidence: { fontSize: '10px', color: '#52525b', paddingLeft: '13px', marginTop: '2px' },
  precursorCard: { background: '#111113', border: '1px solid #27272a', borderRadius: '4px', padding: '8px' },
  precursorHeader: { display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px' },
  sevBadge: { fontSize: '10px', padding: '2px 5px', borderRadius: '3px', fontWeight: 600 },
  precursorNode: { fontSize: '12px', color: '#e2e2e6', fontWeight: 500 },
  precursorLead: { fontSize: '10px', color: '#52525b', marginLeft: 'auto' },
  precursorSig: { fontSize: '11px', color: '#6366f1', textTransform: 'capitalize', marginBottom: '2px' },
  precursorMode: { fontSize: '11px', color: '#71717a' },
  precursorEvidence: { fontSize: '10px', color: '#52525b', marginTop: '2px' },
  analogName: { fontSize: '11px', color: '#a78bfa', fontFamily: 'monospace' },
  analogRate: { fontSize: '12px', color: '#d4d4d8' },
  analogNarrative: { fontSize: '11px', color: '#a1a1aa', lineHeight: 1.6, marginTop: '4px' },
  dangerBadge: { fontSize: '11px', padding: '2px 6px', borderRadius: '4px', background: 'rgba(239,68,68,0.15)', color: '#ef4444' },
  gapWarning: { fontSize: '11px', color: '#fca5a5', background: 'rgba(239,68,68,0.08)', padding: '4px 8px', borderRadius: '3px' },
  advCard: { background: '#111113', border: '1px solid #27272a', borderRadius: '4px', padding: '8px' },
  advCategory: { fontSize: '10px', color: '#f97316', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '4px' },
  advDanger: { fontSize: '11px', color: '#d4d4d8', lineHeight: 1.5, marginBottom: '4px' },
  advMissed: { fontSize: '10px', color: '#52525b', fontStyle: 'italic', lineHeight: 1.5 },
  confSmall: { fontSize: '11px', color: '#a1a1aa' },
  ensRow: { display: 'flex', justifyContent: 'space-between', fontSize: '11px', padding: '2px 0' },
  ensLabel: { color: '#71717a' },
  ensGreen: { color: '#22c55e', fontWeight: 600 },
  ensYellow: { color: '#eab308', fontWeight: 600 },
  ensOrange: { color: '#f97316', fontWeight: 600 },
  riskBadge: { fontSize: '11px', color: '#a78bfa' },
  unknownItem: { fontSize: '11px', color: '#71717a', lineHeight: 1.5, paddingLeft: '8px', borderLeft: '2px solid #3f3f46' },
}
