import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, post } from '../api/client'
import type { ReqT } from '../api/types'
import { Badge, Button, Card, Empty, IST, PageHeader, StatusBadge, short } from '../components/ui'

export default function Requests() {
  const [rows, setRows] = useState<ReqT[] | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const load = () => api<ReqT[]>('/requests').then(setRows)
  useEffect(() => { load() }, [])
  const send = async (id: string) => { await post(`/requests/${id}/send`); load() }

  return (
    <>
      <PageHeader title="Sahyog requests" sub="Drafted notices under Section 94 BNSS, routed to VASPs (Sahyog integration mocked in this prototype)" />
      {rows === null ? <Empty>Loading…</Empty> : rows.length === 0 ? <Empty>No requests yet. Open a case and draft a notice from a candidate VASP.</Empty> : (
        <div className="space-y-3">
          {rows.map((r) => (
            <Card key={r.id} className="p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="flex flex-wrap items-center gap-2"><b>{r.vasp_name}</b><StatusBadge status={r.status} /><Badge>{r.type.replaceAll('_', ' ')}</Badge>{r.sahyog_ref && <Badge tone="blue">{r.sahyog_ref}</Badge>}</div>
                  <div className="mt-1 text-xs text-muted"><Link to={`/cases/${r.case_id}`} className="text-blue hover:underline">Case #{r.case_no}</Link> · FIR {r.fir_no} · {r.legal_basis} · {r.addresses.map(short).join(', ')} · {IST(r.sent_at ?? r.created_at)}</div>
                  {r.reply && <div className="mt-2 text-sm">{r.reply.outcome === 'confirmed'
                    ? <span className="text-teal">✓ Confirmed by {r.vasp_name}: account {r.reply.account_ref ?? '-'}{r.reply.frozen_amount_usd ? `, $${r.reply.frozen_amount_usd.toLocaleString()} frozen` : ''}</span>
                    : <span className="text-red">Denied by {r.vasp_name}{r.reply.note ? `: ${r.reply.note}` : ''}</span>}</div>}
                </div>
                <div className="flex gap-2">
                  <Button variant="ghost" className="px-3 py-1.5 text-xs" onClick={() => setOpen(open === r.id ? null : r.id)}>{open === r.id ? 'Hide' : 'View'} notice</Button>
                  {r.status === 'draft' && <Button variant="teal" className="px-3 py-1.5 text-xs" onClick={() => send(r.id)}>Send via Sahyog</Button>}
                </div>
              </div>
              {open === r.id && <pre className="mt-3 whitespace-pre-wrap rounded-xl border border-line bg-paper p-4 font-sans text-sm">{r.body_md.replace(/\*\*/g, '').replace(/\*/g, '').replace(/`/g, '')}</pre>}
            </Card>
          ))}
        </div>
      )}
    </>
  )
}
