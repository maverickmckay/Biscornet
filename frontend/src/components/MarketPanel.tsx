import React, { useState } from 'react'
import { useStore } from '../store/useStore'
import { enrichAnalysis, type MarketIntel } from '../api/client'

export function MarketPanel() {
  const { analysis, graphData } = useStore()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [intel, setIntel] = useState<MarketIntel[] | null>(null)

  const graphId = analysis?.graph_id ?? graphData?.id

  async function handleEnrich() {
    if (!graphId) return
    setLoading(true)
    setError(null)
    try {
      const result = await enrichAnalysis(graphId)
      setIntel(result.market_intelligence)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Market fetch failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={s.wrap}>
      <div style={s.header}>
        <span style={s.title}>Market Intelligence</span>
        <button style={s.btn} onClick={handleEnrich} disabled={loading || !graphId}>
          {loading ? 'Fetching...' : 'Enrich from SEC/Markets'}
        </button>
      </div>

      {error && <div style={s.error}>{error}</div>}

      {!intel && !loading && (
        <div style={s.empty}>
          Enriches collapse points with SEC EDGAR filings, news sentiment, and price signals.
          No API keys required.
        </div>
      )}

      {intel && intel.length === 0 && (
        <div style={s.empty}>No market-mapped nodes found. Add ticker/CIK to node metadata.</div>
      )}

      {intel && intel.map(item => (
        <div key={item.node_id} style={s.card}>
          <div style={s.cardHeader}>
            <span style={s.nodeLabel}>{item.node_label}</span>
            <span style={deltaStyle(item.market_risk_delta)}>
              {item.market_risk_delta > 0 ? '+' : ''}{(item.market_risk_delta * 100).toFixed(0)}% risk
            </span>
          </div>
          <div style={s.narrative}>{item.narrative}</div>

          {item.price_signal && (
            <div style={s.row}>
              <span style={s.label}>Price 30d</span>
              <span style={priceStyle(item.price_signal.price_change_30d)}>
                {item.price_signal.price_change_30d != null
                  ? `${item.price_signal.price_change_30d > 0 ? '+' : ''}${item.price_signal.price_change_30d.toFixed(1)}%`
                  : '—'}{' '}
                <span style={s.sub}>({item.price_signal.trend})</span>
              </span>
            </div>
          )}

          {item.sec_signal && item.sec_signal.material_event_count > 0 && (
            <div style={s.row}>
              <span style={s.label}>SEC events</span>
              <span style={s.value}>{item.sec_signal.material_event_count} ({item.sec_signal.latest_form})</span>
            </div>
          )}

          {item.news_signal && item.news_signal.article_count > 0 && (
            <div style={s.row}>
              <span style={s.label}>News mentions</span>
              <span style={s.value}>{item.news_signal.article_count}</span>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function deltaStyle(delta: number): React.CSSProperties {
  if (delta > 0.05) return { ...s.badge, background: '#450a0a', color: '#fca5a5' }
  if (delta < -0.05) return { ...s.badge, background: '#052e16', color: '#86efac' }
  return { ...s.badge, background: '#27272a', color: '#a1a1aa' }
}

function priceStyle(change: number | null): React.CSSProperties {
  if (change == null) return s.value
  if (change > 0) return { ...s.value, color: '#86efac' }
  if (change < 0) return { ...s.value, color: '#fca5a5' }
  return s.value
}

const s: Record<string, React.CSSProperties> = {
  wrap: {
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
    padding: '12px',
    overflowY: 'auto',
    height: '100%',
    boxSizing: 'border-box',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    flexShrink: 0,
  },
  title: {
    fontSize: '12px',
    color: '#a1a1aa',
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
  },
  btn: {
    fontSize: '11px',
    padding: '4px 10px',
    borderRadius: '4px',
    border: '1px solid #3b82f6',
    background: 'transparent',
    color: '#3b82f6',
    cursor: 'pointer',
  },
  error: {
    background: '#450a0a',
    color: '#fca5a5',
    fontSize: '11px',
    padding: '6px 8px',
    borderRadius: '4px',
  },
  empty: {
    color: '#52525b',
    fontSize: '12px',
    lineHeight: 1.6,
    padding: '8px 0',
  },
  card: {
    background: '#18181b',
    border: '1px solid #27272a',
    borderRadius: '6px',
    padding: '10px',
    display: 'flex',
    flexDirection: 'column',
    gap: '6px',
  },
  cardHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  nodeLabel: {
    fontSize: '13px',
    color: '#e2e2e6',
    fontWeight: 600,
  },
  badge: {
    fontSize: '11px',
    padding: '2px 6px',
    borderRadius: '4px',
    fontWeight: 600,
  },
  narrative: {
    fontSize: '11px',
    color: '#a1a1aa',
    lineHeight: 1.5,
  },
  row: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: '11px',
  },
  label: { color: '#52525b' },
  value: { color: '#d4d4d8' },
  sub: { color: '#52525b' },
}
