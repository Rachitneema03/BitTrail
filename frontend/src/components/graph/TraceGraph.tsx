import cytoscape, { type Core, type ElementDefinition } from 'cytoscape'
import { useEffect, useRef } from 'react'
import type { Graph } from '../../api/types'

export const KIND_STYLE: Record<string, { color: string; label: string }> = {
  suspect: { color: '#D35F1F', label: 'Suspect' },
  intermediary: { color: '#9AA5B8', label: 'Intermediary' },
  vasp_deposit: { color: '#0F7A6B', label: 'VASP deposit' },
  vasp_hot: { color: '#14213D', label: 'VASP hot wallet' },
  vasp_cold: { color: '#14213D', label: 'VASP cold wallet' },
  mixer: { color: '#B42318', label: 'Mixer (stop)' },
  bridge: { color: '#7A4FBF', label: 'Bridge' },
  sanctioned: { color: '#B42318', label: 'Sanctioned' },
  offramp: { color: '#1F5FBF', label: 'P2P / off-ramp' },
  bridge_dest: { color: '#7A4FBF', label: 'Cross-chain' },
  unknown_service: { color: '#C99A2E', label: 'Unknown service' },
}

const short = (a: string) => (a.length > 12 ? `${a.slice(0, 5)}…${a.slice(-4)}` : a)

interface Props {
  graph: Graph; onSelect: (id: string | null) => void; selected: string | null
  /** Replay: only these edge ids are shown (null = everything); the focus edge is highlighted. */
  revealed?: Set<string> | null; focusEdge?: string | null
}

export default function TraceGraph({ graph, onSelect, selected, revealed = null, focusEdge = null }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const cy = useRef<Core | null>(null)

  useEffect(() => {
    if (!ref.current) return
    const els: ElementDefinition[] = [
      ...graph.nodes.map((n) => ({
        data: {
          ...n.data,
          label: (n.data.entity ? `${n.data.entity}\n` : '') + short(n.data.address),
          color: KIND_STYLE[n.data.kind]?.color ?? '#9AA5B8',
          size: n.data.kind === 'suspect' ? 58 : n.data.kind.startsWith('vasp') ? 52 : 26 + Math.min(1, n.data.value_share) * 22,
          // backward (on-ramp) nodes sit left of the suspect
          col: n.data.depth,
        },
        classes: [n.data.kind, n.data.flags.includes('sanctioned') ? 'flagged' : '', n.data.depth < 0 ? 'back' : ''].join(' '),
      })),
      ...graph.edges.map((e) => ({
        data: { ...e.data, width: 2 + Math.min(1, e.data.value_share) * 12, label: `$${Math.round(e.data.amount_usd).toLocaleString()}` },
        classes: e.data.direction,
      })),
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
        { selector: 'node.intermediary', style: { 'background-color': '#FDFDFE', 'border-color': '#5B6477', 'border-width': 3 } },
        { selector: 'node.back', style: { 'border-style': 'dashed' } },
        { selector: 'node.flagged', style: { 'border-color': '#B42318', 'border-width': 5 } },
        { selector: 'node.mixer', style: { shape: 'diamond' } },
        { selector: 'node.vasp_hot, node.vasp_cold', style: { shape: 'round-rectangle' } },
        { selector: 'node:selected', style: { 'overlay-color': '#D35F1F', 'overlay-opacity': 0.18, 'overlay-padding': 8 } },
        { selector: 'edge', style: {
          width: 'data(width)', 'line-color': '#9AA5B8', 'target-arrow-color': '#9AA5B8', 'target-arrow-shape': 'triangle',
          'curve-style': 'bezier', label: 'data(label)', 'font-size': 10, color: '#5B6477', 'text-rotation': 'autorotate',
          'text-background-color': '#F6F7FB', 'text-background-opacity': 0.9, 'text-background-padding': '1px', opacity: 0.9 } },
        { selector: 'edge.forward', style: { 'line-color': '#D35F1F', 'target-arrow-color': '#D35F1F' } },
        { selector: 'edge.sweep', style: { 'line-color': '#0F7A6B', 'target-arrow-color': '#0F7A6B', 'line-style': 'dashed' } },
        { selector: 'edge.backward', style: { 'line-color': '#1F5FBF', 'target-arrow-color': '#1F5FBF', 'line-style': 'dotted', width: 3 } },
        { selector: 'edge.bridge', style: { 'line-color': '#7A4FBF', 'target-arrow-color': '#7A4FBF', 'line-style': 'dashed' } },
        { selector: '.dim', style: { opacity: 0.07 } },
        { selector: 'edge.focus', style: { 'line-color': '#1F5FBF', 'target-arrow-color': '#1F5FBF', width: 10, opacity: 1, 'z-index': 99 } },
      ],
      layout: {
        name: 'breadthfirst', directed: true, spacingFactor: 1.25, padding: 30, animate: true, animationDuration: 600,
        roots: graph.nodes.filter((n) => n.data.depth === Math.min(...graph.nodes.map((m) => m.data.depth))).map((n) => `#${CSS.escape(n.data.id)}`).join(','),
        transform: (_n, pos) => ({ x: pos.y, y: pos.x }), // left -> right
      } as cytoscape.LayoutOptions,
    })
    c.on('tap', 'node', (e) => onSelect(e.target.id()))
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
    c.nodes().forEach((n) => { if (!visibleNodes.has(n.id())) n.addClass('dim') })
    if (focusEdge) c.getElementById(focusEdge).addClass('focus')
  }, [revealed, focusEdge, graph])

  return <div ref={ref} className="h-full w-full" />
}
