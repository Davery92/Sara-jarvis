import React, { createContext, useContext, useState, useCallback, ReactNode } from 'react';
import { APP_CONFIG } from '../config';

interface DashboardData {
  morningBrief: any;
  weather: any;
  calendarEvents: any[];
  saraStatus: any;
  connectedDevices: any[];
  standingOrders: any[];
  journalEntries: any[];
  attentionCounts: { new: number; sent: number; read: number; archived: number; unread: number };
  attentionItems: any[];
  missions: any[];
  contentInboxStats: { unread: number; read: number; kept: number; total: number };
}

interface DashboardContextType extends DashboardData {
  loading: boolean;
  refreshDashboard: () => Promise<void>;
  setAttentionItems: (items: any[]) => void;
  setAttentionCounts: (counts: any) => void;
  setMissions: (missions: any[]) => void;
}

const defaultData: DashboardData = {
  morningBrief: null,
  weather: null,
  calendarEvents: [],
  saraStatus: null,
  connectedDevices: [],
  standingOrders: [],
  journalEntries: [],
  attentionCounts: { new: 0, sent: 0, read: 0, archived: 0, unread: 0 },
  attentionItems: [],
  missions: [],
  contentInboxStats: { unread: 0, read: 0, kept: 0, total: 0 },
};

const DashboardContext = createContext<DashboardContextType | null>(null);

export function DashboardProvider({ children }: { children: ReactNode }) {
  const [data, setData] = useState<DashboardData>(defaultData);
  const [loading, setLoading] = useState(false);

  const refreshDashboard = useCallback(async () => {
    setLoading(true);
    try {
      const fetchJson = async (path: string) => {
        const resp = await fetch(`${APP_CONFIG.apiUrl}${path}`, { credentials: 'include' });
        if (!resp.ok) throw new Error(`${resp.status}`);
        return resp.json();
      };
      const results = await Promise.allSettled([
        fetchJson('/api/sara/brief'),
        fetchJson('/api/calendar/upcoming'),
        fetchJson('/api/sara/status'),
        fetchJson('/api/autonomy/attention/counts'),
        fetchJson('/api/content-inbox/stats'),
      ]);

      const brief = results[0].status === 'fulfilled' ? results[0].value : null;
      const calendar = results[1].status === 'fulfilled' ? results[1].value : [];
      const status = results[2].status === 'fulfilled' ? results[2].value : null;
      const attention = results[3].status === 'fulfilled' ? results[3].value : defaultData.attentionCounts;
      const inbox = results[4].status === 'fulfilled' ? results[4].value : defaultData.contentInboxStats;

      setData(prev => ({
        ...prev,
        morningBrief: brief,
        calendarEvents: Array.isArray(calendar) ? calendar : calendar?.events || [],
        saraStatus: status,
        attentionCounts: attention,
        contentInboxStats: inbox,
        weather: brief?.weather || prev.weather,
      }));
    } catch (e) {
      console.error('Dashboard refresh failed:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  const setAttentionItems = useCallback((items: any[]) => {
    setData(prev => ({ ...prev, attentionItems: items }));
  }, []);

  const setAttentionCounts = useCallback((counts: any) => {
    setData(prev => ({ ...prev, attentionCounts: counts }));
  }, []);

  const setMissions = useCallback((missions: any[]) => {
    setData(prev => ({ ...prev, missions }));
  }, []);

  return (
    <DashboardContext.Provider value={{
      ...data, loading, refreshDashboard,
      setAttentionItems, setAttentionCounts, setMissions,
    }}>
      {children}
    </DashboardContext.Provider>
  );
}

export function useDashboard() {
  const ctx = useContext(DashboardContext);
  if (!ctx) throw new Error('useDashboard must be used within DashboardProvider');
  return ctx;
}
