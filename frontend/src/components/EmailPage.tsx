/**
 * Email Page Component - Microsoft Graph email integration
 *
 * Three-column layout:
 * - Left: Email list with filters
 * - Center: Email detail view
 * - Right: Sara chat about selected email
 */

import React, { useState, useEffect, useRef } from 'react';
import { APP_CONFIG } from '../config';

// Types
interface EmailAttachment {
  id: string;
  filename: string;
  content_type: string | null;
  size: number;
  is_inline: boolean;
  is_riskninja_relevant: boolean;
  has_download: boolean;
}

interface Email {
  id: string;
  mailbox: string;
  subject: string;
  sender_email: string;
  sender_name: string | null;
  received_at: string;
  importance: string;
  is_read: boolean;
  body_preview: string | null;
  has_attachments: boolean;
  attachment_count: number;
  category: string | null;
  importance_score: number | null;
  summary: string | null;
  action_required: boolean;
  to_recipients: Array<{ email: string; name: string }>;
  cc_recipients: Array<{ email: string; name: string }>;
}

interface EmailDetail extends Email {
  body_text: string | null;
  body_html: string | null;
  conversation_id: string | null;
  internet_message_id: string | null;
  attachments: EmailAttachment[];
  analyzed_at: string | null;
  synced_at: string;
}

interface EmailStats {
  total_emails: number;
  unread_count: number;
  by_category: Record<string, number>;
  by_mailbox: Record<string, number>;
  action_required_count: number;
  high_importance_count: number;
  last_sync: string | null;
}

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

// Cap alarming counts — never render a raw triple-digit number
const capCount = (n: number): string => (n > 99 ? '99+' : String(n));

// Format file size
const formatFileSize = (bytes: number): string => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

// Format date
const formatDate = (dateStr: string): string => {
  const date = new Date(dateStr);
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  const days = Math.floor(diff / (1000 * 60 * 60 * 24));

  if (days === 0) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } else if (days === 1) {
    return 'Yesterday';
  } else if (days < 7) {
    return date.toLocaleDateString([], { weekday: 'short' });
  } else {
    return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
  }
};

interface EmailPageProps {
  className?: string;
}

export const EmailPage: React.FC<EmailPageProps> = ({ className }) => {
  // State
  const [emails, setEmails] = useState<Email[]>([]);
  const [selectedEmail, setSelectedEmail] = useState<EmailDetail | null>(null);
  const [stats, setStats] = useState<EmailStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);

  // Filters
  const [filter, setFilter] = useState<{
    mailbox: string | null;
    category: string | null;
    unreadOnly: boolean;
    actionRequired: boolean;
    search: string;
  }>({
    mailbox: null,
    category: null,
    unreadOnly: false,
    actionRequired: false,
    search: '',
  });

  // Chat state
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [chatLoading, setChatLoading] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);

  // Fetch emails
  const fetchEmails = async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams();
      if (filter.mailbox) params.append('mailbox', filter.mailbox);
      if (filter.category) params.append('category', filter.category);
      if (filter.unreadOnly) params.append('unread_only', 'true');
      if (filter.actionRequired) params.append('action_required_only', 'true');
      if (filter.search) params.append('search', filter.search);

      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/email?${params.toString()}`,
        { credentials: 'include' }
      );

      if (response.ok) {
        const data = await response.json();
        setEmails(data.emails || []);
      }
    } catch (error) {
      console.error('Error fetching emails:', error);
    } finally {
      setLoading(false);
    }
  };

  // Fetch email stats
  const fetchStats = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/email/stats`, {
        credentials: 'include',
      });

      if (response.ok) {
        const data = await response.json();
        setStats(data);
      }
    } catch (error) {
      console.error('Error fetching stats:', error);
    }
  };

  // Fetch email detail
  const fetchEmailDetail = async (emailId: string) => {
    try {
      setDetailLoading(true);
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/email/${emailId}`, {
        credentials: 'include',
      });

      if (response.ok) {
        const data = await response.json();
        setSelectedEmail(data);
        setChatMessages([]); // Clear chat when switching emails

        // Mark as read if unread
        if (!data.is_read) {
          markAsRead(emailId);
        }
      }
    } catch (error) {
      console.error('Error fetching email detail:', error);
    } finally {
      setDetailLoading(false);
    }
  };

  // Mark as read
  const markAsRead = async (emailId: string) => {
    try {
      await fetch(`${APP_CONFIG.apiUrl}/api/email/${emailId}/mark-read`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_read: true }),
      });

      // Update local state
      setEmails((prev) =>
        prev.map((e) => (e.id === emailId ? { ...e, is_read: true } : e))
      );
      fetchStats();
    } catch (error) {
      console.error('Error marking as read:', error);
    }
  };

  // Trigger sync
  const triggerSync = async () => {
    try {
      setSyncing(true);
      await fetch(`${APP_CONFIG.apiUrl}/api/email/sync`, {
        method: 'POST',
        credentials: 'include',
      });
      // Wait a bit then refresh
      setTimeout(() => {
        fetchEmails();
        fetchStats();
        setSyncing(false);
      }, 3000);
    } catch (error) {
      console.error('Error triggering sync:', error);
      setSyncing(false);
    }
  };

  // Refresh attachments from Graph API
  const refreshAttachments = async (emailId: string) => {
    try {
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/email/${emailId}/refresh-attachments`,
        { method: 'POST', credentials: 'include' }
      );

      if (response.ok) {
        const data = await response.json();
        if (data.new_attachments > 0) {
          // Refresh the email detail to show new attachments
          fetchEmailDetail(emailId);
        }
        return data;
      }
    } catch (error) {
      console.error('Error refreshing attachments:', error);
    }
    return null;
  };

  // Download attachment
  const downloadAttachment = async (emailId: string, attachmentId: string, filename: string) => {
    try {
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/email/${emailId}/attachments/${attachmentId}/download`,
        { credentials: 'include' }
      );

      if (response.ok) {
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        a.remove();
      } else if (response.status === 202) {
        alert('Attachment download queued. Please try again in a moment.');
      }
    } catch (error) {
      console.error('Error downloading attachment:', error);
    }
  };

  // Send chat message
  const sendChatMessage = async () => {
    if (!chatInput.trim() || !selectedEmail) return;

    const userMessage = chatInput.trim();
    setChatInput('');
    setChatMessages((prev) => [...prev, { role: 'user', content: userMessage }]);
    setChatLoading(true);

    try {
      const response = await fetch(
        `${APP_CONFIG.apiUrl}/api/email/${selectedEmail.id}/chat`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: userMessage }),
        }
      );

      if (response.ok) {
        const data = await response.json();
        setChatMessages((prev) => [
          ...prev,
          { role: 'assistant', content: data.response },
        ]);
      }
    } catch (error) {
      console.error('Error sending chat:', error);
      setChatMessages((prev) => [
        ...prev,
        { role: 'assistant', content: 'Sorry, I encountered an error processing your request.' },
      ]);
    } finally {
      setChatLoading(false);
    }
  };

  // Scroll chat to bottom only when there are messages
  useEffect(() => {
    if (chatMessages.length > 0) {
      chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [chatMessages]);

  // Initial load
  useEffect(() => {
    fetchEmails();
    fetchStats();
  }, [filter]);

  return (
    <div className={`h-full flex flex-col ${className || ''}`}>
      {/* Header — one slim row: title + live state, sync on the right */}
      <div className="flex h-12 flex-shrink-0 items-center justify-between gap-3 border-b border-white/5 px-4">
        <div className="flex min-w-0 items-baseline gap-3">
          <h2 className="font-display text-xl font-semibold text-white">Email</h2>
          {stats && (
            <span className="truncate text-sm text-slate-500">
              {capCount(stats.unread_count)} unread
              {syncing
                ? ' · syncing…'
                : stats.last_sync
                  ? ` · synced ${formatDate(stats.last_sync)}`
                  : ''}
            </span>
          )}
        </div>
        <button
          onClick={triggerSync}
          disabled={syncing}
          className="flex flex-shrink-0 items-center gap-1.5 text-xs text-slate-500 transition-colors hover:text-teal-300 disabled:opacity-50"
          title="Sync emails"
        >
          <span className={`material-icons text-[16px] ${syncing ? 'animate-spin' : ''}`}>sync</span>
          Sync
        </button>
      </div>

      <div className="flex min-h-0 flex-1">
      {/* Left Panel - Email List (takes the space when nothing is selected) */}
      <div
        className={`flex min-h-0 flex-col border-r border-white/5 ${
          selectedEmail ? 'w-80 flex-shrink-0' : 'w-full max-w-2xl'
        }`}
      >
        {/* Search */}
        <div className="px-3 pt-3">
          <input
            type="text"
            placeholder="Search emails…"
            value={filter.search}
            onChange={(e) => setFilter({ ...filter, search: e.target.value })}
            className="w-full rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-sm text-slate-100 placeholder-slate-500 outline-none focus:border-teal-300/30"
          />
        </div>

        {/* Filters — quiet text tabs */}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5">
          <button
            onClick={() => setFilter({ ...filter, unreadOnly: !filter.unreadOnly })}
            className={`text-xs transition-colors ${
              filter.unreadOnly ? 'font-medium text-teal-300' : 'text-slate-500 hover:text-slate-300'
            }`}
          >
            Unread
          </button>
          <button
            onClick={() => setFilter({ ...filter, actionRequired: !filter.actionRequired })}
            className={`text-xs transition-colors ${
              filter.actionRequired ? 'font-medium text-teal-300' : 'text-slate-500 hover:text-slate-300'
            }`}
          >
            Action required
            {stats && stats.action_required_count > 0 && (
              <span className="ml-1 text-slate-600">{capCount(stats.action_required_count)}</span>
            )}
          </button>
          {filter.category && (
            <button
              onClick={() => setFilter({ ...filter, category: null })}
              className="flex items-center gap-1 text-xs text-slate-400 transition-colors hover:text-slate-200"
            >
              {filter.category}
              <span className="material-icons text-xs">close</span>
            </button>
          )}
        </div>

        {/* Email List */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <p className="px-4 py-4 text-sm text-slate-500">Loading…</p>
          ) : emails.length === 0 ? (
            <p className="px-4 py-6 text-sm text-slate-500">No emails match.</p>
          ) : (
            emails.map((email) => (
              <div
                key={email.id}
                onClick={() => fetchEmailDetail(email.id)}
                className={`cursor-pointer px-4 py-3 transition-colors hover:bg-white/[0.04] ${
                  selectedEmail?.id === email.id ? 'bg-white/[0.06]' : ''
                } ${!email.is_read ? 'border-l-2 border-l-teal-400/80' : 'border-l-2 border-l-transparent'}`}
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span
                    className={`min-w-0 flex-1 truncate text-[15px] ${
                      !email.is_read ? 'font-medium text-white' : 'text-slate-200'
                    }`}
                  >
                    {email.sender_name || email.sender_email}
                  </span>
                  <span className="flex-shrink-0 text-xs tabular-nums text-slate-500">
                    {formatDate(email.received_at)}
                  </span>
                </div>
                <div
                  className={`mt-0.5 truncate text-sm ${
                    !email.is_read ? 'text-slate-300' : 'text-slate-400'
                  }`}
                >
                  {email.subject}
                </div>
                {(email.summary || email.body_preview) && (
                  <div
                    className={`mt-0.5 text-sm text-slate-500 ${
                      selectedEmail ? 'truncate' : 'line-clamp-2'
                    }`}
                  >
                    {email.summary || email.body_preview}
                  </div>
                )}
                {(email.category || email.action_required || email.has_attachments) && (
                  <div className="mt-1.5 flex items-center gap-2">
                    {email.category && (
                      <span className="rounded bg-white/[0.05] px-1.5 py-0.5 text-[11px] text-slate-500">
                        {email.category}
                      </span>
                    )}
                    {email.action_required && (
                      <span className="text-[11px] text-amber-300/80">action needed</span>
                    )}
                    {email.has_attachments && (
                      <span className="material-icons text-sm text-slate-600">attachment</span>
                    )}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </div>

      {/* Center Panel - Email Detail */}
      <div className="flex min-w-0 flex-1 flex-col">
        {detailLoading ? (
          <div className="flex flex-1 items-center justify-center text-sm text-slate-500">Loading…</div>
        ) : selectedEmail ? (
          <>
            {/* Email Header */}
            <div className="border-b border-white/5 px-6 py-4">
              <h1 className="font-display text-xl font-semibold leading-snug text-white">
                {selectedEmail.subject}
              </h1>
              <div className="mt-1.5 flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-sm">
                <span className="text-slate-300">
                  {selectedEmail.sender_name ? (
                    <>
                      {selectedEmail.sender_name}{' '}
                      <span className="text-slate-500">&lt;{selectedEmail.sender_email}&gt;</span>
                    </>
                  ) : (
                    selectedEmail.sender_email
                  )}
                </span>
                <span className="text-xs text-slate-500">
                  {new Date(selectedEmail.received_at).toLocaleString()}
                </span>
              </div>
              {selectedEmail.to_recipients.length > 0 && (
                <div className="mt-1 text-xs text-slate-500">
                  To: {selectedEmail.to_recipients.map((r) => r.name || r.email).join(', ')}
                </div>
              )}
              {selectedEmail.attachments.length === 0 && (
                <button
                  onClick={() => refreshAttachments(selectedEmail.id)}
                  className="mt-2 text-xs text-slate-500 transition-colors hover:text-teal-300"
                >
                  Check for attachments
                </button>
              )}
            </div>

            {/* Sara's Analysis */}
            {selectedEmail.analyzed_at && (
              <div className="border-b border-white/5 px-6 py-4">
                <div className="border-l-2 border-teal-400/60 pl-3">
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="text-[11px] font-semibold uppercase tracking-[0.16em] text-teal-300/90">
                      Sara's read
                    </span>
                    {selectedEmail.category && (
                      <span className="rounded bg-white/[0.05] px-1.5 py-0.5 text-[11px] text-slate-500">
                        {selectedEmail.category}
                      </span>
                    )}
                    {selectedEmail.importance_score !== null && (
                      <span className="text-xs text-slate-500">
                        importance {Math.round(selectedEmail.importance_score * 100)}%
                      </span>
                    )}
                  </div>
                  {selectedEmail.summary && (
                    <p className="mt-1.5 text-sm leading-relaxed text-slate-300">{selectedEmail.summary}</p>
                  )}
                </div>
              </div>
            )}

            {/* Attachments */}
            {selectedEmail.attachments.length > 0 && (
              <div className="border-b border-white/5 px-6 py-3">
                <div className="flex flex-wrap gap-2">
                  {selectedEmail.attachments.map((att) => (
                    <button
                      key={att.id}
                      onClick={() => downloadAttachment(selectedEmail.id, att.id, att.filename)}
                      className="flex items-center gap-2 rounded-xl border border-white/10 px-3 py-1.5 text-sm text-slate-300 transition-colors hover:bg-white/[0.06] hover:text-white"
                    >
                      <span className="material-icons text-sm text-slate-500">
                        {att.content_type?.startsWith('image/') ? 'image' : 'description'}
                      </span>
                      <span className="max-w-[200px] truncate">{att.filename}</span>
                      <span className="text-xs text-slate-500">{formatFileSize(att.size)}</span>
                      {att.is_riskninja_relevant && (
                        <span className="text-xs text-teal-300/80">RiskNinja</span>
                      )}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Email Body */}
            <div className="flex-1 overflow-y-auto px-6 py-4">
              {selectedEmail.body_html ? (
                <div
                  className="prose prose-invert max-w-none prose-headings:text-white prose-p:text-slate-200 prose-li:text-slate-200"
                  dangerouslySetInnerHTML={{ __html: selectedEmail.body_html }}
                />
              ) : (
                <pre className="whitespace-pre-wrap font-sans text-[15px] leading-relaxed text-slate-300">
                  {selectedEmail.body_text || selectedEmail.body_preview}
                </pre>
              )}
            </div>
          </>
        ) : (
          <div className="flex flex-1 items-center justify-center p-8">
            <p className="text-sm text-slate-500">Select an email to read it here.</p>
          </div>
        )}
      </div>

      {/* Right Panel - Sara Chat (only once an email is selected) */}
      {selectedEmail && (
        <div className="flex w-80 flex-shrink-0 flex-col border-l border-white/5">
          <div className="border-b border-white/5 px-4 py-3">
            <h3 className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">
              Ask Sara
            </h3>
            <p className="mt-1 truncate text-xs text-slate-500">{selectedEmail.subject}</p>
          </div>

          {/* Chat Messages */}
          <div className="flex-1 space-y-4 overflow-y-auto p-4">
            {chatMessages.length === 0 ? (
              <div className="space-y-1">
                {['Summarize this email', 'Draft a reply', 'What action should I take?', 'Is this urgent?'].map(
                  (suggestion) => (
                    <button
                      key={suggestion}
                      onClick={() => {
                        setChatInput(suggestion);
                      }}
                      className="block w-full rounded-lg px-2 py-1.5 text-left text-sm text-slate-400 transition-colors hover:bg-white/[0.04] hover:text-slate-200"
                    >
                      {suggestion}
                    </button>
                  )
                )}
              </div>
            ) : (
              chatMessages.map((msg, idx) => (
                <div key={idx}>
                  <div
                    className={`text-xs ${msg.role === 'user' ? 'text-slate-500' : 'text-teal-300/80'}`}
                  >
                    {msg.role === 'user' ? 'You' : 'Sara'}
                  </div>
                  <div className="mt-0.5 whitespace-pre-wrap text-sm leading-relaxed text-slate-200">
                    {msg.content}
                  </div>
                </div>
              ))
            )}
            {chatLoading && (
              <div>
                <div className="text-xs text-teal-300/80">Sara</div>
                <div className="mt-0.5 text-sm text-slate-500">Thinking…</div>
              </div>
            )}
            <div ref={chatEndRef} />
          </div>

          {/* Chat Input */}
          <div className="border-t border-white/5 p-3">
            <div className="flex items-center gap-1 rounded-xl border border-white/10 bg-white/[0.04] px-3 transition-colors focus-within:border-teal-300/30">
              <input
                type="text"
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyPress={(e) => e.key === 'Enter' && sendChatMessage()}
                placeholder="Ask about this email…"
                className="min-w-0 flex-1 bg-transparent py-2 text-sm text-slate-100 placeholder-slate-500 outline-none"
              />
              <button
                onClick={sendChatMessage}
                disabled={!chatInput.trim() || chatLoading}
                className="rounded-lg p-1.5 text-slate-500 transition-colors enabled:text-teal-300 enabled:hover:bg-teal-400/10 disabled:opacity-40"
                aria-label="Send to Sara"
              >
                <span className="material-icons text-[18px]">arrow_upward</span>
              </button>
            </div>
          </div>
        </div>
      )}
      </div>
    </div>
  );
};

export default EmailPage;
