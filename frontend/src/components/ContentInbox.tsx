/**
 * Content Inbox — Share URLs, Reddit posts, PDFs, and text to Sara.
 * Full-width item list; reader pane appears on selection.
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { APP_CONFIG } from '../config';

// Types
interface InboxItem {
  id: string;
  content_type: string;
  title: string | null;
  description: string | null;
  thumbnail_url: string | null;
  original_url: string | null;
  status: string;
  extraction_status: string;
  word_count: number | null;
  shared_at: string | null;
}

interface InboxItemDetail extends InboxItem {
  extracted_text: string | null;
  meta: Record<string, any> | null;
  discussed: boolean;
  consolidated: boolean;
  original_filename: string | null;
  mime_type: string | null;
  file_size: number | null;
  storage_key: string | null;
  read_at: string | null;
  decided_at: string | null;
  episode_id: string | null;
}

interface InboxStats {
  unread: number;
  read: number;
  kept: number;
  total: number;
}

interface ContentInboxProps {
  onNavigateToChat?: (inboxItemId: string, title: string, excerpt?: string) => void;
}

export default function ContentInbox({ onNavigateToChat }: ContentInboxProps) {
  const [items, setItems] = useState<InboxItem[]>([]);
  const [selectedItem, setSelectedItem] = useState<InboxItemDetail | null>(null);
  const [stats, setStats] = useState<InboxStats>({ unread: 0, read: 0, kept: 0, total: 0 });
  const [filter, setFilter] = useState<string>('all');
  const [loading, setLoading] = useState(false);
  const [shareUrl, setShareUrl] = useState('');
  const [shareLoading, setShareLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Native file viewer state
  const [viewMode, setViewMode] = useState<'original' | 'text'>('text');
  const [fileBlobUrl, setFileBlobUrl] = useState<string | null>(null);
  const [fileLoading, setFileLoading] = useState(false);
  const [docxHtml, setDocxHtml] = useState<string | null>(null);

  const apiUrl = APP_CONFIG.apiUrl;

  // Fetch helpers
  const apiFetch = useCallback(async (path: string, options: RequestInit = {}) => {
    const res = await fetch(`${apiUrl}${path}`, {
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...options.headers as any },
      ...options,
    });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return res.json();
  }, [apiUrl]);

  // Load items + stats
  const loadItemsList = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filter !== 'all') params.set('status', filter);
      params.set('limit', '100');
      const qs = params.toString();
      const [itemsData, statsData] = await Promise.all([
        apiFetch(`/api/inbox?${qs}`),
        apiFetch('/api/inbox/stats'),
      ]);
      setItems(Array.isArray(itemsData) ? itemsData : []);
      setStats(statsData);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [apiFetch, filter]);

  useEffect(() => { loadItemsList(); }, [loadItemsList]);

  // Reset view mode when selected item changes
  useEffect(() => {
    // Clean up previous blob URL
    if (fileBlobUrl) {
      URL.revokeObjectURL(fileBlobUrl);
      setFileBlobUrl(null);
    }
    setDocxHtml(null);
    setViewMode(selectedItem?.storage_key ? 'original' : 'text');
  }, [selectedItem?.id]);

  // Fetch file blob when switching to original view
  useEffect(() => {
    if (viewMode !== 'original' || !selectedItem?.storage_key) return;
    if (fileBlobUrl) return; // already loaded

    let cancelled = false;
    const fetchFile = async () => {
      setFileLoading(true);
      try {
        const res = await fetch(`${apiUrl}/api/inbox/${selectedItem.id}/file`, {
          credentials: 'include',
        });
        if (!res.ok) throw new Error(`${res.status}`);
        const blob = await res.blob();
        if (cancelled) return;

        const mime = selectedItem.mime_type || '';
        if (mime.includes('word') || mime.includes('docx') || selectedItem.original_filename?.endsWith('.docx')) {
          // DOCX: convert to HTML with mammoth
          const arrayBuffer = await blob.arrayBuffer();
          const mammoth = await import('mammoth');
          const result = await mammoth.default.convertToHtml({ arrayBuffer });
          if (!cancelled) setDocxHtml(result.value);
        } else {
          const url = URL.createObjectURL(blob);
          if (!cancelled) setFileBlobUrl(url);
        }
      } catch (e: any) {
        console.error('Failed to fetch file:', e);
        if (!cancelled) setViewMode('text'); // fall back
      } finally {
        if (!cancelled) setFileLoading(false);
      }
    };
    fetchFile();
    return () => { cancelled = true; };
  }, [viewMode, selectedItem?.id, selectedItem?.storage_key]);

  // Cleanup blob URL on unmount
  useEffect(() => {
    return () => {
      if (fileBlobUrl) URL.revokeObjectURL(fileBlobUrl);
    };
  }, [fileBlobUrl]);

  // Select item (loads detail)
  const selectItem = async (id: string) => {
    try {
      const detail = await apiFetch(`/api/inbox/${id}`);
      setSelectedItem(detail);
      // Refresh list to update read status
      loadItemsList();
    } catch (e: any) {
      setError(e.message);
    }
  };

  // Share URL
  const handleShareUrl = async () => {
    if (!shareUrl.trim()) return;
    setShareLoading(true);
    setError(null);
    try {
      // Detect if it's a URL or plain text
      const isUrl = /^https?:\/\//i.test(shareUrl.trim());
      if (isUrl) {
        await apiFetch('/api/inbox/share', {
          method: 'POST',
          body: JSON.stringify({ url: shareUrl.trim() }),
        });
      } else {
        await apiFetch('/api/inbox/share/text', {
          method: 'POST',
          body: JSON.stringify({ text: shareUrl.trim() }),
        });
      }
      setShareUrl('');
      loadItemsList();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setShareLoading(false);
    }
  };

  // Share file
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setShareLoading(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const res = await fetch(`${apiUrl}/api/inbox/upload`, {
        method: 'POST',
        credentials: 'include',
        body: formData,
      });
      if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
      loadItemsList();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setShareLoading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  // Status update
  const updateStatus = async (id: string, status: 'kept' | 'discarded') => {
    try {
      await apiFetch(`/api/inbox/${id}/status`, {
        method: 'PATCH',
        body: JSON.stringify({ status }),
      });
      if (selectedItem?.id === id) {
        setSelectedItem({ ...selectedItem, status });
      }
      loadItemsList();
    } catch (e: any) {
      setError(e.message);
    }
  };

  // Delete
  const deleteItem = async (id: string) => {
    try {
      await apiFetch(`/api/inbox/${id}`, { method: 'DELETE' });
      if (selectedItem?.id === id) setSelectedItem(null);
      loadItemsList();
    } catch (e: any) {
      setError(e.message);
    }
  };

  // Discuss with Sara
  const discussItem = () => {
    if (!selectedItem || !onNavigateToChat) return;
    const excerpt = (selectedItem.extracted_text || selectedItem.description || '').trim();
    onNavigateToChat(selectedItem.id, selectedItem.title || 'Inbox item', excerpt);
  };

  const timeAgo = (dateStr: string | null) => {
    if (!dateStr) return '';
    const d = new Date(dateStr);
    const diff = Date.now() - d.getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    return `${days}d ago`;
  };

  const getDomain = (url: string | null) => {
    if (!url) return '';
    try { return new URL(url).hostname.replace('www.', ''); } catch { return ''; }
  };

  // Filter tabs
  const tabs = [
    { key: 'all', label: 'All', count: stats.total },
    { key: 'unread', label: 'Unread', count: stats.unread },
    { key: 'read', label: 'Read', count: stats.read },
    { key: 'kept', label: 'Kept', count: stats.kept },
  ];

  const rowBorder = (item: InboxItem) => {
    if (item.extraction_status === 'failed') return 'border-rose-400/70';
    if (item.status === 'unread') return 'border-sky-400/70';
    return 'border-transparent';
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Capture input */}
      <div className="flex-shrink-0 pb-4">
        <div className="flex gap-2">
          <input
            type="text"
            value={shareUrl}
            onChange={(e) => setShareUrl(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleShareUrl()}
            placeholder="Paste a URL or type something to save…"
            className="min-w-0 flex-1 rounded-xl border border-white/10 bg-white/[0.04] px-4 py-2.5 text-[15px] text-slate-100 placeholder-slate-500 outline-none transition-colors focus:border-teal-300/30"
          />
          <button
            onClick={handleShareUrl}
            disabled={!shareUrl.trim() || shareLoading}
            className="rounded-xl bg-teal-400/90 px-3.5 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-teal-300 disabled:bg-white/[0.06] disabled:text-slate-500"
          >
            {shareLoading ? '…' : 'Save'}
          </button>
          <button
            onClick={() => fileInputRef.current?.click()}
            className="rounded-xl border border-white/10 px-3.5 py-2 text-sm text-slate-300 transition-colors hover:bg-white/[0.06] hover:text-white"
            title="Upload file"
          >
            +
          </button>
          <input
            ref={fileInputRef}
            type="file"
            className="hidden"
            accept=".pdf,.doc,.docx,.txt,.pptx"
            onChange={handleFileUpload}
          />
        </div>
        {error && (
          <p className="mt-2 text-sm text-rose-300">{error}</p>
        )}
      </div>

      <div className="flex min-h-0 flex-1">
        {/* Item list — full width until something is selected */}
        <div
          className={
            selectedItem
              ? 'hidden w-80 flex-shrink-0 flex-col border-r border-white/8 pr-4 md:flex'
              : 'flex min-w-0 flex-1 flex-col'
          }
        >
          {/* Filter tabs */}
          <div className="flex flex-shrink-0 gap-4 px-3 pb-3">
            {tabs.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setFilter(tab.key)}
                className={`text-xs transition-colors ${
                  filter === tab.key ? 'text-white' : 'text-slate-500 hover:text-slate-300'
                }`}
              >
                {tab.label}
                {tab.count > 0 && <span className="ml-1 text-slate-600">{tab.count}</span>}
              </button>
            ))}
          </div>

          {/* Rows */}
          <div className="min-h-0 flex-1 overflow-y-auto">
            {loading && items.length === 0 ? (
              <p className="px-3 pt-3 text-sm text-slate-500">Loading…</p>
            ) : items.length === 0 ? (
              <p className="px-3 pt-3 text-sm text-slate-500">Nothing captured yet.</p>
            ) : (
              items.map((item) => (
                <button
                  key={item.id}
                  onClick={() => selectItem(item.id)}
                  className={`w-full border-l-2 px-3 py-2.5 text-left transition-colors hover:bg-white/[0.04] ${rowBorder(item)} ${
                    selectedItem?.id === item.id ? 'bg-white/[0.04]' : ''
                  }`}
                >
                  <div
                    className={`truncate text-[15px] ${
                      item.status === 'unread' ? 'font-medium text-slate-100' : 'text-slate-200'
                    }`}
                  >
                    {item.title || 'Untitled'}
                  </div>
                  <div className="mt-0.5 flex items-baseline gap-2 text-xs text-slate-500">
                    <span className="min-w-0 truncate">
                      {item.original_url ? getDomain(item.original_url) : item.content_type}
                      {item.word_count ? ` · ${item.word_count} words` : ''}
                      {item.status === 'kept' ? ' · kept' : item.status === 'discarded' ? ' · discarded' : ''}
                      {item.extraction_status === 'pending' ? ' · extracting…' : ''}
                      {item.extraction_status === 'failed' ? ' · extraction failed' : ''}
                    </span>
                    <span className="ml-auto flex-shrink-0 tabular-nums">{timeAgo(item.shared_at)}</span>
                  </div>
                  {item.description && !selectedItem && (
                    <div className="mt-0.5 truncate text-xs text-slate-500">{item.description}</div>
                  )}
                </button>
              ))
            )}
          </div>
        </div>

        {/* Reader — only rendered when an item is selected */}
        {selectedItem && (
          <div className="flex min-w-0 flex-1 flex-col md:pl-5">
            {/* Reader header */}
            <div className="flex-shrink-0 border-b border-white/8 pb-3">
              <div className="flex items-start gap-3">
                <div className="min-w-0 flex-1">
                  <h2 className="truncate font-display text-lg font-semibold text-white">
                    {selectedItem.title || 'Untitled'}
                  </h2>
                  <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
                    {selectedItem.original_url && (
                      <a
                        href={selectedItem.original_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="max-w-md truncate transition-colors hover:text-teal-300"
                      >
                        {getDomain(selectedItem.original_url)}
                      </a>
                    )}
                    {selectedItem.word_count && (
                      <span>{selectedItem.word_count.toLocaleString()} words</span>
                    )}
                    <span>{timeAgo(selectedItem.shared_at)}</span>
                    {selectedItem.discussed && <span>discussed</span>}
                    {selectedItem.consolidated && <span>in memory</span>}
                  </div>
                </div>
                <button
                  onClick={() => setSelectedItem(null)}
                  className="flex-shrink-0 text-xs text-slate-500 transition-colors hover:text-slate-300"
                  title="Close"
                >
                  ✕ Close
                </button>
              </div>

              {/* Actions — quiet text, destructive quietest */}
              <div className="mt-2.5 flex flex-wrap items-baseline gap-x-4 gap-y-1.5">
                <button
                  onClick={() => updateStatus(selectedItem.id, 'kept')}
                  disabled={selectedItem.status === 'kept'}
                  className={`text-xs transition-colors ${
                    selectedItem.status === 'kept'
                      ? 'cursor-default text-teal-300/80'
                      : 'text-slate-400 hover:text-teal-300'
                  }`}
                >
                  {selectedItem.status === 'kept' ? 'Kept' : 'Keep'}
                </button>
                {onNavigateToChat && (
                  <button
                    onClick={discussItem}
                    className="text-xs text-teal-300/90 transition-colors hover:text-teal-200"
                  >
                    Discuss with Sara
                  </button>
                )}
                {selectedItem.original_url && (
                  <a
                    href={selectedItem.original_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-slate-400 transition-colors hover:text-slate-200"
                  >
                    Open source
                  </a>
                )}
                <span className="ml-auto flex items-baseline gap-4">
                  <button
                    onClick={() => updateStatus(selectedItem.id, 'discarded')}
                    disabled={selectedItem.status === 'discarded'}
                    className={`text-xs transition-colors ${
                      selectedItem.status === 'discarded'
                        ? 'cursor-default text-slate-600'
                        : 'text-slate-500 hover:text-rose-300'
                    }`}
                  >
                    {selectedItem.status === 'discarded' ? 'Discarded' : 'Discard'}
                  </button>
                  <button
                    onClick={() => deleteItem(selectedItem.id)}
                    className="text-xs text-slate-500 transition-colors hover:text-rose-300"
                  >
                    Delete
                  </button>
                </span>
              </div>

              {/* Original / Text toggle — only for items with files */}
              {selectedItem.storage_key && (
                <div className="mt-2.5 flex gap-4">
                  <button
                    onClick={() => setViewMode('original')}
                    className={`border-b-2 pb-0.5 text-xs transition-colors ${
                      viewMode === 'original'
                        ? 'border-teal-300 text-white'
                        : 'border-transparent text-slate-500 hover:text-slate-300'
                    }`}
                  >
                    Original
                  </button>
                  <button
                    onClick={() => setViewMode('text')}
                    className={`border-b-2 pb-0.5 text-xs transition-colors ${
                      viewMode === 'text'
                        ? 'border-teal-300 text-white'
                        : 'border-transparent text-slate-500 hover:text-slate-300'
                    }`}
                  >
                    Text
                  </button>
                </div>
              )}
            </div>

            {/* Reader body */}
            <div className="min-h-0 flex-1 overflow-y-auto pt-4">
              {selectedItem.extraction_status === 'pending' || selectedItem.extraction_status === 'extracting' ? (
                <p className="text-sm text-slate-500">
                  Extracting content…{' '}
                  <button
                    onClick={() => selectItem(selectedItem.id)}
                    className="text-slate-400 transition-colors hover:text-teal-300"
                  >
                    Refresh
                  </button>
                </p>
              ) : selectedItem.extraction_status === 'failed' ? (
                <p className="text-sm text-slate-500">
                  Extraction failed.
                  {selectedItem.original_url && (
                    <>
                      {' '}
                      <a
                        href={selectedItem.original_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-slate-400 transition-colors hover:text-teal-300"
                      >
                        Open the original source
                      </a>
                    </>
                  )}
                </p>
              ) : viewMode === 'original' && selectedItem.storage_key ? (
                // Native file viewer
                fileLoading ? (
                  <p className="text-sm text-slate-500">Loading file…</p>
                ) : docxHtml ? (
                  // DOCX rendered as HTML
                  <div
                    className="prose prose-invert prose-sm max-w-[75ch]"
                    dangerouslySetInnerHTML={{ __html: docxHtml }}
                  />
                ) : fileBlobUrl && (selectedItem.mime_type?.includes('pdf') || selectedItem.original_filename?.endsWith('.pdf')) ? (
                  // PDF in native browser viewer
                  <iframe
                    src={fileBlobUrl}
                    className="h-full min-h-[600px] w-full rounded-md border border-white/10"
                    title={selectedItem.title || 'PDF viewer'}
                  />
                ) : fileBlobUrl && selectedItem.mime_type?.startsWith('image/') ? (
                  // Images
                  <div className="flex justify-center">
                    <img
                      src={fileBlobUrl}
                      alt={selectedItem.title || 'Uploaded image'}
                      className="max-h-[80vh] max-w-full rounded-md object-contain"
                    />
                  </div>
                ) : fileBlobUrl ? (
                  // Other file types — download
                  <div className="pt-6 text-center">
                    <p className="text-sm text-slate-400">
                      {selectedItem.original_filename || 'File'}
                      {selectedItem.file_size && (
                        <span className="text-slate-500"> · {(selectedItem.file_size / 1024 / 1024).toFixed(1)} MB</span>
                      )}
                    </p>
                    <a
                      href={fileBlobUrl}
                      download={selectedItem.original_filename || 'download'}
                      className="mt-3 inline-block rounded-xl border border-white/10 px-3.5 py-2 text-sm text-slate-300 transition-colors hover:bg-white/[0.06] hover:text-white"
                    >
                      Download
                    </a>
                  </div>
                ) : (
                  <p className="text-sm text-slate-500">Couldn't load the file.</p>
                )
              ) : selectedItem.extracted_text ? (
                <div className="max-w-[75ch]">
                  {/* Reddit-specific metadata line */}
                  {selectedItem.content_type === 'reddit' && selectedItem.meta && (
                    <p className="mb-3 text-xs text-slate-500">
                      r/{selectedItem.meta.subreddit} · u/{selectedItem.meta.author} ·{' '}
                      {selectedItem.meta.score} points · {selectedItem.meta.num_comments} comments
                    </p>
                  )}

                  {/* PDF: page count line */}
                  {selectedItem.content_type === 'pdf' && selectedItem.meta?.page_count && (
                    <p className="mb-3 text-xs text-slate-500">
                      PDF · {selectedItem.meta.page_count} pages
                      {selectedItem.file_size && (
                        <span> · {(selectedItem.file_size / 1024 / 1024).toFixed(1)} MB</span>
                      )}
                    </p>
                  )}

                  <div className="prose prose-invert prose-sm max-w-none text-[15px] leading-relaxed text-slate-300">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {selectedItem.extracted_text}
                    </ReactMarkdown>
                  </div>
                </div>
              ) : (
                <p className="text-sm text-slate-500">No content extracted.</p>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
