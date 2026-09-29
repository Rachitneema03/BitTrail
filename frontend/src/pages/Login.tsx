import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { Logo } from '../components/Layout'
import { Button, Card } from '../components/ui'
import { useAuth } from '../store/auth'

interface DemoUsers { password: string; users: { email: string; name: string; role: string }[] }

export default function Login() {
  const { login } = useAuth()
  const nav = useNavigate()
  const [demo, setDemo] = useState<DemoUsers | null>(null)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { api<DemoUsers>('/auth/demo-users').then(setDemo).catch(() => null) }, [])

  const go = async (e: string, p: string) => {
    setBusy(true); setErr('')
    try {
      const u = await login(e, p)
      nav(u.role === 'vasp' ? '/vasp' : '/')
    } catch (x) { setErr((x as Error).message) } finally { setBusy(false) }
  }

  return (
    <div className="grid min-h-full lg:grid-cols-2">
      <div className="hidden flex-col justify-between bg-navy p-12 text-paper lg:flex">
        <Logo light />
        <div>
          <h1 className="font-serif text-5xl font-bold leading-tight">From suspect wallet<br />to the exchange<br />that can freeze it.</h1>
          <p className="mt-6 max-w-md text-lg text-[#C9D2E3]">Automated, explainable attribution of unknown crypto wallets to the nearest VASP, with a court-ready evidence pack and a drafted Sahyog request.</p>
        </div>
        <div className="text-sm text-white/50">SIH 2026 · PS 26182 (MHA / I4C) · Team TrackSense · Prototype</div>
      </div>
      <div className="flex items-center justify-center p-6">
        <div className="w-full max-w-md">
          <div className="mb-8 lg:hidden"><Logo /></div>
          <h2 className="font-serif text-3xl font-bold">Sign in</h2>
          <p className="mt-1 text-sm text-muted">Prototype with demo accounts. No real personal data.</p>
          <form className="mt-6 space-y-3" onSubmit={(e) => { e.preventDefault(); go(email, password) }}>
            <input className="w-full rounded-lg border border-line bg-card px-3 py-2.5" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} />
            <input className="w-full rounded-lg border border-line bg-card px-3 py-2.5" placeholder="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
            {err && <div className="text-sm text-red">{err}</div>}
            <Button className="w-full py-2.5" disabled={busy}>Sign in</Button>
          </form>
          {demo && (
            <Card className="mt-8 p-4">
              <div className="mb-3 text-sm font-semibold">One-click demo roles</div>
              <div className="grid gap-2">
                {demo.users.map((u) => (
                  <button key={u.email} disabled={busy} onClick={() => go(u.email, demo.password)}
                    className="flex items-center justify-between rounded-lg border border-line px-3 py-2 text-left text-sm hover:bg-paper">
                    <span className="font-medium">{u.name}</span>
                    <span className="text-xs text-muted">{u.role === 'io' ? 'Officer' : u.role === 'analyst' ? 'I4C' : 'VASP'}</span>
                  </button>
                ))}
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}
