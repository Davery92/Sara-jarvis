import React, { useState } from 'react'
import { APP_CONFIG } from '../config'

type Source =
  | string
  | { url: string; title?: string; snippet?: string; source?: string; published?: string }

interface SourcesChipProps {
  sources: Source[]
}

function hostnameFrom(url: string): string {
  try {
    return new URL(url).hostname
  } catch {
    return url
  }
}

export default function SourcesChip({ sources }: SourcesChipProps) {
  const [open, setOpen] = useState(false)
  const [loadingUrl, setLoadingUrl] = useState<string | null>(null)
  const [readerData, setReaderData] = useState<Record<string, { title: string; plain_text: string; readable_html: string }>>({})
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  if (!sources || sources.length === 0) return null

  const normalized = sources
    .map((s) =>
      typeof s === 'string'
        ? { url: s, title: undefined, snippet: undefined }
        : { url: s.url, title: s.title, snippet: s.snippet, source: s.source, published: s.published }
    )
    .slice(0, 5)

  const openReader = async (url: string) => {
    try {
      setLoadingUrl(url)
      const res = await fetch(`${APP_CONFIG.apiUrl}/search/open_page?url=${encodeURIComponent(url)}`, {
        credentials: 'include'
      })
      if (!res.ok) throw new Error('Reader fetch failed')
      const data = await res.json()
      setReaderData(prev => ({ ...prev, [url]: { title: data.title, plain_text: data.plain_text, readable_html: data.readable_html } }))
      setExpanded(prev => ({ ...prev, [url]: true }))
    } catch (e) {
      console.error('Open reader failed', e)
    } finally {
      setLoadingUrl(null)
    }
  }

  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen((v) => !v)}
        className="text-xs bg-gray-100 hover:bg-gray-200 text-gray-800 px-2 py-1 rounded-md border border-gray-200"
        title={open ? 'Hide sources' : 'Show sources'}
      >
        Sources {open ? '▴' : '▾'}
      </button>
      {open && (
        <div className="mt-2 space-y-2">
          {normalized.map((s, idx) => (
            <div key={idx} className="bg-gray-50 border border-gray-200 rounded-lg p-2">
              <div className="flex items-center justify-between">
                <a href={s.url} target="_blank" rel="noreferrer" className="text-xs text-gray-600 truncate hover:underline">
                  {s.title || hostnameFrom(s.url)}
                </a>
                <div className="flex items-center gap-2">
                  <span className="text-[11px] text-gray-500 hidden sm:block">{hostnameFrom(s.url)}</span>
                  <button
                    onClick={() => openReader(s.url)}
                    className="text-[11px] px-2 py-0.5 rounded bg-gray-200 hover:bg-gray-300 text-gray-700"
                    disabled={loadingUrl === s.url}
                  >
                    {loadingUrl === s.url ? 'Loading…' : 'Reader'}
                  </button>
                </div>
              </div>
              {expanded[s.url] && readerData[s.url] && (
                <div className="mt-2 text-[12px] text-gray-700 bg-white border border-gray-200 rounded p-2 max-h-64 overflow-auto">
                  <div className="font-medium mb-1">{readerData[s.url].title || s.title || hostnameFrom(s.url)}</div>
                  <div className="whitespace-pre-wrap">{readerData[s.url].plain_text?.slice(0, 2000)}</div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
