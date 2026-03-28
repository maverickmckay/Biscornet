import axios from 'axios'

export const api = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' },
})

export type NodeType =
  | 'person' | 'team' | 'function' | 'process_step' | 'system'
  | 'contract_clause' | 'vendor' | 'asset' | 'decision_gate'
  | 'assumption' | 'narrative'

export type ActionLabel =
  | 'fix' | 'monitor' | 'avoid' | 'hedge' | 'escalate'
  | 'stress_test' | 'exploit_lawful'

export type CollapseRisk = 'none' | 'low' | 'medium' | 'high' | 'critical'

export interface CollapsePoint {
  node_id: string
  node_label: string
  node_type: NodeType
  nnm_score: number
  hidden_constraint_score: number
  false_redundancy_score: number
  pressure_absorption_score: number
  reversion_potential_score: number
  collapse_risk: CollapseRisk
  action: ActionLabel
  action_rationale: string
  downstream_failures: string[]
  reversion_targets: string[]
  evidence: string[]
  confidence: number
}

export interface GraphAnalysis {
  graph_id: string
  graph_name: string
  collapse_points: CollapsePoint[]
  hidden_assumptions: string[]
  false_redundancies: { node_id: string; node_label: string; score: number }[]
  top_actions: { action: string; count: number }[]
  summary: string
  node_scores: Record<string, {
    node_id: string
    nnm_score: number
    hidden_constraint_score: number
    false_redundancy_score: number
    pressure_absorption_score: number
    reversion_potential_score: number
    collapse_risk: CollapseRisk
  }>
}

export interface GraphMeta {
  id: string
  name: string
  nodes: number
  edges: number
}

export interface GraphData {
  id: string
  name: string
  nodes: {
    id: string
    label: string
    node_type: NodeType
    attributes: {
      criticality: number
      replaceability: number
      load: number
      visibility: number
    }
  }[]
  edges: {
    id: string
    source: string
    target: string
    edge_type: string
    attributes: { weight: number; reliability: number; latency: number }
  }[]
}

export const fetchDemo = (): Promise<GraphAnalysis> =>
  api.get('/demo').then(r => r.data)

export const fetchGraphs = (): Promise<GraphMeta[]> =>
  api.get('/graphs').then(r => r.data)

export const fetchGraph = (id: string): Promise<GraphData> =>
  api.get(`/graphs/${id}`).then(r => r.data)

export const analyzeGraph = (id: string): Promise<GraphAnalysis> =>
  api.post(`/graphs/${id}/analyze`).then(r => r.data)

export const uploadGraphJson = (file: File): Promise<GraphData> => {
  const fd = new FormData()
  fd.append('file', file)
  return api.post('/graphs/json', fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }).then(r => r.data)
}

export const uploadGraphCsv = (file: File, name: string): Promise<GraphData> => {
  const fd = new FormData()
  fd.append('file', file)
  fd.append('name', name)
  return api.post('/graphs/csv', fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }).then(r => r.data)
}

export const simulate = (graphId: string, simulationType: string, nodeId: string, params?: Record<string, unknown>) =>
  api.post(`/graphs/${graphId}/simulate`, {
    simulation_type: simulationType,
    node_id: nodeId,
    params: params ?? {},
  }).then(r => r.data)
