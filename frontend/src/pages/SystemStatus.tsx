import { useState, useEffect } from 'react';
import { APP_CONFIG } from '../config';

interface MetricsData {
  health: {
    overall_status: string;
    checks?: Record<string, { status: string; message: string }>;
  };
  llm: {
    background?: {
      primary_degraded: boolean;
      consecutive_primary_failures: number;
      total_requests: number;
      total_failures: number;
      failover_events: number;
      primary_url: string;
      fallback_url: string;
    };
  };
  acs: {
    state: string;
    sessions_24h: number;
    errors_24h: number;
    error_rate_24h: number;
    avg_turns_24h: number;
    notes_24h: number;
  };
  queues: Record<string, number>;
  notifications: {
    sent_24h: number;
    engaged_24h: number;
    engagement_rate: number;
  };
  memory: {
    episodes_total: number;
    episodes_24h: number;
  };
  interest_graph: {
    active_nodes: number;
    edges: number;
  };
  timestamp: string;
}

const STATUS_COLORS: Record<string, string> = {
  healthy: 'bg-green-500/20 text-green-400 border-green-500/30',
  warning: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  error: 'bg-red-500/20 text-red-400 border-red-500/30',
  critical: 'bg-red-600/20 text-red-300 border-red-600/30',
  unknown: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium border ${STATUS_COLORS[status] || STATUS_COLORS.unknown}`}>
      {status}
    </span>
  );
}

function Card({ title, children, status }: { title: string; children: React.ReactNode; status?: string }) {
  const borderColor = status ? (STATUS_COLORS[status]?.split(' ')[2] || 'border-gray-700') : 'border-gray-700';
  return (
    <div className={`bg-gray-800/50 rounded-lg p-4 border ${borderColor}`}>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">{title}</h3>
        {status && <StatusBadge status={status} />}
      </div>
      {children}
    </div>
  );
}

function Metric({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div>
      <div className="text-2xl font-bold text-white">{value}</div>
      <div className="text-xs text-gray-400">{label}</div>
      {sub && <div className="text-xs text-gray-500">{sub}</div>}
    </div>
  );
}

export default function SystemStatus() {
  const [metrics, setMetrics] = useState<MetricsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());

  const fetchMetrics = async () => {
    try {
      const resp = await fetch(`${APP_CONFIG.apiUrl}/api/metrics`, { credentials: 'include' });
      const data = await resp.json();
      setMetrics(data);
      setLastRefresh(new Date());
    } catch (e) {
      console.error('Failed to fetch metrics:', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchMetrics();
    const interval = setInterval(fetchMetrics, 30000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400">
        Loading system metrics...
      </div>
    );
  }

  if (!metrics) {
    return (
      <div className="flex items-center justify-center h-64 text-red-400">
        Failed to load metrics
      </div>
    );
  }

  const bg = metrics.llm?.background;
  const totalQueueDepth = Object.values(metrics.queues || {}).reduce((a: number, b) => a + (typeof b === 'number' ? b : 0), 0);

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-white">System Status</h1>
        <div className="text-xs text-gray-500">
          Last refresh: {lastRefresh.toLocaleTimeString()}
          <button onClick={fetchMetrics} className="ml-2 text-teal-400 hover:text-teal-300">Refresh</button>
        </div>
      </div>

      {/* Overall Health */}
      <Card title="System Health" status={metrics.health?.overall_status}>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {metrics.health?.checks && Object.entries(metrics.health.checks).map(([name, check]) => (
            <div key={name} className="flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full ${check.status === 'healthy' ? 'bg-green-400' : check.status === 'warning' ? 'bg-yellow-400' : 'bg-red-400'}`} />
              <span className="text-sm text-gray-300">{name.replace(/_/g, ' ')}</span>
            </div>
          ))}
        </div>
      </Card>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {/* ACS */}
        <Card title="ACS (Autonomous Cognition)" status={metrics.acs?.error_rate_24h > 0.3 ? 'warning' : 'healthy'}>
          <div className="grid grid-cols-2 gap-3">
            <Metric label="State" value={metrics.acs?.state || 'unknown'} />
            <Metric label="Sessions (24h)" value={metrics.acs?.sessions_24h || 0} />
            <Metric label="Error Rate" value={`${((metrics.acs?.error_rate_24h || 0) * 100).toFixed(0)}%`} />
            <Metric label="Notes (24h)" value={metrics.acs?.notes_24h || 0} />
            <Metric label="Avg Turns" value={metrics.acs?.avg_turns_24h || 0} />
            <Metric label="Errors (24h)" value={metrics.acs?.errors_24h || 0} />
          </div>
        </Card>

        {/* LLM */}
        <Card title="LLM Backend" status={bg?.primary_degraded ? 'warning' : 'healthy'}>
          <div className="grid grid-cols-2 gap-3">
            <Metric label="Primary Status" value={bg?.primary_degraded ? 'DEGRADED' : 'OK'} />
            <Metric label="Failover Events" value={bg?.failover_events || 0} />
            <Metric label="Total Requests" value={bg?.total_requests || 0} />
            <Metric label="Total Failures" value={bg?.total_failures || 0} />
            <Metric label="Consec. Failures" value={bg?.consecutive_primary_failures || 0} />
          </div>
        </Card>

        {/* Queues */}
        <Card title="Task Queues" status={totalQueueDepth > 50 ? 'warning' : 'healthy'}>
          <div className="space-y-1.5">
            {metrics.queues && typeof metrics.queues === 'object' && !('error' in metrics.queues) &&
              Object.entries(metrics.queues).map(([q, depth]) => (
                <div key={q} className="flex items-center justify-between text-sm">
                  <span className="text-gray-400">{q}</span>
                  <span className={`font-mono ${(depth as number) > 10 ? 'text-yellow-400' : 'text-gray-300'}`}>{depth as number}</span>
                </div>
              ))
            }
            <div className="border-t border-gray-700 pt-1 flex justify-between text-sm font-medium">
              <span className="text-gray-300">Total</span>
              <span className="text-white">{totalQueueDepth}</span>
            </div>
          </div>
        </Card>

        {/* Notifications */}
        <Card title="Notifications (24h)">
          <div className="grid grid-cols-3 gap-3">
            <Metric label="Sent" value={metrics.notifications?.sent_24h || 0} />
            <Metric label="Engaged" value={metrics.notifications?.engaged_24h || 0} />
            <Metric label="Rate" value={`${((metrics.notifications?.engagement_rate || 0) * 100).toFixed(0)}%`} />
          </div>
        </Card>

        {/* Memory */}
        <Card title="Memory">
          <div className="grid grid-cols-2 gap-3">
            <Metric label="Total Episodes" value={(metrics.memory?.episodes_total || 0).toLocaleString()} />
            <Metric label="New (24h)" value={metrics.memory?.episodes_24h || 0} />
          </div>
        </Card>

        {/* Interest Graph */}
        <Card title="Interest Graph">
          <div className="grid grid-cols-2 gap-3">
            <Metric label="Active Nodes" value={metrics.interest_graph?.active_nodes || 0} />
            <Metric label="Edges" value={metrics.interest_graph?.edges || 0} />
          </div>
        </Card>
      </div>
    </div>
  );
}
