import React, { useState } from 'react'
import { useStore } from '../store/useStore'
import { runAgentSim, type AgentSimResult } from '../api/client'

export function AgentSimPanel() {
  const { analysis, graphData, selectedNodeId } = useStore()
  const graphId = analysis?.graph_id ?? graphData?.id
  const nodes = graphData?.nodes ?? []

  const [stressNode, setStressNode] = useState(selectedNodeId ?? '')
  const [nSteps, setNSteps] = useState(8)
  const [initialStress, setInitialStress] = useState(0.9)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<AgentSimResult | null>(null)
  const [expandedStep, setExpandedStep] = useState<number | null>(null)

  async function handleRun() {
    if (!graphId || !stressNode) return
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const r = await runAgentSim(graphId, stressNode, nSteps, initialStress)
      setResult(r)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Simulation failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={s.wrap}>
      <div style={s.title}>Agent Simulation</div>

      <label style={s.label}>Stress node</label>
      <select style={s.select} value={stressNode} onChange={e => setStressNode(e.target.value)}>
        <option value="">— select node —</option>
        {nodes.map(n => (
          <option key={n.id} value={n.id}>{n.label}</option>
        ))}
      </select>

      <div style={s.row}>
        <div style={s.field}>
          <label style={s.label}>Steps</label>
          <input
            type="number" min={1} max={20}
            style={s.input} value={nSteps}
            onChange={e => setNSteps(Number(e.target.value))}
          />
        </div>
        <div style={s.field}>
          <label style={s.label}>Initial stress</label>
          <input
            type="number" min={0.1} max={1} step={0.1}
            style={s.input} value={initialStress}
            onChange={e => setInitialStress(Number(e.target.value))}
          />
        </div>
      </div>

      <button style={s.btn} onClick={handleRun} disabled={loading || !graphId || !stressNode}>
        {loading ? 'Simulating...' : 'Run Simulation'}
      </button>

      {error && <div style={s.error}>{error}</div>}

      {result && (
        <>
          <div style={result.cascade_contained ? s.contained : s.notContained}>
            {result.cascade_contained ? 'Cascade contained' : 'Cascade NOT contained'}
          </div>

          <div style={s.narrative}>{result.narrative}</div>

          <div style={s.sectionTitle}>Summary</div>
          <div style={s.grid}>
            <div style={s.statCard}>
              <div style={s.statVal}>{result.final_failed_nodes.length}</div>
              <div style={s.statLbl}>Failed nodes</div>
            </div>
            <div style={s.statCard}>
              <div style={s.statVal}>{result.final_stabilised_nodes.length}</div>
              <div style={s.statLbl}>Stabilised</div>
            </div>
            <div style={s.statCard}>
              <div style={s.statVal}>{result.agents.filter((a: { active: boolean }) => a.active).length}</div>
              <div style={s.statLbl}>Agents active</div>
            </div>
            <div style={s.statCard}>
              <div style={s.statVal}>{result.reversion_opportunities.length}</div>
              <div style={s.statLbl}>Reversion opps</div>
            </div>
          </div>

          {result.reversion_opportunities.length > 0 && (
            <>
              <div style={s.sectionTitle}>Reversion opportunities</div>
              {result.reversion_opportunities.map((o: string, i: number) => (
                <div key={i} style={s.opp}>{o}</div>
              ))}
            </>
          )}

          <div style={s.sectionTitle}>Steps ({result.n_steps} total)</div>
          {result.steps.map((step: { step: number; events: string[]; failed_nodes: string[]; agent_actions: Record<string, string> }) => (
            <div key={step.step} style={s.stepCard}>
              <div
                style={s.stepHeader}
                onClick={() => setExpandedStep(expandedStep === step.step ? null : step.step)}
              >
                <span style={s.stepNum}>Step {step.step}</span>
                <span style={s.stepMeta}>
                  {step.failed_nodes.length > 0 && (
                    <span style={s.failBadge}>{step.failed_nodes.length} failed</span>
                  )}
                  {step.events.length} events
                </span>
              </div>
              {expandedStep === step.step && (
                <div style={s.stepBody}>
                  {step.events.map((ev: string, i: number) => (
                    <div key={i} style={s.event}>{ev}</div>
                  ))}
                </div>
              )}
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
    flexShrink: 0,
  },
  label: { fontSize: '11px', color: '#71717a', marginBottom: '2px', display: 'block' },
  select: {
    width: '100%',
    background: '#18181b',
    border: '1px solid #27272a',
    borderRadius: '4px',
    color: '#e2e2e6',
    padding: '5px 8px',
    fontSize: '12px',
  },
  row: { display: 'flex', gap: '8px' },
  field: { flex: 1, display: 'flex', flexDirection: 'column' },
  input: {
    background: '#18181b',
    border: '1px solid #27272a',
    borderRadius: '4px',
    color: '#e2e2e6',
    padding: '4px 8px',
    fontSize: '12px',
    width: '100%',
    boxSizing: 'border-box',
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
  error: {
    background: '#450a0a',
    color: '#fca5a5',
    fontSize: '11px',
    padding: '6px 8px',
    borderRadius: '4px',
  },
  contained: {
    background: '#052e16',
    color: '#86efac',
    fontSize: '12px',
    padding: '6px 10px',
    borderRadius: '4px',
    fontWeight: 600,
  },
  notContained: {
    background: '#450a0a',
    color: '#fca5a5',
    fontSize: '12px',
    padding: '6px 10px',
    borderRadius: '4px',
    fontWeight: 600,
  },
  narrative: { fontSize: '11px', color: '#a1a1aa', lineHeight: 1.6 },
  sectionTitle: {
    fontSize: '11px',
    color: '#52525b',
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
    marginTop: '4px',
  },
  grid: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px' },
  statCard: {
    background: '#18181b',
    border: '1px solid #27272a',
    borderRadius: '4px',
    padding: '8px',
    textAlign: 'center',
  },
  statVal: { fontSize: '20px', color: '#e2e2e6', fontWeight: 700 },
  statLbl: { fontSize: '10px', color: '#52525b', marginTop: '2px' },
  opp: {
    background: '#0c1a2e',
    border: '1px solid #1e3a5f',
    borderRadius: '4px',
    color: '#93c5fd',
    fontSize: '11px',
    padding: '4px 8px',
  },
  stepCard: {
    background: '#18181b',
    border: '1px solid #27272a',
    borderRadius: '4px',
    overflow: 'hidden',
  },
  stepHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '6px 8px',
    cursor: 'pointer',
    userSelect: 'none',
  },
  stepNum: { fontSize: '12px', color: '#d4d4d8', fontWeight: 600 },
  stepMeta: { fontSize: '11px', color: '#52525b', display: 'flex', gap: '6px', alignItems: 'center' },
  failBadge: {
    background: '#450a0a',
    color: '#fca5a5',
    fontSize: '10px',
    padding: '1px 5px',
    borderRadius: '3px',
  },
  stepBody: { padding: '0 8px 8px', borderTop: '1px solid #27272a' },
  event: { fontSize: '11px', color: '#a1a1aa', padding: '3px 0', lineHeight: 1.4 },
}
