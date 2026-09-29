import { SankeyChart as ESankey } from 'echarts/charts'
import { TooltipComponent } from 'echarts/components'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { useEffect, useRef } from 'react'

echarts.use([ESankey, TooltipComponent, CanvasRenderer])
import type { Graph } from '../../api/types'
import { KIND_STYLE } from '../graph/TraceGraph'

const short = (a: string) => (a.length > 12 ? `${a.slice(0, 5)}…${a.slice(-4)}` : a)

/** Fund flow as a Sankey: forward + sweep edges, width = USD moved. */
export default function SankeyChart({ graph }: { graph: Graph }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!ref.current) return
    const chart = echarts.init(ref.current)
    const nodesById = new Map(graph.nodes.map((n) => [n.data.id, n.data]))
    const edges = graph.edges.filter((e) => e.data.direction !== 'backward' && e.data.source !== e.data.target)
    const used = new Set(edges.flatMap((e) => [e.data.source, e.data.target]))
    const name = (id: string) => {
      const n = nodesById.get(id)
      return n ? `${n.entity ? n.entity + ' · ' : ''}${short(n.address)}` : id
    }
    chart.setOption({
      tooltip: { trigger: 'item', formatter: (p: { dataType: string; data: { source?: string; target?: string; value?: number }; name: string }) =>
        p.dataType === 'edge' ? `${p.data.source} → ${p.data.target}<br/><b>$${Math.round(p.data.value ?? 0).toLocaleString()}</b>` : p.name },
      series: [{
        type: 'sankey', left: 10, right: 160, top: 20, bottom: 20, nodeGap: 14, nodeWidth: 16, draggable: false,
        emphasis: { focus: 'adjacency' },
        label: { fontFamily: 'IBM Plex Sans', fontSize: 12, color: '#14213D' },
        lineStyle: { color: 'gradient', curveness: 0.5, opacity: 0.45 },
        data: [...used].map((id) => ({ name: name(id), itemStyle: { color: KIND_STYLE[nodesById.get(id)?.kind ?? '']?.color ?? '#9AA5B8' } })),
        links: edges.map((e) => ({ source: name(e.data.source), target: name(e.data.target), value: Math.max(1, e.data.amount_usd) })),
      }],
    })
    const ro = new ResizeObserver(() => chart.resize())
    ro.observe(ref.current)
    return () => { ro.disconnect(); chart.dispose() }
  }, [graph])
  return <div ref={ref} className="h-full w-full" />
}
