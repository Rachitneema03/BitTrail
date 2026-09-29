import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { AlertT, CaseSummary, Stats } from '../api/types'
import { Badge, Card, Empty, IST, PageHeader, Stat, StatusBadge, cx, pct, usd } from '../components/ui'

export default function Dashboard() {
  const [s, setS] = useState<Stats | null>(null)
  const [cases, setCases] = useState<CaseSummary[]>([])
  const [alerts, setAlerts] = useState<AlertT[]>([])
  useEffect(() => {
    const load = () => {
      api<Stats>('/stats').then(setS)
      api<CaseSummary[]>('/cases').then(setCases)
      api<AlertT[]>('/alerts').then(setAlerts)
    }
    load()
    const t = setInterval(load, 8000)
    return () => clearInterval(t)
  }, [])
  const maxV = Math.max(1, ...(s?.top_vasps.map((v) => v.value_usd) ?? [1]))

  return (
    <>
      <PageHeader title="Dashboard" sub="Case-based analytics across all traced wallets"
        right={<Link to="/cases/new" className="rounded-lg bg-orange px-4 py-2 text-sm font-semibold text-white">+ New case</Link>} />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Cases" value={s?.cases ?? '–'} sub={`${s?.attributed ?? 0} attributed to a VASP`} />
        <Stat label="Value traced" value={usd(s?.traced_usd)} tone="orange" sub="Suspect outflows followed" />
        <Stat label="Cross-case links" value={s?.links ?? '–'} tone="blue" sub="Shared deposit / trail addresses" />
        <Stat label="Median trace time" value={s?.median_trace_seconds != null ? `${s.median_trace_seconds}s` : '–'} tone="teal" sub="Wallet in → VASP out" />
      </div>
      <div className="mt-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="Requests sent (Sahyog)" value={s?.requests_sent ?? '–'} />
        <Stat label="Confirmed by VASPs" value={s?.requests_confirmed ?? '–'} tone="teal" />
        <Stat label="Verified labels learned" value={s?.verified_labels ?? '–'} tone="teal" sub="Labels flywheel" />
        <Stat label="Unread alerts" value={s?.unread_alerts ?? '–'} tone="orange" />
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-3">
        <Card className="p-5 xl:col-span-2">
          <div className="mb-4 flex items-center justify-between"><h2 className="text-lg font-semibold">Recent cases</h2><Link to="/cases" className="text-sm text-blue">All cases →</Link></div>
          {cases.length === 0 ? <Empty>No cases yet.</Empty> : (
            <div className="divide-y divide-line">
              {cases.slice(0, 6).map((c) => (
                <Link key={c.id} to={`/cases/${c.id}`} className="flex flex-wrap items-center gap-3 py-3 hover:bg-paper">
                  <span className="w-12 font-mono text-sm text-muted">#{c.case_no}</span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium">{c.title ?? c.fir_no}</div>
                    <div className="text-xs text-muted">{c.state} · FIR {c.fir_no} {c.is_demo && '· demo'}</div>
                  </div>
                  {c.top_vasp && <Badge tone="teal">{c.top_vasp.vasp_name} · {pct(c.top_vasp.confidence)}</Badge>}
                  {!!c.links && <Badge tone="blue">{c.links} link{c.links > 1 ? 's' : ''}</Badge>}
                  <StatusBadge status={c.status} />
                </Link>
              ))}
            </div>
          )}
        </Card>
        <Card className="p-5">
          <h2 className="mb-4 text-lg font-semibold">Top VASPs by traced value</h2>
          {s?.top_vasps.length ? s.top_vasps.map((v) => (
            <div key={v.vasp} className="mb-3">
              <div className="flex justify-between text-sm"><span className="font-medium">{v.vasp}</span><span className="tabular-nums text-muted">{usd(v.value_usd)} · {v.cases} case{v.cases > 1 ? 's' : ''}</span></div>
              <div className="mt-1 h-2 rounded-full bg-line"><div className="h-2 rounded-full bg-teal" style={{ width: `${(v.value_usd / maxV) * 100}%` }} /></div>
            </div>
          )) : <Empty>Nothing attributed yet.</Empty>}
        </Card>
      </div>

      <Card className="mt-6 p-5">
        <div className="mb-4 flex items-center justify-between"><h2 className="text-lg font-semibold">Latest alerts</h2><Link to="/alerts" className="text-sm text-blue">All alerts →</Link></div>
        {alerts.length === 0 ? <Empty>No alerts.</Empty> : alerts.slice(0, 5).map((a) => (
          <Link key={a.id} to={`/cases/${a.case_id}`} className="flex gap-3 border-b border-line py-3 last:border-0 hover:bg-paper">
            <span className={cx('mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full', a.severity === 'high' ? 'bg-orange' : 'bg-blue')} />
            <div className="min-w-0 flex-1"><div className="text-sm">{a.message}</div><div className="text-xs text-muted">Case #{a.case_no} · {IST(a.created_at)}</div></div>
          </Link>
        ))}
      </Card>
    </>
  )
}
