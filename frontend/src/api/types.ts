export type Role = 'io' | 'analyst'

export interface Me { id: string; name: string; email: string; role: Role; vasp_id: string | null; vasp_name: string | null }

export interface Wallet { chain: string; address: string; victim_tx_hash: string | null }

export interface Contribution { factor: string; label: string; signal: number; weight: number; points: number }
export interface WhatIf { scenario: string; confidence: number; delta: number }
export interface Explain {
  contributions: Contribution[]; path_factor: number; what_if: WhatIf[]; formula: string
  evidence: { transactions: number; intermediaries: number; hops: number; chains: string[] }
}

export interface Candidate {
  id: string; vasp_id: string | null; vasp_name: string; role: 'off_ramp' | 'on_ramp'; chain: string; address: string
  address_kind: string; hops: number; value_share: number; value_usd: number; confidence: number; actionability: number
  rank_score: number; funds_status: string; signals: Record<string, number>; reasons: string[]; evidence_tx: string[]; path: string[]
  explain: Explain | null
}

export interface RiskAxis { key: string; label: string; score: number; why: string }
export interface Typology { code: string; name: string; severity: 'medium' | 'high' | 'critical'; detail: string; addresses: string[]; tx: string[] }
export interface Analysis {
  risk?: { overall: number; level: 'low' | 'medium' | 'high' | 'critical'; axes: RiskAxis[] }
  typologies?: Typology[]
  integrity?: Record<string, unknown>
  narratives?: Record<string, { text: string; source: string; model: string | null }>
}

export interface Job {
  id: string; status: 'queued' | 'running' | 'done' | 'failed'; params: Record<string, number>
  progress: { message?: string; nodes?: number; edges?: number; seconds?: number; notes?: string[]; seed_out_usd?: number; candidates?: number }
  chain_heights: Record<string, number | null>; analysis: Analysis | null; started_at: string | null; finished_at: string | null; error: string | null
}

export interface CaseLinkT { peer_case_id: string; peer_case_no: number; peer_state: string | null; peer_fir: string; chain: string; address: string; kind: string; entity: string | null }

export interface AlertT { id: string; case_id?: string; case_no?: number; type: string; severity: 'info' | 'medium' | 'high'; message: string; data: Record<string, unknown>; read: boolean; created_at: string }

export interface CaseSummary {
  id: string; case_no: number; title: string | null; fir_no: string; ncrp_id: string | null; police_station: string | null
  state: string | null; fraud_type: string | null; fraud_time: string; amount_inr: number | null; status: string
  is_demo: boolean; created_at: string; wallets: Wallet[]; top_vasp?: Candidate | null; vasps?: string[]; links?: number; monitoring: boolean
}

export interface CaseDetail extends Omit<CaseSummary, 'links' | 'top_vasp'> {
  job: Job | null; done_job: Job | null; candidates: Candidate[]; links: CaseLinkT[]; alerts: AlertT[]
}

export interface GNode { data: { id: string; address: string; chain: string; kind: string; entity: string | null; depth: number; value_share: number; value_usd: number; label_source: string | null; label_tier: string | null; flags: string[]; reasons: string[]; stats: Record<string, unknown> } }
export interface GEdge { data: { id: string; source: string; target: string; chain: string; to_chain: string; direction: string; asset: string; amount_usd: number; value_share: number; tx_hashes: string[]; tx_count: number; first_ts: string } }
export interface Graph { job_id: string | null; nodes: GNode[]; edges: GEdge[] }

export interface TimelineEvent {
  ts: string; kind: 'case' | 'system' | 'onchain' | 'alert' | 'evidence' | 'legal'; title: string; detail: string
  data?: { chain?: string; to_chain?: string; direction?: string; tx?: string[]; tx_count?: number; amount_usd?: number; edge_id?: string; severity?: string }
}

export interface ReqT {
  id: string; case_id: string; case_no: number; fir_no: string; state: string | null; vasp_name: string; vasp_id: string | null
  type: string; legal_basis: string; chain: string; addresses: string[]; body_md: string; status: string; sahyog_ref: string | null
  report_id: string | null; created_at: string; sent_at: string | null
  linked_cases: { id: string; case_no: number; fir_no: string; state: string | null }[]
  translations: Record<string, string>
  reply: { outcome: string; account_ref: string | null; frozen_amount_usd: number | null; note: string | null; replied_at: string } | null
}

export interface Stats {
  cases: number; attributed: number; traced_usd: number; median_trace_seconds: number | null; links: number
  requests_sent: number; requests_confirmed: number; unread_alerts: number; verified_labels: number
  top_vasps: { vasp: string; cases: number; value_usd: number }[]
}

export interface AlertRules {
  large_transfer_usd: number; new_activity: boolean; score_increase_points: number; new_relationship: boolean
  risk_patterns: boolean; min_risk_level: 'low' | 'medium' | 'high' | 'critical'
}

export interface AiStatus { provider: string; configured: boolean; model: string; translate_model: string; used_for_attribution: boolean }

export interface Health {
  status: string; demo_mode: boolean; labels: number; chains: Record<string, boolean>; db: string
  ai?: { provider: string; configured: boolean }; bridge_tracker?: string | null; version?: string
}
