import type { Analysis } from '../api/types'
import { Badge, Empty, cx, short, txUrl } from './ui'

export const LEVEL_TONE = { low: 'teal', medium: 'blue', high: 'orange', critical: 'red' } as const

export function RiskBadge({ analysis }: { analysis: Analysis | null | undefined }) {
  const r = analysis?.risk
  if (!r) return null
  return <Badge tone={LEVEL_TONE[r.level]}>Risk {r.level.toUpperCase()} · {r.overall}/100</Badge>
}

export default function RiskPanel({ analysis, chain }: { analysis: Analysis | null | undefined; chain: string }) {
  const r = analysis?.risk
  if (!r) return <div className="p-6"><Empty>Re-run the trace to compute the risk profile.</Empty></div>
  const barColor = (s: number) => (s >= 75 ? 'bg-red' : s >= 55 ? 'bg-orange' : s >= 30 ? 'bg-blue' : 'bg-teal')
  return (
    <div className="grid h-full gap-6 overflow-auto p-5 lg:grid-cols-2">
      <div>
        <div className="mb-3 flex items-center justify-between">
          <h3 className="font-semibold">Risk profile</h3><RiskBadge analysis={analysis} />
        </div>
        {(r.categories ?? []).map((cat) => (
          <div key={cat.code} className="mb-3 rounded-xl border border-red/30 bg-red-tint p-3 text-sm">
            <div className="flex flex-wrap items-center gap-2"><Badge tone="red">High-risk exposure</Badge><b className="text-red">{cat.label}</b></div>
            <div className="mt-1 text-xs text-body">{cat.entities.join(', ')} · OFAC SDN programs {cat.programs.join(', ')} · {cat.addresses.length} address{cat.addresses.length > 1 ? 'es' : ''} on this trail</div>
          </div>
        ))}
        <div className="space-y-3">
          {r.axes.map((a) => (
            <div key={a.key}>
              <div className="flex justify-between text-sm"><span className="font-medium">{a.label}</span><span className="tabular-nums text-muted">{a.score}</span></div>
              <div className="mt-1 h-2 rounded-full bg-line"><div className={cx('h-2 rounded-full', barColor(a.score))} style={{ width: `${a.score}%` }} /></div>
              <div className="mt-0.5 text-xs text-muted">{a.why}</div>
            </div>
          ))}
        </div>
        <p className="mt-4 text-xs text-muted">Rule outputs on this trace (see config/heuristics.yaml), not probabilities.</p>
      </div>
      <div>
        <h3 className="mb-3 font-semibold">Detected laundering typologies</h3>
        {!analysis?.typologies?.length ? <Empty>No typology rule fired on this trace.</Empty> : (
          <div className="space-y-3">
            {analysis.typologies.map((t, i) => (
              <div key={t.code + i} className="rounded-xl border border-line p-3">
                <div className="flex items-center gap-2"><Badge tone={t.severity === 'critical' ? 'red' : t.severity === 'high' ? 'orange' : 'blue'}>{t.severity}</Badge><b className="text-sm">{t.name}</b></div>
                <div className="mt-1 text-sm text-body">{t.detail}</div>
                {t.tx.length > 0 && <div className="mt-1 flex flex-wrap gap-x-3 text-xs">{t.tx.slice(0, 4).map((h) => <a key={h} className="addr text-blue hover:underline" href={txUrl(chain, h)} target="_blank" rel="noreferrer">{short(h)}</a>)}</div>}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
