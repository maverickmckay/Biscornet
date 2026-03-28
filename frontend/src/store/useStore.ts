import { create } from 'zustand'
import type { GraphAnalysis, GraphData, CollapsePoint } from '../api/client'
import { createEventSource } from '../api/client'

interface AppState {
  analysis: GraphAnalysis | null
  graphData: GraphData | null
  selectedNodeId: string | null
  selectedCollapsePoint: CollapsePoint | null
  stressLevel: number
  loading: boolean
  error: string | null
  liveConnected: boolean
  showImport: boolean

  setAnalysis: (a: GraphAnalysis) => void
  setGraphData: (g: GraphData) => void
  selectNode: (id: string | null) => void
  setStressLevel: (v: number) => void
  setLoading: (v: boolean) => void
  setError: (msg: string | null) => void
  connectLive: () => void
  disconnectLive: () => void
  setShowImport: (v: boolean) => void
}

let _es: EventSource | null = null

export const useStore = create<AppState>((set, get) => ({
  analysis: null,
  graphData: null,
  selectedNodeId: null,
  selectedCollapsePoint: null,
  stressLevel: 0,
  loading: false,
  error: null,
  liveConnected: false,
  showImport: false,

  setAnalysis: (analysis) => {
    const { selectedNodeId } = get()
    const cp = selectedNodeId
      ? (analysis?.collapse_points.find(p => p.node_id === selectedNodeId) ?? null)
      : null
    set({ analysis, selectedCollapsePoint: cp })
  },

  setGraphData: (graphData) => set({ graphData }),

  selectNode: (id) => {
    const { analysis } = get()
    const cp = analysis?.collapse_points.find(p => p.node_id === id) ?? null
    set({ selectedNodeId: id, selectedCollapsePoint: cp })
  },

  setStressLevel: (stressLevel) => set({ stressLevel }),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),
  setShowImport: (showImport) => set({ showImport }),

  connectLive: () => {
    if (_es) return
    _es = createEventSource()
    _es.addEventListener('analysis_updated', (e: MessageEvent) => {
      try {
        const payload = JSON.parse(e.data)
        // Payload has graph_id + summary; trigger a lightweight state note
        // (full analysis refresh would require a re-fetch)
        const { analysis } = get()
        if (analysis && payload.graph_id === analysis.graph_id) {
          set({ analysis: { ...analysis, summary: payload.summary ?? analysis.summary } })
        }
      } catch { /* ignore malformed events */ }
    })
    _es.onerror = () => {
      _es?.close()
      _es = null
      set({ liveConnected: false })
    }
    set({ liveConnected: true })
  },

  disconnectLive: () => {
    _es?.close()
    _es = null
    set({ liveConnected: false })
  },
}))
