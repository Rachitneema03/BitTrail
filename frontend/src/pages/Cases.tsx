import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { CaseSummary } from '../api/types'
import { Badge, Card, Empty, IST, PageHeader, StatusBadge, pct, short } from '../components/ui'

export default function Cases() {
  const [cases, setCases] = useState<CaseSummary[] | null>(null)
  useEffect(() => {
    const load = () => api<CaseSummary[]>('/cases').then(setCases)
    load()
    const t = setInterval(load, 6000)
    return () => clearInterval(t)
  }, [])
  return (
    <>
      <PageHeader title="Cases" sub="Suspect wallets received from Sahyog / NCRP"
        right={<Link to="/cases/new" className="rounded-lg bg-orange px-4 py-2 text-sm font-semibold text-white">+ New case</Link>} />
      {cases === null ? <Empty>Loading…</Empty> : cases.length === 0 ? <Empty>No cases yet.</Empty> : (
        <Card className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm">
            <thead className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
              <tr><th className="p-4">Case</th><th className="p-4">Suspect wallet</th><th className="p-4">Reported</th><th className="p-4">Nearest VASP</th><th className="p-4">Status</th></tr>
            </thead>
            <tbody className="divide-y divide-line">
              {cases.map((c) => (
                <tr key={c.id} className="hover:bg-paper">
                  <td className="p-4"><Link to={`/cases/${c.id}`} className="font-semibold text-ink hover:text-blue">#{c.case_no} · {c.title ?? c.fir_no}</Link>
                    <div className="text-xs text-muted">{c.police_station}, {c.state} · FIR {c.fir_no}</div></td>
                  <td className="p-4">{c.wallets.map((w) => <div key={w.address}><Badge>{w.chain}</Badge> <span className="addr text-xs">{short(w.address)}</span></div>)}</td>
                  <td className="p-4 text-xs text-muted">{IST(c.fraud_time)}</td>
                  <td className="p-4">{c.top_vasp ? <div><span className="font-semibold text-teal">{c.top_vasp.vasp_name}</span>
                    <div className="text-xs text-muted">{c.top_vasp.address_kind.replace('_', ' ')} · conf {pct(c.top_vasp.confidence)}</div></div> : <span className="text-muted">-</span>}
                    {!!c.links && <div className="mt-1"><Badge tone="blue">{c.links} cross-case link{c.links > 1 ? 's' : ''}</Badge></div>}</td>
                  <td className="p-4"><StatusBadge status={c.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </>
  )
}
