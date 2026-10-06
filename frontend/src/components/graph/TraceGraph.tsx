import cytoscape, { type Core, type ElementDefinition } from 'cytoscape'
import { useEffect, useRef } from 'react'
import type { CrossHop, Graph } from '../../api/types'

export const KIND_STYLE: Record<string, { color: string; label: string }> = {
  suspect: { color: '#D35F1F', label: 'Suspect' },
  intermediary: { color: '#9AA5B8', label: 'Intermediary' },
  vasp_deposit: { color: '#0F7A6B', label: 'VASP deposit' },
  vasp_hot: { color: '#14213D', label: 'VASP hot wallet' },
  vasp_cold: { color: '#14213D', label: 'VASP cold wallet' },
  mixer: { color: '#B42318', label: 'Mixer / CoinJoin (stop)' },
  bridge: { color: '#7A4FBF', label: 'Bridge' },
  swap_service: { color: '#A23B9A', label: 'Cross-chain swap' },
  sanctioned: { color: '#B42318', label: 'Sanctioned' },
  offramp: { color: '#1F5FBF', label: 'P2P / off-ramp' },
  unknown_service: { color: '#C99A2E', label: 'Unknown service' },
}

/** One colour per chain: lane tint, lane label and the chain chips elsewhere in the UI. */
export const CHAIN_STYLE: Record<string, { color: string; label: string }> = {
  tron: { color: '#C23B3B', label: 'TRON' },
  ethereum: { color: '#4F65C9', label: 'ETHEREUM' },
  polygon: { color: '#7B3FE4', label: 'POLYGON' },
  bsc: { color: '#B88A00', label: 'BNB CHAIN' },
  bitcoin: { color: '#E07B00', label: 'BITCOIN' },
  solana: { color: '#0E8F6A', label: 'SOLANA' },
}
export const chainColor = (c: string) => CHAIN_STYLE[c]?.color ?? '#5B6477'

const short = (a: string) => (a.startsWith('coinjoin:') ? `CoinJoin ${a.slice(9, 15)}…` : a.length > 12 ? `${a.slice(0, 5)}…${a.slice(-4)}` : a)
const COL = 200
const ROW = 92
const LANE_GAP = 70

interface Props {
  graph: Graph; onSelect: (id: string | null) => void; selected: string | null
  /** Replay: only these edge ids are shown (null = everything); the focus edge is highlighted. */
  revealed?: Set<string> | null; focusEdge?: string | null
}

/** Swimlane layout: x = hop depth, one horizontal lane per chain (seed chain first), so bridge hops visibly
 *  jump from one chain's lane into another's. */
function lanePositions(graph: Graph) {
  const nodes = graph.nodes.map((n) => n.data)
  const minDepth = Math.min(0, ...nodes.map((n) => n.depth))
  const firstSeen = new Map<string, number>()
  for (const n of [...nodes].sort((a, b) => Math.abs(a.depth) - Math.abs(b.depth) || (a.kind === 'suspect' ? -1 : 1))) {
    if (!firstSeen.has(n.chain)) firstSeen.set(n.chain, firstSeen.size)
  }
  const chains = [...firstSeen.keys()]
  const pos = new Map<string, { x: number; y: number }>()
  let top = 0
  for (const chain of chains) {
    const cols = new Map<number, typeof nodes>()
    for (const n of nodes.filter((m) => m.chain === chain)) cols.set(n.depth, [...(cols.get(n.depth) ?? []), n])
    let rows = 1
    for (const [depth, col] of cols) {
      col.sort((a, b) => b.value_share - a.value_share)
      col.forEach((n, i) => pos.set(n.id, { x: (depth - minDepth) * COL, y: top + i * ROW }))
      rows = Math.max(rows, col.length)
    }
    top += rows * ROW + LANE_GAP
  }
  return { pos, chains }
}

export default function TraceGraph({ graph, onSelect, selected, revealed = null, focusEdge = null }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const cy = useRef<Core | null>(null)

  useEffect(() => {
    if (!ref.current) return
    const { pos, chains } = lanePositions(graph)
    const hops = new Map<string, CrossHop>()
    for (const n of graph.nodes) for (const h of (n.data.stats.crosschain as CrossHop[] | undefined) ?? []) hops.set(`${h.to_chain}:${h.to_address}`, h)
    const els: ElementDefinition[] = [
      ...chains.map((c) => ({
        data: { id: `lane:${c}`, label: `${CHAIN_STYLE[c]?.label ?? c.toUpperCase()}  ·  ${graph.nodes.filter((n) => n.data.chain === c).length} addresses`, lane: chainColor(c) },
        classes: 'lane', selectable: false, grabbable: false,
      })),
      ...graph.nodes.map((n) => ({
        data: {
          ...n.data,
          parent: `lane:${n.data.chain}`,
          label: (n.data.entity ? `${n.data.entity}\n` : '') + short(n.data.address),
          color: KIND_STYLE[n.data.kind]?.color ?? '#9AA5B8',
          ring: chainColor(n.data.chain),
          size: n.data.kind === 'suspect' ? 58 : n.data.kind.startsWith('vasp') ? 52 : 26 + Math.min(1, n.data.value_share) * 22,
        },
        position: pos.get(n.data.id),
        classes: [n.data.kind, n.data.flags.includes('sanctioned') ? 'flagged' : '', n.data.depth < 0 ? 'back' : ''].join(' '),
      })),
      ...graph.edges.map((e) => {
        const hop = e.data.direction === 'bridge' ? hops.get(e.data.target) : undefined
        const amount = `$${Math.round(e.data.amount_usd).toLocaleString()}`
        return {
          data: {
            ...e.data, width: 2 + Math.min(1, e.data.value_share) * 12,
            label: hop ? `${amount} · ${hop.tool ?? hop.provider} · continuity ${hop.continuity.toFixed(2)}` : amount,
          },
          classes: [e.data.direction, hop && !hop.confirmed ? 'unconfirmed' : ''].join(' '),
        }
      }),
    ]
    const c = cytoscape({
      container: ref.current,
      elements: els,
      wheelSensitivity: 0.3,
      style: [
        { selector: 'node', style: {
          'background-color': 'data(color)', width: 'data(size)', height: 'data(size)', label: 'data(label)',
          'font-family': 'IBM Plex Sans, sans-serif', 'font-size': 11, color: '#14213D', 'text-wrap': 'wrap',
          'text-valign': 'bottom', 'text-margin-y': 6, 'text-background-color': '#F6F7FB', 'text-background-opacity': 0.85,
          'text-background-padding': '2px', 'border-width': 3, 'border-color': '#FDFDFE' } },
        { selector: 'node.lane', style: {
          shape: 'round-rectangle', 'background-color': 'data(lane)', 'background-opacity': 0.06, 'border-color': 'data(lane)',
          'border-width': 1.5, 'border-style': 'dashed', 'border-opacity': 0.55, label: 'data(label)', 'text-valign': 'top',
          'text-halign': 'center', 'font-size': 16, 'font-weight': 700, color: 'data(lane)', 'text-margin-y': -6,
          'text-background-opacity': 0, padding: '28px', events: 'no' } as cytoscape.Css.Node },
        { selector: 'node.intermediary', style: { 'background-color': '#FDFDFE', 'border-color': '#5B6477', 'border-width': 3 } },
        { selector: 'node.back', style: { 'border-style': 'dashed' } },
        { selector: 'node.flagged', style: { 'border-color': '#B42318', 'border-width': 5 } },
        { selector: 'node.mixer', style: { shape: 'diamond' } },
        { selector: 'node.bridge, node.swap_service', style: { shape: 'hexagon', 'border-color': '#FDFDFE' } },
        { selector: 'node.vasp_hot, node.vasp_cold', style: { shape: 'round-rectangle' } },
        { selector: 'node:selected', style: { 'overlay-color': '#D35F1F', 'overlay-opacity': 0.18, 'overlay-padding': 8 } },
        { selector: 'edge', style: {
          width: 'data(width)', 'line-color': '#9AA5B8', 'target-arrow-color': '#9AA5B8', 'target-arrow-shape': 'triangle',
          'curve-style': 'bezier', label: 'data(label)', 'font-size': 10, color: '#5B6477', 'text-rotation': 'autorotate',
          'text-background-color': '#F6F7FB', 'text-background-opacity': 0.9, 'text-background-padding': '1px', opacity: 0.9 } },
        { selector: 'edge.forward', style: { 'line-color': '#D35F1F', 'target-arrow-color': '#D35F1F' } },
        { selector: 'edge.sweep', style: { 'line-color': '#0F7A6B', 'target-arrow-color': '#0F7A6B', 'line-style': 'dashed' } },
        { selector: 'edge.backward', style: { 'line-color': '#1F5FBF', 'target-arrow-color': '#1F5FBF', 'line-style': 'dotted', width: 3 } },
        { selector: 'edge.bridge', style: {
          'line-color': '#7A4FBF', 'target-arrow-color': '#7A4FBF', 'line-style': 'dashed', 'line-dash-pattern': [10, 5],
          'curve-style': 'unbundled-bezier', 'font-weight': 700, color: '#5B3A99', 'font-size': 11, 'z-index': 50 } as cytoscape.Css.Edge },
        { selector: 'edge.bridge.unconfirmed', style: { 'line-style': 'dotted', opacity: 0.7 } },
        { selector: 'edge.mix', style: { 'line-color': '#B42318', 'target-arrow-color': '#B42318', 'line-style': 'dashed' } },
        { selector: '.dim', style: { opacity: 0.07 } },
        { selector: 'edge.focus', style: { 'line-color': '#1F5FBF', 'target-arrow-color': '#1F5FBF', width: 10, opacity: 1, 'z-index': 99 } },
      ],
      layout: { name: 'preset', padding: 40, animate: true, animationDuration: 500 } as cytoscape.LayoutOptions,
    })
    c.on('tap', 'node', (e) => { if (!e.target.hasClass('lane')) onSelect(e.target.id()) })
    c.on('tap', (e) => { if (e.target === c) onSelect(null) })
    cy.current = c
    return () => c.destroy()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph])

  useEffect(() => {
    const c = cy.current
    if (!c) return
    c.$(':selected').unselect()
    if (selected) c.getElementById(selected).select()
  }, [selected])

  useEffect(() => {
    const c = cy.current
    if (!c) return
    c.elements().removeClass('dim focus')
    if (!revealed) return
    const visibleNodes = new Set<string>(graph.nodes.filter((n) => n.data.kind === 'suspect').map((n) => n.data.id))
    c.edges().forEach((e) => {
      if (revealed.has(e.id())) { visibleNodes.add(e.data('source')); visibleNodes.add(e.data('target')) } else e.addClass('dim')
    })
    c.nodes().not('.lane').forEach((n) => { if (!visibleNodes.has(n.id())) n.addClass('dim') })
    if (focusEdge) c.getElementById(focusEdge).addClass('focus')
  }, [revealed, focusEdge, graph])

  return <div ref={ref} className="h-full w-full" />
}
