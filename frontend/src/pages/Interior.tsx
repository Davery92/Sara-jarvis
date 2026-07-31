import { lazy, Suspense, useEffect, useState, type ComponentType } from 'react';
import { APP_CONFIG } from '../config';

// item 2.3 (2026-07-31, ruling 4): embedded in place of a standalone route,
// one view at a time — lazy so an unexpanded dashboard costs nothing.
const SystemStatus = lazy(() => import('./SystemStatus'));
const MindDashboard = lazy(() => import('../components/mind/MindDashboard'));
const SystemDashboard = lazy(() => import('../components/system/SystemDashboard'));
const SensoryMonitor = lazy(() => import('../components/SensoryMonitor'));

// ── Types (mirror backend/app/schemas/contracts.py + the diagnostics
// endpoints in backend/app/routes/diagnostics.py — SINGULAR_SARA_MASTER_
// PLAN §13/U1 "shared projection client," kept local to this file for now
// rather than a shared package since Interior is currently its only
// consumer). ──

interface SelfState {
  kernel_state: string;
  wake_reason: string | null;
  focus: string | null;
  open_concerns: string[];
  confidence: number;
}

interface WorldState {
  summary: string | null;
  active_calendar_events: number;
  open_threads: number;
  confidence: number;
}

interface RelationshipState {
  active_conversation_id: string | null;
  recent_promises: string[];
  confidence: number;
}

interface ContextSnapshot {
  self_state: SelfState;
  world_state: WorldState;
  relationship_state: RelationshipState;
}

interface BodyComponent {
  name: string;
  label: string | null;
  status: 'ok' | 'degraded' | 'unknown';
  impact: string | null;
  severity: string | null;
  source: string;
  confidence: number;
}

interface BodyState {
  healthy: boolean;
  components: BodyComponent[];
  degraded_count: number;
  confidence: number;
  as_of: string;
}

interface Intent {
  intent_id: string;
  kind: string;
  origin: string;
  status: string;
  next_step: string | null;
  priority: string | null;
}

interface IntentGraph {
  total: number;
  by_source: Record<string, number>;
  intents: Intent[];
}

interface TruthViolation {
  rule: string;
  severity: string;
  description: string;
}

interface TruthAudit {
  violation_count: number;
  violations: TruthViolation[];
}

interface AttentionLogItem {
  outbound_intent_id: string;
  subject: string;
  why_now: string | null;
  created_at: string;
  decision: string;
  rendered_text: string | null;
  delivered_at: string | null;
}

interface ActionReceipt {
  action_id: string;
  action_type: string;
  target: string | null;
  permission_tier: string;
  status: string;
  executed_at: string | null;
  ledger_id: number | null;
  undo_expires_at: string | null;
  undone: boolean;
}

interface EventEnvelope {
  event_id: string;
  kind: string;
  source: string;
  occurred_at: string;
  confidence: number | null;
}

interface BodyCapability {
  name: string;
  kind: string;
  version: string | null;
  alive: boolean;
  last_seen_at: string | null;
}

interface FeatureFlags {
  flags: Record<string, boolean>;
}

interface SchedulerDietJob {
  key: string;
  display_name: string;
  category: string;
  enabled: boolean;
  singular_class: string | null;
}

interface Interest {
  id: string;
  topic: string;
  display_name: string;
  why: string | null;
  weight: number;
  blocked: boolean;
  last_acted_at: string | null;
}

// §8 singularity metrics — presence latency, calibration (from /api/mind/self,
// already built and live) and self-story/kill-rate/batch-flush (new, work-
// order item 5, 2026-07-30 — these had no surface until now).
interface PresenceLatency {
  p50: number | null;
  p90: number | null;
  red_line: boolean;
  last_breach: string | null;
}

interface CalibrationByDomain {
  [domain: string]: { hit_rate: number; n: number };
}

interface SelfModel {
  calibration?: { by_domain?: CalibrationByDomain; error?: string };
  presence_latency?: PresenceLatency | null;
}

interface KillRate {
  total: number;
  killed: number;
  rate: number | null;
  meta_commentary_share: number | null;
}

interface BatchFlush {
  pending: number;
  last_flushed_at: string | null;
}

interface InteriorMetrics {
  self_story: string | null;
  kill_rate: KillRate;
  batch_flush: BatchFlush;
}

async function getJson<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${APP_CONFIG.apiUrl}${path}`, { credentials: 'include' });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

async function postJson<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${APP_CONFIG.apiUrl}${path}`, { method: 'POST', credentials: 'include' });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

function Section({ title, subtitle, children, className = '' }: { title: string; subtitle?: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-gray-800/50 rounded-lg p-4 border border-gray-700 ${className}`}>
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wide">{title}</h3>
        {subtitle && <p className="text-xs text-gray-500 mt-0.5">{subtitle}</p>}
      </div>
      {children}
    </div>
  );
}

function Empty({ label }: { label: string }) {
  return <div className="text-sm text-gray-500 italic">{label}</div>;
}

function StatusDot({ ok }: { ok: boolean }) {
  return <div className={`w-2 h-2 rounded-full flex-shrink-0 ${ok ? 'bg-green-400' : 'bg-red-400'}`} />;
}

function relTime(iso: string | null): string {
  if (!iso) return '—';
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 0) return 'just now';
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

// item 2.3 (2026-07-30, extended 2026-07-31 ruling 4): the 5 legacy
// standalone dashboards below read as pure engineering/diagnostics views —
// the same nature as Interior itself — so they're demoted out of the
// primary nav registry, same "Advanced" disclosure pattern as the
// migration-status section below. Machines and ACS stayed in the main nav
// (David's call): real features he reaches directly, not internals sprawl.
//
// Ruling 4: one at a time, each one's `embedded: true` means its button
// expands the real component inline (via EMBEDDED_LEGACY_COMPONENTS)
// instead of navigating away — the standalone route gets deleted the same
// pass its embed is verified. The rest still navigate away until their
// turn.
const LEGACY_OPS_VIEWS: Array<{ view: 'system' | 'mind' | 'system-status' | 'sensory-monitor' | 'orchestrator-lab'; label: string; embedded?: boolean }> = [
  { view: 'system', label: 'System', embedded: true },
  { view: 'mind', label: 'Mind', embedded: true },
  { view: 'system-status', label: 'System Status', embedded: true },
  { view: 'sensory-monitor', label: 'Sensory Monitor', embedded: true },
  { view: 'orchestrator-lab', label: 'Orchestrator Lab' },
];

const EMBEDDED_LEGACY_COMPONENTS: Partial<Record<(typeof LEGACY_OPS_VIEWS)[number]['view'], ComponentType>> = {
  'system-status': SystemStatus,
  mind: MindDashboard,
  system: SystemDashboard,
  'sensory-monitor': SensoryMonitor,
};

interface InteriorProps {
  onNavigate?: (view: string) => void;
}

export default function Interior({ onNavigate }: InteriorProps) {
  const [context, setContext] = useState<ContextSnapshot | null>(null);
  const [bodyState, setBodyState] = useState<BodyState | null>(null);
  const [intentGraph, setIntentGraph] = useState<IntentGraph | null>(null);
  const [truthAudit, setTruthAudit] = useState<TruthAudit | null>(null);
  const [attentionLog, setAttentionLog] = useState<AttentionLogItem[]>([]);
  const [actionReceipts, setActionReceipts] = useState<ActionReceipt[]>([]);
  const [recentEvents, setRecentEvents] = useState<EventEnvelope[]>([]);
  const [bodyCapabilities, setBodyCapabilities] = useState<BodyCapability[]>([]);
  const [featureFlags, setFeatureFlags] = useState<FeatureFlags | null>(null);
  const [schedulerJobs, setSchedulerJobs] = useState<SchedulerDietJob[]>([]);
  const [interests, setInterests] = useState<Interest[]>([]);
  const [interestBusy, setInterestBusy] = useState<string | null>(null);
  const [selfModel, setSelfModel] = useState<SelfModel | null>(null);
  const [interiorMetrics, setInteriorMetrics] = useState<InteriorMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [expandedLegacyView, setExpandedLegacyView] = useState<string | null>(null);

  const fetchAll = async () => {
    const [ctx, body, intents, audit, attention, actions, events, capabilities, flags, scheduler, interestRows, self, metrics] = await Promise.all([
      getJson<ContextSnapshot>('/api/diagnostics/context-snapshot'),
      getJson<BodyState>('/api/diagnostics/body-state'),
      getJson<IntentGraph>('/api/diagnostics/intent-graph'),
      getJson<TruthAudit>('/api/diagnostics/truth-audit'),
      getJson<{ items: AttentionLogItem[] }>('/api/diagnostics/attention-log?limit=8'),
      getJson<{ receipts: ActionReceipt[] }>('/api/diagnostics/action-receipts?limit=8'),
      getJson<{ events: EventEnvelope[] }>('/api/diagnostics/recent-events?limit=10'),
      getJson<{ bodies: BodyCapability[] }>('/api/diagnostics/body-capabilities'),
      getJson<FeatureFlags>('/api/diagnostics/feature-flags'),
      getJson<{ jobs: SchedulerDietJob[] }>('/api/diagnostics/scheduler-diet'),
      getJson<Interest[]>('/api/acs/v2/interests?include_blocked=true&limit=20'),
      getJson<SelfModel>('/api/mind/self'),
      getJson<InteriorMetrics>('/api/diagnostics/interior-metrics'),
    ]);
    setContext(ctx);
    setBodyState(body);
    setIntentGraph(intents);
    setTruthAudit(audit);
    setAttentionLog(attention?.items || []);
    setActionReceipts(actions?.receipts || []);
    setRecentEvents(events?.events || []);
    setBodyCapabilities(capabilities?.bodies || []);
    setFeatureFlags(flags);
    setSchedulerJobs(scheduler?.jobs || []);
    setInterests(interestRows || []);
    setSelfModel(self);
    setInteriorMetrics(metrics);
    setLastRefresh(new Date());
    setLoading(false);
  };

  const [undoingLedgerId, setUndoingLedgerId] = useState<number | null>(null);

  // item 5.10: same endpoint SystemDashboard's Undo already uses — Interior
  // is David's actual home surface, so the ledger's Undo belongs here too,
  // not only on the demoted System Dashboard.
  const undoAction = async (ledgerId: number) => {
    setUndoingLedgerId(ledgerId);
    try {
      await fetch(`${APP_CONFIG.apiUrl}/api/system/actions/undo`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ ledger_id: ledgerId }),
      });
      await fetchAll();
    } finally {
      setUndoingLedgerId(null);
    }
  };

  const toggleInterestBlock = async (interest: Interest) => {
    setInterestBusy(interest.id);
    const next = !interest.blocked;
    const updated = await postJson<Interest>(`/api/acs/v2/interests/${interest.id}/block?blocked=${next}`);
    if (updated) {
      setInterests((prev) => prev.map((i) => (i.id === interest.id ? updated : i)));
    }
    setInterestBusy(null);
  };

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 30000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return <div className="flex items-center justify-center h-64 text-gray-400">Loading Interior…</div>;
  }

  const self = context?.self_state;
  const world = context?.world_state;
  const degraded = bodyState?.components.filter((c) => c.status === 'degraded') || [];
  const openIntents = intentGraph?.intents.slice(0, 8) || [];
  const flagEntries = Object.entries(featureFlags?.flags || {});
  const schedulerByClass = schedulerJobs.reduce<Record<string, number>>((acc, job) => {
    const cls = job.singular_class || 'unclassified';
    acc[cls] = (acc[cls] || 0) + 1;
    return acc;
  }, {});

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Interior</h1>
          <p className="text-xs text-gray-500 mt-1">
            What Sara knows, wants, is doing, and needs — one truthful surface (SINGULAR_SARA_MASTER_PLAN §U7)
          </p>
        </div>
        <div className="text-xs text-gray-500">
          Last refresh: {lastRefresh.toLocaleTimeString()}
          <button onClick={fetchAll} className="ml-2 text-teal-400 hover:text-teal-300">Refresh</button>
        </div>
      </div>

      {/* Current state */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Section title="Kernel state">
          <div className="text-2xl font-bold text-white capitalize">{self?.kernel_state || 'unknown'}</div>
          <div className="text-xs text-gray-400 mt-1">
            {self?.wake_reason ? `woke: ${self.wake_reason.replace(/_/g, ' ')}` : 'resting'}
          </div>
          {self && self.open_concerns.length > 0 && (
            <div className="mt-3 space-y-1">
              {self.open_concerns.map((c, i) => (
                <div key={i} className="text-xs text-yellow-400 flex items-start gap-1.5">
                  <span>⚠</span><span>{c}</span>
                </div>
              ))}
            </div>
          )}
        </Section>

        <Section title="World">
          <div className="text-sm text-gray-200">{world?.summary || '—'}</div>
          <div className="grid grid-cols-2 gap-3 mt-3">
            <div>
              <div className="text-xl font-bold text-white">{world?.active_calendar_events ?? '—'}</div>
              <div className="text-xs text-gray-400">calendar today</div>
            </div>
            <div>
              <div className="text-xl font-bold text-white">{world?.open_threads ?? '—'}</div>
              <div className="text-xs text-gray-400">open threads</div>
            </div>
          </div>
        </Section>

        <Section title="Body">
          <div className="flex items-center gap-2">
            <StatusDot ok={!!bodyState?.healthy} />
            <span className="text-lg font-semibold text-white">{bodyState?.healthy ? 'Healthy' : 'Degraded'}</span>
          </div>
          {degraded.length > 0 ? (
            <div className="mt-3 space-y-1.5">
              {degraded.map((c) => (
                <div key={c.name} className="text-xs text-red-300">
                  <span className="font-medium">{c.label || c.name}</span>
                  {c.impact && <span className="text-gray-400"> — {c.impact}</span>}
                </div>
              ))}
            </div>
          ) : (
            <Empty label="Nothing degraded" />
          )}
        </Section>
      </div>

      {/* §8 singularity metrics — presence latency, calibration, self-story,
          kill-rate, batch-flush health. Nearly all of this shipped this
          week with no surface until now (work-order item 5, 2026-07-30). */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Section title="Presence latency" subtitle="first-token time, engaged state — budget is <2s">
          {!selfModel?.presence_latency ? <Empty label="No samples yet" /> : (
            <div>
              <div className="flex items-center gap-2">
                <StatusDot ok={!selfModel.presence_latency.red_line} />
                <span className={`text-2xl font-bold ${selfModel.presence_latency.red_line ? 'text-red-400' : 'text-white'}`}>
                  {selfModel.presence_latency.p50 != null ? `${selfModel.presence_latency.p50.toFixed(1)}s` : '—'}
                </span>
                <span className="text-xs text-gray-500">p50</span>
              </div>
              <div className="text-xs text-gray-400 mt-1">
                p90: {selfModel.presence_latency.p90 != null ? `${selfModel.presence_latency.p90.toFixed(1)}s` : '—'}
                {selfModel.presence_latency.red_line && (
                  <span className="text-red-400 ml-2">⚠ over budget</span>
                )}
              </div>
            </div>
          )}
        </Section>

        <Section title="Calibration" subtitle="per-domain hit rate at stated confidence, 30 days">
          {!selfModel?.calibration?.by_domain || Object.keys(selfModel.calibration.by_domain).length === 0 ? (
            <Empty label={selfModel?.calibration?.error ? 'Unavailable' : 'No resolved predictions yet'} />
          ) : (
            <div className="space-y-1.5">
              {Object.entries(selfModel.calibration.by_domain).map(([domain, stats]) => (
                <div key={domain} className="flex items-center justify-between text-xs">
                  <span className="text-gray-400 capitalize">{domain}</span>
                  <span className={stats.hit_rate < 0.35 ? 'text-yellow-400' : 'text-gray-200'}>
                    {(stats.hit_rate * 100).toFixed(0)}% ({stats.n})
                  </span>
                </div>
              ))}
            </div>
          )}
        </Section>

        <Section title="Utterance kill rate" subtitle="review_verdict='kill' / total composed, all-time">
          {!interiorMetrics?.kill_rate || interiorMetrics.kill_rate.total === 0 ? (
            <Empty label="No composed utterances yet" />
          ) : (
            <div>
              <div className="text-2xl font-bold text-white">
                {((interiorMetrics.kill_rate.rate ?? 0) * 100).toFixed(0)}%
              </div>
              <div className="text-xs text-gray-400 mt-1">
                {interiorMetrics.kill_rate.killed} killed / {interiorMetrics.kill_rate.total} total — watch the trend, not the number (review is supposed to kill often)
              </div>
            </div>
          )}
        </Section>

        <Section title="Batch flush" subtitle="judged_batch → judged_send promotion health">
          <div className="flex items-center gap-4">
            <div>
              <div className="text-2xl font-bold text-white">{interiorMetrics?.batch_flush.pending ?? '—'}</div>
              <div className="text-xs text-gray-400">pending</div>
            </div>
            <div className="text-xs text-gray-400">
              last flush: {relTime(interiorMetrics?.batch_flush.last_flushed_at ?? null)}
            </div>
          </div>
        </Section>
      </div>

      {/* Self-story — the rolling consolidated narrative dreaming writes,
          "yesterday's self constrains today's" (Arc 4.2). */}
      <Section title="Self-story" subtitle="the rolling narrative every context reads from">
        {!interiorMetrics?.self_story ? <Empty label="No self-story chapter yet" /> : (
          <p className="text-sm text-gray-300 leading-relaxed whitespace-pre-wrap">{interiorMetrics.self_story}</p>
        )}
      </Section>

      {/* Intents + contradictions */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Section title="Active intents" subtitle={`${intentGraph?.total ?? 0} open across every source`}>
          {openIntents.length === 0 ? <Empty label="Nothing open" /> : (
            <div className="space-y-2">
              {openIntents.map((i) => (
                <div key={i.intent_id} className="flex items-center justify-between text-sm">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className={`text-xs px-1.5 py-0.5 rounded ${i.origin === 'sara' ? 'bg-purple-500/20 text-purple-300' : 'bg-blue-500/20 text-blue-300'}`}>
                      {i.origin}
                    </span>
                    <span className="text-gray-200 truncate">{i.next_step || i.kind}</span>
                  </div>
                  <span className="text-xs text-gray-500 flex-shrink-0 ml-2">{i.status}</span>
                </div>
              ))}
            </div>
          )}
        </Section>

        <Section title="Contradictions" subtitle="impossible state combinations, scanned live">
          {!truthAudit || truthAudit.violation_count === 0 ? (
            <Empty label="None found" />
          ) : (
            <div className="space-y-2 max-h-80 overflow-y-auto pr-1">
              {truthAudit.violations.slice(0, 10).map((v, i) => (
                <div key={i} className="text-xs">
                  <span className={`px-1.5 py-0.5 rounded mr-2 ${v.severity === 'critical' ? 'bg-red-500/20 text-red-300' : 'bg-yellow-500/20 text-yellow-300'}`}>
                    {v.severity}
                  </span>
                  <span className="text-gray-300">{v.description}</span>
                </div>
              ))}
              {truthAudit.violation_count > 10 && (
                <div className="text-xs text-gray-500 pt-1">
                  +{truthAudit.violation_count - 10} more — {truthAudit.violation_count} total
                </div>
              )}
            </div>
          )}
        </Section>
      </div>

      {/* Sara's interests — first-class, actionable (§4.3: "not downgraded
          into notifications or hidden cron tasks"). Approve = keep active;
          reject = block (a permanent veto, not a delete — reflection can't
          silently resurrect a blocked topic). */}
      <Section title="Sara's interests" subtitle="what she's curious about, on her own initiative">
        {interests.length === 0 ? <Empty label="No interests yet" /> : (
          <div className="space-y-2">
            {interests.map((interest) => (
              <div key={interest.id} className="flex items-center justify-between text-sm gap-3">
                <div className="min-w-0">
                  <div className={`truncate ${interest.blocked ? 'text-gray-500 line-through' : 'text-gray-200'}`}>
                    {interest.display_name}
                  </div>
                  {interest.why && !interest.blocked && (
                    <div className="text-xs text-gray-500 truncate">{interest.why}</div>
                  )}
                </div>
                <button
                  onClick={() => toggleInterestBlock(interest)}
                  disabled={interestBusy === interest.id}
                  className={`text-xs px-2 py-1 rounded flex-shrink-0 transition-colors ${
                    interest.blocked
                      ? 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                      : 'bg-red-500/10 text-red-300 hover:bg-red-500/20'
                  } disabled:opacity-50`}
                >
                  {interestBusy === interest.id ? '…' : interest.blocked ? 'Restore' : 'Block'}
                </button>
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* Attention + actions */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Section title="Recent attention decisions" subtitle="what send_notification() actually decided">
          {attentionLog.length === 0 ? <Empty label="No decisions recorded yet" /> : (
            <div className="space-y-2">
              {attentionLog.map((a) => (
                <div key={a.outbound_intent_id} className="text-sm">
                  <div className="flex items-center justify-between">
                    <span className="text-gray-200 truncate">{a.subject}</span>
                    <span className="text-xs text-gray-500 ml-2 flex-shrink-0">{relTime(a.created_at)}</span>
                  </div>
                  <span className="text-xs text-gray-500">{a.decision.replace(/_/g, ' ')}</span>
                </div>
              ))}
            </div>
          )}
        </Section>

        <Section title="Recent actions" subtitle="permission tier + true status, never a bare flag">
          {actionReceipts.length === 0 ? <Empty label="No actions recorded yet" /> : (
            <div className="space-y-2">
              {actionReceipts.map((a) => {
                const canUndo =
                  a.ledger_id != null &&
                  !a.undone &&
                  a.status === 'completed' &&
                  !!a.undo_expires_at &&
                  new Date(a.undo_expires_at).getTime() > Date.now();
                return (
                  <div key={a.action_id} className="flex items-center justify-between text-sm">
                    <span className="text-gray-200">{a.action_type.replace(/_/g, ' ')}</span>
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-gray-500">{a.permission_tier.replace(/_/g, ' ')}</span>
                      <span className={`text-xs px-1.5 py-0.5 rounded ${a.status === 'completed' ? 'bg-green-500/20 text-green-300' : a.status === 'failed' ? 'bg-red-500/20 text-red-300' : 'bg-gray-500/20 text-gray-300'}`}>
                        {a.status}
                      </span>
                      {a.undone ? (
                        <span className="text-xs text-gray-500 italic">undone</span>
                      ) : canUndo ? (
                        <button
                          onClick={() => undoAction(a.ledger_id as number)}
                          disabled={undoingLedgerId === a.ledger_id}
                          className="text-xs px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300 hover:bg-amber-500/30 disabled:opacity-50"
                        >
                          {undoingLedgerId === a.ledger_id ? 'Undoing…' : 'Undo'}
                        </button>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </Section>
      </div>

      {/* Bodies (VM workshop, etc.) */}
      <Section title="Bodies" subtitle="VM workshop, tool runners, managed hosts">
        {bodyCapabilities.length === 0 ? <Empty label="No bodies have reported in yet" /> : (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {bodyCapabilities.map((b) => (
              <div key={b.name} className="flex items-center gap-2">
                <StatusDot ok={b.alive} />
                <div>
                  <div className="text-sm text-gray-200">{b.name}</div>
                  <div className="text-xs text-gray-500">{b.kind} · {b.version || 'unknown version'}</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* Recent events (compact) */}
      <Section title="Recent events" subtitle="every event on the bus, canonicalized">
        {recentEvents.length === 0 ? <Empty label="No events recorded yet" /> : (
          <div className="flex flex-wrap gap-2">
            {recentEvents.map((e) => (
              <span key={e.event_id} className="text-xs bg-gray-700/50 text-gray-300 px-2 py-1 rounded" title={e.occurred_at}>
                {e.kind}
              </span>
            ))}
          </div>
        )}
      </Section>

      {/* Advanced: migration status */}
      <div>
        <button
          onClick={() => setShowAdvanced((v) => !v)}
          className="text-xs text-gray-500 hover:text-gray-300 flex items-center gap-1"
        >
          <span>{showAdvanced ? '▾' : '▸'}</span> Advanced — migration status
        </button>
        {showAdvanced && (
          <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-4">
            <Section title="Feature flags" subtitle="every flag defaults off until you flip it">
              <div className="space-y-1.5">
                {flagEntries.map(([name, enabled]) => (
                  <div key={name} className="flex items-center justify-between text-xs">
                    <span className="text-gray-400">{name}</span>
                    <span className={enabled ? 'text-green-400' : 'text-gray-600'}>{enabled ? 'ON' : 'off'}</span>
                  </div>
                ))}
              </div>
            </Section>

            <Section title="Scheduler diet" subtitle={`${schedulerJobs.length} scheduled jobs classified`}>
              <div className="space-y-1.5">
                {Object.entries(schedulerByClass).map(([cls, count]) => (
                  <div key={cls} className="flex items-center justify-between text-xs">
                    <span className="text-gray-400">{cls.replace(/_/g, ' ')}</span>
                    <span className="text-gray-200">{count}</span>
                  </div>
                ))}
              </div>
            </Section>

            <Section title="Legacy dashboards" subtitle="demoted out of the main nav — still fully live" className="md:col-span-2">
              <div className="flex flex-wrap gap-2">
                {LEGACY_OPS_VIEWS.map(({ view, label, embedded }) => (
                  <button
                    key={view}
                    onClick={() =>
                      embedded
                        ? setExpandedLegacyView((v) => (v === view ? null : view))
                        : onNavigate?.(view)
                    }
                    className={`text-xs px-2 py-1 rounded ${
                      expandedLegacyView === view
                        ? 'bg-gray-600 text-gray-100'
                        : 'bg-gray-700/50 hover:bg-gray-700 text-gray-300'
                    }`}
                  >
                    {embedded ? (expandedLegacyView === view ? '▾ ' : '▸ ') : ''}
                    {label}
                  </button>
                ))}
              </div>
              {expandedLegacyView &&
                (() => {
                  const EmbeddedView = EMBEDDED_LEGACY_COMPONENTS[expandedLegacyView as (typeof LEGACY_OPS_VIEWS)[number]['view']];
                  if (!EmbeddedView) return null;
                  return (
                    <div className="mt-3 -mx-4 border-t border-gray-700 pt-3">
                      <Suspense fallback={<div className="text-xs text-gray-500 px-4">Loading…</div>}>
                        <EmbeddedView />
                      </Suspense>
                    </div>
                  );
                })()}
            </Section>
          </div>
        )}
      </div>
    </div>
  );
}
