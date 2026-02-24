import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  RefreshControl,
  TextInput,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import temerantService, {
  TemerantAttribute,
  TemerantDashboard,
  TemerantJournalEntry,
  TemerantOracleEvent,
  TemerantStarterProfile,
  TemerantTerm,
} from '../../services/temerant';

const ATTRIBUTE_META: Record<TemerantAttribute, { label: string; color: string }> = {
  body: { label: 'Body', color: '#ef4444' },
  mind: { label: 'Mind', color: '#3b82f6' },
  craft: { label: 'Craft', color: '#f59e0b' },
  coin: { label: 'Coin', color: '#10b981' },
  name: { label: 'Name', color: '#8b5cf6' },
};

const QUICK_ACTIONS = [
  { action_type: 'workout', label: 'Workout' },
  { action_type: 'study', label: 'Study' },
  { action_type: 'guitar', label: 'Guitar' },
  { action_type: 'coding', label: 'Coding' },
  { action_type: 'workday_complete', label: 'Workday' },
  { action_type: 'meditation', label: 'Meditation' },
];

function rankLabel(rank: string) {
  if (rank === 'relar') return 'Re\'lar';
  if (rank === 'elthe') return 'El\'the';
  return 'E\'lir';
}

function formatDate(value?: string | null) {
  if (!value) return 'n/a';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString();
}

export default function TemerantScreen() {
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [needsCharacter, setNeedsCharacter] = useState(false);

  const [dashboard, setDashboard] = useState<TemerantDashboard | null>(null);
  const [term, setTerm] = useState<TemerantTerm | null>(null);
  const [journal, setJournal] = useState<TemerantJournalEntry[]>([]);
  const [events, setEvents] = useState<TemerantOracleEvent[]>([]);
  const [starterProfiles, setStarterProfiles] = useState<TemerantStarterProfile[]>([]);

  const [characterName, setCharacterName] = useState('');
  const [origin, setOrigin] = useState('');
  const [backstory, setBackstory] = useState('');
  const [resolution, setResolution] = useState('');

  const loadData = useCallback(async () => {
    setError(null);
    try {
      const profiles = await temerantService.getStarterProfiles();
      setStarterProfiles(profiles || []);
    } catch {
      setStarterProfiles([]);
    }
    try {
      await temerantService.getCharacter();
      setNeedsCharacter(false);

      const [nextDashboard, currentTerm, journalEntries, oracleEvents] = await Promise.all([
        temerantService.getDashboard(),
        temerantService.getCurrentTerm(),
        temerantService.listJournal(5),
        temerantService.listOracleEvents(undefined, 10),
      ]);

      setDashboard(nextDashboard);
      setTerm(currentTerm);
      setJournal(journalEntries);
      setEvents(oracleEvents);
    } catch (err: any) {
      if (err?.response?.status === 404) {
        setNeedsCharacter(true);
        setDashboard(null);
        setTerm(null);
        setJournal([]);
        setEvents([]);
      } else {
        const detail = err?.response?.data?.detail;
        setError(typeof detail === 'string' ? detail : 'Failed to load Temerant data.');
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const activeEvent = useMemo(() => {
    if (dashboard?.oracle_event?.status === 'open') return dashboard.oracle_event;
    return events.find((event) => event.status === 'open') || null;
  }, [dashboard, events]);

  const davethProfile = useMemo(
    () => starterProfiles.find((profile) => profile.id === 'daveth_of_andentown') || null,
    [starterProfiles]
  );

  const runAction = async (action: () => Promise<void>, successMessage: string) => {
    setSubmitting(true);
    setError(null);
    setStatus(null);
    try {
      await action();
      setStatus(successMessage);
      await loadData();
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Action failed.');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.container} edges={['top']}>
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color={colors.primary} />
          <Text style={styles.loadingText}>Loading Temerant...</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); loadData(); }} tintColor={colors.primary} />}
      >
        <Text style={styles.title}>Temerant</Text>
        <Text style={styles.subtitle}>Reality to University progression</Text>

        {error && <Text style={styles.error}>{error}</Text>}
        {status && <Text style={styles.status}>{status}</Text>}

        {needsCharacter && (
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Create Character</Text>
            {davethProfile && (
              <View style={styles.presetCard}>
                <Text style={styles.presetTitle}>{davethProfile.name}</Text>
                <Text style={styles.presetDescription}>{davethProfile.description}</Text>
                <TouchableOpacity
                  disabled={submitting}
                  style={[styles.secondaryButton, submitting && styles.disabledButton]}
                  onPress={() =>
                    runAction(async () => {
                      await temerantService.createCharacter({
                        starter_profile: davethProfile.id,
                      });
                    }, 'Daveth profile applied.')
                  }
                >
                  <Text style={styles.secondaryButtonText}>Use Daveth Preset</Text>
                </TouchableOpacity>
              </View>
            )}
            <TextInput
              placeholder="Character name"
              placeholderTextColor={colors.textMuted}
              value={characterName}
              onChangeText={setCharacterName}
              style={styles.input}
            />
            <TextInput
              placeholder="Origin (optional)"
              placeholderTextColor={colors.textMuted}
              value={origin}
              onChangeText={setOrigin}
              style={styles.input}
            />
            <TextInput
              placeholder="Backstory (optional)"
              placeholderTextColor={colors.textMuted}
              value={backstory}
              onChangeText={setBackstory}
              style={[styles.input, styles.multiline]}
              multiline
            />
            <TouchableOpacity
              disabled={!characterName.trim() || submitting}
              style={[styles.primaryButton, (!characterName.trim() || submitting) && styles.disabledButton]}
              onPress={() =>
                runAction(async () => {
                  await temerantService.createCharacter({
                    character_name: characterName.trim(),
                    origin: origin || undefined,
                    backstory: backstory || undefined,
                  });
                  setCharacterName('');
                  setOrigin('');
                  setBackstory('');
                }, 'Character created.')
              }
            >
              <Text style={styles.primaryButtonText}>Begin Term</Text>
            </TouchableOpacity>
          </View>
        )}

        {!needsCharacter && dashboard && (
          <>
            <View style={styles.card}>
              <Text style={styles.cardTitle}>
                {dashboard.character.character_name} - {rankLabel(dashboard.character.current_rank)}
              </Text>
              <Text style={styles.cardMeta}>Date: {formatDate(dashboard.date)}</Text>
              <View style={styles.statRow}>
                <Text style={styles.statLabel}>Coin</Text>
                <Text style={styles.statValue}>{dashboard.character.coin_balance.toFixed(1)} talents</Text>
              </View>
              <View style={styles.statRow}>
                <Text style={styles.statLabel}>Categories Today</Text>
                <Text style={styles.statValue}>{dashboard.daily.categories_completed}/5</Text>
              </View>
            </View>

            <View style={styles.card}>
              <Text style={styles.cardTitle}>Attributes</Text>
              {(Object.keys(ATTRIBUTE_META) as TemerantAttribute[]).map((key) => {
                const attribute = dashboard.attributes[key];
                if (!attribute) return null;
                const progress = Math.min(1, (attribute.xp_total % 25) / 25);
                return (
                  <View key={key} style={styles.attributeBlock}>
                    <View style={styles.attributeHeader}>
                      <Text style={styles.attributeName}>{ATTRIBUTE_META[key].label}</Text>
                      <Text style={styles.attributeMeta}>Lv {attribute.level} | +{attribute.xp_today}</Text>
                    </View>
                    <View style={styles.attributeBarTrack}>
                      <View style={[styles.attributeBarFill, { width: `${progress * 100}%`, backgroundColor: ATTRIBUTE_META[key].color }]} />
                    </View>
                  </View>
                );
              })}
            </View>

            <View style={styles.card}>
              <Text style={styles.cardTitle}>Quick Log</Text>
              <View style={styles.quickGrid}>
                {QUICK_ACTIONS.map((item) => (
                  <TouchableOpacity
                    key={item.action_type}
                    disabled={submitting}
                    style={[styles.quickButton, submitting && styles.disabledButton]}
                    onPress={() =>
                      runAction(async () => {
                        await temerantService.createManualLog({
                          action_type: item.action_type,
                          action_label: item.label,
                          quantity: 1,
                        });
                      }, `${item.label} logged.`)
                    }
                  >
                    <Text style={styles.quickButtonText}>{item.label}</Text>
                  </TouchableOpacity>
                ))}
              </View>
            </View>

            <View style={styles.card}>
              <View style={styles.cardActionHeader}>
                <Text style={styles.cardTitle}>Oracle</Text>
                <TouchableOpacity
                  disabled={submitting}
                  style={[styles.secondaryButton, submitting && styles.disabledButton]}
                  onPress={() => runAction(async () => { await temerantService.rollOracle(); }, 'Oracle rolled.')}
                >
                  <Text style={styles.secondaryButtonText}>Roll</Text>
                </TouchableOpacity>
              </View>
              {activeEvent ? (
                <>
                  <Text style={styles.oracleTier}>{activeEvent.tier.toUpperCase()} - {activeEvent.category}</Text>
                  <Text style={styles.oracleTitle}>{activeEvent.title}</Text>
                  <Text style={styles.oracleHook}>{activeEvent.hook}</Text>
                  <TextInput
                    placeholder="Resolution notes (optional)"
                    placeholderTextColor={colors.textMuted}
                    value={resolution}
                    onChangeText={setResolution}
                    style={[styles.input, styles.multiline]}
                    multiline
                  />
                  <View style={styles.inlineActions}>
                    <TouchableOpacity
                      disabled={submitting}
                      style={[styles.resolveButton, submitting && styles.disabledButton]}
                      onPress={() =>
                        runAction(async () => {
                          await temerantService.resolveOracleEvent(activeEvent.id, {
                            status: 'resolved',
                            resolution: resolution || undefined,
                          });
                          setResolution('');
                        }, 'Oracle event resolved.')
                      }
                    >
                      <Text style={styles.primaryButtonText}>Resolve</Text>
                    </TouchableOpacity>
                    <TouchableOpacity
                      disabled={submitting}
                      style={[styles.dismissButton, submitting && styles.disabledButton]}
                      onPress={() =>
                        runAction(async () => {
                          await temerantService.resolveOracleEvent(activeEvent.id, {
                            status: 'dismissed',
                            resolution: resolution || undefined,
                          });
                          setResolution('');
                        }, 'Oracle event dismissed.')
                      }
                    >
                      <Text style={styles.primaryButtonText}>Dismiss</Text>
                    </TouchableOpacity>
                  </View>
                </>
              ) : (
                <Text style={styles.emptyText}>No open event.</Text>
              )}
            </View>

            <View style={styles.card}>
              <Text style={styles.cardTitle}>Term</Text>
              {term ? (
                <>
                  <View style={styles.statRow}>
                    <Text style={styles.statLabel}>Completion</Text>
                    <Text style={styles.statValue}>{term.completion_pct.toFixed(1)}%</Text>
                  </View>
                  <View style={styles.statRow}>
                    <Text style={styles.statLabel}>Admissions</Text>
                    <Text style={styles.statValue}>{term.admissions_result}</Text>
                  </View>
                  <View style={styles.statRow}>
                    <Text style={styles.statLabel}>Tuition</Text>
                    <Text style={styles.statValue}>{term.tuition_talents} talents</Text>
                  </View>
                </>
              ) : (
                <Text style={styles.emptyText}>No term data.</Text>
              )}
            </View>

            <View style={styles.card}>
              <Text style={styles.cardTitle}>Journal</Text>
              {journal.length === 0 && <Text style={styles.emptyText}>No entries yet.</Text>}
              {journal.map((entry) => (
                <View key={entry.id} style={styles.journalCard}>
                  <Text style={styles.journalDate}>{formatDate(entry.local_date)} - {entry.source_event_count} events</Text>
                  <Text style={styles.journalText} numberOfLines={4}>{entry.summary_markdown}</Text>
                </View>
              ))}
            </View>
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  content: {
    padding: spacing.md,
    paddingBottom: spacing.xxl,
  },
  loadingContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.sm,
  },
  loadingText: {
    color: colors.textSecondary,
    fontSize: fontSizes.md,
  },
  title: {
    fontSize: fontSizes.xxl,
    fontWeight: '700',
    color: colors.text,
  },
  subtitle: {
    marginTop: 2,
    marginBottom: spacing.md,
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  cardTitle: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
    marginBottom: spacing.xs,
  },
  cardMeta: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginBottom: spacing.sm,
  },
  presetCard: {
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: 'rgba(20,184,166,0.4)',
    backgroundColor: 'rgba(20,184,166,0.12)',
    padding: spacing.sm,
    marginBottom: spacing.sm,
    gap: spacing.xs,
  },
  presetTitle: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  presetDescription: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
  },
  error: {
    color: '#fca5a5',
    backgroundColor: 'rgba(239,68,68,0.15)',
    borderWidth: 1,
    borderColor: 'rgba(239,68,68,0.35)',
    borderRadius: borderRadius.md,
    padding: spacing.sm,
    marginBottom: spacing.sm,
    fontSize: fontSizes.sm,
  },
  status: {
    color: '#86efac',
    backgroundColor: 'rgba(16,185,129,0.15)',
    borderWidth: 1,
    borderColor: 'rgba(16,185,129,0.35)',
    borderRadius: borderRadius.md,
    padding: spacing.sm,
    marginBottom: spacing.sm,
    fontSize: fontSizes.sm,
  },
  input: {
    backgroundColor: colors.background,
    borderWidth: 1,
    borderColor: colors.border,
    color: colors.text,
    borderRadius: borderRadius.md,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.sm,
    marginBottom: spacing.sm,
    fontSize: fontSizes.md,
  },
  multiline: {
    minHeight: 72,
    textAlignVertical: 'top',
  },
  statRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: spacing.xs,
  },
  statLabel: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
  },
  statValue: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  attributeBlock: {
    marginBottom: spacing.sm,
  },
  attributeHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 4,
  },
  attributeName: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '500',
  },
  attributeMeta: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
  },
  attributeBarTrack: {
    backgroundColor: colors.background,
    borderRadius: borderRadius.full,
    height: 6,
    overflow: 'hidden',
  },
  attributeBarFill: {
    height: 6,
    borderRadius: borderRadius.full,
  },
  quickGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.xs,
  },
  quickButton: {
    width: '31%',
    backgroundColor: colors.background,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: borderRadius.md,
    paddingVertical: spacing.sm,
    alignItems: 'center',
  },
  quickButtonText: {
    color: colors.text,
    fontSize: fontSizes.xs,
    fontWeight: '600',
  },
  primaryButton: {
    backgroundColor: colors.primary,
    borderRadius: borderRadius.md,
    paddingVertical: spacing.sm,
    alignItems: 'center',
  },
  resolveButton: {
    backgroundColor: colors.success,
    borderRadius: borderRadius.md,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    alignItems: 'center',
    flex: 1,
  },
  dismissButton: {
    backgroundColor: colors.textMuted,
    borderRadius: borderRadius.md,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    alignItems: 'center',
    flex: 1,
  },
  primaryButtonText: {
    color: '#fff',
    fontSize: fontSizes.sm,
    fontWeight: '700',
  },
  disabledButton: {
    opacity: 0.5,
  },
  secondaryButton: {
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
  },
  secondaryButtonText: {
    color: colors.text,
    fontSize: fontSizes.xs,
    fontWeight: '600',
  },
  cardActionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.xs,
  },
  oracleTier: {
    color: colors.primary,
    fontSize: fontSizes.xs,
    fontWeight: '700',
    marginBottom: 2,
  },
  oracleTitle: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
    marginBottom: 4,
  },
  oracleHook: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    marginBottom: spacing.sm,
    lineHeight: 18,
  },
  inlineActions: {
    flexDirection: 'row',
    gap: spacing.xs,
  },
  emptyText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
  },
  journalCard: {
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.sm,
    marginTop: spacing.xs,
  },
  journalDate: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginBottom: 4,
  },
  journalText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: 18,
  },
});
