/**
 * ImportPanel — unified import UI for all Phase 2 ingest types:
 *   - Graph JSON / CSV
 *   - Document (PDF/DOCX/TXT) → extract + analyze
 *   - Workflow log (CSV/JSON) → ingest
 */
import React, { useRef, useState } from 'react'
import { useStore } from '../store/useStore'
import {
  fetchDemo, uploadGraphJson, uploadGraphCsv, analyzeGraph,
  uploadDocument, uploadLog, calibrateFromLog,
} from '../api/client'

type Tab = 'graph' | 'document' | 'log'

function TabButton({ active, label, onClick }: { active: boolean; label: string; onClick: () => void }) {
  return (
    <button
      style={{ ...s.tab, ...(active ? s.tabActive : {}) }}
      onClick={onClick}
    >
      {label}
    </button>
  )
}

export function ImportPanel({ onClose }: { onClose: () => void }) {
  const { setAnalysis, setGraphData, setLoading, setError, loading, graphData } = useStore()
  const [tab, setTab] = useState<Tab>('graph')
  const [graphIdForCalibrate, setGraphIdForCalibrate] = useState(graphData?.id ?? '')
  const jsonRef = useRef<HTMLInputElement>(null)
  const csvRef = useRef<HTMLInputElement>(null)
  const docRef = useRef<HTMLInputElement>(null)
  const logRef = useRef<HTMLInputElement>(null)
  const logCalRef = useRef<HTMLInputElement>(null)

  async function runDemo() {
    setLoading(true); setError(null)
    try {
      const analysis = await fetchDemo()
      setAnalysis(analysis)
      const { fetchGraph } = await import('../api/client')
      setGraphData(await fetchGraph('demo'))
    } catch (e: any) { setError(e?.message ?? 'Demo failed') }
    finally { setLoading(false) }
  }

  async function handleJson(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]; if (!file) return
    setLoading(true); setError(null)
    try {
      const g = await uploadGraphJson(file)
      setGraphData(g)
      setAnalysis(await analyzeGraph(g.id))
    } catch (e: any) { setError(e?.message ?? 'Failed') }
    finally { setLoading(false); e.target.value = '' }
  }

  async function handleCsv(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]; if (!file) return
    setLoading(true); setError(null)
    try {
      const g = await uploadGraphCsv(file, file.name.replace(/\.csv$/i, ''))
      setGraphData(g)
      setAnalysis(await analyzeGraph(g.id))
    } catch (e: any) { setError(e?.message ?? 'Failed') }
    finally { setLoading(false); e.target.value = '' }
  }

  async function handleDocument(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]; if (!file) return
    setLoading(true); setError(null)
    try {
      const result = await uploadDocument(file)
      if (result.analysis) {
        setAnalysis(result.analysis)
        // Fetch the newly created graph for the map
        const { fetchGraph } = await import('../api/client')
        setGraphData(await fetchGraph(result.graph_id))
      }
    } catch (e: any) { setError(e?.message ?? 'Failed') }
    finally { setLoading(false); e.target.value = '' }
  }

  async function handleLog(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]; if (!file) return
    setLoading(true); setError(null)
    try {
      const result = await uploadLog(file)
      alert(`Log analysed: ${result.summary_stats?.unique_activities} activities, ${result.bottleneck_labels?.length} bottlenecks detected.`)
    } catch (e: any) { setError(e?.message ?? 'Failed') }
    finally { setLoading(false); e.target.value = '' }
  }

  async function handleLogCalibrate(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]; if (!file) return
    if (!graphIdForCalibrate) { setError('Enter a graph ID to calibrate'); return }
    setLoading(true); setError(null)
    try {
      const result = await calibrateFromLog(graphIdForCalibrate, file)
      if (result.analysis) setAnalysis(result.analysis)
    } catch (e: any) { setError(e?.message ?? 'Failed') }
    finally { setLoading(false); e.target.value = '' }
  }

  return (
    <div style={s.overlay}>
      <div style={s.modal}>
        <div style={s.modalHeader}>
          <span style={s.modalTitle}>Import</span>
          <button style={s.closeBtn} onClick={onClose}>✕</button>
        </div>

        <div style={s.tabs}>
          <TabButton active={tab === 'graph'} label="Graph" onClick={() => setTab('graph')} />
          <TabButton active={tab === 'document'} label="Document" onClick={() => setTab('document')} />
          <TabButton active={tab === 'log'} label="Workflow Log" onClick={() => setTab('log')} />
        </div>

        <div style={s.body}>
          {tab === 'graph' && (
            <div style={s.section}>
              <p style={s.desc}>Load a graph from JSON, CSV edge list, or run the built-in demo.</p>
              <div style={s.btns}>
                <button style={s.actionBtn} onClick={runDemo} disabled={loading}>Load demo</button>
                <button style={s.actionBtn} onClick={() => jsonRef.current?.click()} disabled={loading}>Upload JSON</button>
                <button style={s.actionBtn} onClick={() => csvRef.current?.click()} disabled={loading}>Upload CSV</button>
              </div>
              <input ref={jsonRef} type="file" accept=".json" onChange={handleJson} style={{ display: 'none' }} />
              <input ref={csvRef} type="file" accept=".csv" onChange={handleCsv} style={{ display: 'none' }} />
              <p style={s.hint}>CSV columns: source_id, target_id, edge_type, [source_label, target_label, source_type, target_type, weight, reliability, latency]</p>
            </div>
          )}

          {tab === 'document' && (
            <div style={s.section}>
              <p style={s.desc}>Extract dependency, approval, and assumption relationships from a document. Supported: PDF, DOCX, TXT, MD.</p>
              <div style={s.btns}>
                <button style={s.actionBtn} onClick={() => docRef.current?.click()} disabled={loading}>
                  {loading ? 'Extracting…' : 'Upload document'}
                </button>
              </div>
              <input ref={docRef} type="file" accept=".pdf,.docx,.doc,.txt,.md" onChange={handleDocument} style={{ display: 'none' }} />
              <p style={s.hint}>The extractor uses regex patterns to find: depends on, approved by, governed by, assumes, contingent on, escalates to, funds, blocks, substitutes for.</p>
            </div>
          )}

          {tab === 'log' && (
            <div style={s.section}>
              <p style={s.desc}>Analyse a workflow event log to detect bottlenecks and calibrate node load values.</p>
              <div style={s.btns}>
                <button style={s.actionBtn} onClick={() => logRef.current?.click()} disabled={loading}>Analyse log only</button>
              </div>
              <input ref={logRef} type="file" accept=".csv,.json" onChange={handleLog} style={{ display: 'none' }} />

              <div style={s.divider} />
              <p style={s.desc}>Calibrate an existing graph with log data:</p>
              <input
                type="text"
                placeholder="Graph ID"
                value={graphIdForCalibrate}
                onChange={e => setGraphIdForCalibrate(e.target.value)}
                style={s.textInput}
              />
              <div style={s.btns}>
                <button style={s.actionBtn} onClick={() => logCalRef.current?.click()} disabled={loading || !graphIdForCalibrate}>
                  Upload log and calibrate
                </button>
              </div>
              <input ref={logCalRef} type="file" accept=".csv,.json" onChange={handleLogCalibrate} style={{ display: 'none' }} />
              <p style={s.hint}>Log columns (flexible): task/activity, actor/user, duration_s/duration_h, status, timestamp</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

const s: Record<string, React.CSSProperties> = {
  overlay: { position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 100, display: 'flex', alignItems: 'center', justifyContent: 'center' },
  modal: { background: '#18181b', border: '1px solid #3f3f46', borderRadius: '8px', width: '420px', maxHeight: '80vh', display: 'flex', flexDirection: 'column' },
  modalHeader: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', borderBottom: '1px solid #27272a' },
  modalTitle: { fontSize: '14px', fontWeight: 600, color: '#e2e2e6' },
  closeBtn: { background: 'transparent', border: 'none', color: '#6b7280', fontSize: '16px', cursor: 'pointer' },
  tabs: { display: 'flex', borderBottom: '1px solid #27272a' },
  tab: { flex: 1, padding: '8px', fontSize: '12px', background: 'transparent', border: 'none', color: '#6b7280', cursor: 'pointer' },
  tabActive: { color: '#e2e2e6', borderBottom: '2px solid #3b82f6' },
  body: { padding: '16px', overflowY: 'auto', flex: 1 },
  section: { display: 'flex', flexDirection: 'column', gap: '10px' },
  desc: { fontSize: '12px', color: '#9ca3af', lineHeight: 1.5 },
  btns: { display: 'flex', gap: '8px', flexWrap: 'wrap' },
  actionBtn: { fontSize: '12px', padding: '6px 14px', background: '#27272a', color: '#e2e2e6', border: '1px solid #3f3f46', borderRadius: '5px', cursor: 'pointer' },
  hint: { fontSize: '10px', color: '#52525b', lineHeight: 1.5, fontFamily: 'monospace' },
  divider: { height: '1px', background: '#27272a', margin: '4px 0' },
  textInput: { fontSize: '12px', background: '#111113', color: '#e2e2e6', border: '1px solid #3f3f46', borderRadius: '4px', padding: '5px 8px', width: '100%' },
}
