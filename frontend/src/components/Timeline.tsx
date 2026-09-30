import type { TimelineEvent } from '../api/types'
import { Badge, Empty, IST, cx, short, txUrl } from './ui'

const KIND: Record<TimelineEvent['kind'], { tone: 'grey' | 'teal' | 'orange' | 'blue' | 'red' | 'navy'; label: string; dot: string }> = {
  case: { tone: 'orange', label: 'case', dot: 'bg-orange' },
  onchain: { tone: 'grey', label: 'on-chain', dot: 'bg-muted' },
  system: { tone: 'navy', label: 'BitTrail', dot: 'bg-navy' },
  alert: { tone: 'orange', label: 'alert', dot: 'bg-orange' },
  evidence: { tone: 'teal', label: 'evidence', dot: 'bg-teal' },
  legal: { tone: 'blue', label: 'Sahyog', dot: 'bg-blue' },
}

export default function Timeline({ events, onPick }: { events: TimelineEvent[]; onPick?: (edgeId: string) => void }) {
  if (!events.length) return <div className="p-6"><Empty>No events yet.</Empty></div>
  return (
    <div className="h-full overflow-auto p-5">
      <ol className="relative border-l-2 border-line pl-6">
        {events.map((e, i) => {
          const k = KIND[e.kind]
          return (
            <li key={i} className="mb-4">
              <span className={cx('absolute -left-[7px] mt-1.5 h-3 w-3 rounded-full ring-4 ring-card', k.dot)} />
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-muted">{IST(e.ts)}</span><Badge tone={k.tone}>{k.label}</Badge>
                <button className={cx('text-sm font-semibold', e.data?.edge_id && onPick ? 'text-blue hover:underline' : 'cursor-default')}
                  onClick={() => e.data?.edge_id && onPick?.(e.data.edge_id)}>{e.title}</button>
              </div>
              <div className="text-sm text-body">{e.detail}</div>
              {e.data?.tx && e.data.tx.length > 0 && (
                <div className="flex flex-wrap gap-x-3 text-xs">{e.data.tx.slice(0, 2).map((h) => (
                  <a key={h} className="addr text-blue hover:underline" href={txUrl(e.data?.chain ?? '', h)} target="_blank" rel="noreferrer">{short(h)}</a>))}
                  {(e.data.tx_count ?? 0) > 2 && <span className="text-muted">+{(e.data.tx_count ?? 0) - 2} more</span>}</div>
              )}
            </li>
          )
        })}
      </ol>
    </div>
  )
}
