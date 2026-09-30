import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { post } from '../api/client'
import { Button, Card, PageHeader } from '../components/ui'

const detect = (a: string) => /^T[1-9A-HJ-NP-Za-km-z]{33}$/.test(a) ? 'tron' : /^0x[0-9a-fA-F]{40}$/.test(a) ? 'ethereum'
  : /^(bc1[0-9a-z]{11,71}|[13][1-9A-HJ-NP-Za-km-z]{25,33})$/.test(a) ? 'bitcoin' : /^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(a) ? 'solana' : ''

export default function NewCase() {
  const nav = useNavigate()
  const [f, setF] = useState({ title: '', fir_no: '', ncrp_id: '', police_station: '', state: '', fraud_type: 'Investment scam',
    fraud_time: new Date(Date.now() - 7 * 864e5).toISOString().slice(0, 16), amount_inr: '' })
  const [wallets, setWallets] = useState([{ address: '', chain: '' }])
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value })

  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setErr(''); setBusy(true)
    try {
      const r = await post<{ id: string }>('/cases', {
        ...f, amount_inr: f.amount_inr ? Number(f.amount_inr) : null, fraud_time: new Date(f.fraud_time).toISOString(),
        wallets: wallets.filter((w) => w.address.trim()).map((w) => ({ address: w.address.trim(), chain: w.chain || undefined })),
      })
      nav(`/cases/${r.id}`)
    } catch (x) { setErr((x as Error).message) } finally { setBusy(false) }
  }
  const input = 'w-full rounded-lg border border-line bg-card px-3 py-2'
  const label = 'mb-1 block text-sm font-medium'

  return (
    <>
      <PageHeader title="New case" sub="Case intake. In production this arrives automatically from Sahyog (POST /api/v1/sahyog/webhook)." />
      <form onSubmit={submit} className="grid max-w-4xl gap-6">
        <Card className="grid gap-4 p-6 md:grid-cols-2">
          <div className="md:col-span-2"><label className={label}>Title</label><input className={input} value={f.title} onChange={set('title')} placeholder="e.g. Fake trading app, USDT investment scam" /></div>
          <div><label className={label}>FIR no. *</label><input required className={input} value={f.fir_no} onChange={set('fir_no')} /></div>
          <div><label className={label}>NCRP complaint ID</label><input className={input} value={f.ncrp_id} onChange={set('ncrp_id')} /></div>
          <div><label className={label}>Police station</label><input className={input} value={f.police_station} onChange={set('police_station')} /></div>
          <div><label className={label}>State / UT</label><input className={input} value={f.state} onChange={set('state')} /></div>
          <div><label className={label}>Fraud type</label>
            <select className={input} value={f.fraud_type} onChange={set('fraud_type')}>
              {['Investment scam', 'Job / task scam', 'Digital arrest', 'Romance / pig-butchering', 'Ransomware', 'Loan app', 'Other'].map((t) => <option key={t}>{t}</option>)}
            </select></div>
          <div><label className={label}>Amount lost (₹)</label><input type="number" className={input} value={f.amount_inr} onChange={set('amount_inr')} /></div>
          <div className="md:col-span-2"><label className={label}>Fraud / first payment time *</label>
            <input required type="datetime-local" className={input} value={f.fraud_time} onChange={set('fraud_time')} />
            <p className="mt-1 text-xs text-muted">The trace follows funds that left the suspect wallet after this time (90-day window).</p></div>
        </Card>
        <Card className="p-6">
          <div className="mb-3 font-semibold">Suspect wallet(s)</div>
          {wallets.map((w, i) => (
            <div key={i} className="mb-3 flex flex-wrap gap-2">
              <input required={i === 0} className={`${input} addr min-w-[280px] flex-1`} placeholder="Tron T… / EVM 0x… / Bitcoin bc1… / Solana address" value={w.address}
                onChange={(e) => setWallets(wallets.map((x, j) => (j === i ? { address: e.target.value, chain: detect(e.target.value.trim()) } : x)))} />
              <select className={`${input} w-40`} value={w.chain} onChange={(e) => setWallets(wallets.map((x, j) => (j === i ? { ...x, chain: e.target.value } : x)))}>
                <option value="">auto-detect</option><option value="tron">Tron</option><option value="ethereum">Ethereum</option><option value="polygon">Polygon</option>
                <option value="bsc">BNB Chain</option><option value="solana">Solana</option><option value="bitcoin">Bitcoin</option>
              </select>
            </div>
          ))}
          <button type="button" className="text-sm font-semibold text-blue" onClick={() => setWallets([...wallets, { address: '', chain: '' }])}>+ Add wallet</button>
        </Card>
        {err && <div className="text-sm text-red">{err}</div>}
        <div><Button variant="orange" disabled={busy} className="px-6 py-2.5">{busy ? 'Creating…' : 'Create case and start trace'}</Button></div>
      </form>
    </>
  )
}
