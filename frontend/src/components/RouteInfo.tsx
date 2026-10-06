import type { ReqT } from '../api/types'

const link = (u: string) => (u.startsWith('http') || u.startsWith('mailto:') ? u : undefined)

/** Why a request goes through this channel, with the public sources behind the VASP's status. */
export default function RouteInfo({ route }: { route: NonNullable<ReqT['route']> }) {
  return (
    <div className="text-xs text-body">
      <div>{route.why}.</div>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-muted">
        {route.url && <a className="text-blue underline" href={link(route.url)} target="_blank" rel="noreferrer">{route.url.replace('mailto:', '')}</a>}
        {route.alt_url && <a className="text-blue underline" href={link(route.alt_url)} target="_blank" rel="noreferrer">VASP LE channel</a>}
        {(route.sources ?? []).map((s) => <a key={s.label} className="hover:underline" href={s.url} target="_blank" rel="noreferrer">source: {s.label} ↗</a>)}
      </div>
    </div>
  )
}
