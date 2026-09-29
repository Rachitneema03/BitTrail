import type { ButtonHTMLAttributes, ReactNode } from 'react'

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(' ')

export const IST = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) + ' IST' : '-'
export const usd = (n: number | null | undefined) => (n == null ? '-' : '$' + n.toLocaleString('en-US', { maximumFractionDigits: 0 }))
export const pct = (n: number) => `${Math.round(n * 100)}%`
export const short = (a: string) => (a.length > 14 ? `${a.slice(0, 6)}…${a.slice(-4)}` : a)

const EXPLORER_TX: Record<string, string> = {
  tron: 'https://tronscan.org/#/transaction/', ethereum: 'https://etherscan.io/tx/', polygon: 'https://polygonscan.com/tx/', bitcoin: 'https://mempool.space/tx/',
}
const EXPLORER_ADDR: Record<string, string> = {
  tron: 'https://tronscan.org/#/address/', ethereum: 'https://etherscan.io/address/', polygon: 'https://polygonscan.com/address/', bitcoin: 'https://mempool.space/address/',
}
export const txUrl = (chain: string, tx: string) => (EXPLORER_TX[chain] ?? '') + tx
export const addrUrl = (chain: string, a: string) => (EXPLORER_ADDR[chain] ?? '') + a

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx('rounded-2xl border border-line bg-card', className)}>{children}</div>
}

export function Button({ variant = 'primary', className, ...p }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'ghost' | 'teal' | 'orange' | 'danger' }) {
  const v = {
    primary: 'bg-navy text-paper hover:bg-navy-2',
    teal: 'bg-teal text-white hover:brightness-110',
    orange: 'bg-orange text-white hover:brightness-110',
    danger: 'bg-red text-white hover:brightness-110',
    ghost: 'border border-line bg-card text-ink hover:bg-paper',
  }[variant]
  return <button {...p} className={cx('inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50', v, className)} />
}

export function Badge({ tone = 'grey', children }: { tone?: 'grey' | 'teal' | 'orange' | 'blue' | 'red' | 'navy'; children: ReactNode }) {
  const t = {
    grey: 'bg-paper text-muted border-line', teal: 'bg-teal-tint text-teal border-teal/20', orange: 'bg-orange-tint text-orange-ink border-orange/20',
    blue: 'bg-blue-tint text-blue border-blue/20', red: 'bg-red-tint text-red border-red/20', navy: 'bg-navy text-paper border-navy',
  }[tone]
  return <span className={cx('inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-semibold', t)}>{children}</span>
}

export function Stat({ label, value, tone = 'ink', sub }: { label: string; value: ReactNode; tone?: 'ink' | 'orange' | 'teal' | 'blue'; sub?: string }) {
  const c = { ink: 'text-ink', orange: 'text-orange', teal: 'text-teal', blue: 'text-blue' }[tone]
  return (
    <Card className="p-5">
      <div className="text-sm text-muted">{label}</div>
      <div className={cx('mt-1 text-3xl font-bold tabular-nums', c)}>{value}</div>
      {sub && <div className="mt-1 text-xs text-muted">{sub}</div>}
    </Card>
  )
}

export function PageHeader({ title, sub, right }: { title: string; sub?: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="font-serif text-3xl font-bold text-ink">{title}</h1>
        {sub && <div className="mt-1 text-sm text-muted">{sub}</div>}
      </div>
      {right}
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="rounded-2xl border border-dashed border-line p-10 text-center text-sm text-muted">{children}</div>
}

export function StatusBadge({ status }: { status: string }) {
  const tone = ({ attributed: 'teal', request_sent: 'blue', tracing: 'orange', open: 'grey', closed: 'navy', confirmed: 'teal', denied: 'red', sent: 'blue', draft: 'grey' } as const)[status as 'open'] ?? 'grey'
  return <Badge tone={tone}>{status.replace('_', ' ')}</Badge>
}

export function ConfBar({ value, tone = 'teal' }: { value: number; tone?: 'teal' | 'orange' | 'blue' }) {
  const c = { teal: 'bg-teal', orange: 'bg-orange', blue: 'bg-blue' }[tone]
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-24 overflow-hidden rounded-full bg-line"><div className={cx('h-full rounded-full', c)} style={{ width: `${Math.round(value * 100)}%` }} /></div>
      <span className="text-sm font-semibold tabular-nums">{value.toFixed(2)}</span>
    </div>
  )
}
