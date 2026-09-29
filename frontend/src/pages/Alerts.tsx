import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, post } from '../api/client'
import type { AlertT } from '../api/types'
import { Badge, Card, Empty, IST, PageHeader, cx } from '../components/ui'

const TYPE: Record<string, string> = { freeze_window: 'Freeze window', case_link: 'Cross-case link', funds_moved: 'Funds moved', reached_vasp: 'Reached VASP', sanctioned_hit: 'Sanctioned', no_vasp: 'No VASP' }

export default function Alerts() {
  const [rows, setRows] = useState<AlertT[] | null>(null)
  const load = () => api<AlertT[]>('/alerts').then(setRows)
  useEffect(() => { load(); const t = setInterval(load, 10000); return () => clearInterval(t) }, [])
  const read = async (id: string) => { await post(`/alerts/${id}/read`); load() }
  return (
    <>
      <PageHeader title="Alerts" sub="Freeze windows, cross-case links and watch-list movements (polled every 5 min)" />
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
