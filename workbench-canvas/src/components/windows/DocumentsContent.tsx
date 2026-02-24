import { useEffect, useMemo, useRef, useState } from 'react'
import { Search, FileText, ExternalLink, Loader2, Upload, Pencil, Check, X } from 'lucide-react'
import { documentsApi, type WorkspaceDocument, type WorkspaceDocumentSearchResult } from '../../services/api'
import { useCanvasStore } from '../../store/canvasStore'
import type { DocumentsWindowData } from '../../types'

interface DocumentsContentProps {
  data: DocumentsWindowData
  windowId: string
}

type DisplayDoc = {
  id: string
  title: string
  filename: string
  mimeType?: string
  snippet?: string
}

export default function DocumentsContent({ data }: DocumentsContentProps) {
  const { openWindow } = useCanvasStore()
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [query, setQuery] = useState(data.initialQuery || '')
  const [documents, setDocuments] = useState<WorkspaceDocument[]>([])
  const [searchResults, setSearchResults] = useState<WorkspaceDocumentSearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const [searching, setSearching] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [editingDocId, setEditingDocId] = useState<string | null>(null)
  const [editingTitle, setEditingTitle] = useState('')
  const [savingTitle, setSavingTitle] = useState(false)

  const fetchDocuments = async () => {
    setLoading(true)
    setError(null)
    try {
      const docs = await documentsApi.list()
      setDocuments(docs)
    } catch (error) {
      console.error('Failed to load documents:', error)
      setError('Could not load documents.')
    } finally {
      setLoading(false)
    }
  }

  const runSearch = async (q: string) => {
    const trimmed = q.trim()
    if (!trimmed) {
      setSearchResults([])
      return
    }
    setSearching(true)
    setError(null)
    try {
      const results = await documentsApi.search(trimmed, 25)
      setSearchResults(results)
    } catch (error) {
      console.error('Document search failed:', error)
      setError('Search failed.')
    } finally {
      setSearching(false)
    }
  }

  const handleUpload = async (files: FileList | null) => {
    if (!files || files.length === 0) return
    setUploading(true)
    setError(null)
    try {
      for (const file of Array.from(files)) {
        await documentsApi.upload(file)
      }
      await fetchDocuments()
      if (query.trim()) {
        await runSearch(query)
      }
    } catch (uploadError) {
      console.error('Document upload failed:', uploadError)
      setError('Upload failed. Please try again.')
    } finally {
      setUploading(false)
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }

  useEffect(() => {
    fetchDocuments()
  }, [])

  useEffect(() => {
    if (data.initialQuery) {
      runSearch(data.initialQuery)
    }
  }, [data.initialQuery])

  const displayDocs: DisplayDoc[] = useMemo(() => {
    if (query.trim()) {
      return searchResults.map((r) => ({
        id: r.document_id,
        title: r.title || r.original_filename || r.filename || 'Untitled',
        filename: r.original_filename || r.filename || 'document',
        mimeType: documents.find((d) => d.id === r.document_id)?.mime_type,
        snippet: r.chunk_text,
      }))
    }
    return documents.map((d) => ({
      id: d.id,
      title: d.title || d.original_filename || d.filename || 'Untitled',
      filename: d.original_filename || d.filename || 'document',
      mimeType: d.mime_type,
      snippet: d.content_text?.slice(0, 180),
    }))
  }, [documents, query, searchResults])

  const openDocument = (doc: DisplayDoc) => {
    const url = documentsApi.getDownloadUrl(doc.id)
    openWindow(
      'fileviewer',
        {
          filename: doc.filename,
          content: url,
          mimeType: doc.mimeType,
          source: 'local',
        },
      {
        title: doc.filename,
        width: 900,
        height: 800,
      }
    )
  }

  const startEditingTitle = (doc: DisplayDoc) => {
    setEditingDocId(doc.id)
    setEditingTitle(doc.title)
  }

  const cancelEditingTitle = () => {
    setEditingDocId(null)
    setEditingTitle('')
  }

  const saveTitle = async (docId: string) => {
    const nextTitle = editingTitle.trim()
    if (!nextTitle) return
    setSavingTitle(true)
    setError(null)
    try {
      await documentsApi.updateTitle(docId, nextTitle)
      await fetchDocuments()
      if (query.trim()) {
        await runSearch(query)
      }
      setEditingDocId(null)
      setEditingTitle('')
    } catch (saveError) {
      console.error('Failed to update document title:', saveError)
      setError('Could not update title.')
    } finally {
      setSavingTitle(false)
    }
  }

  return (
    <div className="flex flex-col h-full bg-canvas-bg">
      <div className="p-3 border-b border-canvas-border">
        <div className="flex gap-2">
          <div className="flex-1 relative">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-canvas-muted" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') runSearch(query)
              }}
              placeholder="Search documents..."
              className="w-full pl-9 pr-3 py-2 bg-canvas-surface border border-canvas-border rounded text-white"
            />
          </div>
          <button
            onClick={() => runSearch(query)}
            className="px-3 py-2 bg-teal-600 hover:bg-teal-500 rounded text-white text-sm"
          >
            Search
          </button>
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            className="px-3 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-60 rounded text-white text-sm flex items-center gap-2"
          >
            {uploading ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
            Upload
          </button>
          <input
            ref={fileInputRef}
            type="file"
            className="hidden"
            multiple
            onChange={(e) => handleUpload(e.target.files)}
          />
        </div>
        {error && <div className="text-xs text-red-400 mt-2">{error}</div>}
      </div>

      <div className="flex-1 overflow-y-auto custom-scrollbar p-2">
        {(loading || searching) && (
          <div className="flex items-center justify-center py-8 text-canvas-muted">
            <Loader2 size={18} className="animate-spin mr-2" />
            {loading ? 'Loading documents...' : 'Searching...'}
          </div>
        )}

        {!loading && !searching && displayDocs.length === 0 && (
          <div className="text-canvas-muted text-sm text-center py-8">No documents found</div>
        )}

        {!loading && !searching && displayDocs.map((doc) => (
          <div
            key={`${doc.id}-${doc.filename}`}
            onClick={() => openDocument(doc)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                openDocument(doc)
              }
            }}
            role="button"
            tabIndex={0}
            className="w-full p-3 mb-2 text-left rounded border border-canvas-border bg-canvas-surface hover:bg-canvas-elevated transition-colors"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <FileText size={15} className="text-blue-400 flex-shrink-0" />
                  {editingDocId === doc.id ? (
                    <div className="flex items-center gap-1.5 w-full" onClick={(e) => e.stopPropagation()}>
                      <input
                        value={editingTitle}
                        onChange={(e) => setEditingTitle(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') saveTitle(doc.id)
                          if (e.key === 'Escape') cancelEditingTitle()
                        }}
                        className="flex-1 min-w-0 px-2 py-1 text-xs bg-canvas-bg border border-canvas-border rounded text-white"
                        autoFocus
                      />
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          saveTitle(doc.id)
                        }}
                        disabled={savingTitle}
                        className="p-1 rounded bg-emerald-600 hover:bg-emerald-500 disabled:opacity-60 text-white"
                        title="Save title"
                      >
                        <Check size={12} />
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          cancelEditingTitle()
                        }}
                        className="p-1 rounded bg-canvas-elevated hover:bg-canvas-border text-canvas-muted"
                        title="Cancel"
                      >
                        <X size={12} />
                      </button>
                    </div>
                  ) : (
                    <>
                      <span className="text-white text-sm font-medium truncate">{doc.title}</span>
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          startEditingTitle(doc)
                        }}
                        className="p-1 rounded hover:bg-canvas-elevated text-canvas-muted hover:text-white"
                        title="Edit title"
                      >
                        <Pencil size={12} />
                      </button>
                    </>
                  )}
                </div>
                <div className="text-canvas-muted text-xs mt-1 truncate">{doc.filename}</div>
                {doc.snippet && (
                  <div className="text-canvas-muted text-xs mt-2 line-clamp-2">{doc.snippet}</div>
                )}
              </div>
              <ExternalLink size={14} className="text-canvas-muted flex-shrink-0 mt-1" />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
