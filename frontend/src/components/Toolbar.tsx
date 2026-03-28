/**
 * Toolbar — top bar with load/upload actions and graph metadata.
 */
import React, { useRef } from 'react'
import { useStore } from '../store/useStore'
import { fetchDemo, uploadGraphJson, uploadGraphCsv, analyzeGraph } from '../api/client'

export function Toolbar() {
  const { setAnalysis, setGraphData, setLoading, setError, loading } = useStore()
  const jsonRef = useRef<HTMLInputElement>(null)
  const csvRef = useRef<HTMLInputElement>(null)

  async function runDemo() {
    setLoading(true)
    setError(null)
    try {
      const analysis = await fetchDemo()
      setAnalysis(analysis)
      // Also fetch the graph structure for the map
      const { fetchGraph } = await import('../api/client')
      const g = await fetchGraph('demo')
      setGraphData(g)
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? e?.message ?? 'Demo failed')
    } finally {
      setLoading(false)
    }
  }

  async function handleJsonUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setLoading(true)
    setError(null)
    try {
      const g = await uploadGraphJson(file)
      setGraphData(g)
      const analysis = await analyzeGraph(g.id)
      setAnalysis(analysis)
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? err?.message ?? 'Upload failed')
    } finally {
      setLoading(false)
      e.target.value = ''
    }
  }

  async function handleCsvUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    const name = file.name.replace(/\.csv$/i, '')
    setLoading(true)
    setError(null)
    try {
      const g = await uploadGraphCsv(file, name)
      setGraphData(g)
      const analysis = await analyzeGraph(g.id)
      setAnalysis(analysis)
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? err?.message ?? 'Upload failed')
    } finally {
      setLoading(false)
      e.target.value = ''
    }
  }

  return (
    <div style={s.bar}>
      <span style={s.brand}>No Next Move</span>
      <div style={s.actions}>
        <button style={s.btn} onClick={runDemo} disabled={loading}>
          {loading ? 'Loading…' : 'Load demo'}
        </button>
        <button style={s.btn} onClick={() => jsonRef.current?.click()} disabled={loading}>
          Upload JSON
        </button>
        <button style={s.btn} onClick={() => csvRef.current?.click()} disabled={loading}>
          Upload CSV
        </button>
        <input ref={jsonRef} type="file" accept=".json" onChange={handleJsonUpload} style={{ display: 'none' }} />
        <input ref={csvRef} type="file" accept=".csv" onChange={handleCsvUpload} style={{ display: 'none' }} />
      </div>
    </div>
  )
}

const s: Record<string, React.CSSProperties> = {
  bar: {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
    padding: '10px 16px',
    background: '#111113',
    borderBottom: '1px solid #27272a',
  },
  brand: { fontSize: '15px', fontWeight: 700, color: '#e2e2e6', letterSpacing: '-0.02em', flex: 1 },
  actions: { display: 'flex', gap: '8px' },
  btn: {
    fontSize: '12px',
    padding: '5px 12px',
    background: '#27272a',
    color: '#e2e2e6',
    border: '1px solid #3f3f46',
    borderRadius: '5px',
    cursor: 'pointer',
  },
}
