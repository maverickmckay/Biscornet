import { create } from 'zustand'
import type { GraphAnalysis, GraphData, CollapsePoint } from '../api/client'

interface AppState {
  analysis: GraphAnalysis | null
  graphData: GraphData | null
  selectedNodeId: string | null
  selectedCollapsePoint: CollapsePoint | null
  stressLevel: number           // 0-1, drives visual pressure overlay
  loading: boolean
  error: string | null

  setAnalysis: (a: GraphAnalysis) => void
  setGraphData: (g: GraphData) => void
  selectNode: (id: string | null) => void
  setStressLevel: (v: number) => void
  setLoading: (v: boolean) => void
  setError: (msg: string | null) => void
}

export const useStore = create<AppState>((set, get) => ({
  analysis: null,
  graphData: null,
  selectedNodeId: null,
  selectedCollapsePoint: null,
  stressLevel: 0,
  loading: false,
  error: null,

  setAnalysis: (analysis) => set({ analysis }),
  setGraphData: (graphData) => set({ graphData }),

  selectNode: (id) => {
    const { analysis } = get()
    const cp = analysis?.collapse_points.find(p => p.node_id === id) ?? null
    set({ selectedNodeId: id, selectedCollapsePoint: cp })
  },

  setStressLevel: (stressLevel) => set({ stressLevel }),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),
}))
