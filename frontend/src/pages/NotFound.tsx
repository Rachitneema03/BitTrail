import { Link, useLocation } from 'react-router-dom'
import { Logo } from '../components/Layout'
import { Card } from '../components/ui'
import { useAuth } from '../store/auth'

/** A trail that goes cold: suspect → hop → hop → dashed break → unresolved node. */
function ColdTrail() {
  return (
    <svg viewBox="0 0 420 120" className="h-auto w-full max-w-md" aria-hidden>
      <path d="M24 92 L112 44 L196 78" fill="none" stroke="#D35F1F" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M196 78 L282 36" fill="none" stroke="#D35F1F" strokeWidth="6" strokeLinecap="round" strokeDasharray="2 14" opacity="0.55" />
      <path d="M300 30 L396 64" fill="none" stroke="#9AA5B8" strokeWidth="3" strokeLinecap="round" strokeDasharray="6 10" opacity="0.6" />
      <circle cx="24" cy="92" r="11" fill="#D35F1F" />
      <circle cx="112" cy="44" r="8" fill="#14213D" />
      <circle cx="196" cy="78" r="8" fill="#14213D" />
      <circle cx="396" cy="64" r="16" fill="none" stroke="#9AA5B8" strokeWidth="3" strokeDasharray="5 5" />
      <text x="396" y="71" textAnchor="middle" fontSize="20" fontWeight="700" fill="#9AA5B8">?</text>
    </svg>
  )
}

export default function NotFound({ embedded = false, what = 'page' }: { embedded?: boolean; what?: 'page' | 'case' }) {
  const { me } = useAuth()
  const { pathname } = useLocation()
  const home = me ? '/' : '/login'
  const body = (
    <Card className="mx-auto w-full max-w-2xl p-8 text-center md:p-12">
      <div className="flex justify-center"><ColdTrail /></div>
      <div className="mt-6 text-xs font-semibold tracking-[0.2em] text-orange-ink">ERROR 404 · TRAIL WENT COLD</div>
      <h1 className="mt-2 font-serif text-3xl font-bold text-ink md:text-4xl">
        {what === 'case' ? 'No case at this address' : 'No page at this address'}
      </h1>
      <p className="mx-auto mt-3 max-w-md text-sm text-muted">
        {what === 'case'
          ? 'This case may have been removed, or the link is incomplete. Like a trail that stops at an unlabelled wallet, there is nothing further to attribute here.'
          : 'We followed the link but it leads nowhere. Check the address, or go back to a known starting point.'}
      </p>
      <div className="mx-auto mt-4 max-w-md truncate rounded-lg border border-line bg-paper px-3 py-1.5 font-mono text-xs text-muted" title={pathname}>{pathname}</div>
      <div className="mt-6 flex flex-wrap justify-center gap-2">
        <Link to={home} className="rounded-lg bg-navy px-4 py-2 text-sm font-semibold text-paper hover:bg-navy-2">
          {me ? 'Dashboard' : 'Sign in'}</Link>
        {me && <>
          <Link to="/cases" className="rounded-lg border border-line bg-card px-4 py-2 text-sm font-semibold text-ink hover:bg-paper">All cases</Link>
          <Link to="/cases/new" className="rounded-lg bg-orange px-4 py-2 text-sm font-semibold text-white hover:brightness-110">+ New case</Link>
        </>}
      </div>
    </Card>
  )
  if (embedded) return <div className="py-6">{body}</div>
  return (
    <div className="flex min-h-full flex-col bg-paper">
      <header className="p-5"><Link to={home}><Logo /></Link></header>
      <main className="flex flex-1 items-center justify-center px-4 pb-16">{body}</main>
    </div>
  )
}
