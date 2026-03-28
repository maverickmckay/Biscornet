/**
 * MonteCarloPanel — shows probabilistic simulation results for a selected node.
 * Renders a mini SVG histogram (no chart library needed) and key stats.
 */
import React, { useState } from 'react'
import { runMonteCarlo, type MonteCarloResult } from '../api/client'
import { useStore } from '../store/useStore'

const SIM_TYPES = [
  { value: 'node_removal', label: 'Node removal' },
  { value: 'delay_injection', label: 'Delay injection' },
  { value: 'cost_shock', label: 'Cost shock' },
  { value: 'vendor_outage', label: 'Vendor outage' },
  { value: 'approval_blockage', label: 'Approval blockage' },
]

function Histogram({ bins }: { bins: MonteCarloResult['histogram_reroute'] }) {
  if (!bins || bins.length === 0) return null
  const maxCount = Math.max(...bins.map(b => b.count), 1)
  const W = 200
  const H = 60
  const barW = W / bins.length

  return (
    <svg width={W} height={H + 20} style={{ overflow: 'visible' }}>
      {bins.map((bin, i) => {
        const barH = (bin.count / maxCount) * H
        const x = i * barW
        const y = H - barH
        const midVal = ((bin.bin_start + bin.bin_end) / 2).toFixed(1)
        const colour = bin.bin_start < 0.3 ? '#ef4444' : bin.bin_start < 0.6 ? '#f97316' : '#22c55e'
        return (
          <g key={i}>
            <rect x={x + 1} y={y} width={barW - 2} height={barH} fill={colour} opacity={0.8} />
          </g>
        )
      })}
      <text x={0} y={H + 16} fontSize={9} fill="#6b7280">0</text>
      <text x={W - 6} y={H + 16} fontSize={9} fill="#6b7280">1</text>
      <text x={W / 2 - 20} y={H + 16} fontSize={9} fill="#6b7280">reroute score</text>
    </svg>
  )
}

function StatRow({ label, val }: { label: string; val?: number | null }) {
  if (val == null) return null
  return (
    <div style={s.statRow}>
      <span style={s.statLabel}>{label}</span>
      <span style={s.statVal}>{val.toFixed(3)}</span>
    </div>
  )
}

export function MonteCarloPanel() {
  const { selectedNodeId, graphData, analysis } = useStore()
  const [simType, setSimType] = useState('node_removal')
  const [nTrials, setNTrials] = useState(500)
  const [result, setResult] = useState<MonteCarloResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!selectedNodeId || !graphData) {
    return <div style={s.empty}>Select a node to run Monte Carlo simulation.</div>
  }

  const nodeLabel = graphData.nodes.find(n => n.id === selectedNodeId)?.label ?? selectedNodeId

  async function run() {
    if (!graphData) return
    setLoading(true)
    setError(null)
    try {
      const r = await runMonteCarlo(graphData.id, simType, selectedNodeId!, nTrials)
      setResult(r)
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? e?.message ?? 'Failed')
    } finally {
      setLoading(false)
    }
  }

  const collapsePct = result ? Math.round(result.collapse_probability * 100) : null

  return (
    <div style={s.panel}>
      <div style={s.header}>Monte Carlo — {nodeLabel}</div>

      <div style={s.controls}>
        <select
          value={simType}
          onChange={e => setSimType(e.target.value)}
          style={s.select}
        >
          {SIM_TYPES.map(t => (
            <option key={t.value} value={t.value}>{t.label}</option>
          ))}
        </select>
        <input
          type="number"
          min={50}
          max={2000}
          step={50}
          value={nTrials}
          onChange={e => setNTrials(Number(e.target.value))}
          style={s.input}
        />
        <button style={s.btn} onClick={run} disabled={loading}>
          {loading ? 'Running…' : `Run ${nTrials} trials`}
        </button>
      </div>

      {error && <div style={s.error}>{error}</div>}

      {result && (
        <div style={s.results}>
          <div style={{
            ...s.collapseBadge,
            background: collapsePct! > 50 ? '#450a0a' : collapsePct! > 20 ? '#431407' : '#052e16',
          }}>
            <span style={s.collapseNum}>{collapsePct}%</span>
            <span style={s.collapseLabel}>collapse probability</span>
          </div>

          <div style={s.section}>
            <div style={s.sectionTitle}>Reroute score distribution</div>
            <Histogram bins={result.histogram_reroute} />
          </div>

          <div style={s.section}>
            <div style={s.sectionTitle}>Reroute score</div>
            <StatRow label="Median" val={result.reroute_score?.median} />
            <StatRow label="p5" val={result.reroute_score?.p5} />
            <StatRow label="p95" val={result.reroute_score?.p95} />
            <StatRow label="Std dev" val={result.reroute_score?.std} />
          </div>

          {result.cascade_depth && (
            <div style={s.section}>
              <div style={s.sectionTitle}>Cascade depth</div>
              <StatRow label="Median" val={result.cascade_depth.median} />
              <StatRow label="p95" val={result.cascade_depth.p95} />
            </div>
          )}

          {result.time_to_failure_hours && (
            <div style={s.section}>
              <div style={s.sectionTitle}>Time to failure (hours)</div>
              <StatRow label="Median" val={result.time_to_failure_hours.median} />
              <StatRow label="p5" val={result.time_to_failure_hours.p5} />
            </div>
          )}

          {result.recommendations.length > 0 && (
            <div style={s.section}>
              <div style={s.sectionTitle}>Recommendations</div>
              {result.recommendations.map((r, i) => (
                <p key={i} style={s.rec}>{r}</p>
              ))}
            </div>
          )}

          <div style={s.meta}>{result.n_trials} trials · {result.simulation_type}</div>
        </div>
      )}
    </div>
  )
}

const s: Record<string, React.CSSProperties> = {
  panel: { padding: '12px', display: 'flex', flexDirection: 'column', gap: '10px', height: '100%', overflowY: 'auto' },
  header: { fontSize: '13px', fontWeight: 600, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.05em' },
  controls: { display: 'flex', gap: '6px', flexWrap: 'wrap', alignItems: 'center' },
  select: { fontSize: '11px', background: '#27272a', color: '#e2e2e6', border: '1px solid #3f3f46', borderRadius: '4px', padding: '4px 6px', flex: 1 },
  input: { fontSize: '11px', background: '#27272a', color: '#e2e2e6', border: '1px solid #3f3f46', borderRadius: '4px', padding: '4px 6px', width: '64px' },
  btn: { fontSize: '11px', padding: '4px 10px', background: '#3f3f46', color: '#e2e2e6', border: '1px solid #52525b', borderRadius: '4px', cursor: 'pointer', whiteSpace: 'nowrap' },
  error: { fontSize: '11px', color: '#fca5a5', background: '#450a0a', padding: '6px 8px', borderRadius: '4px' },
  results: { display: 'flex', flexDirection: 'column', gap: '10px' },
  collapseBadge: { display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '12px', borderRadius: '6px' },
  collapseNum: { fontSize: '28px', fontWeight: 700, color: '#f87171' },
  collapseLabel: { fontSize: '11px', color: '#9ca3af' },
  section: { display: 'flex', flexDirection: 'column', gap: '4px' },
  sectionTitle: { fontSize: '10px', fontWeight: 600, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.04em' },
  statRow: { display: 'flex', justifyContent: 'space-between', fontSize: '11px' },
  statLabel: { color: '#9ca3af' },
  statVal: { color: '#e2e2e6', fontVariantNumeric: 'tabular-nums' },
  rec: { fontSize: '11px', color: '#9ca3af', lineHeight: 1.5 },
  meta: { fontSize: '10px', color: '#52525b', textAlign: 'right' },
  empty: { fontSize: '12px', color: '#6b7280', padding: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' },
}
