import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, openPdf, post } from '../api/client'
import type { Candidate, CaseDetail as CaseT, CaseLinkT, Graph, Job, ReqT } from '../api/types'
import TraceGraph, { KIND_STYLE } from '../components/graph/TraceGraph'
import SankeyChart from '../components/sankey/SankeyChart'
import { Badge, Button, Card, ConfBar, Empty, IST, StatusBadge, addrUrl, cx, pct, short, txUrl, usd } from '../components/ui'

interface ReportRow { id: string; sha256: string; created_at: string }

function groupLinks(links: CaseLinkT[]): CaseLinkT[][] {
  const m = new Map<string, CaseLinkT[]>()
  for (const l of links) m.set(l.peer_case_id, [...(m.get(l.peer_case_id) ?? []), l])
  return [...m.values()]
}

export default function CaseDetail() {
  const { id } = useParams()
  const [c, setC] = useState<CaseT | null>(null)
  const [graph, setGraph] = useState<Graph | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  const [tab, setTab] = useState<'graph' | 'sankey' | 'evidence'>('graph')
  const [sel, setSel] = useState<string | null>(null)
  const [reports, setReports] = useState<ReportRow[]>([])
  const [draft, setDraft] = useState<ReqT | null>(null)
  const [busy, setBusy] = useState('')

  const load = useCallback(async () => {
    const d = await api<CaseT>(`/cases/${id}`)
    setC(d); setJob(d.job)
    if (d.done_job) setGraph(await api<Graph>(`/cases/${id}/graph`))
    setReports(await api<ReportRow[]>(`/cases/${id}/reports`))
  }, [id])
  useEffect(() => { load() }, [load])

  // poll a running job
  useEffect(() => {
    if (!job || !['queued', 'running'].includes(job.status)) return
    const t = setInterval(async () => {
      const j = await api<Job>(`/jobs/${job.id}`)
      setJob(j)
      if (!['queued', 'running'].includes(j.status)) load()
    }, 1500)
    return () => clearInterval(t)
  }, [job, load])

  const nodes = useMemo(() => new Map(graph?.nodes.map((n) => [n.data.id, n.data]) ?? []), [graph])
  if (!c) return <Empty>Loading case…</Empty>
  const running = job && ['queued', 'running'].includes(job.status)
  const off = c.candidates.filter((x) => x.role === 'off_ramp')
  const on = c.candidates.filter((x) => x.role === 'on_ramp')
  const freeze = c.alerts.filter((a) => a.type === 'freeze_window')
  const selNode = sel ? nodes.get(sel) : null

  const retrace = async () => { setBusy('trace'); const r = await post<{ job_id: string }>(`/cases/${id}/trace`); setJob(await api<Job>(`/jobs/${r.job_id}`)); setBusy('') }
  const report = async () => { setBusy('report'); await post(`/cases/${id}/reports`); await load(); setBusy('') }
  const draftReq = async (cand: Candidate, type: string) => { setBusy(cand.id); setDraft(await post<ReqT>(`/cases/${id}/requests`, { candidate_id: cand.id, type })); setBusy('') }
  const send = async () => { if (!draft) return; setBusy('send'); setDraft(await post<ReqT>(`/requests/${draft.id}/send`)); await load(); setBusy('') }

  return (
    <>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted"><Link to="/cases" className="hover:text-ink">Cases</Link> / #{c.case_no} <StatusBadge status={c.status} /> {c.is_demo && <Badge>demo case</Badge>}</div>
          <h1 className="mt-1 font-serif text-3xl font-bold">{c.title ?? `FIR ${c.fir_no}`}</h1>
          <div className="mt-1 text-sm text-muted">FIR {c.fir_no} · NCRP {c.ncrp_id ?? '-'} · {c.police_station}, {c.state} · {c.fraud_type} · reported {IST(c.fraud_time)}{c.amount_inr ? ` · ₹${c.amount_inr.toLocaleString('en-IN')}` : ''}</div>
          <div className="mt-2 flex flex-wrap gap-2">{c.wallets.map((w) => (
            <a key={w.address} href={addrUrl(w.chain, w.address)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 rounded-lg border border-line bg-card px-2.5 py-1 text-xs hover:border-orange">
              <span className="h-2 w-2 rounded-full bg-orange" /><b>{w.chain}</b><span className="addr">{w.address}</span></a>))}</div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="ghost" onClick={retrace} disabled={!!running || busy === 'trace'}>Re-run trace</Button>
          <Button onClick={report} disabled={!c.done_job || busy === 'report'}>{busy === 'report' ? 'Sealing…' : 'Generate evidence report'}</Button>
        </div>
      </div>

      {running && (
        <Card className="mb-4 flex items-center gap-4 border-orange/40 bg-orange-tint p-4">
          <div className="h-3 w-3 animate-ping rounded-full bg-orange" />
          <div className="text-sm"><b>Tracing on live blockchain data…</b> {job?.progress?.message}</div>
        </Card>
      )}
      {job?.status === 'failed' && <Card className="mb-4 border-red/30 bg-red-tint p-4 text-sm text-red">Trace failed: {job.error}</Card>}

      {groupLinks(c.links).map((ls) => (
        <Card key={ls[0].peer_case_id} className="mb-3 flex flex-wrap items-center gap-3 border-blue/30 bg-blue-tint p-4 text-sm">
          <Badge tone="blue">Cross-case link</Badge>
          <span>Also in <Link className="font-semibold text-blue underline" to={`/cases/${ls[0].peer_case_id}`}>Case #{ls[0].peer_case_no}</Link> ({ls[0].peer_state}, FIR {ls[0].peer_fir}): both trails share{' '}
            {ls.sort((a, b) => Number(b.kind === 'vasp_deposit') - Number(a.kind === 'vasp_deposit')).map((l, i) => (
              <span key={l.address}>{i > 0 && ' and '}{l.kind === 'vasp_deposit' ? `${l.entity ?? 'VASP'} deposit address` : `${l.kind.replace('_', ' ')} wallet`} <span className="addr">{short(l.address)}</span></span>
            ))}. Likely the same beneficiary: consider one consolidated request.</span>
        </Card>
      ))}
      {freeze.map((a) => (
        <Card key={a.id} className="mb-3 flex items-center gap-3 border-orange/40 bg-orange-tint p-4 text-sm"><Badge tone="orange">Freeze window</Badge>{a.message}</Card>
      ))}

      <div className="grid gap-6 xl:grid-cols-5">
        <Card className="relative overflow-hidden xl:col-span-3">
          <div className="flex items-center justify-between border-b border-line px-4">
            <div className="flex">
              {(['graph', 'sankey', 'evidence'] as const).map((t) => (
                <button key={t} onClick={() => setTab(t)} className={cx('whitespace-nowrap border-b-2 px-3 py-3 text-sm font-semibold md:px-4', tab === t ? 'border-orange text-ink' : 'border-transparent text-muted hover:text-ink')}>
                  {t === 'graph' ? 'Fund-flow graph' : t === 'sankey' ? 'Value flow (Sankey)' : 'Transactions'}</button>))}
            </div>
            {c.done_job?.progress && <span className="hidden text-xs text-muted md:block">{c.done_job.progress.nodes} addresses · {c.done_job.progress.edges} links · {c.done_job.progress.seconds}s · {usd(c.done_job.progress.seed_out_usd)} followed</span>}
          </div>
          <div className="h-[560px]">
            {!graph || graph.nodes.length === 0 ? <div className="p-6"><Empty>{running ? 'Graph appears when the trace finishes.' : 'No trace yet.'}</Empty></div>
              : tab === 'graph' ? <TraceGraph graph={graph} onSelect={setSel} selected={sel} />
              : tab === 'sankey' ? <SankeyChart graph={graph} />
              : <EvidenceTable graph={graph} nodes={nodes} />}
          </div>
          {tab === 'graph' && graph && graph.nodes.length > 0 && (
            <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-line px-4 py-2 text-xs text-muted">
              {Object.entries(KIND_STYLE).filter(([k]) => graph.nodes.some((n) => n.data.kind === k)).map(([k, v]) => (
                <span key={k} className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full" style={{ background: v.color }} />{v.label}</span>))}
              <span>· line width = share of value · <span className="text-teal">dashed teal = sweep</span> · <span className="text-blue">dotted blue = on-ramp</span></span>
            </div>
          )}
          {selNode && tab === 'graph' && (
            <div className="absolute right-3 top-14 max-h-[480px] w-80 overflow-auto rounded-xl border border-line bg-card p-4 shadow-xl">
              <div className="mb-2 flex items-start justify-between gap-2">
                <Badge tone={selNode.kind.startsWith('vasp') ? 'teal' : selNode.kind === 'suspect' ? 'orange' : 'grey'}>{KIND_STYLE[selNode.kind]?.label ?? selNode.kind}</Badge>
                <button className="text-muted hover:text-ink" onClick={() => setSel(null)} aria-label="Close">✕</button>
              </div>
              {selNode.entity && <div className="font-semibold">{selNode.entity}</div>}
              <a className="addr text-xs text-blue hover:underline" href={addrUrl(selNode.chain, selNode.address)} target="_blank" rel="noreferrer">{selNode.address}</a>
              <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
                <div><div className="text-muted">Depth</div><b>{selNode.depth}</b></div>
                <div><div className="text-muted">Share of value</div><b>{selNode.depth >= 0 ? pct(selNode.value_share) : '-'}</b></div>
                <div><div className="text-muted">Label source</div><b>{selNode.label_source ?? '-'}</b></div>
                <div><div className="text-muted">Tier</div><b>{selNode.label_tier ?? '-'}</b></div>
              </div>
              {selNode.flags.length > 0 && <div className="mt-2 flex flex-wrap gap-1">{selNode.flags.map((f) => <Badge key={f} tone={f === 'sanctioned' ? 'red' : 'grey'}>{f.replace('_', ' ')}</Badge>)}</div>}
              {selNode.reasons.length > 0 && <ul className="mt-3 list-disc space-y-1 pl-4 text-xs text-body">{selNode.reasons.map((r) => <li key={r}>{r}</li>)}</ul>}
            </div>
          )}
        </Card>

        <div className="space-y-4 xl:col-span-2">
          <h2 className="text-lg font-semibold">Nearest VASPs <span className="text-sm font-normal text-muted">(ranked: value × confidence × actionability)</span></h2>
          {off.length === 0 && !running && <Empty>No VASP reached within trace limits. Watch-list armed on end-point wallets.</Empty>}
          {off.map((x, i) => <CandidateCard key={x.id} c={x} rank={i + 1} busy={busy === x.id} onDraft={draftReq} />)}
          {on.length > 0 && <>
            <h3 className="pt-2 font-semibold">On-ramp: where the suspect's funds came from</h3>
            {on.map((x) => <CandidateCard key={x.id} c={x} busy={busy === x.id} onDraft={draftReq} />)}
          </>}
          {reports.length > 0 && (
            <Card className="p-4">
              <div className="mb-2 font-semibold">Evidence reports</div>
              {reports.map((r) => (
                <div key={r.id} className="flex flex-wrap items-center justify-between gap-2 border-t border-line py-2 text-xs first:border-0">
                  <div><div className="text-muted">{IST(r.created_at)}</div><div className="addr">SHA-256 {r.sha256.slice(0, 24)}…</div></div>
                  <Button variant="ghost" className="px-3 py-1.5 text-xs" onClick={() => openPdf(r.id)}>Open PDF</Button>
                </div>))}
            </Card>
          )}
          {c.done_job?.progress?.notes && c.done_job.progress.notes.length > 0 && (
            <Card className="p-4 text-xs text-muted"><div className="mb-1 font-semibold text-ink">Trace notes</div>{[...new Set(c.done_job.progress.notes)].slice(0, 6).map((n) => <div key={n}>• {n}</div>)}</Card>
          )}
        </div>
      </div>

      {draft && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-navy/50 p-4" onClick={() => setDraft(null)}>
          <Card className="max-h-[90vh] w-full max-w-3xl overflow-auto p-6">
            <div onClick={(e) => e.stopPropagation()}>
              <div className="mb-3 flex items-center justify-between gap-2">
                <h2 className="font-serif text-2xl font-bold">{draft.status === 'draft' ? 'Draft notice' : 'Sent via Sahyog'}</h2>
                <StatusBadge status={draft.status} />
              </div>
              <div className="mb-3 text-sm text-muted">To {draft.vasp_name} · {draft.legal_basis}{draft.sahyog_ref ? ` · Ref ${draft.sahyog_ref}` : ''}{!draft.report_id && ' · tip: generate the evidence report first so the notice cites its hash'}</div>
              <pre className="whitespace-pre-wrap rounded-xl border border-line bg-paper p-4 font-sans text-sm leading-relaxed">{draft.body_md.replace(/\*\*/g, '').replace(/\*/g, '').replace(/`/g, '')}</pre>
              <div className="mt-4 flex justify-end gap-2">
                <Button variant="ghost" onClick={() => setDraft(null)}>Close</Button>
                {draft.status === 'draft' && <Button variant="teal" onClick={send} disabled={busy === 'send'}>Send via Sahyog (mock)</Button>}
              </div>
            </div>
          </Card>
        </div>
      )}
    </>
  )
}

function CandidateCard({ c, rank, busy, onDraft }: { c: Candidate; rank?: number; busy: boolean; onDraft: (c: Candidate, type: string) => void }) {
  const [open, setOpen] = useState(rank === 1)
  const [type, setType] = useState('disclosure_and_freeze')
  return (
    <Card className={cx('p-4', rank === 1 && 'border-teal/40 ring-1 ring-teal/20')}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            {rank && <span className="flex h-6 w-6 items-center justify-center rounded-full bg-navy text-xs font-bold text-white">{rank}</span>}
            <span className="text-lg font-bold">{c.vasp_name}</span>
            <Badge tone={c.role === 'off_ramp' ? 'teal' : 'blue'}>{c.role === 'off_ramp' ? 'off-ramp' : 'on-ramp'}</Badge>
            {c.funds_status === 'at_deposit' && <Badge tone="orange">funds at deposit</Badge>}
            {c.funds_status === 'swept' && <Badge>swept to hot wallet</Badge>}
          </div>
          <a href={addrUrl(c.chain, c.address)} target="_blank" rel="noreferrer" className="addr mt-1 block text-xs text-blue hover:underline">{c.address}</a>
          <div className="text-xs text-muted">{c.address_kind.replace('_', ' ')} · {c.hops} hop{c.hops !== 1 ? 's' : ''} · {pct(c.value_share)} of traced value{c.value_usd ? ` (${usd(c.value_usd)})` : ''}</div>
        </div>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-3 text-xs">
        <div><div className="mb-1 text-muted">Confidence</div><ConfBar value={c.confidence} /></div>
        <div><div className="mb-1 text-muted">Actionability</div><ConfBar value={c.actionability} tone="blue" /></div>
      </div>
      <button className="mt-3 text-xs font-semibold text-blue" onClick={() => setOpen(!open)}>{open ? 'Hide' : 'Show'} reasons and evidence</button>
      {open && (
        <div className="mt-2 space-y-2">
          <ul className="list-disc space-y-1 pl-4 text-xs text-body">{c.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
          <div className="flex flex-wrap gap-1 text-[11px] text-muted">{Object.entries(c.signals).map(([k, v]) => <span key={k} className="rounded bg-paper px-1.5 py-0.5">{k}: {typeof v === 'number' ? v.toFixed(2) : String(v)}</span>)}</div>
          {c.evidence_tx.length > 0 && <div className="text-xs"><div className="text-muted">Evidence transactions</div>
            {c.evidence_tx.slice(0, 6).map((t) => <a key={t} href={txUrl(c.chain, t)} target="_blank" rel="noreferrer" className="addr block text-blue hover:underline">{short(t)}</a>)}</div>}
        </div>
      )}
      <div className="mt-3 flex flex-wrap gap-2 border-t border-line pt-3">
        <select className="rounded-lg border border-line bg-card px-2 py-1.5 text-xs" value={type} onChange={(e) => setType(e.target.value)}>
          <option value="disclosure_and_freeze">Disclosure + freeze</option><option value="disclosure">Disclosure (KYC)</option><option value="freeze">Freeze only</option>
        </select>
        <Button variant={rank === 1 ? 'teal' : 'ghost'} className="px-3 py-1.5 text-xs" disabled={busy} onClick={() => onDraft(c, type)}>Draft Section 94 BNSS notice</Button>
      </div>
    </Card>
  )
}

function EvidenceTable({ graph, nodes }: { graph: Graph; nodes: Map<string, Graph['nodes'][number]['data']> }) {
  const lab = (id: string) => { const n = nodes.get(id); return n ? `${n.entity ? n.entity + ' ' : ''}${short(n.address)}` : id }
  const rows = [...graph.edges].sort((a, b) => a.data.first_ts.localeCompare(b.data.first_ts))
  return (
    <div className="h-full overflow-auto">
      <table className="w-full min-w-[680px] text-xs">
        <thead className="sticky top-0 bg-card text-left text-muted"><tr><th className="p-3">First seen</th><th className="p-3">From → To</th><th className="p-3">Type</th><th className="p-3 text-right">USD</th><th className="p-3">Tx</th></tr></thead>
        <tbody className="divide-y divide-line">
          {rows.map((e) => (
            <tr key={e.data.id}>
              <td className="p-3 whitespace-nowrap text-muted">{IST(e.data.first_ts)}</td>
              <td className="p-3"><span className="addr">{lab(e.data.source)}</span> → <span className="addr">{lab(e.data.target)}</span></td>
              <td className="p-3"><Badge tone={e.data.direction === 'sweep' ? 'teal' : e.data.direction === 'backward' ? 'blue' : 'orange'}>{e.data.direction}</Badge> {e.data.asset}</td>
              <td className="p-3 text-right tabular-nums">{usd(e.data.amount_usd)}</td>
              <td className="p-3">{e.data.tx_hashes.slice(0, 2).map((t) => <a key={t} className="addr block text-blue hover:underline" href={txUrl(e.data.chain, t)} target="_blank" rel="noreferrer">{short(t)}</a>)}{e.data.tx_count > 2 && <span className="text-muted">+{e.data.tx_count - 2} more</span>}</td>
            </tr>))}
        </tbody>
      </table>
    </div>
  )
}
