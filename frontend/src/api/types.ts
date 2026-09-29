export type Role = 'io' | 'analyst' | 'vasp'

export interface Me { id: string; name: string; email: string; role: Role; vasp_id: string | null; vasp_name: string | null }

export interface Wallet { chain: string; address: string; victim_tx_hash: string | null }

export interface Candidate {
  id: string; vasp_id: string | null; vasp_name: string; role: 'off_ramp' | 'on_ramp'; chain: string; address: string
  address_kind: string; hops: number; value_share: number; value_usd: number; confidence: number; actionability: number
  rank_score: number; funds_status: string; signals: Record<string, number>; reasons: string[]; evidence_tx: string[]; path: string[]
}

export interface Job {
  id: string; status: 'queued' | 'running' | 'done' | 'failed'; params: Record<string, number>
  progress: { message?: string; nodes?: number; edges?: number; seconds?: number; notes?: string[]; seed_out_usd?: number; candidates?: number }
  chain_heights: Record<string, number | null>; started_at: string | null; finished_at: string | null; error: string | null
}

export interface CaseLinkT { peer_case_id: string; peer_case_no: number; peer_state: string | null; peer_fir: string; chain: string; address: string; kind: string; entity: string | null }

export interface AlertT { id: string; case_id?: string; case_no?: number; type: string; severity: 'info' | 'medium' | 'high'; message: string; data: Record<string, unknown>; read: boolean; created_at: string }

export interface CaseSummary {
  id: string; case_no: number; title: string | null; fir_no: string; ncrp_id: string | null; police_station: string | null
  state: string | null; fraud_type: string | null; fraud_time: string; amount_inr: number | null; status: string
  is_demo: boolean; created_at: string; wallets: Wallet[]; top_vasp?: Candidate | null; links?: number
}

export interface CaseDetail extends Omit<CaseSummary, 'links' | 'top_vasp'> {
  job: Job | null; done_job: Job | null; candidates: Candidate[]; links: CaseLinkT[]; alerts: AlertT[]
}

export interface GNode { data: { id: string; address: string; chain: string; kind: string; entity: string | null; depth: number; value_share: number; value_usd: number; label_source: string | null; label_tier: string | null; flags: string[]; reasons: string[]; stats: Record<string, unknown> } }
export interface GEdge { data: { id: string; source: string; target: string; chain: string; direction: string; asset: string; amount_usd: number; value_share: number; tx_hashes: string[]; tx_count: number; first_ts: string } }
export interface Graph { job_id: string | null; nodes: GNode[]; edges: GEdge[] }

export interface ReqT {
  id: string; case_id: string; case_no: number; fir_no: string; state: string | null; vasp_name: string; vasp_id: string | null
  type: string; legal_basis: string; chain: string; addresses: string[]; body_md: string; status: string; sahyog_ref: string | null
  report_id: string | null; created_at: string; sent_at: string | null
  reply: { outcome: string; account_ref: string | null; frozen_amount_usd: number | null; note: string | null; replied_at: string } | null
}

export interface Stats {
  cases: number; attributed: number; traced_usd: number; median_trace_seconds: number | null; links: number
  requests_sent: number; requests_confirmed: number; unread_alerts: number; verified_labels: number
  top_vasps: { vasp: string; cases: number; value_usd: number }[]
}

export interface Health { status: string; demo_mode: boolean; labels: number; chains: Record<string, boolean>; db: string }
