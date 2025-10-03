/**
 * Daily Brief Component
 *
 * Displays the daily briefing with:
 * - Top priorities from reminders
 * - Calendar overview
 * - Carry-over tasks
 * - Dream highlights
 * - Suggested focus areas
 */

import React, { useState, useEffect } from 'react';
import { APP_CONFIG } from '../config';

interface BriefItem {
  id?: string;
  title: string;
  subtitle?: string;
  type: string;
  source_id?: number;
  action?: string;
}

interface BriefSection {
  id: string;
  title: string;
  items: BriefItem[];
}

interface DailyBriefData {
  id: number;
  brief_date: string;
  sections: BriefSection[];
  generated_at: string;
  generation_duration_ms: number;
  calendar_events_count: number;
  reminders_count: number;
  insights_count: number;
  dream_highlights_count: number;
  viewed_at: string | null;
  pinned_items: string[];
  total_items: number;
  is_today: boolean;
}

interface DailyBriefProps {
  date?: string; // YYYY-MM-DD format
  className?: string;
}

export const DailyBrief: React.FC<DailyBriefProps> = ({ date, className }) => {
  const [brief, setBrief] = useState<DailyBriefData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [regenerating, setRegenerating] = useState(false);

  const fetchBrief = async () => {
    try {
      setLoading(true);
      setError(null);

      const queryParam = date ? `?t=${date}` : '';
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/brief/daily${queryParam}`, {
        credentials: 'include',
      });

      if (response.ok) {
        const data = await response.json();
        setBrief(data);
      } else {
        setError('Failed to load daily brief');
      }
    } catch (err) {
      console.error('Error fetching daily brief:', err);
      setError('Failed to load daily brief');
    } finally {
      setLoading(false);
    }
  };

  const regenerateBrief = async () => {
    if (!brief) return;

    try {
      setRegenerating(true);
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/brief/daily/${brief.id}/regenerate`, {
        method: 'POST',
        credentials: 'include',
      });

      if (response.ok) {
        await fetchBrief();
      }
    } catch (err) {
      console.error('Error regenerating brief:', err);
    } finally {
      setRegenerating(false);
    }
  };

  const pinItem = async (itemId: string) => {
    if (!brief) return;

    try {
      await fetch(`${APP_CONFIG.apiUrl}/api/brief/daily/${brief.id}/pin`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ item_id: itemId }),
      });

      // Refresh brief to update pinned items
      await fetchBrief();
    } catch (err) {
      console.error('Error pinning item:', err);
    }
  };

  useEffect(() => {
    fetchBrief();
  }, [date]);

  const getItemIcon = (type: string) => {
    switch (type) {
      case 'reminder': return '✅';
      case 'calendar_event': return '📅';
      case 'insight': return '💡';
      case 'suggestion': return '💭';
      case 'carry_over': return '📌';
      case 'dream_highlight': return '✨';
      default: return '•';
    }
  };

  if (loading) {
    return (
      <div className={`daily-brief ${className || ''}`}>
        <div className="bg-card border border-card rounded-xl p-6">
          <div className="text-center py-8">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-teal-500 mx-auto mb-4"></div>
            <p className="text-gray-400">Loading daily brief...</p>
          </div>
        </div>
      </div>
    );
  }

  if (error || !brief) {
    return (
      <div className={`daily-brief ${className || ''}`}>
        <div className="bg-card border border-card rounded-xl p-6">
          <div className="text-center py-8">
            <p className="text-red-400">{error || 'Failed to load brief'}</p>
            <button
              onClick={fetchBrief}
              className="mt-4 px-4 py-2 bg-teal-600 text-white rounded hover:bg-teal-700"
            >
              Retry
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={`daily-brief ${className || ''}`}>
      <div className="bg-card border border-card rounded-xl">
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-gray-700">
          <div>
            <h2 className="text-xl font-semibold">🌅 Daily Brief</h2>
            <p className="text-sm text-gray-400 mt-1">
              {new Date(brief.brief_date).toLocaleDateString('en-US', {
                weekday: 'long',
                month: 'long',
                day: 'numeric'
              })}
            </p>
          </div>

          <div className="flex items-center space-x-4">
            <div className="text-sm text-gray-400">
              {brief.total_items} items
            </div>
            <button
              onClick={regenerateBrief}
              disabled={regenerating}
              className="px-4 py-2 bg-teal-600 text-white rounded hover:bg-teal-700 disabled:opacity-50 transition-colors"
            >
              {regenerating ? '🔄 Regenerating...' : '🔄 Refresh'}
            </button>
          </div>
        </div>

        {/* Stats Bar */}
        <div className="grid grid-cols-4 gap-4 p-4 bg-gray-800/30 border-b border-gray-700">
          <div className="text-center">
            <div className="text-2xl font-bold text-teal-400">{brief.calendar_events_count}</div>
            <div className="text-xs text-gray-500">Calendar Events</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-blue-400">{brief.reminders_count}</div>
            <div className="text-xs text-gray-500">Reminders</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-purple-400">{brief.insights_count}</div>
            <div className="text-xs text-gray-500">Insights</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-amber-400">{brief.dream_highlights_count}</div>
            <div className="text-xs text-gray-500">Dream Highlights</div>
          </div>
        </div>

        {/* Sections */}
        <div className="p-6 space-y-6">
          {brief.sections.length === 0 ? (
            <div className="text-center py-12">
              <div className="text-6xl mb-4">✨</div>
              <h3 className="text-lg font-medium text-gray-300 mb-2">All clear!</h3>
              <p className="text-gray-400">No items in today's brief.</p>
            </div>
          ) : (
            brief.sections.map((section) => (
              <div key={section.id} className="brief-section">
                <h3 className="text-lg font-semibold text-white mb-3 flex items-center">
                  {section.title}
                  <span className="ml-2 text-sm text-gray-500">
                    ({section.items.length})
                  </span>
                </h3>

                <div className="space-y-2">
                  {section.items.map((item, idx) => (
                    <div
                      key={item.id || idx}
                      className="flex items-start justify-between p-3 bg-gray-800/30 rounded-lg hover:bg-gray-800/50 transition-colors"
                    >
                      <div className="flex items-start space-x-3 flex-1">
                        <span className="text-xl">
                          {getItemIcon(item.type)}
                        </span>
                        <div className="flex-1">
                          <div className="font-medium text-white">{item.title}</div>
                          {item.subtitle && (
                            <div className="text-sm text-gray-400 mt-1">{item.subtitle}</div>
                          )}
                          {item.action && (
                            <div className="text-xs text-teal-400 mt-2">→ {item.action}</div>
                          )}
                        </div>
                      </div>

                      {item.id && !brief.pinned_items.includes(item.id) && (
                        <button
                          onClick={() => pinItem(item.id!)}
                          className="ml-4 p-2 text-gray-400 hover:text-teal-400 transition-colors"
                          title="Pin as reminder"
                        >
                          📌
                        </button>
                      )}

                      {item.id && brief.pinned_items.includes(item.id) && (
                        <span className="ml-4 p-2 text-teal-400" title="Pinned">
                          ✓
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-gray-700 text-center text-sm text-gray-500">
          Generated {new Date(brief.generated_at).toLocaleTimeString()}
          {brief.generation_duration_ms && ` • ${brief.generation_duration_ms}ms`}
          {brief.viewed_at && ` • Viewed ${new Date(brief.viewed_at).toLocaleTimeString()}`}
        </div>
      </div>
    </div>
  );
};

export default DailyBrief;
