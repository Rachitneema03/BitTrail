import { useEffect, useState } from 'react'
import { api, post } from '../api/client'
import type { ReqT } from '../api/types'
import { Badge, Button, Card, Empty, IST, PageHeader, StatusBadge } from '../components/ui'
import { useAuth } from '../store/auth'

export default function VaspInbox() {
  const { me } = useAuth()
  const [rows, setRows] = useState<ReqT[] | null>(null)
  const [form, setForm] = useState<Record<string, { account: string; frozen: string; note: string }>>({})
  const [msg, setMsg] = useState('')
  const load = () => api<ReqT[]>('/requests').then(setRows)
  useEffect(() => { load() }, [])

  const reply = async (r: ReqT, outcome: 'confirmed' | 'denied') => {
    const f = form[r.id] ?? { account: '', frozen: '', note: '' }
    const res = await post<ReqT & { rescored_candidates: number }>(`/requests/${r.id}/reply`, {
      outcome, account_ref: f.account || null, frozen_amount_usd: f.frozen ? Number(f.frozen) : null, note: f.note || null,
    })
    setMsg(`${outcome === 'confirmed' ? 'Confirmed' : 'Denied'}. BitTrail learned a ${outcome === 'confirmed' ? 'verified' : 'negative'} label and re-scored ${res.rescored_candidates} open candidate(s) across cases.`)
    load()
  }
  const upd = (id: string, k: 'account' | 'frozen' | 'note', v: string) => setForm({ ...form, [id]: { ...(form[id] ?? { account: '', frozen: '', note: '' }), [k]: v } })

  return (
    <>
      <PageHeader title={`${me?.vasp_name ?? 'VASP'} · Law-enforcement request inbox`} sub="Simulated VASP nodal-officer view. Replies feed BitTrail's labels flywheel." />
      {msg && <Card className="mb-4 border-teal/30 bg-teal-tint p-4 text-sm text-teal">{msg}</Card>}
      {rows === null ? <Empty>Loading…</Empty> : rows.length === 0 ? <Empty>No requests addressed to {me?.vasp_name}.</Empty> : rows.map((r) => (
        <Card key={r.id} className="mb-4 p-5">
          <div className="flex flex-wrap items-center gap-2"><Badge tone="blue">{r.sahyog_ref}</Badge><StatusBadge status={r.status} /><Badge>{r.type.replaceAll('_', ' ')}</Badge>
            <span className="text-xs text-muted">received {IST(r.sent_at)} · {r.state}</span></div>
          <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap rounded-xl border border-line bg-paper p-4 font-sans text-sm">{r.body_md.replace(/\*\*/g, '').replace(/\*/g, '').replace(/`/g, '')}</pre>
          {['sent', 'acknowledged'].includes(r.status) ? (
            <div className="mt-4 grid gap-3 md:grid-cols-4">
              <input className="rounded-lg border border-line bg-card px-3 py-2 text-sm" placeholder="Account ref (e.g. ACC-…)" value={form[r.id]?.account ?? ''} onChange={(e) => upd(r.id, 'account', e.target.value)} />
              <input className="rounded-lg border border-line bg-card px-3 py-2 text-sm" placeholder="Amount frozen (USD)" type="number" value={form[r.id]?.frozen ?? ''} onChange={(e) => upd(r.id, 'frozen', e.target.value)} />
              <Button variant="teal" onClick={() => reply(r, 'confirmed')}>Confirm: our deposit address</Button>
              <Button variant="danger" onClick={() => reply(r, 'denied')}>Deny: not ours</Button>
            </div>
          ) : r.reply && <div className="mt-3 text-sm text-muted">Replied {IST(r.reply.replied_at)}: <b>{r.reply.outcome}</b>{r.reply.account_ref ? ` · ${r.reply.account_ref}` : ''}</div>}
        </Card>
      ))}
    </>
  )
}
