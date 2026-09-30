import type { Candidate, Contribution } from '../api/types'
import { cx } from './ui'

const COLORS: Record<string, string> = {
  label_tier: '#1F5FBF', sweep: '#0F7A6B', history: '#7A4FBF', value: '#D35F1F', recency: '#C99A2E', ext_tag: '#5B6477',
}

/** Confidence broken into additive factor points (they sum to confidence x 100). */
export function ScoreBreakdown({ c }: { c: Candidate }) {
  const parts = c.explain?.contributions ?? []
  if (!parts.length) return null
  return (
    <div className="space-y-2">
      <div className="flex h-3 overflow-hidden rounded-full bg-line" title={`confidence ${c.confidence.toFixed(2)}`}>
        {parts.map((p) => <div key={p.factor} style={{ width: `${p.points}%`, background: COLORS[p.factor] ?? '#9AA5B8' }} />)}
      </div>
      <div className="space-y-1">
        {parts.map((p) => (
          <div key={p.factor} className="flex items-center justify-between gap-2 text-xs">
            <span className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: COLORS[p.factor] ?? '#9AA5B8' }} />{p.label}</span>
            <span className="tabular-nums text-muted">signal {p.signal.toFixed(2)} × w {p.weight.toFixed(2)} → <b className="text-ink">+{p.points.toFixed(1)}</b></span>
          </div>
        ))}
        {c.explain && c.explain.path_factor < 1 && <div className="text-xs text-orange-ink">× path factor {c.explain.path_factor.toFixed(2)} (bridge / cross-chain)</div>}
      </div>
    </div>
  )
}

export function WhatIfList({ c }: { c: Candidate }) {
  const w = c.explain?.what_if ?? []
  if (!w.length) return null
  return (
    <div className="space-y-1 text-xs">
      {w.map((s) => (
        <div key={s.scenario} className="flex justify-between gap-2">
          <span className="text-body">{s.scenario}</span>
          <span className={cx('whitespace-nowrap font-semibold tabular-nums', s.delta > 0 ? 'text-teal' : 'text-red')}>
            {c.confidence.toFixed(2)} → {s.confidence.toFixed(2)}</span>
        </div>
      ))}
    </div>
  )
}

/** Side-by-side matrix of every candidate VASP: rank inputs, factor points and evidence. Best value per row is highlighted. */
export function CompareAll({ cands }: { cands: Candidate[] }) {
  const pts = cands.map((c) => new Map((c.explain?.contributions ?? []).map((p) => [p.factor, p])))
  const factors = [...new Map(cands.flatMap((c) => c.explain?.contributions ?? []).map((p) => [p.factor, p.label])).entries()]
  const top = cands[0]?.rank_score || 1
  type Row = { label: string; vals: number[]; fmt: (v: number) => string; best?: 'max' | 'min'; hint?: string }
  const rows: Row[] = [
    { label: 'Rank score', vals: cands.map((c) => c.rank_score), fmt: (v) => v.toFixed(3), best: 'max', hint: 'value × confidence × actionability' },
    { label: 'Value reached', vals: cands.map((c) => c.value_share), fmt: (v) => `${Math.round(v * 100)}%`, best: 'max' },
    { label: 'Value (USD)', vals: cands.map((c) => c.value_usd ?? 0), fmt: (v) => '$' + v.toLocaleString('en-US', { maximumFractionDigits: 0 }), best: 'max' },
    { label: 'Confidence', vals: cands.map((c) => c.confidence), fmt: (v) => v.toFixed(2), best: 'max' },
    { label: 'Actionability', vals: cands.map((c) => c.actionability), fmt: (v) => v.toFixed(2), best: 'max', hint: 'FIU-IND / Sahyog reachability' },
    { label: 'Hops from suspect', vals: cands.map((c) => c.hops), fmt: (v) => String(v), best: 'min' },
    ...factors.map(([k, label]) => ({ label: `  ${label}`, vals: pts.map((m) => m.get(k)?.points ?? 0), fmt: (v: number) => `+${v.toFixed(1)}`, best: 'max' as const })),
  ]
  const bestOf = (r: Row) => (r.best === 'min' ? Math.min(...r.vals) : Math.max(...r.vals))
  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        {cands.map((c, i) => (
          <div key={c.id} className="flex items-center gap-3 text-sm">
            <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-navy text-[10px] font-bold text-white">{i + 1}</span>
            <span className="w-28 shrink-0 truncate font-semibold">{c.vasp_name}</span>
            <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-line"><div className={cx('h-full rounded-full', i === 0 ? 'bg-teal' : 'bg-blue/60')} style={{ width: `${(c.rank_score / top) * 100}%` }} /></div>
            <span className="w-12 text-right text-xs tabular-nums text-muted">{c.rank_score.toFixed(3)}</span>
          </div>
        ))}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[520px] text-sm">
          <thead className="text-left text-xs text-muted">
            <tr><th className="py-1.5 pr-3">Factor</th>{cands.map((c, i) => <th key={c.id} className="px-2 py-1.5 text-right"><div className="text-ink">{i + 1}. {c.vasp_name}</div>
              <div className="font-normal">{c.address_kind.replace('_', ' ')}{c.chain !== 'tron' ? ` · ${c.chain}` : ''}</div></th>)}</tr>
          </thead>
          <tbody className="divide-y divide-line">
            {rows.map((r) => {
              const b = bestOf(r)
              const tie = r.vals.every((v) => v === b)
              return (
                <tr key={r.label} className={r.label.startsWith('  ') ? 'text-xs' : ''}>
                  <td className={cx('py-1.5 pr-3 whitespace-pre', r.label.startsWith('  ') && 'text-muted')} title={r.hint}>{r.label}{r.hint && <span className="text-muted"> ⓘ</span>}</td>
                  {r.vals.map((v, i) => <td key={i} className={cx('px-2 py-1.5 text-right tabular-nums', !tie && v === b && 'font-bold text-teal')}>{r.fmt(v)}</td>)}
                </tr>
              )
            })}
            <tr className="text-xs"><td className="py-1.5 pr-3">Funds status</td>{cands.map((c) => <td key={c.id} className={cx('px-2 py-1.5 text-right', c.funds_status === 'at_deposit' && 'font-bold text-orange-ink')}>{c.funds_status.replace('_', ' ')}</td>)}</tr>
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted">Factor rows are confidence points (signal × weight); they add up to confidence × 100. Highlighted = strongest value in that row. Ranking comes only from labels, rules and scores; no LLM is involved.</p>
    </div>
  )
}

/** "Why A, not B?" — factor-by-factor gap, computed from both candidates' stored breakdowns. */
export function Compare({ a, b }: { a: Candidate; b: Candidate }) {
  const pa = new Map<string, Contribution>((a.explain?.contributions ?? []).map((p) => [p.factor, p]))
  const pb = new Map<string, Contribution>((b.explain?.contributions ?? []).map((p) => [p.factor, p]))
  const keys = [...new Set([...pa.keys(), ...pb.keys()])]
  const rows = keys.map((k) => ({ k, label: (pa.get(k) ?? pb.get(k))!.label, a: pa.get(k)?.points ?? 0, b: pb.get(k)?.points ?? 0 }))
    .sort((x, y) => Math.abs(y.a - y.b) - Math.abs(x.a - x.b))
  const valueGap = a.value_share - b.value_share
  return (
    <div className="space-y-4">
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-muted"><tr><th className="py-1">Factor</th><th className="py-1 text-right">{a.vasp_name}</th><th className="py-1 text-right">{b.vasp_name}</th><th className="py-1 text-right">Gap</th></tr></thead>
        <tbody className="divide-y divide-line">
          {rows.map((r) => (
            <tr key={r.k}><td className="py-1.5">{r.label}</td><td className="py-1.5 text-right tabular-nums">+{r.a.toFixed(1)}</td>
              <td className="py-1.5 text-right tabular-nums">+{r.b.toFixed(1)}</td>
              <td className={cx('py-1.5 text-right font-semibold tabular-nums', r.a - r.b >= 0 ? 'text-teal' : 'text-red')}>{(r.a - r.b >= 0 ? '+' : '') + (r.a - r.b).toFixed(1)}</td></tr>
          ))}
          <tr className="font-semibold"><td className="py-1.5">Confidence</td><td className="py-1.5 text-right">{a.confidence.toFixed(2)}</td><td className="py-1.5 text-right">{b.confidence.toFixed(2)}</td><td /></tr>
          <tr><td className="py-1.5">Value reached</td><td className="py-1.5 text-right">{Math.round(a.value_share * 100)}%</td><td className="py-1.5 text-right">{Math.round(b.value_share * 100)}%</td><td /></tr>
          <tr><td className="py-1.5">Actionability</td><td className="py-1.5 text-right">{a.actionability.toFixed(2)}</td><td className="py-1.5 text-right">{b.actionability.toFixed(2)}</td><td /></tr>
        </tbody>
      </table>
      <p className="text-sm text-body">
        {a.vasp_name} ranks above {b.vasp_name} mainly on <b>{rows[0]?.label.toLowerCase() ?? 'evidence'}</b>
        {Math.abs(valueGap) >= 0.05 && <> and receives {Math.round(Math.abs(valueGap) * 100)} percentage points {valueGap > 0 ? 'more' : 'less'} of the traced value</>}.
        Rank = value reached × confidence × actionability ({a.rank_score.toFixed(3)} vs {b.rank_score.toFixed(3)}).
      </p>
    </div>
  )
}
