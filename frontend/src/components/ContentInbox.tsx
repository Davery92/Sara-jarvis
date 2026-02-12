/**
 * Content Inbox — Share URLs, Reddit posts, PDFs, and text to Sara.
 * Two-panel layout: item list + detail/reader.
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

// Content type icons
const TYPE_ICONS: Record<string, string> = {
  url: '🔗',
  reddit: '🟠',
  pdf: '📄',
  text: '📝',
  document: '📎',
};

const STATUS_BADGES: Record<string, string> = {
  unread: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  read: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
  kept: 'bg-green-500/20 text-green-400 border-green-500/30',
  discarded: 'bg-red-500/20 text-red-400 border-red-500/30',
};

interface ContentInboxProps {
  onNavigateToChat?: (inboxItemId: string, title: string) => void;
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
  const loadItems = useCallback(async () => {
    setLoading(true);
    try {
      const statusParam = filter !== 'all' ? `?status=${filter}` : '';
      const [itemsData, statsData] = await Promise.all([
        apiFetch(`/api/inbox${statusParam}&limit=100`.replace('?&', '?').replace(/^\/api\/inbox&/, '/api/inbox?')),
        apiFetch('/api/inbox/stats'),
      ]);
      // Fix: handle case where statusParam is empty
      setItems(Array.isArray(itemsData) ? itemsData : []);
      setStats(statsData);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [apiFetch, filter]);

  // Properly construct the URL for list
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
  }, [selectedItem?.id]); // eslint-disable-line react-hooks/exhaustive-deps

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
  }, [viewMode, selectedItem?.id, selectedItem?.storage_key]); // eslint-disable-line react-hooks/exhaustive-deps

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
    onNavigateToChat(selectedItem.id, selectedItem.title || 'Inbox item');
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

  return (
    <div className="flex flex-col h-full bg-gray-900">
      {/* Share input bar */}
      <div className="flex-shrink-0 p-4 border-b border-gray-700/50">
        <div className="flex gap-2">
          <input
            type="text"
            value={shareUrl}
            onChange={(e) => setShareUrl(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleShareUrl()}
            placeholder="Paste a URL or type something to save..."
            className="flex-1 bg-gray-800 border border-gray-600 rounded-lg px-4 py-2.5 text-white placeholder-gray-500 focus:outline-none focus:border-teal-500"
          />
          <button
            onClick={handleShareUrl}
            disabled={!shareUrl.trim() || shareLoading}
            className="px-4 py-2.5 bg-teal-600 hover:bg-teal-500 disabled:bg-gray-700 disabled:text-gray-500 text-white rounded-lg font-medium transition-colors"
          >
            {shareLoading ? '...' : 'Save'}
          </button>
          <button
            onClick={() => fileInputRef.current?.click()}
            className="px-4 py-2.5 bg-gray-700 hover:bg-gray-600 text-white rounded-lg font-medium transition-colors"
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
          <div className="mt-2 text-red-400 text-sm">{error}</div>
        )}
      </div>

      {/* Main two-panel layout */}
      <div className="flex flex-1 min-h-0">
        {/* Left panel — item list */}
        <div className="w-96 flex-shrink-0 border-r border-gray-700/50 flex flex-col">
          {/* Filter tabs */}
          <div className="flex gap-1 p-2 border-b border-gray-700/30">
            {tabs.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setFilter(tab.key)}
                className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                  filter === tab.key
                    ? 'bg-teal-600/20 text-teal-400'
                    : 'text-gray-400 hover:text-white hover:bg-gray-800'
                }`}
              >
                {tab.label}
                {tab.count > 0 && (
                  <span className="ml-1.5 text-xs opacity-60">({tab.count})</span>
                )}
              </button>
            ))}
          </div>

          {/* Item list */}
          <div className="flex-1 overflow-y-auto">
            {loading && items.length === 0 ? (
              <div className="p-4 text-gray-500 text-center">Loading...</div>
            ) : items.length === 0 ? (
              <div className="p-8 text-gray-500 text-center">
                <div className="text-3xl mb-2">📥</div>
                <div className="font-medium">No items yet</div>
                <div className="text-sm mt-1">Paste a URL above to get started</div>
              </div>
            ) : (
              items.map((item) => (
                <button
                  key={item.id}
                  onClick={() => selectItem(item.id)}
                  className={`w-full text-left p-3 border-b border-gray-800/50 hover:bg-gray-800/50 transition-colors ${
                    selectedItem?.id === item.id ? 'bg-gray-800 border-l-2 border-l-teal-500' : ''
                  }`}
                >
                  <div className="flex items-start gap-3">
                    <span className="text-lg flex-shrink-0 mt-0.5">
                      {TYPE_ICONS[item.content_type] || '📄'}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className={`text-sm font-medium truncate ${
                          item.status === 'unread' ? 'text-white' : 'text-gray-300'
                        }`}>
                          {item.title || 'Untitled'}
                        </span>
                      </div>
                      <div className="text-xs text-gray-500 mt-0.5 truncate">
                        {item.original_url ? getDomain(item.original_url) : item.content_type}
                        {item.word_count ? ` · ${item.word_count} words` : ''}
                      </div>
                      {item.description && (
                        <div className="text-xs text-gray-500 mt-1 line-clamp-2">
                          {item.description}
                        </div>
                      )}
                      <div className="flex items-center gap-2 mt-1.5">
                        <span className={`text-[10px] px-1.5 py-0.5 rounded border ${STATUS_BADGES[item.status] || STATUS_BADGES.read}`}>
                          {item.status}
                        </span>
                        {item.extraction_status === 'pending' && (
                          <span className="text-[10px] text-yellow-500">extracting...</span>
                        )}
                        {item.extraction_status === 'failed' && (
                          <span className="text-[10px] text-red-500">failed</span>
                        )}
                        <span className="text-[10px] text-gray-600 ml-auto">
                          {timeAgo(item.shared_at)}
                        </span>
                      </div>
                    </div>
                  </div>
                </button>
              ))
            )}
          </div>
        </div>

        {/* Right panel — detail */}
        <div className="flex-1 flex flex-col min-w-0">
          {selectedItem ? (
            <>
              {/* Detail header */}
              <div className="flex-shrink-0 p-4 border-b border-gray-700/50">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <h2 className="text-lg font-semibold text-white truncate">
                      {TYPE_ICONS[selectedItem.content_type]} {selectedItem.title || 'Untitled'}
                    </h2>
                    <div className="flex items-center gap-3 mt-1 text-sm text-gray-400">
                      {selectedItem.original_url && (
                        <a
                          href={selectedItem.original_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="hover:text-teal-400 truncate max-w-md"
                        >
                          {getDomain(selectedItem.original_url)}
                        </a>
                      )}
                      {selectedItem.word_count && (
                        <span>{selectedItem.word_count.toLocaleString()} words</span>
                      )}
                      <span>{timeAgo(selectedItem.shared_at)}</span>
                      {selectedItem.discussed && (
                        <span className="text-teal-400 text-xs">discussed</span>
                      )}
                      {selectedItem.consolidated && (
                        <span className="text-purple-400 text-xs">in memory</span>
                      )}
                    </div>
                  </div>
                </div>

                {/* Action bar */}
                <div className="flex gap-2 mt-3">
                  <button
                    onClick={() => updateStatus(selectedItem.id, 'kept')}
                    disabled={selectedItem.status === 'kept'}
                    className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                      selectedItem.status === 'kept'
                        ? 'bg-green-600/20 text-green-400 cursor-default'
                        : 'bg-green-600/10 text-green-400 hover:bg-green-600/20 border border-green-500/30'
                    }`}
                  >
                    {selectedItem.status === 'kept' ? 'Kept' : 'Keep'}
                  </button>
                  <button
                    onClick={() => updateStatus(selectedItem.id, 'discarded')}
                    disabled={selectedItem.status === 'discarded'}
                    className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                      selectedItem.status === 'discarded'
                        ? 'bg-red-600/20 text-red-400 cursor-default'
                        : 'bg-red-600/10 text-red-400 hover:bg-red-600/20 border border-red-500/30'
                    }`}
                  >
                    {selectedItem.status === 'discarded' ? 'Discarded' : 'Discard'}
                  </button>
                  {onNavigateToChat && (
                    <button
                      onClick={discussItem}
                      className="px-3 py-1.5 rounded-md text-sm font-medium bg-teal-600/10 text-teal-400 hover:bg-teal-600/20 border border-teal-500/30 transition-colors"
                    >
                      Discuss with Sara
                    </button>
                  )}
                  {selectedItem.original_url && (
                    <a
                      href={selectedItem.original_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="px-3 py-1.5 rounded-md text-sm font-medium bg-gray-700/50 text-gray-300 hover:bg-gray-700 transition-colors"
                    >
                      Open Source
                    </a>
                  )}
                  <button
                    onClick={() => deleteItem(selectedItem.id)}
                    className="px-3 py-1.5 rounded-md text-sm font-medium text-gray-500 hover:text-red-400 hover:bg-red-500/10 transition-colors ml-auto"
                  >
                    Delete
                  </button>
                </div>

                {/* Original / Text toggle — only for items with files */}
                {selectedItem.storage_key && (
                  <div className="flex gap-1 mt-3 bg-gray-800/50 rounded-lg p-1 w-fit">
                    <button
                      onClick={() => setViewMode('original')}
                      className={`px-3 py-1 rounded-md text-sm font-medium transition-colors ${
                        viewMode === 'original'
                          ? 'bg-gray-700 text-white'
                          : 'text-gray-400 hover:text-white'
                      }`}
                    >
                      Original
                    </button>
                    <button
                      onClick={() => setViewMode('text')}
                      className={`px-3 py-1 rounded-md text-sm font-medium transition-colors ${
                        viewMode === 'text'
                          ? 'bg-gray-700 text-white'
                          : 'text-gray-400 hover:text-white'
                      }`}
                    >
                      Text
                    </button>
                  </div>
                )}
              </div>

              {/* Content body */}
              <div className="flex-1 overflow-y-auto p-4">
                {selectedItem.extraction_status === 'pending' || selectedItem.extraction_status === 'extracting' ? (
                  <div className="text-center text-gray-500 py-12">
                    <div className="text-4xl mb-3 animate-pulse">⏳</div>
                    <div>Extracting content...</div>
                    <button
                      onClick={() => selectItem(selectedItem.id)}
                      className="mt-3 text-teal-400 hover:text-teal-300 text-sm"
                    >
                      Refresh
                    </button>
                  </div>
                ) : selectedItem.extraction_status === 'failed' ? (
                  <div className="text-center text-red-400 py-12">
                    <div className="text-4xl mb-3">❌</div>
                    <div>Extraction failed</div>
                    <div className="text-sm text-gray-500 mt-1">
                      {selectedItem.original_url && (
                        <a href={selectedItem.original_url} target="_blank" rel="noopener noreferrer"
                          className="text-teal-400 hover:text-teal-300">
                          Open original source
                        </a>
                      )}
                    </div>
                  </div>
                ) : viewMode === 'original' && selectedItem.storage_key ? (
                  // Native file viewer
                  fileLoading ? (
                    <div className="text-center text-gray-500 py-12">
                      <div className="text-4xl mb-3 animate-pulse">📄</div>
                      <div>Loading file...</div>
                    </div>
                  ) : docxHtml ? (
                    // DOCX rendered as HTML
                    <div
                      className="prose prose-invert prose-sm max-w-none"
                      dangerouslySetInnerHTML={{ __html: docxHtml }}
                    />
                  ) : fileBlobUrl && (selectedItem.mime_type?.includes('pdf') || selectedItem.original_filename?.endsWith('.pdf')) ? (
                    // PDF in native browser viewer
                    <iframe
                      src={fileBlobUrl}
                      className="w-full h-full min-h-[600px] rounded-lg border border-gray-700/50"
                      title={selectedItem.title || 'PDF viewer'}
                    />
                  ) : fileBlobUrl && selectedItem.mime_type?.startsWith('image/') ? (
                    // Images
                    <div className="flex justify-center">
                      <img
                        src={fileBlobUrl}
                        alt={selectedItem.title || 'Uploaded image'}
                        className="max-w-full max-h-[80vh] object-contain rounded-lg"
                      />
                    </div>
                  ) : fileBlobUrl ? (
                    // Other file types — download button
                    <div className="text-center text-gray-500 py-12">
                      <div className="text-4xl mb-3">📎</div>
                      <div className="mb-3">
                        {selectedItem.original_filename || 'File'}
                        {selectedItem.file_size && (
                          <span className="text-sm ml-2">({(selectedItem.file_size / 1024 / 1024).toFixed(1)} MB)</span>
                        )}
                      </div>
                      <a
                        href={fileBlobUrl}
                        download={selectedItem.original_filename || 'download'}
                        className="px-4 py-2 bg-teal-600 hover:bg-teal-500 text-white rounded-lg font-medium transition-colors inline-block"
                      >
                        Download
                      </a>
                    </div>
                  ) : (
                    <div className="text-center text-gray-500 py-12">
                      Failed to load file
                    </div>
                  )
                ) : selectedItem.extracted_text ? (
                  <div className="prose prose-invert prose-sm max-w-none">
                    {/* Reddit-specific: show metadata header */}
                    {selectedItem.content_type === 'reddit' && selectedItem.meta && (
                      <div className="mb-4 p-3 bg-orange-500/5 rounded-lg border border-orange-500/20">
                        <div className="flex items-center gap-3 text-sm text-gray-400">
                          <span className="text-orange-400 font-medium">
                            r/{selectedItem.meta.subreddit}
                          </span>
                          <span>u/{selectedItem.meta.author}</span>
                          <span>{selectedItem.meta.score} points</span>
                          <span>{selectedItem.meta.num_comments} comments</span>
                        </div>
                      </div>
                    )}

                    {/* PDF: show page count */}
                    {selectedItem.content_type === 'pdf' && selectedItem.meta?.page_count && (
                      <div className="mb-4 p-3 bg-blue-500/5 rounded-lg border border-blue-500/20 text-sm text-gray-400">
                        PDF document — {selectedItem.meta.page_count} pages
                        {selectedItem.file_size && (
                          <span> · {(selectedItem.file_size / 1024 / 1024).toFixed(1)} MB</span>
                        )}
                      </div>
                    )}

                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {selectedItem.extracted_text}
                    </ReactMarkdown>
                  </div>
                ) : (
                  <div className="text-center text-gray-500 py-12">
                    No content extracted
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center text-gray-500">
              <div className="text-center">
                <div className="text-5xl mb-3">📥</div>
                <div className="text-lg font-medium">Content Inbox</div>
                <div className="text-sm mt-1">
                  Save URLs, Reddit posts, PDFs, and notes.
                  <br />
                  Kept items are consolidated into memory overnight.
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
