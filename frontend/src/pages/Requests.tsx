import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, post } from '../api/client'
import type { ReqT } from '../api/types'
import { Badge, Button, Card, Empty, IST, PageHeader, StatusBadge, short } from '../components/ui'
import RouteInfo from '../components/RouteInfo'
import { useAuth } from '../store/auth'

interface ReplyForm { account: string; frozen: string; note: string }
const BLANK: ReplyForm = { account: '', frozen: '', note: '' }

export default function Requests() {
  const [rows, setRows] = useState<ReqT[] | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [recording, setRecording] = useState<string | null>(null)
  const [form, setForm] = useState<ReplyForm>(BLANK)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const { me } = useAuth()
  const load = () => api<ReqT[]>('/requests').then(setRows)
  useEffect(() => { load() }, [])
  const send = async (id: string) => { setErr(''); try { await post(`/requests/${id}/send`); load() } catch (x) { setErr((x as Error).message) } }
  const approve = async (id: string) => { setErr(''); try { await post(`/requests/${id}/approve`); load() } catch (x) { setErr((x as Error).message) } }

  const reply = async (r: ReqT, outcome: 'confirmed' | 'denied') => {
    setErr('')
    try {
      const res = await post<ReqT & { rescored_candidates: number }>(`/requests/${r.id}/reply`, {
        outcome, account_ref: form.account || null, frozen_amount_usd: form.frozen ? Number(form.frozen) : null, note: form.note || null,
      })
      setMsg(`${r.vasp_name} ${outcome} (${r.sahyog_ref}). BitTrail learned a ${outcome === 'confirmed' ? 'verified' : 'negative'} label and re-scored ${res.rescored_candidates} open candidate(s) across cases.`)
      setRecording(null); setForm(BLANK); load()
    } catch (x) { setErr((x as Error).message) }
  }

  return (
    <>
      <PageHeader title="Sahyog requests" sub="Drafted notices under Section 94 BNSS, routed to VASPs through Sahyog. VASPs reply on Sahyog; the reply is recorded here (Sahyog integration mocked in this prototype)." />
      {msg && <Card className="mb-4 border-teal/30 bg-teal-tint p-4 text-sm text-teal">{msg}</Card>}
      {err && !recording && <Card className="mb-4 border-red/30 bg-red-tint p-4 text-sm text-red">{err}</Card>}
      {rows === null ? <Empty>Loading…</Empty> : rows.length === 0 ? <Empty>No requests yet. Open a case and draft a notice from a candidate VASP.</Empty> : (
        <div className="space-y-3">
          {rows.map((r) => (
            <Card key={r.id} className="p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="flex flex-wrap items-center gap-2"><b>{r.vasp_name}</b><StatusBadge status={r.status} /><Badge>{r.type.replaceAll('_', ' ')}</Badge>{r.sahyog_ref && <Badge tone="blue">{r.sahyog_ref}</Badge>}
                    {r.route && <Badge tone={r.route.channel.startsWith('sahyog') ? 'teal' : r.route.channel === 'le_portal' ? 'orange' : 'red'}>{r.route.label}</Badge>}</div>
                  <div className="mt-1 text-xs text-muted"><Link to={`/cases/${r.case_id}`} className="text-blue hover:underline">Case #{r.case_no}</Link> · FIR {r.fir_no} · {r.legal_basis} · {r.addresses.map(short).join(', ')} · {IST(r.sent_at ?? r.created_at)}{r.approved_by ? ` · approved by ${r.approved_by}` : ''}</div>
                  {r.route && <div className="mt-1"><RouteInfo route={r.route} /></div>}
                  {r.reply && <div className="mt-2 text-sm">{r.reply.outcome === 'confirmed'
                    ? <span className="text-teal">✓ {r.vasp_name} confirmed via Sahyog: account {r.reply.account_ref ?? '-'}{r.reply.frozen_amount_usd ? `, $${r.reply.frozen_amount_usd.toLocaleString()} frozen` : ''}</span>
                    : <span className="text-red">{r.vasp_name} denied via Sahyog{r.reply.note ? `: ${r.reply.note}` : ''}</span>}</div>}
                </div>
                <div className="flex gap-2">
                  <Button variant="ghost" className="px-3 py-1.5 text-xs" onClick={() => setOpen(open === r.id ? null : r.id)}>{open === r.id ? 'Hide' : 'View'} notice</Button>
                  {r.status === 'pending_approval' && (me?.role === 'analyst'
                    ? <Button variant="orange" className="px-3 py-1.5 text-xs" onClick={() => approve(r.id)}>Approve</Button>
                    : <span className="self-center text-xs text-orange-ink">Awaiting I4C analyst approval</span>)}
                  {r.status === 'draft' && <Button variant="teal" className="px-3 py-1.5 text-xs" onClick={() => send(r.id)}>
                    {r.route?.channel === 'le_portal' ? 'Mark submitted (LE portal)' : r.route?.channel === 'international' ? 'Forward for MLAT / Interpol' : 'Send via Sahyog'}</Button>}
                  {['sent', 'acknowledged'].includes(r.status) && recording !== r.id &&
                    <Button variant="ghost" className="px-3 py-1.5 text-xs" onClick={() => { setRecording(r.id); setForm(BLANK); setErr('') }}>Record VASP reply</Button>}
                </div>
              </div>
              {recording === r.id && (
                <div className="mt-3 rounded-xl border border-line bg-paper p-3">
                  <div className="mb-2 text-xs text-muted">Reply from {r.vasp_name} received on Sahyog for <b>{r.sahyog_ref}</b></div>
                  <div className="grid gap-2 md:grid-cols-3">
                    <input className="rounded-lg border border-line bg-card px-3 py-2 text-sm" placeholder="Account ref (e.g. ACC-…)" value={form.account} onChange={(e) => setForm({ ...form, account: e.target.value })} />
                    <input className="rounded-lg border border-line bg-card px-3 py-2 text-sm" placeholder="Amount frozen (USD)" type="number" value={form.frozen} onChange={(e) => setForm({ ...form, frozen: e.target.value })} />
                    <input className="rounded-lg border border-line bg-card px-3 py-2 text-sm" placeholder="Note (optional)" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
                  </div>
                  {err && <div className="mt-2 text-sm text-red">{err}</div>}
                  <div className="mt-3 flex flex-wrap justify-end gap-2">
                    <Button variant="ghost" className="px-3 py-1.5 text-xs" onClick={() => setRecording(null)}>Cancel</Button>
                    <Button variant="danger" className="px-3 py-1.5 text-xs" onClick={() => reply(r, 'denied')}>Denied: not their address</Button>
                    <Button variant="teal" className="px-3 py-1.5 text-xs" onClick={() => reply(r, 'confirmed')}>Confirmed: their deposit address</Button>
                  </div>
                </div>
              )}
              {open === r.id && <pre className="mt-3 whitespace-pre-wrap rounded-xl border border-line bg-paper p-4 font-sans text-sm">{r.body_md.replace(/\*\*/g, '').replace(/\*/g, '').replace(/`/g, '')}</pre>}
            </Card>
          ))}
        </div>
      )}
    </>
  )
}
