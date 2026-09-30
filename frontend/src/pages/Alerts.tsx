import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, post } from '../api/client'
import type { AlertRules, AlertT } from '../api/types'
import { Badge, Button, Card, Empty, IST, PageHeader, cx } from '../components/ui'

const TYPE: Record<string, string> = {
  freeze_window: 'Freeze window', case_link: 'Cross-case link', funds_moved: 'New activity', reached_vasp: 'Reached VASP',
  sanctioned_hit: 'Sanctioned', no_vasp: 'No VASP', large_transfer: 'Large transfer', score_increase: 'Score increase',
  risk_pattern: 'Risk pattern',
}

function RulesCard() {
  const [r, setR] = useState<AlertRules | null>(null)
  const [saved, setSaved] = useState(false)
  useEffect(() => { api<AlertRules>('/settings/alerts').then(setR) }, [])
  if (!r) return null
  const save = async () => {
    setR(await api<AlertRules>('/settings/alerts', { method: 'PUT', body: JSON.stringify(r) }))
    setSaved(true); setTimeout(() => setSaved(false), 2000)
  }
  const box = 'flex items-center gap-2 text-sm'
  return (
    <Card className="mb-6 p-5">
      <div className="mb-3 flex items-center justify-between"><h2 className="text-lg font-semibold">Alert rules</h2>{saved && <Badge tone="teal">saved</Badge>}</div>
      <div className="grid gap-4 md:grid-cols-3">
        <label className="text-sm">Large transfer threshold (USD)
          <input type="number" className="mt-1 w-full rounded-lg border border-line bg-card px-3 py-1.5" value={r.large_transfer_usd}
            onChange={(e) => setR({ ...r, large_transfer_usd: Number(e.target.value) })} /></label>
        <label className="text-sm">Score increase (points)
          <input type="number" className="mt-1 w-full rounded-lg border border-line bg-card px-3 py-1.5" value={r.score_increase_points}
            onChange={(e) => setR({ ...r, score_increase_points: Number(e.target.value) })} /></label>
        <label className="text-sm">Minimum risk level for pattern alerts
          <select className="mt-1 w-full rounded-lg border border-line bg-card px-3 py-1.5" value={r.min_risk_level}
            onChange={(e) => setR({ ...r, min_risk_level: e.target.value as AlertRules['min_risk_level'] })}>
            {['low', 'medium', 'high', 'critical'].map((l) => <option key={l}>{l}</option>)}</select></label>
      </div>
      <div className="mt-4 flex flex-wrap gap-5">
        <label className={box}><input type="checkbox" checked={r.new_activity} onChange={(e) => setR({ ...r, new_activity: e.target.checked })} />New activity on watched wallets</label>
        <label className={box}><input type="checkbox" checked={r.new_relationship} onChange={(e) => setR({ ...r, new_relationship: e.target.checked })} />New cross-case relationships</label>
        <label className={box}><input type="checkbox" checked={r.risk_patterns} onChange={(e) => setR({ ...r, risk_patterns: e.target.checked })} />Detected risk patterns</label>
      </div>
      <div className="mt-4"><Button onClick={save}>Save rules</Button></div>
    </Card>
  )
}

export default function Alerts() {
  const [rows, setRows] = useState<AlertT[] | null>(null)
  const load = () => api<AlertT[]>('/alerts').then(setRows)
  useEffect(() => { load(); const t = setInterval(load, 10000); return () => clearInterval(t) }, [])
  const read = async (id: string) => { await post(`/alerts/${id}/read`); load() }
  return (
    <>
      <PageHeader title="Alerts" sub="Freeze windows, large transfers, score jumps, cross-case links, risk patterns and new activity on watched wallets (polled every 5 min)" />
      <RulesCard />
      {rows === null ? <Empty>Loading…</Empty> : rows.length === 0 ? <Empty>No alerts.</Empty> : (
        <Card className="divide-y divide-line">
          {rows.map((a) => (
            <div key={a.id} className={cx('flex flex-wrap items-start gap-3 p-4', a.read && 'opacity-60')}>
              <span className={cx('mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full', a.severity === 'high' ? 'bg-orange' : a.severity === 'medium' ? 'bg-blue' : 'bg-muted')} />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2"><Badge tone={a.severity === 'high' ? 'orange' : 'blue'}>{TYPE[a.type] ?? a.type}</Badge>
                  <Link to={`/cases/${a.case_id}`} className="text-xs font-semibold text-blue hover:underline">Case #{a.case_no}</Link><span className="text-xs text-muted">{IST(a.created_at)}</span></div>
                <div className="mt-1 text-sm">{a.message}</div>
              </div>
              {!a.read && <button className="text-xs font-semibold text-muted hover:text-ink" onClick={() => read(a.id)}>Mark read</button>}
            </div>
          ))}
        </Card>
      )}
    </>
  )
}
