import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { AuditRow } from '../api/types'
import { Badge, Button, Card, Empty, IST, PageHeader } from '../components/ui'
import { useAuth } from '../store/auth'

interface Verify { ok: boolean; rows_checked: number; first_bad_id?: number; head: string }

/** I4C analysts: the append-only, hash-chained audit trail and a one-click integrity check. */
export default function Audit() {
  const { me } = useAuth()
  const [rows, setRows] = useState<AuditRow[] | null>(null)
  const [verify, setVerify] = useState<Verify | null>(null)
  const [busy, setBusy] = useState(false)
  const [filter, setFilter] = useState('')
  useEffect(() => { if (me?.role === 'analyst') api<AuditRow[]>('/audit?limit=300').then(setRows) }, [me])
  const check = async () => { setBusy(true); try { setVerify(await api<Verify>('/audit/verify')) } finally { setBusy(false) } }

  if (me?.role !== 'analyst') return <Empty>The audit log is visible to I4C analysts only (role-based access).</Empty>
  const shown = (rows ?? []).filter((r) => !filter || r.action.includes(filter) || r.user.toLowerCase().includes(filter.toLowerCase()))
  return (
    <>
      <PageHeader title="Audit log" sub="Every mutating action, append-only. Each row's hash = SHA-256(previous hash + row), so editing or deleting any row breaks the chain."
        right={<Button onClick={check} disabled={busy}>{busy ? 'Verifying…' : 'Verify hash chain'}</Button>} />
      {verify && (
        <Card className={`mb-4 p-4 text-sm ${verify.ok ? 'border-teal/30 bg-teal-tint text-teal' : 'border-red/30 bg-red-tint text-red'}`}>
          {verify.ok ? <>✓ Chain intact: {verify.rows_checked} rows verified. Head <span className="addr">{verify.head.slice(0, 24)}…</span></>
            : <>✗ Chain broken at row #{verify.first_bad_id} after {verify.rows_checked} good rows.</>}
        </Card>
      )}
      <input className="mb-3 w-full max-w-sm rounded-lg border border-line bg-card px-3 py-2 text-sm" placeholder="Filter by action or user (e.g. request.send)" value={filter} onChange={(e) => setFilter(e.target.value)} />
      {rows === null ? <Empty>Loading…</Empty> : (
        <Card className="overflow-auto">
          <table className="w-full min-w-[760px] text-xs">
            <thead className="bg-paper text-left text-muted"><tr><th className="p-3">#</th><th className="p-3">When</th><th className="p-3">Who</th><th className="p-3">Action</th><th className="p-3">Details</th><th className="p-3">Hash</th></tr></thead>
            <tbody className="divide-y divide-line">
              {shown.map((r) => (
                <tr key={r.id}>
                  <td className="p-3 tabular-nums text-muted">{r.id}</td>
                  <td className="whitespace-nowrap p-3 text-muted">{IST(r.at)}</td>
                  <td className="p-3">{r.user}</td>
                  <td className="p-3"><Badge tone={r.action.startsWith('request') ? 'blue' : r.action.startsWith('reply') ? 'teal' : r.action.startsWith('ai') ? 'orange' : 'grey'}>{r.action}</Badge></td>
                  <td className="max-w-[340px] truncate p-3 text-body" title={JSON.stringify(r.data)}>{Object.entries(r.data).map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : String(v)}`).join(' · ')}</td>
                  <td className="addr p-3 text-muted">{r.hash.slice(0, 12)}…</td>
                </tr>))}
            </tbody>
          </table>
        </Card>
      )}
    </>
  )
}
