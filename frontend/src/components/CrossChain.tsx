import { useState } from 'react'
import type { CrossHop } from '../api/types'
import { CHAIN_STYLE, chainColor } from './graph/TraceGraph'
import { Badge, Card, addrUrl, cx, short, txUrl, usd } from './ui'

export function ChainChip({ chain, className }: { chain: string; className?: string }) {
  return (
    <span className={cx('inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-bold tracking-wide', className)}
      style={{ color: chainColor(chain), borderColor: chainColor(chain) + '55', background: chainColor(chain) + '12' }}>
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: chainColor(chain) }} />{CHAIN_STYLE[chain]?.label ?? chain.toUpperCase()}
    </span>
  )
}

export function ChainPath({ chains }: { chains: string[] }) {
  return <span className="inline-flex flex-wrap items-center gap-1">{chains.map((c, i) => <span key={c + i} className="inline-flex items-center gap-1">{i > 0 && <span className="text-muted">→</span>}<ChainChip chain={c} /></span>)}</span>
}

const COMP: [keyof CrossHop['components'], string, number][] = [['amount', 'Amount match', 0.35], ['time', 'Timing', 0.25], ['bridge', 'Tracker-confirmed', 0.3], ['destination', 'Destination check', 0.1]]

/** Every bridge / swap hop of the trail, with the evidence that the money on chain B is the money from chain A. */
export function CrossChainPanel({ hops }: { hops: CrossHop[] }) {
  const [all, setAll] = useState(false)
  if (!hops.length) return null
  const shown = all ? hops : hops.slice(0, 3)
  return (
    <Card className="border-[#7A4FBF]/30 p-4">
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <b>Cross-chain hops</b><Badge tone="navy">{hops.length}</Badge>
        <ChainPath chains={[...new Set(hops.flatMap((h) => [h.from_chain, h.to_chain]))]} />
      </div>
      <p className="mb-3 text-xs text-muted">Resolved from the deposit transaction hash by public bridge / swap trackers. Continuity = how sure we are the money that left chain B is the money that entered on chain A.</p>
      {hops.length > 1 && (
        <div className="mb-3 text-xs text-muted">
          Total {usd(hops.reduce((s, h) => s + h.usd_in, 0))} in → {usd(hops.reduce((s, h) => s + h.usd_out, 0))} out ·
          lowest continuity {Math.min(...hops.map((h) => h.continuity)).toFixed(2)} · {hops.filter((h) => h.confirmed).length}/{hops.length} tracker-confirmed
        </div>
      )}
      <div className="space-y-3">
        {shown.map((h) => (
          <div key={h.src_tx + h.dest_tx} className="rounded-xl border border-line p-3">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <ChainChip chain={h.from_chain} /><span className="text-muted">→</span><ChainChip chain={h.to_chain} />
              <b>via {h.tool ?? h.provider}</b>
              {h.confirmed ? <Badge tone="teal">{h.provider}</Badge> : <Badge tone="orange">unconfirmed match</Badge>}
              {!h.supported && <Badge tone="red">destination chain not covered</Badge>}
            </div>
            <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
              <div><div className="text-muted">In</div><b>{usd(h.usd_in)}</b></div>
              <div><div className="text-muted">Out{h.asset ? ` (${h.asset})` : ''}</div><b>{usd(h.usd_out)}</b></div>
              <div><div className="text-muted">Bridge time</div><b>{h.minutes < 1 ? '< 1' : h.minutes.toFixed(0)} min</b></div>
            </div>
            <div className="mt-2">
              <div className="flex items-center justify-between text-xs"><span className="text-muted">Continuity</span><b className="tabular-nums">{h.continuity.toFixed(2)}</b></div>
              <div className="mt-1 flex h-2 overflow-hidden rounded-full bg-line">
                {COMP.map(([k, , w]) => <div key={k} title={`${k}: ${h.components[k]}`} className="h-full border-r border-card" style={{ width: `${w * h.components[k] * 100}%`, background: '#7A4FBF', opacity: 0.45 + 0.55 * h.components[k] }} />)}
              </div>
              <div className="mt-1 flex flex-wrap gap-x-3 text-[11px] text-muted">{COMP.map(([k, label, w]) => <span key={k}>{label} {h.components[k].toFixed(2)} × {w}</span>)}</div>
            </div>
            <div className="mt-2 grid gap-1 text-[11px]">
              <div><span className="text-muted">Deposit </span><a className="addr text-blue hover:underline" href={txUrl(h.from_chain, h.src_tx)} target="_blank" rel="noreferrer">{short(h.src_tx)}</a>
                <span className="text-muted"> into </span><a className="addr text-blue hover:underline" href={addrUrl(h.from_chain, h.bridge_address)} target="_blank" rel="noreferrer">{short(h.bridge_address)}</a></div>
              <div><span className="text-muted">Release </span><a className="addr text-blue hover:underline" href={txUrl(h.to_chain, h.dest_tx)} target="_blank" rel="noreferrer">{short(h.dest_tx)}</a>
                <span className="text-muted"> to </span><a className="addr text-blue hover:underline" href={addrUrl(h.to_chain, h.to_address)} target="_blank" rel="noreferrer">{short(h.to_address)}</a></div>
            </div>
          </div>
        ))}
      </div>
      {hops.length > 3 && (
        <button className="mt-3 text-xs font-semibold text-blue" onClick={() => setAll(!all)}>
          {all ? 'Show fewer' : `Show all ${hops.length} hops`}
        </button>
      )}
    </Card>
  )
}
