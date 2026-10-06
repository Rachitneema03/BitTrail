import { useEffect, useState } from 'react'
import { api, post } from '../api/client'
import type { AiStatus, Analysis, AskResult } from '../api/types'
import { Badge, Button, Card, cx } from './ui'

/** Sarvam AI: narrates BitTrail's evidence and answers questions. Never used for attribution. */
export default function AiPanel({ caseId, analysis }: { caseId: string; analysis: Analysis | null | undefined }) {
  const [status, setStatus] = useState<AiStatus | null>(null)
  const [lang, setLang] = useState<'en-IN' | 'hi-IN'>('en-IN')
  const [text, setText] = useState<{ text: string; source: string } | null>(null)
  const [q, setQ] = useState('')
  const [answer, setAnswer] = useState<AskResult | null>(null)
  const [openCite, setOpenCite] = useState<number | null>(null)
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState('')
  useEffect(() => { api<AiStatus>('/ai/status').then(setStatus).catch(() => null) }, [])
  useEffect(() => {
    const n = analysis?.narratives?.[lang]
    setText(n ? { text: n.text, source: n.source } : null)
  }, [analysis, lang])

  const generate = async () => {
    setBusy('n'); setErr('')
    try { const r = await post<{ text: string; source: string }>(`/cases/${caseId}/narrative`, { lang }); setText(r) }
    catch (x) { setErr((x as Error).message) } finally { setBusy('') }
  }
  const ask = async () => {
    if (!q.trim()) return
    setBusy('a'); setErr(''); setAnswer(null)
    try { setAnswer(await post<AskResult>(`/cases/${caseId}/ask`, { question: q })); setOpenCite(null) }
    catch (x) { setErr((x as Error).message) } finally { setBusy('') }
  }

  return (
    <Card className="p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2"><b>AI case summary</b><Badge tone={status?.configured ? 'teal' : 'grey'}>Sarvam AI{status?.configured ? '' : ' · not configured'}</Badge></div>
        <div className="flex overflow-hidden rounded-lg border border-line text-xs">
          {(['en-IN', 'hi-IN'] as const).map((l) => (
            <button key={l} onClick={() => setLang(l)} disabled={l === 'hi-IN' && !status?.configured}
              className={cx('px-2.5 py-1 font-semibold disabled:opacity-40', lang === l ? 'bg-navy text-white' : 'bg-card')}>{l === 'en-IN' ? 'English' : 'हिंदी'}</button>))}
        </div>
      </div>
      {text ? <p className="whitespace-pre-wrap text-sm leading-relaxed text-body">{text.text}</p>
        : <p className="text-sm text-muted">Generate a plain-language summary of this case, written only from the evidence on this page.</p>}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button variant="ghost" className="px-3 py-1.5 text-xs" onClick={generate} disabled={busy === 'n'}>{busy === 'n' ? 'Writing…' : text ? 'Regenerate' : 'Generate summary'}</Button>
        {text && <span className="text-xs text-muted">{text.source === 'sarvam' ? 'AI-written from the evidence; not used for attribution' : 'Template summary (Sarvam AI not configured)'}</span>}
      </div>
      <div className="mt-4 border-t border-line pt-3">
        <div className="mb-1 flex items-center gap-2 text-sm font-semibold">Ask this case <Badge tone="blue">RAG: retrieval over this case's evidence</Badge></div>
        <div className="flex gap-2">
          <input className="min-w-0 flex-1 rounded-lg border border-line bg-card px-3 py-1.5 text-sm" placeholder="e.g. Why CoinDCX? Which bridge was used? What does Section 94 require?"
            value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && ask()} />
          <Button className="px-3 py-1.5 text-xs" onClick={ask} disabled={busy === 'a'}>{busy === 'a' ? '…' : 'Ask'}</Button>
        </div>
        {!status?.configured && <p className="mt-1 text-xs text-muted">Without SARVAM_API_KEY answers are the retrieved evidence itself; with it, Sarvam writes the answer from those passages only.</p>}
        {answer && (
          <div className="mt-2 rounded-lg bg-paper p-3">
            <p className="whitespace-pre-wrap text-sm text-body">{answer.answer}</p>
            <div className="mt-2 text-[11px] text-muted">{answer.note}</div>
            {answer.citations.length > 0 && (
              <div className="mt-2 space-y-1">
                {answer.citations.map((ct) => (
                  <div key={ct.n} className="rounded-lg border border-line bg-card text-xs">
                    <button className="flex w-full items-center gap-2 px-2 py-1 text-left" onClick={() => setOpenCite(openCite === ct.n ? null : ct.n)}>
                      <span className="font-bold text-blue">[{ct.n}]</span><Badge>{ct.kind}</Badge><span className="truncate">{ct.title}</span>
                    </button>
                    {openCite === ct.n && <div className="border-t border-line px-2 py-1.5 text-body">{ct.text}</div>}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
      {err && <p className="mt-2 text-xs text-red">{err}</p>}
    </Card>
  )
}
