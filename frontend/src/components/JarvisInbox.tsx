/**
 * Jarvis Inbox Component - Unified notification system
 * 
 * This component displays all proactive notifications from monitors,
 * background tasks, and system insights.
 */

import React, { useState, useEffect } from 'react';
import { APP_CONFIG } from '../config';

interface InboxItem {
  id: string;
  kind: 'insight' | 'alert' | 'reminder' | 'suggestion';
  title: string;
  body?: string;
  source?: string;
  priority: number;
  status: 'new' | 'read' | 'archived';
  created_at: string;
  payload?: any;
}

interface JarvisInboxProps {
  className?: string;
}

export const JarvisInbox: React.FC<JarvisInboxProps> = ({ className }) => {
  const [items, setItems] = useState<InboxItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<'all' | 'new' | 'read' | 'archived'>('all');
  const [unreadCount, setUnreadCount] = useState(0);

  // Fetch inbox items
  const fetchInboxItems = async () => {
    try {
      setLoading(true);
      const status = filter === 'all' ? '' : `?status=${filter}`;
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/inbox${status}`, {
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
      });

      if (response.ok) {
        const data = await response.json();
        setItems(data.items || []);
        setUnreadCount(data.unread_count || 0);
      } else {
        console.error('Failed to fetch inbox items');
        // Show sample data for development
        setItems([
          {
            id: '1',
            kind: 'insight',
            title: 'Daily Brief Ready',
            body: 'Your morning briefing has been generated with 3 priority items.',
            source: 'daily_brief',
            priority: 7,
            status: 'new',
            created_at: new Date().toISOString(),
          }
        ]);
        setUnreadCount(1);
      }
    } catch (error) {
      console.error('Error fetching inbox:', error);
      // Show sample data for development
      setItems([
        {
          id: '1',
          kind: 'suggestion',
          title: 'Welcome to Jarvis Mode',
          body: 'Your proactive AI assistant is now active. Expect intelligent insights and suggestions throughout the day.',
          source: 'system',
          priority: 8,
          status: 'new',
          created_at: new Date().toISOString(),
        }
      ]);
      setUnreadCount(1);
    } finally {
      setLoading(false);
    }
  };

  // Mark item as read
  const markAsRead = async (itemId: string) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/inbox/${itemId}/read`, {
        method: 'POST',
        credentials: 'include',
      });
      
      if (response.ok) {
        setItems(prev => prev.map(item => 
          item.id === itemId ? { ...item, status: 'read' as const } : item
        ));
        setUnreadCount(prev => Math.max(0, prev - 1));
      }
    } catch (error) {
      console.error('Error marking item as read:', error);
    }
  };

  // Archive item
  const archiveItem = async (itemId: string) => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/inbox/${itemId}/archive`, {
        method: 'POST',
        credentials: 'include',
      });
      
      if (response.ok) {
        setItems(prev => prev.map(item => 
          item.id === itemId ? { ...item, status: 'archived' as const } : item
        ));
      }
    } catch (error) {
      console.error('Error archiving item:', error);
    }
  };

  // Mark all as read
  const markAllAsRead = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/inbox/mark-all-read`, {
        method: 'POST',
        credentials: 'include',
      });
      
      if (response.ok) {
        setItems(prev => prev.map(item => ({ ...item, status: 'read' as const })));
        setUnreadCount(0);
      }
    } catch (error) {
      console.error('Error marking all as read:', error);
    }
  };

  useEffect(() => {
    fetchInboxItems();
  }, [filter]);

  const getKindIcon = (kind: string) => {
    switch (kind) {
      case 'insight': return '💡';
      case 'alert': return '🚨';
      case 'reminder': return '📅';
      case 'suggestion': return '💭';
      default: return '📥';
    }
  };

  const getKindColor = (kind: string) => {
    switch (kind) {
      case 'insight': return 'text-blue-400';
      case 'alert': return 'text-red-400';
      case 'reminder': return 'text-yellow-400';
      case 'suggestion': return 'text-green-400';
      default: return 'text-gray-400';
    }
  };

  return (
    <div className={`jarvis-inbox ${className || ''}`}>
      <div className="bg-card border border-card rounded-xl">
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-gray-700">
          <div className="flex items-center space-x-3">
            <h2 className="text-xl font-semibold">📥 Jarvis Inbox</h2>
            {unreadCount > 0 && (
              <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-teal-500/20 text-teal-400">
                {unreadCount} new
              </span>
            )}
          </div>
          
          <div className="flex items-center space-x-2">
            {unreadCount > 0 && (
              <button
                onClick={markAllAsRead}
                className="px-3 py-1 text-sm bg-teal-600 text-white rounded hover:bg-teal-700 transition-colors"
              >
                Mark All Read
              </button>
            )}
            <button
              onClick={fetchInboxItems}
              className="p-2 text-gray-400 hover:text-white"
              title="Refresh"
            >
              🔄
            </button>
          </div>
        </div>

        {/* Filters */}
        <div className="flex space-x-1 p-4 border-b border-gray-700">
          {['all', 'new', 'read', 'archived'].map((status) => (
            <button
              key={status}
              onClick={() => setFilter(status as any)}
              className={`px-3 py-1.5 text-sm rounded transition-colors ${
                filter === status
                  ? 'bg-teal-600 text-white'
                  : 'text-gray-400 hover:text-white hover:bg-gray-700'
              }`}
            >
              {status.charAt(0).toUpperCase() + status.slice(1)}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="p-6">
          {loading ? (
            <div className="text-center py-8">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-teal-500 mx-auto mb-4"></div>
              <p className="text-gray-400">Loading inbox items...</p>
            </div>
          ) : items.length === 0 ? (
            <div className="text-center py-12">
              <div className="text-6xl mb-4">📪</div>
              <h3 className="text-lg font-medium text-gray-300 mb-2">All caught up!</h3>
              <p className="text-gray-400">No {filter === 'all' ? '' : filter + ' '}items in your inbox.</p>
            </div>
          ) : (
            <div className="space-y-4">
              {items.map((item) => (
                <div
                  key={item.id}
                  className={`p-4 border rounded-lg transition-all ${
                    item.status === 'new'
                      ? 'border-teal-500/30 bg-teal-500/5'
                      : 'border-gray-700 bg-gray-800/30'
                  }`}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex items-start space-x-3 flex-1">
                      <span className={`text-2xl ${getKindColor(item.kind)}`}>
                        {getKindIcon(item.kind)}
                      </span>
                      
                      <div className="flex-1">
                        <div className="flex items-center space-x-2 mb-1">
                          <h3 className="font-medium text-white">{item.title}</h3>
                          {item.status === 'new' && (
                            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-teal-500/20 text-teal-400">
                              New
                            </span>
                          )}
                        </div>
                        
                        {item.body && (
                          <p className="text-gray-300 text-sm mb-2">{item.body}</p>
                        )}
                        
                        <div className="flex items-center space-x-4 text-xs text-gray-500">
                          <span>Priority: {item.priority}</span>
                          {item.source && <span>Source: {item.source}</span>}
                          <span>{new Date(item.created_at).toLocaleString()}</span>
                        </div>
                      </div>
                    </div>

                    {/* Actions */}
                    <div className="flex items-center space-x-2 ml-4">
                      {item.status === 'new' && (
                        <button
                          onClick={() => markAsRead(item.id)}
                          className="p-2 text-gray-400 hover:text-teal-400 transition-colors"
                          title="Mark as read"
                        >
                          ✓
                        </button>
                      )}
                      <button
                        onClick={() => archiveItem(item.id)}
                        className="p-2 text-gray-400 hover:text-yellow-400 transition-colors"
                        title="Archive"
                      >
                        📁
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default JarvisInbox;