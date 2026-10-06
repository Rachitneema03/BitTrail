import { useEffect, useState } from 'react'
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom'
import { api, streamUrl } from '../api/client'
import type { Health, Stats } from '../api/types'
import { useAuth } from '../store/auth'
import { cx } from './ui'

export function Logo({ light = false }: { light?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <svg width="34" height="34" viewBox="0 0 64 64" aria-hidden><rect width="64" height="64" rx="14" fill={light ? '#FDFDFE' : '#14213D'} />
        <path d="M14 44 L28 24 L38 36 L50 18" fill="none" stroke="#D35F1F" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="14" cy="44" r="6" fill="#D35F1F" /><circle cx="50" cy="18" r="7" fill="#0F7A6B" /></svg>
      <div className="leading-tight">
        <div className={cx('font-serif text-xl font-bold', light ? 'text-paper' : 'text-ink')}>BitTrail</div>
        <div className={cx('text-[11px] font-semibold tracking-wider', light ? 'text-[#F0A36B]' : 'text-orange-ink')}>TRACE · ATTRIBUTE · FREEZE</div>
      </div>
    </div>
  )
}

interface LiveAlert { id: string; case_id: string; case_no: number | null; type: string; severity: string; message: string }

export default function Layout() {
  const { me, logout } = useAuth()
  const nav = useNavigate()
  const [health, setHealth] = useState<Health | null>(null)
  const [open, setOpen] = useState(false)
  const [unread, setUnread] = useState(0)
  const [toasts, setToasts] = useState<LiveAlert[]>([])
  const [live, setLive] = useState(false)
  useEffect(() => { api<Health>('/health').then(setHealth).catch(() => null) }, [])
  useEffect(() => { api<Stats>('/stats').then((s) => setUnread(s.unread_alerts)).catch(() => null) }, [])

  // real-time alerts: server-sent events, pushed within ~2 s of the watch poller or a trace raising them
  useEffect(() => {
    if (!me) return
    const es = new EventSource(streamUrl('/alerts/stream'))
    es.onopen = () => setLive(true)
    es.onerror = () => setLive(false)
    es.addEventListener('alert', (ev) => {
      const a = JSON.parse((ev as MessageEvent).data) as LiveAlert
      setUnread((n) => n + 1)
      setToasts((t) => [a, ...t].slice(0, 4))
      setTimeout(() => setToasts((t) => t.filter((x) => x.id !== a.id)), 12000)
    })
    return () => es.close()
  }, [me])

  const links = [{ to: '/', label: 'Dashboard' }, { to: '/cases', label: 'Cases' }, { to: '/cases/new', label: 'New case' },
    { to: '/requests', label: 'Sahyog requests' }, { to: '/alerts', label: 'Alerts', badge: unread },
    ...(me?.role === 'analyst' ? [{ to: '/audit', label: 'Audit log' }] : [])]

  return (
    <div className="flex min-h-full flex-col md:flex-row">
      <aside className="bg-navy text-paper md:sticky md:top-0 md:h-screen md:w-64 md:shrink-0">
        <div className="flex items-center justify-between p-5 md:block">
          <Logo light />
          <button className="rounded-lg border border-white/20 px-3 py-1.5 text-sm md:hidden" onClick={() => setOpen(!open)}>Menu</button>
        </div>
        <nav className={cx('flex-col gap-1 px-3 pb-4 md:flex', open ? 'flex' : 'hidden')}>
          {links.map((l) => (
            <NavLink key={l.to} to={l.to} end={l.to === '/' || l.to === '/cases'} onClick={() => { setOpen(false); if (l.to === '/alerts') setUnread(0) }}
              className={({ isActive }) => cx('flex items-center justify-between rounded-lg px-3 py-2 text-sm font-medium transition',
                isActive ? 'bg-white/12 text-white' : 'text-[#C9D2E3] hover:bg-white/6 hover:text-white')}>
              {l.label}
              {'badge' in l && (l.badge ?? 0) > 0 && <span className="rounded-full bg-orange px-2 text-[11px] font-bold text-white">{l.badge}</span>}
            </NavLink>
          ))}
          <div className="mt-6 border-t border-white/10 px-3 pt-4 text-xs text-[#C9D2E3] md:absolute md:bottom-4 md:left-3 md:right-3">
            <div className="font-semibold text-white">{me?.name}</div>
            <div className="mt-0.5">{me?.role === 'io' ? 'Investigating officer' : 'I4C analyst'}</div>
            {health && (
              <div className="mt-2 flex flex-wrap gap-1">
                {Object.entries(health.chains).map(([c, on]) => {
                  const src = health.chain_sources?.[c]
                  return <span key={c} title={src ? `${src.source}${src.keyless ? ' (no API key needed)' : ''}` : undefined}
                    className={cx('rounded px-1.5 py-0.5 text-[10px] font-semibold', on ? 'bg-teal/40 text-white' : 'bg-white/10 text-white/50')}>{c}</span>
                })}
                {health.demo_mode && <span className="rounded bg-orange/60 px-1.5 py-0.5 text-[10px] font-semibold text-white">demo mode</span>}
                {health.ai && <span className={cx('rounded px-1.5 py-0.5 text-[10px] font-semibold', health.ai.configured ? 'bg-teal/40 text-white' : 'bg-white/10 text-white/50')}>Sarvam AI</span>}
                {health.bridge_tracker && <span title={health.bridge_tracker} className="rounded bg-[#7A4FBF]/60 px-1.5 py-0.5 text-[10px] font-semibold text-white">cross-chain</span>}
              </div>
            )}
            <div className="mt-2 flex items-center gap-1.5 text-[10px]"><span className={cx('h-1.5 w-1.5 rounded-full', live ? 'animate-pulse bg-teal' : 'bg-white/30')} />{live ? 'Live alerts connected' : 'Live alerts offline'}</div>
            <button className="mt-3 text-[#F0A36B] hover:underline" onClick={() => { logout(); nav('/login') }}>Sign out</button>
            <div className="mt-3 text-[10px] text-white/40">SIH 2026 · PS 26182 · Team TrackSense</div>
          </div>
        </nav>
      </aside>
      <main className="min-w-0 flex-1 p-4 md:p-8"><Outlet /></main>
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[min(380px,calc(100vw-32px))] flex-col gap-2">
        {toasts.map((t) => (
          <Link key={t.id} to={`/cases/${t.case_id}`} onClick={() => setToasts((x) => x.filter((y) => y.id !== t.id))}
            className={cx('pointer-events-auto rounded-xl border bg-card p-3 text-sm shadow-xl', t.severity === 'high' ? 'border-red/40' : 'border-orange/40')}>
            <div className="mb-0.5 flex items-center gap-2 text-xs font-bold uppercase tracking-wide">
              <span className={cx('h-2 w-2 rounded-full', t.severity === 'high' ? 'bg-red' : 'bg-orange')} />{t.type.replaceAll('_', ' ')}{t.case_no ? ` · Case #${t.case_no}` : ''}
            </div>
            <div className="text-body">{t.message}</div>
          </Link>
        ))}
      </div>
    </div>
  )
}
