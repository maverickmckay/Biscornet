import axios from 'axios'

export const api = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' },
})

// Attach JWT token from localStorage to every request
api.interceptors.request.use(config => {
  const token = localStorage.getItem('nnm_token')
  if (token) {
    config.headers = config.headers ?? {}
    config.headers['Authorization'] = `Bearer ${token}`
  }
  return config
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

export interface ImplicitAssumption {
  description: string
  affected_node_ids: string[]
  scan_type: 'structural' | 'textual'
  confidence: number
}

export interface GraphAnalysis {
  graph_id: string
  graph_name: string
  collapse_points: CollapsePoint[]
  hidden_assumptions: string[]
  implicit_assumptions: ImplicitAssumption[]
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
      confidence: number
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

export interface DistStats {
  mean: number
  median: number
  p5: number
  p95: number
  std: number
}

export interface MonteCarloResult {
  n_trials: number
  simulation_type: string
  node_id: string
  collapse_probability: number
  reroute_score: DistStats
  cascade_depth: DistStats
  time_to_failure_hours: DistStats | null
  histogram_reroute: { bin_start: number; bin_end: number; count: number }[]
  recommendations: string[]
}

// ---------------------------------------------------------------------------
// Graph API
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Phase 2: Document extraction
// ---------------------------------------------------------------------------

export const uploadDocument = (file: File, graphId?: string): Promise<{
  graph_id: string
  entity_count: number
  relation_count: number
  assumption_sentences: string[]
  confidence_notes: string[]
  analysis?: GraphAnalysis
}> => {
  const fd = new FormData()
  fd.append('file', file)
  if (graphId) fd.append('graph_id', graphId)
  const endpoint = graphId ? '/documents/extract' : '/documents/extract-and-analyze'
  return api.post(endpoint, fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }).then(r => r.data)
}

// ---------------------------------------------------------------------------
// Phase 2: Workflow log ingestion
// ---------------------------------------------------------------------------

export const uploadLog = (file: File): Promise<{
  bottleneck_labels: string[]
  load_updates: Record<string, number>
  summary_stats: Record<string, unknown>
  warnings: string[]
}> => {
  const fd = new FormData()
  fd.append('file', file)
  return api.post('/logs/ingest', fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }).then(r => r.data)
}

export const calibrateFromLog = (graphId: string, file: File): Promise<{
  calibrated_nodes: string[]
  bottleneck_labels: string[]
  analysis: GraphAnalysis
}> => {
  const fd = new FormData()
  fd.append('file', file)
  return api.post(`/logs/ingest-and-calibrate/${graphId}`, fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }).then(r => r.data)
}

// ---------------------------------------------------------------------------
// Phase 2: Monte Carlo
// ---------------------------------------------------------------------------

export const runMonteCarlo = (
  graphId: string,
  simulationType: string,
  nodeId: string,
  nTrials: number = 500,
  seed?: number,
  params?: Record<string, unknown>,
): Promise<MonteCarloResult> =>
  api.post(`/graphs/${graphId}/monte-carlo`, {
    simulation_type: simulationType,
    node_id: nodeId,
    n_trials: nTrials,
    seed: seed ?? null,
    params: params ?? {},
  }).then(r => r.data)

// ---------------------------------------------------------------------------
// Scenario simulation
// ---------------------------------------------------------------------------

export const simulate = (graphId: string, simulationType: string, nodeId: string, params?: Record<string, unknown>) =>
  api.post(`/graphs/${graphId}/simulate`, {
    simulation_type: simulationType,
    node_id: nodeId,
    params: params ?? {},
  }).then(r => r.data)

// ---------------------------------------------------------------------------
// SSE live events
// ---------------------------------------------------------------------------

export function createEventSource(): EventSource {
  return new EventSource('/api/v1/events')
}

// ---------------------------------------------------------------------------
// Phase 3: Auth
// ---------------------------------------------------------------------------

export interface User {
  id: string
  email: string
  name: string
  is_admin: boolean
}

export const login = (email: string, password: string): Promise<{ token: string; user: User }> =>
  api.post('/auth/login', { email, password }).then(r => r.data)

export const register = (email: string, name: string, password: string): Promise<{ token: string; user: User }> =>
  api.post('/auth/register', { email, name, password }).then(r => r.data)

export const getMe = (): Promise<User> =>
  api.get('/auth/me').then(r => r.data)

// ---------------------------------------------------------------------------
// Phase 3: Market intelligence
// ---------------------------------------------------------------------------

export interface PriceSignal {
  ticker: string
  price: number | null
  price_change_30d: number | null
  trend: string
}

export interface SECSignal {
  entity_name: string
  cik: string
  risk_level: string
  material_event_count: number
  latest_form: string | null
  latest_date: string | null
}

export interface NewsSignal {
  entity_name: string
  article_count: number
  sentiment_score: number
  top_headlines: string[]
}

export interface MarketIntel {
  node_id: string
  node_label: string
  market_risk_delta: number
  narrative: string
  sec_signal: SECSignal | null
  news_signal: NewsSignal | null
  price_signal: PriceSignal | null
}

export const enrichAnalysis = (
  graphId: string,
  userMappings?: Record<string, { ticker?: string; cik?: string }>,
  maxEntities = 20,
): Promise<{ graph_id: string; market_intelligence: MarketIntel[]; enriched_collapse_points: unknown[] }> =>
  api.post(`/market/graphs/${graphId}/enrich`, {
    user_mappings: userMappings ?? null,
    max_entities: maxEntities,
  }).then(r => r.data)

// ---------------------------------------------------------------------------
// Phase 3: Agent simulation
// ---------------------------------------------------------------------------

export interface AgentSimResult {
  n_steps: number
  simulation_type: string
  initial_stress_node: string
  agents: { id: string; name: string; type: string; active: boolean; resources: number; final_node: string; actions_taken: [number, string, string][] }[]
  steps: { step: number; node_stresses: Record<string, number>; agent_actions: Record<string, string>; failed_nodes: string[]; events: string[] }[]
  final_failed_nodes: string[]
  final_stabilised_nodes: string[]
  reversion_opportunities: string[]
  cascade_contained: boolean
  narrative: string
}

export const runAgentSim = (
  graphId: string,
  stressNodeId: string,
  nSteps = 8,
  initialStress = 0.9,
  seed?: number,
): Promise<AgentSimResult> =>
  api.post(`/agent-sim/graphs/${graphId}/run`, {
    stress_node_id: stressNodeId,
    n_steps: nSteps,
    initial_stress: initialStress,
    seed: seed ?? null,
  }).then(r => r.data)

// ---------------------------------------------------------------------------
// Phase 3: Feedback / outcome recording
// ---------------------------------------------------------------------------

export interface OutcomeRecord {
  id: string
  recorded_at: string
  current_weights: Record<string, number>
}

export const submitOutcome = (payload: {
  graph_id: string
  node_id: string
  node_label: string
  action_taken: string
  outcome: string
  nnm_score: number
  notes?: string
}): Promise<OutcomeRecord> =>
  api.post('/feedback/outcomes', payload).then(r => r.data)

export const getWeights = (): Promise<Record<string, number>> =>
  api.get('/feedback/weights').then(r => r.data.weights)

export const getOutcomes = (graphId?: string): Promise<{ outcomes: unknown[] }> =>
  api.get('/feedback/outcomes', { params: graphId ? { graph_id: graphId } : {} }).then(r => r.data)
