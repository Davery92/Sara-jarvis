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

// Category colors
const CATEGORY_COLORS: Record<string, string> = {
  support: 'bg-red-500/20 text-red-400 border-red-500/30',
  urgent: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
  sales: 'bg-green-500/20 text-green-400 border-green-500/30',
  internal: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  newsletter: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
  personal: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
  financial: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  notification: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
};

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
    <div className={`h-full flex overflow-hidden ${className || ''}`}>
      {/* Left Panel - Email List */}
      <div className="w-80 border-r border-gray-700 flex flex-col bg-gray-900">
        {/* Header */}
        <div className="p-4 border-b border-gray-700">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <span className="material-icons text-teal-400">email</span>
              Email
            </h2>
            <button
              onClick={triggerSync}
              disabled={syncing}
              className="p-2 rounded hover:bg-gray-700 text-gray-400 hover:text-white transition-colors disabled:opacity-50"
              title="Sync emails"
            >
              <span className={`material-icons ${syncing ? 'animate-spin' : ''}`}>sync</span>
            </button>
          </div>

          {/* Stats */}
          {stats && (
            <div className="flex gap-4 text-sm text-gray-400 mb-3">
              <span>{stats.unread_count} unread</span>
              <span>{stats.action_required_count} action needed</span>
            </div>
          )}

          {/* Search */}
          <div className="relative">
            <span className="material-icons absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 text-lg">
              search
            </span>
            <input
              type="text"
              placeholder="Search emails..."
              value={filter.search}
              onChange={(e) => setFilter({ ...filter, search: e.target.value })}
              className="w-full bg-gray-800 border border-gray-600 rounded-lg pl-10 pr-4 py-2 text-white text-sm focus:outline-none focus:border-teal-500"
            />
          </div>
        </div>

        {/* Filters */}
        <div className="p-2 border-b border-gray-700 flex flex-wrap gap-2">
          <button
            onClick={() => setFilter({ ...filter, unreadOnly: !filter.unreadOnly })}
            className={`px-2 py-1 rounded text-xs transition-colors ${
              filter.unreadOnly
                ? 'bg-teal-500/20 text-teal-400 border border-teal-500/30'
                : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
            }`}
          >
            Unread
          </button>
          <button
            onClick={() => setFilter({ ...filter, actionRequired: !filter.actionRequired })}
            className={`px-2 py-1 rounded text-xs transition-colors ${
              filter.actionRequired
                ? 'bg-red-500/20 text-red-400 border border-red-500/30'
                : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
            }`}
          >
            Action Required
          </button>
          {filter.category && (
            <button
              onClick={() => setFilter({ ...filter, category: null })}
              className="px-2 py-1 rounded text-xs bg-gray-700 text-gray-400 hover:bg-gray-600 flex items-center gap-1"
            >
              {filter.category}
              <span className="material-icons text-xs">close</span>
            </button>
          )}
        </div>

        {/* Email List */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="p-4 text-center text-gray-500">Loading...</div>
          ) : emails.length === 0 ? (
            <div className="p-4 text-center text-gray-500">No emails found</div>
          ) : (
            emails.map((email) => (
              <div
                key={email.id}
                onClick={() => fetchEmailDetail(email.id)}
                className={`p-3 border-b border-gray-800 cursor-pointer hover:bg-gray-800 transition-colors ${
                  selectedEmail?.id === email.id ? 'bg-gray-800' : ''
                } ${!email.is_read ? 'border-l-2 border-l-teal-500' : ''}`}
              >
                <div className="flex items-start justify-between mb-1">
                  <span className={`text-sm truncate flex-1 ${!email.is_read ? 'font-semibold text-white' : 'text-gray-300'}`}>
                    {email.sender_name || email.sender_email}
                  </span>
                  <span className="text-xs text-gray-500 ml-2">{formatDate(email.received_at)}</span>
                </div>
                <div className={`text-sm truncate mb-1 ${!email.is_read ? 'text-white' : 'text-gray-400'}`}>
                  {email.subject}
                </div>
                <div className="text-xs text-gray-500 truncate mb-2">
                  {email.summary || email.body_preview}
                </div>
                <div className="flex items-center gap-2">
                  {email.category && (
                    <span className={`px-2 py-0.5 rounded text-xs border ${CATEGORY_COLORS[email.category] || CATEGORY_COLORS.notification}`}>
                      {email.category}
                    </span>
                  )}
                  {email.action_required && (
                    <span className="text-red-400 text-xs">Action needed</span>
                  )}
                  {email.has_attachments && (
                    <span className="material-icons text-gray-500 text-sm">attachment</span>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Center Panel - Email Detail */}
      <div className="flex-1 flex flex-col bg-gray-900 border-r border-gray-700">
        {detailLoading ? (
          <div className="flex-1 flex items-center justify-center text-gray-500">Loading...</div>
        ) : selectedEmail ? (
          <>
            {/* Email Header */}
            <div className="p-4 border-b border-gray-700">
              <h1 className="text-xl font-semibold text-white mb-2">{selectedEmail.subject}</h1>
              <div className="flex items-center gap-4 text-sm">
                <div className="text-gray-300">
                  <span className="text-gray-500">From:</span>{' '}
                  {selectedEmail.sender_name ? (
                    <>
                      {selectedEmail.sender_name} &lt;{selectedEmail.sender_email}&gt;
                    </>
                  ) : (
                    selectedEmail.sender_email
                  )}
                </div>
                <div className="text-gray-500">
                  {new Date(selectedEmail.received_at).toLocaleString()}
                </div>
              </div>
              {selectedEmail.to_recipients.length > 0 && (
                <div className="text-sm text-gray-500 mt-1">
                  <span>To:</span>{' '}
                  {selectedEmail.to_recipients.map((r) => r.name || r.email).join(', ')}
                </div>
              )}
            </div>

            {/* Refresh Attachments Button */}
            {selectedEmail.attachments.length === 0 && (
              <div className="px-4 py-2 border-b border-gray-700 bg-yellow-500/10">
                <button
                  onClick={() => refreshAttachments(selectedEmail.id)}
                  className="flex items-center gap-2 text-sm text-yellow-400 hover:text-yellow-300"
                >
                  <span className="material-icons text-sm">attachment</span>
                  Check for attachments
                  <span className="text-xs text-gray-500">(fetch from server)</span>
                </button>
              </div>
            )}

            {/* Sara's Analysis */}
            {selectedEmail.analyzed_at && (
              <div className="p-4 border-b border-gray-700">
                <div className="p-3 bg-gray-800 rounded-lg">
                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-teal-400 text-sm font-medium">Sara's Analysis</span>
                    {selectedEmail.category && (
                      <span className={`px-2 py-0.5 rounded text-xs border ${CATEGORY_COLORS[selectedEmail.category] || CATEGORY_COLORS.notification}`}>
                        {selectedEmail.category}
                      </span>
                    )}
                    {selectedEmail.importance_score !== null && (
                      <span className="text-xs text-gray-500">
                        Importance: {Math.round(selectedEmail.importance_score * 100)}%
                      </span>
                    )}
                  </div>
                  {selectedEmail.summary && (
                    <p className="text-sm text-gray-300">{selectedEmail.summary}</p>
                  )}
                </div>
              </div>
            )}

            {/* Attachments */}
            {selectedEmail.attachments.length > 0 && (
              <div className="p-4 border-b border-gray-700 bg-gray-800/50">
                <div className="text-sm text-gray-400 mb-2 flex items-center gap-2">
                  <span className="material-icons text-sm">attachment</span>
                  {selectedEmail.attachments.length} attachment{selectedEmail.attachments.length > 1 ? 's' : ''}
                </div>
                <div className="flex flex-wrap gap-2">
                  {selectedEmail.attachments.map((att) => (
                    <button
                      key={att.id}
                      onClick={() => downloadAttachment(selectedEmail.id, att.id, att.filename)}
                      className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${
                        att.is_riskninja_relevant
                          ? 'bg-green-500/20 text-green-400 hover:bg-green-500/30 border border-green-500/30'
                          : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                      }`}
                    >
                      <span className="material-icons text-sm">
                        {att.content_type?.startsWith('image/') ? 'image' : 'description'}
                      </span>
                      <span className="truncate max-w-[200px]">{att.filename}</span>
                      <span className="text-xs text-gray-500">{formatFileSize(att.size)}</span>
                      {att.is_riskninja_relevant && (
                        <span className="text-xs text-green-400">RiskNinja</span>
                      )}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Email Body */}
            <div className="flex-1 overflow-y-auto p-4">
              {selectedEmail.body_html ? (
                <div
                  className="prose prose-invert max-w-none"
                  dangerouslySetInnerHTML={{ __html: selectedEmail.body_html }}
                />
              ) : (
                <pre className="text-gray-300 whitespace-pre-wrap font-sans">
                  {selectedEmail.body_text || selectedEmail.body_preview}
                </pre>
              )}
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-gray-500">
            <div className="text-center">
              <span className="material-icons text-6xl mb-4 block">email</span>
              <p>Select an email to view</p>
            </div>
          </div>
        )}
      </div>

      {/* Right Panel - Sara Chat */}
      <div className="w-80 flex flex-col bg-gray-900">
        <div className="p-4 border-b border-gray-700">
          <h3 className="text-lg font-semibold text-white flex items-center gap-2">
            <span className="text-teal-400">Sara</span>
            <span className="text-gray-400 text-sm font-normal">Email Assistant</span>
          </h3>
          {selectedEmail && (
            <p className="text-xs text-gray-500 mt-1">
              Context: {selectedEmail.subject.substring(0, 40)}...
            </p>
          )}
        </div>

        {/* Chat Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {!selectedEmail ? (
            <div className="text-gray-500 text-sm text-center mt-8">
              Select an email to chat about it with Sara
            </div>
          ) : chatMessages.length === 0 ? (
            <div className="text-gray-500 text-sm">
              <p className="mb-4">Ask me about this email:</p>
              <div className="space-y-2">
                {['Summarize this email', 'Draft a reply', 'What action should I take?', 'Is this urgent?'].map(
                  (suggestion) => (
                    <button
                      key={suggestion}
                      onClick={() => {
                        setChatInput(suggestion);
                      }}
                      className="w-full text-left px-3 py-2 bg-gray-800 rounded-lg text-gray-300 hover:bg-gray-700 text-sm"
                    >
                      {suggestion}
                    </button>
                  )
                )}
              </div>
            </div>
          ) : (
            chatMessages.map((msg, idx) => (
              <div
                key={idx}
                className={`${
                  msg.role === 'user'
                    ? 'bg-teal-500/20 ml-8'
                    : 'bg-gray-800 mr-8'
                } rounded-lg p-3`}
              >
                <div className="text-xs text-gray-500 mb-1">
                  {msg.role === 'user' ? 'You' : 'Sara'}
                </div>
                <div className="text-sm text-gray-200 whitespace-pre-wrap">{msg.content}</div>
              </div>
            ))
          )}
          {chatLoading && (
            <div className="bg-gray-800 mr-8 rounded-lg p-3">
              <div className="text-xs text-gray-500 mb-1">Sara</div>
              <div className="text-sm text-gray-400">Thinking...</div>
            </div>
          )}
          <div ref={chatEndRef} />
        </div>

        {/* Chat Input */}
        {selectedEmail && (
          <div className="p-4 border-t border-gray-700">
            <div className="flex gap-2">
              <input
                type="text"
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyPress={(e) => e.key === 'Enter' && sendChatMessage()}
                placeholder="Ask about this email..."
                className="flex-1 bg-gray-800 border border-gray-600 rounded-lg px-4 py-2 text-white text-sm focus:outline-none focus:border-teal-500"
              />
              <button
                onClick={sendChatMessage}
                disabled={!chatInput.trim() || chatLoading}
                className="px-4 py-2 bg-teal-600 text-white rounded-lg hover:bg-teal-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <span className="material-icons text-sm">send</span>
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default EmailPage;
