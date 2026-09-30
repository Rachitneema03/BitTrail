import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import type { CaseSummary } from '../api/types'
import { Badge, Card, Empty, IST, PageHeader, StatusBadge, cx, pct, short } from '../components/ui'

type View = 'all' | 'action' | 'attributed' | 'tracing' | 'linked' | 'multi' | 'none'
const VIEWS: [View, string, (c: CaseSummary) => boolean][] = [
  ['all', 'All', () => true],
  ['action', 'Funds at deposit', (c) => c.top_vasp?.funds_status === 'at_deposit'],
  ['attributed', 'Attributed', (c) => !!c.top_vasp],
  ['multi', 'Multiple VASPs', (c) => (c.vasps?.length ?? 0) > 1],
  ['linked', 'Cross-case linked', (c) => (c.links ?? 0) > 0],
  ['tracing', 'Tracing', (c) => c.status === 'tracing'],
  ['none', 'No VASP yet', (c) => !c.top_vasp && c.status !== 'tracing'],
]

type SortKey = 'case' | 'reported' | 'confidence' | 'rank' | 'amount'
const SORTS: [SortKey, string, (c: CaseSummary) => number][] = [
  ['case', 'Case number', (c) => c.case_no],
  ['reported', 'Fraud reported', (c) => Date.parse(c.fraud_time)],
  ['confidence', 'Confidence', (c) => c.top_vasp?.confidence ?? -1],
  ['rank', 'Rank score', (c) => c.top_vasp?.rank_score ?? -1],
  ['amount', 'Amount (₹)', (c) => c.amount_inr ?? -1],
]

const uniq = (xs: (string | null | undefined)[]) => [...new Set(xs.filter((x): x is string => !!x))].sort()

function haystack(c: CaseSummary): string {
  return [`#${c.case_no}`, c.title, c.fir_no, c.ncrp_id, c.police_station, c.state, c.fraud_type, c.status,
    ...c.wallets.map((w) => w.address), ...(c.vasps ?? []), c.top_vasp?.address].filter(Boolean).join(' ').toLowerCase()
}

function Select({ label, value, onChange, options }: { label: string; value: string; onChange: (v: string) => void; options: string[] }) {
  return (
    <label className="flex items-center gap-1.5 text-xs text-muted">
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)}
        className={cx('rounded-lg border bg-card px-2 py-1.5 text-xs text-ink', value ? 'border-orange' : 'border-line')}>
        <option value="">Any</option>
        {options.map((o) => <option key={o} value={o}>{o.replace('_', ' ')}</option>)}
      </select>
    </label>
  )
}

export default function Cases() {
  const [cases, setCases] = useState<CaseSummary[] | null>(null)
  const [params, setParams] = useSearchParams()
  const searchRef = useRef<HTMLInputElement>(null)
  const [q, setQ] = useState(params.get('q') ?? '')

  useEffect(() => {
    const load = () => api<CaseSummary[]>('/cases').then(setCases)
    load()
    const t = setInterval(load, 6000)
    return () => clearInterval(t)
  }, [])

  // "/" focuses search, Esc clears it
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLElement && ['INPUT', 'SELECT', 'TEXTAREA'].includes(e.target.tagName)
      if (e.key === '/' && !typing) { e.preventDefault(); searchRef.current?.focus() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const set = (key: string, value: string) => setParams((p) => { if (value) p.set(key, value); else p.delete(key); return p }, { replace: true })
  useEffect(() => { const t = setTimeout(() => set('q', q.trim()), 150); return () => clearTimeout(t) }, [q]) // eslint-disable-line react-hooks/exhaustive-deps

  const view = (params.get('view') ?? 'all') as View
  const status = params.get('status') ?? ''
  const chain = params.get('chain') ?? ''
  const vasp = params.get('vasp') ?? ''
  const state = params.get('state') ?? ''
  const fraud = params.get('type') ?? ''
  const sort = (params.get('sort') ?? 'case') as SortKey
  const asc = params.get('dir') === 'asc'

  const opts = useMemo(() => ({
    status: uniq(cases?.map((c) => c.status) ?? []),
    chain: uniq(cases?.flatMap((c) => c.wallets.map((w) => w.chain)) ?? []),
    vasp: uniq(cases?.flatMap((c) => c.vasps ?? []) ?? []),
    state: uniq(cases?.map((c) => c.state) ?? []),
    fraud: uniq(cases?.map((c) => c.fraud_type) ?? []),
  }), [cases])

  // everything except the quick view, so each chip can show its count
  const base = useMemo(() => {
    const terms = (params.get('q') ?? '').toLowerCase().split(/\s+/).filter(Boolean)
    return (cases ?? []).filter((c) => {
      if (status && c.status !== status) return false
      if (chain && !c.wallets.some((w) => w.chain === chain)) return false
      if (vasp && !(c.vasps ?? []).includes(vasp)) return false
      if (state && c.state !== state) return false
      if (fraud && c.fraud_type !== fraud) return false
      if (terms.length) { const h = haystack(c); if (!terms.every((t) => h.includes(t))) return false }
      return true
    })
  }, [cases, params, status, chain, vasp, state, fraud])

  const shown = useMemo(() => {
    const pred = VIEWS.find((v) => v[0] === view)?.[2] ?? (() => true)
    const key = SORTS.find((s) => s[0] === sort)?.[2] ?? SORTS[0][2]
    return base.filter(pred).sort((a, b) => (asc ? 1 : -1) * (key(a) - key(b)) || b.case_no - a.case_no)
  }, [base, view, sort, asc])

  const active = [params.get('q'), status, chain, vasp, state, fraud].filter(Boolean).length + (view !== 'all' ? 1 : 0)
  const clear = () => { setQ(''); setParams(new URLSearchParams(sort !== 'case' || asc ? { sort, ...(asc ? { dir: 'asc' } : {}) } : {}), { replace: true }) }

  return (
    <>
      <PageHeader title="Cases" sub="Suspect wallets received from Sahyog / NCRP"
        right={<Link to="/cases/new" className="rounded-lg bg-orange px-4 py-2 text-sm font-semibold text-white">+ New case</Link>} />
      {cases === null ? <Empty>Loading…</Empty> : cases.length === 0 ? <Empty>No cases yet.</Empty> : (
        <>
          <Card className="mb-4 space-y-3 p-4">
            <div className="flex flex-wrap items-center gap-3">
              <div className="relative min-w-[240px] flex-1">
                <input ref={searchRef} value={q} onChange={(e) => setQ(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Escape') { setQ(''); e.currentTarget.blur() } }}
                  placeholder="Search case #, FIR, NCRP, station, wallet, VASP…"
                  className="w-full rounded-lg border border-line bg-paper py-2 pl-3 pr-10 text-sm outline-none focus:border-orange" />
                <kbd className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 rounded border border-line bg-card px-1.5 text-[10px] text-muted">/</kbd>
              </div>
              <label className="flex items-center gap-1.5 text-xs text-muted">Sort
                <select value={sort} onChange={(e) => set('sort', e.target.value === 'case' ? '' : e.target.value)}
                  className="rounded-lg border border-line bg-card px-2 py-1.5 text-xs text-ink">
                  {SORTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                </select>
                <button onClick={() => set('dir', asc ? '' : 'asc')} title={asc ? 'Ascending' : 'Descending'}
                  className="rounded-lg border border-line bg-card px-2 py-1.5 text-xs font-semibold text-ink hover:bg-paper">{asc ? '↑ Asc' : '↓ Desc'}</button>
              </label>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {VIEWS.map(([k, l, pred]) => {
                const n = base.filter(pred).length
                return (
                  <button key={k} onClick={() => set('view', k === 'all' ? '' : k)} disabled={n === 0 && view !== k}
                    className={cx('rounded-full border px-3 py-1 text-xs font-semibold transition disabled:opacity-40',
                      view === k ? 'border-navy bg-navy text-paper' : 'border-line bg-card text-ink hover:bg-paper')}>
                    {l} <span className={cx('ml-0.5 tabular-nums', view === k ? 'text-paper/70' : 'text-muted')}>{n}</span>
                  </button>
                )
              })}
            </div>
            <div className="flex flex-wrap items-center gap-3 border-t border-line pt-3">
              <Select label="Status" value={status} onChange={(v) => set('status', v)} options={opts.status} />
              <Select label="Chain" value={chain} onChange={(v) => set('chain', v)} options={opts.chain} />
              <Select label="VASP" value={vasp} onChange={(v) => set('vasp', v)} options={opts.vasp} />
              <Select label="State" value={state} onChange={(v) => set('state', v)} options={opts.state} />
              <Select label="Fraud type" value={fraud} onChange={(v) => set('type', v)} options={opts.fraud} />
              <span className="ml-auto text-xs text-muted">{shown.length} of {cases.length} cases
                {active > 0 && <> · <button onClick={clear} className="font-semibold text-blue hover:underline">Clear {active} filter{active > 1 ? 's' : ''}</button></>}</span>
            </div>
          </Card>

          {shown.length === 0 ? <Empty>No cases match these filters. <button onClick={clear} className="font-semibold text-blue hover:underline">Clear filters</button></Empty> : (
            <Card className="overflow-x-auto">
              <table className="w-full min-w-[760px] text-sm">
                <thead className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
                  <tr><th className="p-4">Case</th><th className="p-4">Suspect wallet</th><th className="p-4">Reported</th><th className="p-4">Nearest VASP</th><th className="p-4">Status</th></tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {shown.map((c) => (
                    <tr key={c.id} className="hover:bg-paper">
                      <td className="p-4"><Link to={`/cases/${c.id}`} className="font-semibold text-ink hover:text-blue">#{c.case_no} · {c.title ?? c.fir_no}</Link>
                        <div className="text-xs text-muted">{c.police_station}, {c.state} · FIR {c.fir_no}</div></td>
                      <td className="p-4">{c.wallets.map((w) => <div key={w.address}><Badge>{w.chain}</Badge> <span className="addr text-xs">{short(w.address)}</span></div>)}</td>
                      <td className="p-4 text-xs text-muted">{IST(c.fraud_time)}</td>
                      <td className="p-4">{c.top_vasp ? <div><span className="font-semibold text-teal">{c.top_vasp.vasp_name}</span>
                        <div className="text-xs text-muted">{c.top_vasp.address_kind.replace('_', ' ')} · conf {pct(c.top_vasp.confidence)}</div></div> : <span className="text-muted">-</span>}
                        <div className="mt-1 flex flex-wrap gap-1">
                          {(c.vasps?.length ?? 0) > 1 && <Badge tone="teal">+{c.vasps!.length - 1} more VASP{c.vasps!.length > 2 ? 's' : ''}</Badge>}
                          {c.top_vasp?.funds_status === 'at_deposit' && <Badge tone="orange">funds at deposit</Badge>}
                          {!!c.links && <Badge tone="blue">{c.links} cross-case link{c.links > 1 ? 's' : ''}</Badge>}
                        </div></td>
                      <td className="p-4"><StatusBadge status={c.status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}
        </>
      )}
    </>
  )
}
