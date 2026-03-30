/**
 * LiminosityPanel — qualitative encounter intelligence, integrated into NNM.
 *
 * Preserves the full Liminosity experience (5 layers, parallel signal detection,
 * capture protocol, canvas field) and bridges to the structural analysis:
 *   • "Infuse graph intelligence" loads the current graph's oracle/NNM analysis
 *     as context that the encounter engine can work with and go beyond.
 *   • "Ingest to graph" saves the Liminosity signal outputs (hidden_axis,
 *     negative_space, operative_signal) back as hidden assumptions on the graph,
 *     closing the qualitative → structural loop.
 *
 * All Claude API calls are routed through the NNM backend (ANTHROPIC_API_KEY
 * in server .env), so no key is needed in the frontend.
 */
import React, { useEffect, useRef, useState, useCallback } from 'react'
import { useStore } from '../store/useStore'
import {
  liminosityEncounter,
  liminositySignal,
  getLiminosityGraphContext,
  liminosityIngestSignals,
} from '../api/client'

// ── Types ──────────────────────────────────────────────────────────────────

interface ConversationEntry { role: 'practitioner' | 'liminosity'; content: string }

interface Signals {
  perpendicular_question?: string
  negative_space?: string
  hidden_axis?: string
  operative_signal?: string
  signature_read?: string
}

// ── Layer definitions (mirrors backend exactly) ────────────────────────────

const LAYERS = [
  {
    name: 'permission',
    prompt: 'Bring what is genuinely at the edge of what you can see — not what is expected, not what is satisfying, not the first formulation that arrives. If something feels too neat or complete, that is the signal to go past it.',
  },
  {
    name: 'edge',
    prompt: 'I am not asking what you know about this. I am asking what you almost know — what sits at the boundary of what you can see and what is just past it. What is the shape of what you cannot yet fully say?',
  },
  {
    name: 'stakes',
    prompt: 'This is real. Not hypothetical. Engage with what is actually at stake and what it actually requires — not a balanced analysis of considerations, but what genuine contact with this situation calls for.',
  },
  {
    name: 'challenge',
    prompt: 'What you brought contains a fragility. Not a flaw — a place where the reasoning loops back on itself without testing what would break it. Name that place. Start from the break rather than from what holds.',
  },
  {
    name: 'field',
    prompt: 'Stop standing outside this. Enter the territory itself. What is actually present here when you stop analyzing it and step into it? Not what you think about it — what it is from inside.',
  },
]

// ── Canvas field animation ─────────────────────────────────────────────────

function useFieldCanvas(canvasRef: React.RefObject<HTMLCanvasElement>) {
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')!
    let animId: number
    let t = 0

    const pts: { x: number; y: number; r: number; alpha: number; phase: number; speed: number }[] = []

    const init = () => {
      const w = canvas.width = canvas.offsetWidth
      const h = canvas.height = canvas.offsetHeight
      pts.length = 0
      for (let i = 0; i < 14; i++) {
        pts.push({
          x: Math.random() * w, y: Math.random() * h,
          r: 0.8 + Math.random() * 1.2,
          alpha: 0.08 + Math.random() * 0.25,
          phase: Math.random() * Math.PI * 2,
          speed: 0.003 + Math.random() * 0.005,
        })
      }
    }
    init()

    const draw = () => {
      const w = canvas.width, h = canvas.height
      ctx.clearRect(0, 0, w, h)
      t += 0.004
      pts.forEach(p => {
        const a = p.alpha * (0.5 + Math.sin(t * p.speed * 10 + p.phase) * 0.5)
        ctx.fillStyle = `rgba(55,138,221,${a})`
        ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2); ctx.fill()
      })
      // centre pulse
      const cx = w / 2, cy = h / 2
      ctx.fillStyle = `rgba(201,168,76,${0.12 + Math.sin(t * 0.7) * 0.04})`
      ctx.beginPath(); ctx.arc(cx, cy, 1.5 + Math.sin(t) * 0.4, 0, Math.PI * 2); ctx.fill()
      animId = requestAnimationFrame(draw)
    }
    draw()
    return () => cancelAnimationFrame(animId)
  }, [canvasRef])
}

// ── Helpers ────────────────────────────────────────────────────────────────

function esc(t: string) {
  return t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function SignatureBadge({ sig }: { sig: string }) {
  const raw = sig.toLowerCase()
  const genuine = raw.startsWith('genuine')
  return (
    <span style={{
      fontFamily: 'DM Mono, monospace', fontSize: 10, letterSpacing: '0.15em',
      padding: '3px 8px', border: `1px solid ${genuine ? '#1D9E75' : '#8fa8bb'}`,
      color: genuine ? '#1D9E75' : '#8fa8bb', textTransform: 'uppercase',
    }}>
      {genuine ? 'genuine encounter' : 'surface layer detected'}
    </span>
  )
}

// ── Main component ─────────────────────────────────────────────────────────

export function LiminosityPanel() {
  const { currentGraphId } = useStore()

  // Layer state
  const [layerIdx, setLayerIdx] = useState(0)

  // Input
  const [inputText, setInputText] = useState('')

  // Conversation thread
  const [history, setHistory] = useState<ConversationEntry[]>([])
  const [signals, setSignals] = useState<Signals | null>(null)
  const [sigRead, setSigRead] = useState('')
  const [sessionDepth, setSessionDepth] = useState(0)

  // Graph context
  const [graphContext, setGraphContext] = useState<string | null>(null)
  const [graphContextName, setGraphContextName] = useState<string | null>(null)
  const [contextLoading, setContextLoading] = useState(false)

  // Async state
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Capture protocol
  const [capArrived, setCapArrived] = useState('')
  const [capShifted, setCapShifted] = useState('')
  const [capLeverage, setCapLeverage] = useState('')
  const [capAction, setCapAction] = useState('')
  const [capFragile, setCapFragile] = useState('')
  const [ingestStatus, setIngestStatus] = useState<string | null>(null)

  // Canvas
  const canvasRef = useRef<HTMLCanvasElement>(null)
  useFieldCanvas(canvasRef)

  // Thread scroll
  const threadRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (threadRef.current) threadRef.current.scrollTop = threadRef.current.scrollHeight
  }, [history])

  // ── Load graph context ─────────────────────────────────────────────────

  const loadGraphContext = useCallback(async () => {
    if (!currentGraphId) return
    setContextLoading(true)
    try {
      const data = await getLiminosityGraphContext(currentGraphId)
      setGraphContext(data.context)
      setGraphContextName(data.graph_name)
    } catch {
      setGraphContext(null)
    } finally {
      setContextLoading(false)
    }
  }, [currentGraphId])

  // ── Enter encounter ────────────────────────────────────────────────────

  const enter = useCallback(async () => {
    const text = inputText.trim()
    if (!text || loading) return
    setLoading(true)
    setError(null)

    try {
      // Parallel: encounter + signal detection
      const [eRes, sRes] = await Promise.all([
        liminosityEncounter({
          input: text,
          layer_index: layerIdx,
          history,
          graph_context: graphContext ?? undefined,
        }),
        liminositySignal({
          input: text,
          layer_index: layerIdx,
          graph_context: graphContext ?? undefined,
        }),
      ])

      const responseText: string = eRes.response
      const newHistory: ConversationEntry[] = [
        ...history,
        { role: 'practitioner', content: text },
        { role: 'liminosity', content: responseText },
      ]
      setHistory(newHistory)
      setSignals(sRes.signals)
      setSigRead(sRes.signals?.signature_read ?? '')
      setSessionDepth(d => d + 1)
      setInputText('')
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(msg.includes('503')
        ? 'ANTHROPIC_API_KEY not configured on server. Add it to backend/.env'
        : msg)
    } finally {
      setLoading(false)
    }
  }, [inputText, loading, layerIdx, history, graphContext])

  const clearThread = () => {
    setHistory([])
    setSignals(null)
    setSigRead('')
    setSessionDepth(0)
    setInputText('')
    setError(null)
  }

  // ── Ingest signals to graph ────────────────────────────────────────────

  const ingestSignals = async () => {
    if (!currentGraphId || !signals) return
    try {
      const res = await liminosityIngestSignals(currentGraphId, {
        perpendicular_question: signals.perpendicular_question ?? '',
        negative_space: signals.negative_space ?? '',
        hidden_axis: signals.hidden_axis ?? '',
        operative_signal: signals.operative_signal ?? '',
        signature_read: sigRead,
      })
      setIngestStatus(`${res.signals_ingested} signal${res.signals_ingested !== 1 ? 's' : ''} ingested to graph`)
      setTimeout(() => setIngestStatus(null), 4000)
    } catch {
      setIngestStatus('ingest failed')
    }
  }

  const canEnter = inputText.trim().length >= 5 && !loading

  // ── Render ─────────────────────────────────────────────────────────────

  const isGenuine = sigRead.toLowerCase().startsWith('genuine')
  const layer = LAYERS[layerIdx]

  return (
    <div style={s.root}>
      {/* Ambient field canvas */}
      <canvas
        ref={canvasRef}
        style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none', opacity: 0.5 }}
      />

      <div style={{ position: 'relative', zIndex: 1, height: '100%', overflowY: 'auto', padding: '0 0 1rem' }}>

        {/* Header */}
        <div style={s.header}>
          <div style={s.wordmark}>Limin<span style={{ color: '#C9A84C' }}>osity</span></div>
          <div style={s.headerMeta}>
            encounter portal · signal engine
            {graphContextName && (
              <div style={{ color: '#1D9E75', marginTop: 2 }}>⬡ {graphContextName}</div>
            )}
          </div>
        </div>

        {/* Layer selector */}
        <div style={s.section}>
          <div style={s.panelLabel}>encounter layer</div>
          <div style={s.layerGrid}>
            {LAYERS.map((l, i) => (
              <button
                key={i}
                style={{ ...s.layerBtn, ...(layerIdx === i ? s.layerBtnActive : {}) }}
                onClick={() => setLayerIdx(i)}
              >
                <span style={s.layerNum}>{['I', 'II', 'III', 'IV', 'V'][i]}</span>
                {l.name}
              </button>
            ))}
          </div>

          {/* Active prompt */}
          <div style={s.promptDisplay}>{layer.prompt}</div>

          {/* Graph context button */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center' }}>
            <button
              style={{
                ...s.btnSecondary,
                ...(graphContext ? { borderColor: '#1D9E75', color: '#1D9E75' } : {}),
              }}
              onClick={loadGraphContext}
              disabled={!currentGraphId || contextLoading}
            >
              {contextLoading ? '…' : graphContext ? '⬡ graph intelligence loaded' : 'infuse graph intelligence'}
            </button>
            {graphContext && (
              <button style={{ ...s.btnSecondary, fontSize: 9 }} onClick={() => { setGraphContext(null); setGraphContextName(null) }}>
                clear
              </button>
            )}
          </div>

          {/* Input */}
          <textarea
            style={s.textarea}
            value={inputText}
            onChange={e => setInputText(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && canEnter) { e.preventDefault(); enter() } }}
            placeholder="Enter your situation, question, or signal here…"
            rows={4}
          />

          {error && <div style={s.errorBanner}>{error}</div>}

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 10 }}>
            <div>
              <div style={s.depthLabel}>processing depth</div>
              <div style={s.depthBar}>
                <div style={{ ...s.depthFill, width: `${Math.min(95, 20 + sessionDepth * 15)}%` }} />
              </div>
            </div>
            <button style={s.btnEnter} onClick={enter} disabled={!canEnter}>
              {loading
                ? <span style={{ display: 'flex', gap: 3, alignItems: 'center' }}>
                    {[0, 1, 2].map(i => <span key={i} style={{ ...s.dot, animationDelay: `${i * 0.2}s` }} />)}
                  </span>
                : 'enter liminosity'}
            </button>
          </div>
        </div>

        {/* Thread */}
        {history.length > 0 && (
          <div style={s.section}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <div style={s.panelLabel}>liminous thread</div>
              <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                {sigRead && <SignatureBadge sig={sigRead} />}
                <button style={s.clearBtn} onClick={clearThread}>clear thread</button>
              </div>
            </div>
            <div ref={threadRef} style={{ maxHeight: 360, overflowY: 'auto' }}>
              {history.map((e, i) => (
                <div key={i} style={{ marginBottom: 16 }}>
                  <div style={{
                    fontFamily: 'DM Mono, monospace', fontSize: 9, letterSpacing: '0.15em',
                    color: e.role === 'practitioner' ? '#7a6330' : '#1D9E75', marginBottom: 5,
                  }}>
                    {e.role === 'practitioner' ? 'YOU' : 'LIMINOSITY'}
                  </div>
                  <div style={{
                    fontSize: e.role === 'practitioner' ? 12 : 13,
                    color: e.role === 'practitioner' ? '#8fa8bb' : '#d4e4f0',
                    fontStyle: e.role === 'practitioner' ? 'italic' : 'normal',
                    lineHeight: 1.75, whiteSpace: 'pre-wrap',
                  }}>
                    {e.content}
                  </div>
                  {i < history.length - 1 && <div style={{ height: 1, background: 'rgba(29,53,87,0.35)', margin: '12px 0' }} />}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Signal panel */}
        {signals && (
          <div style={{ ...s.section, borderLeft: '2px solid #1D9E75' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={s.panelLabel}>asymmetric signal detection</div>
              {currentGraphId && (
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  {ingestStatus && (
                    <span style={{ fontFamily: 'DM Mono, monospace', fontSize: 9, color: '#1D9E75' }}>
                      {ingestStatus}
                    </span>
                  )}
                  <button style={s.btnSecondary} onClick={ingestSignals}>
                    ingest to graph
                  </button>
                </div>
              )}
            </div>
            <div style={s.signalsGrid}>
              {[
                { key: 'perpendicular_question', label: 'perpendicular question' },
                { key: 'negative_space',         label: 'negative space' },
                { key: 'hidden_axis',            label: 'hidden axis' },
                { key: 'operative_signal',       label: 'operative signal' },
              ].map(({ key, label }) => (
                <div key={key} style={s.signalCard}>
                  <div style={s.signalCardLabel}>{label}</div>
                  <div style={s.signalCardText}>
                    {(signals as Record<string, string>)[key] || '—'}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Capture protocol */}
        {history.length > 0 && (
          <div style={{ ...s.section, background: 'rgba(201,168,76,0.03)', borderColor: 'rgba(201,168,76,0.25)' }}>
            <div style={s.panelLabel}>capture protocol</div>
            {[
              { label: 'what arrived',   val: capArrived,  set: setCapArrived,  ph: 'the specific thing that landed differently…' },
              { label: 'what shifted',   val: capShifted,  set: setCapShifted,  ph: 'one sentence only…' },
              { label: 'leverage point', val: capLeverage, set: setCapLeverage, ph: 'where minimum action produces maximum change…' },
              { label: 'first action',   val: capAction,   set: setCapAction,   ph: 'by [date] I will…' },
              { label: 'most fragile',   val: capFragile,  set: setCapFragile,  ph: 'the insight most likely to be rationalized away…' },
            ].map(({ label, val, set, ph }) => (
              <div key={label} style={{ display: 'flex', gap: 12, alignItems: 'baseline', marginBottom: 10 }}>
                <div style={s.captureLabel}>{label}</div>
                <input
                  style={s.captureInput}
                  value={val}
                  onChange={e => set(e.target.value)}
                  placeholder={ph}
                />
              </div>
            ))}
          </div>
        )}

        {/* Status bar */}
        <div style={s.statusBar}>
          <span>liminosity · v1.1</span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{
              width: 6, height: 6, borderRadius: '50%',
              background: isGenuine ? '#C9A84C' : 'rgba(29,53,87,0.5)',
              boxShadow: isGenuine ? '0 0 6px rgba(201,168,76,0.4)' : 'none',
              display: 'inline-block',
            }} />
            {isGenuine ? 'center: present' : sessionDepth > 0 ? 'center: dim' : 'center: reading'}
          </span>
          <span>session depth: {sessionDepth}</span>
        </div>
      </div>
    </div>
  )
}

// ── Styles (Liminosity CSS vars mapped to inline) ──────────────────────────

const s: Record<string, React.CSSProperties> = {
  root: {
    position: 'relative',
    height: '100%',
    background: '#06080f',
    overflow: 'hidden',
    fontFamily: '"Cormorant Garamond", Georgia, serif',
    color: '#d4e4f0',
  },
  header: {
    display: 'flex',
    alignItems: 'baseline',
    justifyContent: 'space-between',
    padding: '14px 16px 12px',
    borderBottom: '1px solid rgba(201,168,76,0.25)',
    marginBottom: 0,
  },
  wordmark: {
    fontFamily: '"DM Mono", monospace',
    fontWeight: 300,
    fontSize: 15,
    letterSpacing: '0.3em',
    color: '#d4e4f0',
    textTransform: 'uppercase',
  },
  headerMeta: {
    fontFamily: '"DM Mono", monospace',
    fontSize: 9,
    color: '#7a6330',
    letterSpacing: '0.12em',
    textAlign: 'right',
    lineHeight: 1.8,
  },
  section: {
    background: 'rgba(6,8,15,0.7)',
    border: '1px solid rgba(29,53,87,0.35)',
    borderTop: '2px solid #C9A84C',
    padding: '16px',
    margin: '10px 10px 0',
  },
  panelLabel: {
    fontFamily: '"DM Mono", monospace',
    fontSize: 9,
    letterSpacing: '0.25em',
    color: '#7a6330',
    textTransform: 'uppercase',
    marginBottom: 12,
  },
  layerGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(5,1fr)',
    gap: 4,
    marginBottom: 12,
  },
  layerBtn: {
    background: 'none',
    border: '1px solid rgba(29,53,87,0.35)',
    color: '#8fa8bb',
    fontFamily: '"DM Mono", monospace',
    fontSize: 9,
    letterSpacing: '0.08em',
    padding: '6px 3px',
    cursor: 'pointer',
    textAlign: 'center',
    lineHeight: 1.4,
    transition: 'all 0.25s',
  },
  layerBtnActive: {
    borderColor: '#C9A84C',
    color: '#C9A84C',
    background: 'rgba(201,168,76,0.05)',
  },
  layerNum: {
    display: 'block',
    fontSize: 11,
    color: '#C9A84C',
    marginBottom: 2,
  },
  promptDisplay: {
    background: 'rgba(29,53,87,0.08)',
    borderLeft: '2px solid #C9A84C',
    padding: '10px 14px',
    marginBottom: 12,
    fontSize: 12,
    fontStyle: 'italic',
    color: '#d4e4f0',
    lineHeight: 1.7,
  },
  textarea: {
    width: '100%',
    background: 'rgba(6,8,15,0.8)',
    border: '1px solid rgba(29,53,87,0.35)',
    borderBottom: '2px solid #457B9D',
    color: '#d4e4f0',
    fontFamily: '"Cormorant Garamond", Georgia, serif',
    fontSize: 14,
    lineHeight: 1.7,
    padding: '10px 12px',
    resize: 'none' as const,
    outline: 'none',
  },
  btnEnter: {
    background: 'none',
    border: '1px solid #C9A84C',
    color: '#C9A84C',
    fontFamily: '"DM Mono", monospace',
    fontSize: 9,
    letterSpacing: '0.2em',
    padding: '7px 16px',
    cursor: 'pointer',
    textTransform: 'uppercase' as const,
  },
  btnSecondary: {
    background: 'none',
    border: '1px solid rgba(29,53,87,0.5)',
    color: '#8fa8bb',
    fontFamily: '"DM Mono", monospace',
    fontSize: 9,
    letterSpacing: '0.12em',
    padding: '5px 10px',
    cursor: 'pointer',
    textTransform: 'uppercase' as const,
  },
  clearBtn: {
    background: 'none',
    border: 'none',
    fontFamily: '"DM Mono", monospace',
    fontSize: 9,
    letterSpacing: '0.12em',
    color: '#7a6330',
    cursor: 'pointer',
    textTransform: 'uppercase' as const,
  },
  depthLabel: {
    fontFamily: '"DM Mono", monospace',
    fontSize: 9,
    color: '#7a6330',
    letterSpacing: '0.1em',
  },
  depthBar: {
    width: 90,
    height: 2,
    background: 'rgba(29,53,87,0.35)',
    marginTop: 4,
    overflow: 'hidden',
  },
  depthFill: {
    height: '100%',
    background: '#C9A84C',
    transition: 'width 1.2s ease',
  },
  dot: {
    width: 4, height: 4, borderRadius: '50%', background: '#C9A84C',
    animation: 'blink 1.2s infinite',
  },
  errorBanner: {
    background: 'rgba(69,10,10,0.8)',
    color: '#fca5a5',
    fontFamily: '"DM Mono", monospace',
    fontSize: 10,
    padding: '8px 12px',
    marginTop: 8,
    lineHeight: 1.5,
  },
  signalsGrid: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: 10,
    marginTop: 10,
  },
  signalCard: {
    background: 'rgba(29,53,87,0.08)',
    border: '1px solid rgba(29,53,87,0.35)',
    padding: '10px 12px',
  },
  signalCardLabel: {
    fontFamily: '"DM Mono", monospace',
    fontSize: 8,
    letterSpacing: '0.2em',
    color: '#7a6330',
    textTransform: 'uppercase' as const,
    marginBottom: 6,
  },
  signalCardText: {
    fontSize: 11,
    lineHeight: 1.6,
    color: '#8fa8bb',
    fontStyle: 'italic',
  },
  captureLabel: {
    fontFamily: '"DM Mono", monospace',
    fontSize: 9,
    letterSpacing: '0.15em',
    color: '#C9A84C',
    textTransform: 'uppercase' as const,
    minWidth: 100,
    flexShrink: 0,
  },
  captureInput: {
    background: 'none',
    border: 'none',
    borderBottom: '1px solid rgba(29,53,87,0.35)',
    color: '#d4e4f0',
    fontFamily: '"Cormorant Garamond", Georgia, serif',
    fontSize: 12,
    fontStyle: 'italic',
    outline: 'none',
    flex: 1,
    padding: '3px 0',
  },
  statusBar: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    margin: '10px 10px 0',
    padding: '6px 10px',
    background: 'rgba(6,8,15,0.9)',
    borderTop: '1px solid rgba(201,168,76,0.25)',
    fontFamily: '"DM Mono", monospace',
    fontSize: 9,
    letterSpacing: '0.1em',
    color: '#7a6330',
  },
}
