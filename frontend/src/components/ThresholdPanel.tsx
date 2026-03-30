import React, { useState } from 'react'
import { useStore } from '../store/useStore'
import { getThreshold, bootstrapTelemetry } from '../api/client'

type TStatus = 'stable' | 'drifting' | 'approaching' | 'critical' | 'exceeded'

interface TrajectoryPoint {
  hours_from_now: number
  projected_load: number
  projected_reliability: number
  confidence: number
}

interface ProximityScore {
  node_label: string
  current_load: number
  current_reliability: number
  current_stress: number
  load_headroom: number
  load_rate_per_hour: number
  hours_to_failure: number | null
  status: TStatus
  confidence: number
  alert_message: string | null
  trajectory: TrajectoryPoint[]
}

interface ThresholdResult {
  graph_id: string
  node_count: number
  proximity_scores: Record<string, ProximityScore>
}

const STATUS_COLOR: Record<TStatus, string> = {
  stable: '#22c55e',
  drifting: '#eab308',
  approaching: '#f97316',
  critical: '#ef4444',
  exceeded: '#dc2626',
}

const STATUS_BG: Record<TStatus, string> = {
  stable: '#052e16',
  drifting: '#422006',
  approaching: '#431407',
  critical: '#450a0a',
  exceeded: '#3b0a0a',
}

function Gauge({ value, max = 1, color }: { value: number; max?: number; color: string }) {
  const pct = Math.min(100, (value / max) * 100)
  return (
    <div style={{ background: '#1c1c1f', borderRadius: 4, height: 6, width: '100%', overflow: 'hidden' }}>
      <div style={{ width: `${pct}%`, height: '100%', background: color, transition: 'width 0.4s ease', borderRadius: 4 }} />
    </div>
  )
}

function Sparkline({ trajectory }: { trajectory: TrajectoryPoint[] }) {
  if (!trajectory.length) return null
  const W = 160
  const H = 36
  const loads = trajectory.map(t => t.projected_load)
  const minL = Math.min(...loads, 0)
  const maxL = Math.max(...loads, 1)
  const range = maxL - minL || 1

  const pts = trajectory.map((t, i) => {
    const x = (i / (trajectory.length - 1 || 1)) * W
    const y = H - ((t.projected_load - minL) / range) * H
    return `${x},${y}`
  })

  const dangerLine = H - ((0.85 - minL) / range) * H

  return (
    <svg width={W} height={H} style={{ display: 'block' }}>
      {dangerLine > 0 && dangerLine < H && (
        <line x1={0} y1={dangerLine} x2={W} y2={dangerLine}
          stroke="#ef4444" strokeWidth={1} strokeDasharray="3 3" opacity={0.5} />
      )}
      <polyline
        points={pts.join(' ')}
        fill="none"
        stroke="#3b82f6"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {trajectory.map((t, i) => {
        const x = (i / (trajectory.length - 1 || 1)) * W
        const y = H - ((t.projected_load - minL) / range) * H
        return (
          <circle key={i} cx={x} cy={y} r={2}
            fill={t.projected_load >= 0.85 ? '#ef4444' : '#3b82f6'} />
        )
      })}
    </svg>
  )
}

function NodeRow({ nodeId, score }: { nodeId: string; score: ProximityScore }) {
  const [expanded, setExpanded] = useState(false)
  const status = score.status as TStatus
  const color = STATUS_COLOR[status] ?? '#6b7280'
  const bg = STATUS_BG[status] ?? '#1c1c1f'

  return (
    <div style={{ borderBottom: '1px solid #27272a' }}>
      <button
        style={{ ...s.nodeRow, background: expanded ? '#18181b' : 'transparent' }}
        onClick={() => setExpanded(e => !e)}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flex: 1 }}>
          <span style={{
            display: 'inline-block', width: 8, height: 8,
            borderRadius: '50%', background: color, flexShrink: 0,
          }} />
          <span style={{ color: '#e2e2e6', fontSize: 12, fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {score.node_label}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
          {score.hours_to_failure !== null && score.hours_to_failure < 168 && (
            <span style={{ fontSize: 10, color: '#f97316', fontWeight: 600 }}>
              {score.hours_to_failure < 1
                ? `${Math.round(score.hours_to_failure * 60)}m`
                : `${score.hours_to_failure.toFixed(1)}h`}
            </span>
          )}
          <span style={{
            fontSize: 10, padding: '1px 5px', borderRadius: 3,
            background: bg, color: color, textTransform: 'uppercase', fontWeight: 700,
          }}>
            {status}
          </span>
          <span style={{ color: '#6b7280', fontSize: 11 }}>{expanded ? '▲' : '▼'}</span>
        </div>
      </button>

      {expanded && (
        <div style={{ padding: '8px 12px 12px', background: '#111113' }}>
          {score.alert_message && (
            <div style={{ fontSize: 11, color: '#fbbf24', marginBottom: 8, lineHeight: 1.4 }}>
              ⚠ {score.alert_message}
            </div>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 16px', marginBottom: 10 }}>
            <div>
              <div style={s.metaLabel}>Load</div>
              <Gauge value={score.current_load} color={score.current_load > 0.85 ? '#ef4444' : '#3b82f6'} />
              <div style={s.metaVal}>{(score.current_load * 100).toFixed(0)}%</div>
            </div>
            <div>
              <div style={s.metaLabel}>Reliability</div>
              <Gauge value={score.current_reliability} color={score.current_reliability < 0.3 ? '#ef4444' : '#22c55e'} />
              <div style={s.metaVal}>{(score.current_reliability * 100).toFixed(0)}%</div>
            </div>
            <div>
              <div style={s.metaLabel}>Stress</div>
              <Gauge value={score.current_stress} color={score.current_stress > 0.7 ? '#f97316' : '#6b7280'} />
              <div style={s.metaVal}>{(score.current_stress * 100).toFixed(0)}%</div>
            </div>
            <div>
              <div style={s.metaLabel}>Headroom</div>
              <Gauge value={score.load_headroom} color={score.load_headroom < 0.15 ? '#ef4444' : '#22c55e'} />
              <div style={s.metaVal}>{(score.load_headroom * 100).toFixed(0)}%</div>
            </div>
          </div>

          <div style={{ display: 'flex', gap: 16, marginBottom: 10, fontSize: 11, color: '#9ca3af' }}>
            <span>Rate: <span style={{ color: score.load_rate_per_hour > 0 ? '#f97316' : '#22c55e' }}>
              {score.load_rate_per_hour >= 0 ? '+' : ''}{(score.load_rate_per_hour * 100).toFixed(2)}%/h
            </span></span>
            <span>Confidence: <span style={{ color: '#e2e2e6' }}>{(score.confidence * 100).toFixed(0)}%</span></span>
          </div>

          {score.trajectory.length > 0 && (
            <div>
              <div style={{ fontSize: 10, color: '#6b7280', marginBottom: 4 }}>72h load trajectory</div>
              <Sparkline trajectory={score.trajectory} />
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#52525b', marginTop: 2 }}>
                <span>now</span>
                <span>+72h</span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function ThresholdPanel() {
  const { currentGraphId } = useStore()
  const [result, setResult] = useState<ThresholdResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [bootstrapping, setBootstrapping] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<TStatus | 'all'>('all')

  const run = async () => {
    if (!currentGraphId) return
    setLoading(true)
    setError(null)
    try {
      const data = await getThreshold(currentGraphId)
      setResult(data)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  const doBootstrap = async () => {
    if (!currentGraphId) return
    setBootstrapping(true)
    setError(null)
    try {
      await bootstrapTelemetry(currentGraphId)
      await run()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(msg)
      setBootstrapping(false)
    } finally {
      setBootstrapping(false)
    }
  }

  const scores = result?.proximity_scores ?? {}
  const allNodes = Object.entries(scores)
  const filtered = filter === 'all' ? allNodes : allNodes.filter(([, s]) => s.status === filter)

  // Sort by severity
  const ORDER: Record<string, number> = { exceeded: 0, critical: 1, approaching: 2, drifting: 3, stable: 4 }
  filtered.sort(([, a], [, b]) => (ORDER[a.status] ?? 5) - (ORDER[b.status] ?? 5))

  const counts = allNodes.reduce((acc, [, s]) => {
    acc[s.status] = (acc[s.status] ?? 0) + 1
    return acc
  }, {} as Record<string, number>)

  return (
    <div style={s.root}>
      <div style={s.header}>
        <span style={s.title}>Threshold Proximity</span>
        <div style={{ display: 'flex', gap: 6 }}>
          <button style={s.btnSecondary} onClick={doBootstrap} disabled={!currentGraphId || bootstrapping}>
            {bootstrapping ? '…' : 'Bootstrap'}
          </button>
          <button style={s.btn} onClick={run} disabled={!currentGraphId || loading}>
            {loading ? 'Scanning…' : 'Scan'}
          </button>
        </div>
      </div>

      {error && <div style={s.errorBanner}>{error}</div>}

      {!currentGraphId && (
        <div style={s.empty}>Select a graph to scan node thresholds.</div>
      )}

      {result && (
        <>
          {/* Status summary badges */}
          <div style={s.summaryRow}>
            {(['exceeded', 'critical', 'approaching', 'drifting', 'stable'] as TStatus[]).map(st => (
              counts[st] ? (
                <button
                  key={st}
                  style={{
                    ...s.badge,
                    background: filter === st ? STATUS_BG[st] : '#1c1c1f',
                    color: STATUS_COLOR[st],
                    border: filter === st ? `1px solid ${STATUS_COLOR[st]}` : '1px solid #27272a',
                  }}
                  onClick={() => setFilter(f => f === st ? 'all' : st)}
                >
                  {counts[st]} {st}
                </button>
              ) : null
            ))}
          </div>

          <div style={s.list}>
            {filtered.length === 0 && (
              <div style={s.empty}>No nodes match filter.</div>
            )}
            {filtered.map(([nodeId, score]) => (
              <NodeRow key={nodeId} nodeId={nodeId} score={score} />
            ))}
          </div>
        </>
      )}

      {!result && !loading && currentGraphId && (
        <div style={s.hint}>
          <div style={{ fontSize: 12, color: '#6b7280', lineHeight: 1.5 }}>
            Click <strong style={{ color: '#9ca3af' }}>Scan</strong> to compute threshold proximity
            from live telemetry. If no telemetry exists, click <strong style={{ color: '#9ca3af' }}>Bootstrap</strong> to
            synthesize readings from node attributes.
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
    padding: '4px 10px',
    background: '#1d4ed8',
    color: '#fff',
    border: 'none',
    borderRadius: 4,
    cursor: 'pointer',
  },
  btnSecondary: {
    fontSize: 11,
    padding: '4px 10px',
    background: '#27272a',
    color: '#9ca3af',
    border: 'none',
    borderRadius: 4,
    cursor: 'pointer',
  },
  errorBanner: {
    background: '#450a0a',
    color: '#fca5a5',
    fontSize: 11,
    padding: '6px 12px',
    flexShrink: 0,
  },
  summaryRow: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 6,
    padding: '8px 12px',
    borderBottom: '1px solid #27272a',
    flexShrink: 0,
  },
  badge: {
    fontSize: 10,
    padding: '2px 7px',
    borderRadius: 3,
    cursor: 'pointer',
    textTransform: 'uppercase' as const,
    fontWeight: 700,
    letterSpacing: '0.04em',
  },
  list: {
    flex: 1,
    overflowY: 'auto' as const,
  },
  nodeRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    width: '100%',
    padding: '9px 12px',
    border: 'none',
    cursor: 'pointer',
    textAlign: 'left' as const,
    gap: 8,
  },
  metaLabel: {
    fontSize: 10,
    color: '#6b7280',
    marginBottom: 3,
  },
  metaVal: {
    fontSize: 11,
    color: '#9ca3af',
    marginTop: 2,
  },
  empty: {
    padding: '20px 16px',
    fontSize: 12,
    color: '#52525b',
    textAlign: 'center' as const,
  },
  hint: {
    flex: 1,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
  },
}
