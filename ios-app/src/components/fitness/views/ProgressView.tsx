// ProgressView — the new "Progress" section from the mockups. Self-contained: it
// fetches its own 30-day window (recovery, workouts) + 14-day food and renders
// Overview / Training / Nutrition / Recovery sub-tabs with Skia trend charts and
// data-driven insights.
import React, { useEffect, useMemo, useState } from 'react';
import {
  View,
  Text,
  ScrollView,
  StyleSheet,
  Dimensions,
  ActivityIndicator,
  RefreshControl,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import {
  fitnessService,
  RecoveryLog,
  WorkoutSession,
  FoodLog,
  NutritionGoals,
} from '../../../services/fitness';
import {
  Card,
  TrendChart,
  StatTile,
  SegmentedTabs,
  SegmentOption,
} from '../ui';
import RecoveryCard from '../RecoveryCard';
import ProgressPhotosView from './ProgressPhotosView';
import {
  computeBaseline,
  computeReadinessScore,
  buildScoreSeries,
  formatSleep,
} from '../../../utils/recovery';
import { computePRs, sessionVolume, groupByDay, dailyCalories } from '../../../utils/fitnessStats';
import { colors, spacing, fontSizes, fontWeights } from '../../../styles/theme';

type ProgressTab = 'overview' | 'training' | 'nutrition' | 'recovery' | 'photos';

const TABS: SegmentOption<ProgressTab>[] = [
  { key: 'overview', label: 'Overview' },
  { key: 'training', label: 'Training' },
  { key: 'nutrition', label: 'Nutrition' },
  { key: 'recovery', label: 'Recovery' },
  { key: 'photos', label: 'Photos' },
];

const SCREEN_W = Dimensions.get('window').width;
const CHART_W = SCREEN_W - spacing.md * 2 - spacing.md * 2; // screen padding + card padding

function toDateStr(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function shortDate(iso: string): string {
  const d = new Date(iso + 'T00:00:00');
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

interface Insight {
  icon: keyof typeof Ionicons.glyphMap;
  color: string;
  text: string;
}

interface ProgressViewProps {
  onLogRecovery?: () => void;
  onEditRecovery?: (log: RecoveryLog) => void;
  onDeleteRecovery?: (log: RecoveryLog) => void;
}

export default function ProgressView({ onLogRecovery, onEditRecovery, onDeleteRecovery }: ProgressViewProps) {
  const [tab, setTab] = useState<ProgressTab>('overview');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [recovery, setRecovery] = useState<RecoveryLog[]>([]);
  const [sessions, setSessions] = useState<WorkoutSession[]>([]);
  const [foods, setFoods] = useState<FoodLog[]>([]);
  const [goals, setGoals] = useState<NutritionGoals | null>(null);

  const load = async () => {
    const today = toDateStr(new Date());
    const start30 = new Date();
    start30.setDate(start30.getDate() - 30);
    const start14 = new Date();
    start14.setDate(start14.getDate() - 14);

    const [rec, sess, food, g] = await Promise.all([
      fitnessService.getRecoveryLogs(toDateStr(start30), today).catch(() => []),
      fitnessService.getWorkoutSessions(toDateStr(start30), today).catch(() => []),
      fitnessService.getFoodLogs(toDateStr(start14), today).catch(() => []),
      fitnessService.getNutritionGoals().catch(() => null),
    ]);
    setRecovery(rec);
    setSessions(sess);
    setFoods(food);
    setGoals(g);
  };

  useEffect(() => {
    (async () => {
      setLoading(true);
      await load();
      setLoading(false);
    })();
  }, []);

  const handleRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  // ---- Derived recovery data ----
  const sortedRecovery = useMemo(
    () => [...recovery].filter(l => l.log_date).sort((a, b) => (a.log_date < b.log_date ? -1 : 1)),
    [recovery],
  );
  const scoreSeries = useMemo(() => buildScoreSeries(recovery), [recovery]);
  const baseline = useMemo(() => computeBaseline(recovery), [recovery]);
  const latest = sortedRecovery[sortedRecovery.length - 1] ?? null;
  const latestScore = useMemo(() => computeReadinessScore(latest, baseline), [latest, baseline]);
  const avgScore = scoreSeries.length
    ? Math.round(scoreSeries.reduce((s, p) => s + p.score, 0) / scoreSeries.length)
    : null;
  const scoreDelta = latestScore && avgScore != null ? latestScore.score - avgScore : null;

  if (loading) {
    return (
      <View style={styles.loading}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <SegmentedTabs options={TABS} value={tab} onChange={setTab} />
      {tab === 'photos' ? (
        // Photos owns its own scroll view + modal; render it outside the shared
        // ScrollView to avoid nesting vertical scrollers.
        <ProgressPhotosView />
      ) : (
        <ScrollView
          style={styles.scroll}
          contentContainerStyle={styles.scrollContent}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} />}
        >
          {tab === 'overview' && renderOverview()}
          {tab === 'training' && renderTraining()}
          {tab === 'nutrition' && renderNutrition()}
          {tab === 'recovery' && renderRecovery()}
        </ScrollView>
      )}
    </View>
  );

  // ============ OVERVIEW ============
  function renderOverview() {
    const series = scoreSeries.map(p => p.score);
    const weightPts = sortedRecovery.filter(l => l.body_weight != null);
    const weights = weightPts.map(l => l.body_weight as number);
    const weightUnit = latest?.weight_unit || 'lbs';
    const weightDelta = weights.length >= 2 ? weights[weights.length - 1] - weights[0] : null;
    const insights = generateInsights();

    return (
      <>
        {/* Recovery score (30 days) */}
        <Card style={styles.card}>
          <View style={styles.cardHeaderRow}>
            <Text style={styles.cardTitle}>Recovery Score (30 days)</Text>
          </View>
          {series.length >= 2 ? (
            <>
              <View style={styles.bigStatRow}>
                <Text style={[styles.bigStat, { color: scoreColor(latestScore?.color) }]}>
                  {latestScore?.score ?? '--'}
                </Text>
                <View style={styles.bigStatSide}>
                  <Text style={[styles.bigStatLabel, { color: scoreColor(latestScore?.color) }]}>
                    {latestScore?.label ?? '—'}
                  </Text>
                  {scoreDelta != null && Math.round(scoreDelta) !== 0 ? (
                    <View style={styles.deltaRow}>
                      <Ionicons
                        name={scoreDelta >= 0 ? 'arrow-up' : 'arrow-down'}
                        size={12}
                        color={scoreDelta >= 0 ? colors.success : colors.error}
                      />
                      <Text style={[styles.deltaText, { color: scoreDelta >= 0 ? colors.success : colors.error }]}>
                        {Math.abs(Math.round(scoreDelta))} vs avg
                      </Text>
                    </View>
                  ) : null}
                </View>
              </View>
              <TrendChart
                data={series}
                width={CHART_W}
                height={140}
                color={colors.primary}
                yTicks={[0, 25, 50, 75, 100]}
                min={0}
                max={100}
                xLabels={edgeLabels(scoreSeries.map(p => p.date))}
              />
            </>
          ) : (
            <EmptyHint text="Log recovery for a few days to see your trend." />
          )}
        </Card>

        {/* Insights */}
        {insights.length ? (
          <Card style={styles.card}>
            <Text style={styles.cardTitle}>Insights</Text>
            <View style={{ marginTop: spacing.sm, gap: spacing.sm }}>
              {insights.map((ins, i) => (
                <View key={i} style={styles.insightRow}>
                  <View style={[styles.insightIcon, { backgroundColor: ins.color + '22' }]}>
                    <Ionicons name={ins.icon} size={16} color={ins.color} />
                  </View>
                  <Text style={styles.insightText}>{ins.text}</Text>
                </View>
              ))}
            </View>
          </Card>
        ) : null}

        {/* Body weight */}
        <Card style={styles.card}>
          <Text style={styles.cardTitle}>Body Weight</Text>
          {weights.length >= 2 ? (
            <>
              <View style={styles.bigStatRow}>
                <Text style={styles.bigStat}>
                  {weights[weights.length - 1].toFixed(1)}
                  <Text style={styles.bigStatUnit}> {weightUnit}</Text>
                </Text>
                {weightDelta != null && Math.abs(weightDelta) >= 0.1 ? (
                  <View style={styles.deltaRow}>
                    <Ionicons
                      name={weightDelta <= 0 ? 'arrow-down' : 'arrow-up'}
                      size={12}
                      color={weightDelta <= 0 ? colors.success : colors.warning}
                    />
                    <Text style={[styles.deltaText, { color: weightDelta <= 0 ? colors.success : colors.warning }]}>
                      {Math.abs(weightDelta).toFixed(1)} {weightUnit}
                    </Text>
                  </View>
                ) : null}
              </View>
              <TrendChart
                data={weights}
                width={CHART_W}
                height={120}
                color={colors.accent}
                xLabels={edgeLabels(weightPts.map(l => l.log_date))}
              />
            </>
          ) : (
            <EmptyHint text="Log body weight to track the trend." />
          )}
        </Card>
      </>
    );
  }

  // ============ TRAINING ============
  function renderTraining() {
    const byDay = groupByDay(sessions, s => s.session_date || s.created_at);
    const volumes = byDay.map(b => b.items.reduce((sum, s) => sum + sessionVolume(s), 0));
    const totalVolume = volumes.reduce((s, v) => s + v, 0);
    const perWeek = sessions.length ? (sessions.length / 30) * 7 : 0;
    const prs = computePRs(sessions, 3);

    return (
      <>
        <View style={styles.statRow}>
          <StatTile label="Workouts (30d)" value={sessions.length} />
          <StatTile label="Per week" value={perWeek.toFixed(1)} />
          <StatTile label="Total volume" value={`${Math.round(totalVolume / 1000)}k`} unit="lb" />
        </View>

        <Card style={styles.card}>
          <Text style={styles.cardTitle}>Training Volume</Text>
          {volumes.length >= 2 ? (
            <TrendChart
              data={volumes}
              width={CHART_W}
              height={130}
              color={colors.fitness.protein}
              fillColor={colors.fitness.protein}
              xLabels={edgeLabels(byDay.map(b => b.date))}
            />
          ) : (
            <EmptyHint text="Log a few workouts to see your volume trend." />
          )}
        </Card>

        <Card style={styles.card}>
          <Text style={styles.cardTitle}>Personal Records</Text>
          {prs.length ? (
            <View style={[styles.statRow, { marginTop: spacing.sm }]}>
              {prs.map(pr => (
                <StatTile
                  key={pr.exercise}
                  label={pr.exercise}
                  value={pr.weight}
                  unit="lbs"
                  accent={colors.accent}
                />
              ))}
            </View>
          ) : (
            <EmptyHint text="No lifts logged yet." />
          )}
        </Card>
      </>
    );
  }

  // ============ NUTRITION ============
  function renderNutrition() {
    const daily = dailyCalories(foods);
    const series = daily.map(d => d.calories);
    const avgCal = series.length ? Math.round(series.reduce((s, v) => s + v, 0) / series.length) : 0;
    const goalCal = goals?.calories ?? null;
    const onTarget =
      goalCal && series.length
        ? Math.round((daily.filter(d => Math.abs(d.calories - goalCal) <= goalCal * 0.1).length / daily.length) * 100)
        : null;

    return (
      <>
        <View style={styles.statRow}>
          <StatTile label="Avg calories" value={avgCal || '—'} />
          <StatTile label="Goal" value={goalCal ?? '—'} />
          <StatTile label="On target" value={onTarget != null ? `${onTarget}%` : '—'} />
        </View>

        <Card style={styles.card}>
          <Text style={styles.cardTitle}>Calories (14 days)</Text>
          {series.length >= 2 ? (
            <TrendChart
              data={series}
              width={CHART_W}
              height={130}
              color={colors.fitness.calories}
              fillColor={colors.fitness.calories}
              xLabels={edgeLabels(daily.map(d => d.date))}
            />
          ) : (
            <EmptyHint text="Log meals to see your calorie trend." />
          )}
        </Card>
      </>
    );
  }

  // ============ RECOVERY ============
  function renderRecovery() {
    const hrv = sortedRecovery.filter(l => l.hrv != null).map(l => l.hrv as number);
    const sleep = sortedRecovery.filter(l => l.sleep_hours != null).map(l => l.sleep_hours as number);
    const rhr = sortedRecovery.filter(l => l.heart_rate != null).map(l => l.heart_rate as number);

    return (
      <>
        <MiniTrend title="HRV" unit="ms" data={hrv} color={colors.fitness.protein} />
        <MiniTrend title="Sleep" unit="hrs" data={sleep} color={colors.secondary} />
        <MiniTrend title="Resting HR" unit="bpm" data={rhr} color={colors.fitness.fats} />

        <Card style={styles.card}>
          <Text style={styles.cardTitle}>Recent Logs</Text>
          {sortedRecovery.length ? (
            <View style={{ marginTop: spacing.xs }}>
              {[...sortedRecovery].reverse().slice(0, 7).map(log => (
                <RecoveryCard
                  key={log.id}
                  log={log}
                  onPress={onEditRecovery}
                  onLongPress={onDeleteRecovery}
                />
              ))}
            </View>
          ) : (
            <EmptyHint text="No recovery logs in the last 30 days." />
          )}
        </Card>
      </>
    );
  }

  // ---- insight generation ----
  function generateInsights(): Insight[] {
    const out: Insight[] = [];
    const series = scoreSeries.map(p => p.score);

    // Recovery trend (first half vs second half)
    if (series.length >= 6) {
      const half = Math.floor(series.length / 2);
      const firstAvg = series.slice(0, half).reduce((s, v) => s + v, 0) / half;
      const secondAvg = series.slice(half).reduce((s, v) => s + v, 0) / (series.length - half);
      if (firstAvg > 0) {
        const pct = Math.round(((secondAvg - firstAvg) / firstAvg) * 100);
        if (Math.abs(pct) >= 5) {
          out.push({
            icon: pct >= 0 ? 'trending-up' : 'trending-down',
            color: pct >= 0 ? colors.success : colors.warning,
            text:
              pct >= 0
                ? `Your recovery has improved ${pct}% in the last 30 days.`
                : `Your recovery has dropped ${Math.abs(pct)}% recently — consider more rest.`,
          });
        }
      }
    }

    // Sleep average
    const sleeps = sortedRecovery.filter(l => l.sleep_hours != null).map(l => l.sleep_hours as number);
    if (sleeps.length >= 3) {
      const avg = sleeps.reduce((s, v) => s + v, 0) / sleeps.length;
      out.push({
        icon: 'moon',
        color: colors.secondary,
        text:
          avg >= 7.5
            ? `You're averaging ${formatSleep(avg)} of sleep — keep it up.`
            : `You're averaging ${formatSleep(avg)} of sleep; aim for 8+ to lift recovery.`,
      });
    }

    // HRV note
    if (baseline.avgHrv != null) {
      out.push({
        icon: 'pulse',
        color: colors.fitness.protein,
        text: `Your baseline HRV is around ${Math.round(baseline.avgHrv)} ms; days above it are your best training days.`,
      });
    }

    return out.slice(0, 3);
  }
}

// ---- small helpers / subcomponents ----
function scoreColor(c?: 'success' | 'primary' | 'warning' | 'error'): string {
  switch (c) {
    case 'success': return colors.success;
    case 'warning': return colors.warning;
    case 'error': return colors.error;
    default: return colors.primary;
  }
}

/** First + last date labels only (keeps the x-axis uncluttered). */
function edgeLabels(dates: string[]): string[] {
  if (!dates.length) return [];
  if (dates.length === 1) return [shortDate(dates[0])];
  return [shortDate(dates[0]), shortDate(dates[dates.length - 1])];
}

function EmptyHint({ text }: { text: string }) {
  return <Text style={styles.emptyHint}>{text}</Text>;
}

function MiniTrend({ title, unit, data, color }: { title: string; unit: string; data: number[]; color: string }) {
  return (
    <Card style={styles.card}>
      <View style={styles.cardHeaderRow}>
        <Text style={styles.cardTitle}>{title}</Text>
        {data.length ? (
          <Text style={styles.miniLatest}>
            {Math.round(data[data.length - 1])} <Text style={styles.miniUnit}>{unit}</Text>
          </Text>
        ) : null}
      </View>
      {data.length >= 2 ? (
        <TrendChart data={data} width={CHART_W} height={90} color={color} fillColor={color} />
      ) : (
        <EmptyHint text={`Not enough ${title.toLowerCase()} data yet.`} />
      )}
    </Card>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  scroll: {
    flex: 1,
  },
  scrollContent: {
    padding: spacing.md,
    paddingBottom: spacing.xxl,
    gap: spacing.md,
  },
  loading: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  card: {
    // Card already styles surface/border/radius/padding
  },
  cardHeaderRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  cardTitle: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: fontWeights.semibold,
  },
  bigStatRow: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: spacing.sm,
    marginVertical: spacing.sm,
  },
  bigStat: {
    color: colors.text,
    fontSize: 40,
    fontWeight: fontWeights.bold,
    lineHeight: 44,
  },
  bigStatUnit: {
    color: colors.textMuted,
    fontSize: fontSizes.md,
    fontWeight: fontWeights.medium,
  },
  bigStatSide: {
    paddingBottom: 6,
  },
  bigStatLabel: {
    fontSize: fontSizes.md,
    fontWeight: fontWeights.semibold,
  },
  deltaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 2,
    marginTop: 2,
  },
  deltaText: {
    fontSize: fontSizes.xs,
    fontWeight: fontWeights.medium,
  },
  statRow: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  insightRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  insightIcon: {
    width: 30,
    height: 30,
    borderRadius: 15,
    alignItems: 'center',
    justifyContent: 'center',
  },
  insightText: {
    flex: 1,
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: 19,
  },
  emptyHint: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    marginTop: spacing.sm,
  },
  miniLatest: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: fontWeights.bold,
  },
  miniUnit: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    fontWeight: fontWeights.regular,
  },
});
