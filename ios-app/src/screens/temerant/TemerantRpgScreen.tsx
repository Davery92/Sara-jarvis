import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  RefreshControl,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { colors, fontSizes } from '../../styles/theme';
import temerantRpgService, {
  TemerantRpgJournalEntry,
  TemerantRpgState,
  TemerantRpgTerm,
  TemerantRpgTurnResponse,
} from '../../services/temerantRpg';

const ATTRIBUTE_OPTIONS = ['body', 'mind', 'craft', 'voice', 'luck'];

export default function TemerantRpgScreen() {
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [showHowItWorks, setShowHowItWorks] = useState(false);

  const [state, setState] = useState<TemerantRpgState | null>(null);
  const [journal, setJournal] = useState<TemerantRpgJournalEntry[]>([]);
  const [terms, setTerms] = useState<TemerantRpgTerm[]>([]);
  const [lastTurn, setLastTurn] = useState<TemerantRpgTurnResponse | null>(null);

  const [characterName, setCharacterName] = useState('Daveth of Andentown');
  const [origin, setOrigin] = useState('Commonwealth, Andentown');
  const [backstory, setBackstory] = useState('');
  const [action, setAction] = useState('');
  const [attribute, setAttribute] = useState('mind');
  const [skill, setSkill] = useState('');
  const [closeSummary, setCloseSummary] = useState('');

  const loadData = useCallback(async () => {
    setError(null);
    try {
      const rpgState = await temerantRpgService.getState();
      setState(rpgState);
      const [entries, termList] = await Promise.all([
        temerantRpgService.listJournal(8),
        temerantRpgService.listTerms(6),
      ]);
      setJournal(entries);
      setTerms(termList);
    } catch (err: any) {
      if (err?.response?.status === 404) {
        setState(null);
        setJournal([]);
        setTerms([]);
      } else {
        const detail = err?.response?.data?.detail;
        setError(typeof detail === 'string' ? detail : 'Failed to load Temerant RPG state.');
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const runAction = async (actionFn: () => Promise<void>, successMessage?: string) => {
    setSubmitting(true);
    setError(null);
    setStatus(null);
    try {
      await actionFn();
      if (successMessage) setStatus(successMessage);
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
      <SafeAreaView style={styles.container}>
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color={colors.primary} />
          <Text style={styles.loadingText}>Loading Temerant RPG...</Text>
        </View>
      </SafeAreaView>
    );
  }

  const openScene = state?.open_scene || null;

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => {
              setRefreshing(true);
              loadData();
            }}
            tintColor={colors.primary}
          />
        }
      >
        <Text style={styles.title}>Temerant RPG</Text>
        <Text style={styles.subtitle}>Scene-based solo play in a persistent University world</Text>

        <TouchableOpacity
          style={styles.secondaryButton}
          onPress={() => setShowHowItWorks((v) => !v)}
        >
          <Text style={styles.secondaryButtonText}>{showHowItWorks ? 'Hide how it works' : 'How it works'}</Text>
        </TouchableOpacity>

        {showHowItWorks && (
          <View style={styles.infoCard}>
            <Text style={styles.infoTitle}>Play loop</Text>
            <Text style={styles.infoText}>Open a scene, take a specific action, resolve it, then close the scene.</Text>
            <Text style={styles.infoTitle}>What persists</Text>
            <Text style={styles.infoText}>Coin, skills, conditions, relationships, world time, and term outcomes.</Text>
          </View>
        )}

        {error && <Text style={styles.error}>{error}</Text>}
        {status && <Text style={styles.status}>{status}</Text>}

        {!state && (
          <View style={styles.card}>
            <Text style={styles.cardTitle}>Create Character</Text>
            <TextInput
              style={styles.input}
              value={characterName}
              onChangeText={setCharacterName}
              placeholder="Character name"
              placeholderTextColor={colors.textMuted}
            />
            <TextInput
              style={styles.input}
              value={origin}
              onChangeText={setOrigin}
              placeholder="Origin"
              placeholderTextColor={colors.textMuted}
            />
            <TextInput
              style={[styles.input, styles.multiline]}
              value={backstory}
              onChangeText={setBackstory}
              placeholder="Backstory (optional)"
              placeholderTextColor={colors.textMuted}
              multiline
            />
            <TouchableOpacity
              disabled={submitting || !characterName.trim()}
              style={[styles.primaryButton, (submitting || !characterName.trim()) && styles.disabled]}
              onPress={() =>
                runAction(async () => {
                  await temerantRpgService.createCharacter({
                    character_name: characterName.trim(),
                    origin: origin || undefined,
                    backstory: backstory || undefined,
                  });
                }, 'Character created.')
              }
            >
              <Text style={styles.primaryButtonText}>Begin</Text>
            </TouchableOpacity>
          </View>
        )}

        {state && (
          <>
            <View style={styles.card}>
              <Text style={styles.cardTitle}>{state.character.character_name}</Text>
              <Text style={styles.meta}>Term {state.character.term_index} | {state.world.local_date} ({state.world.day_slot})</Text>
              <Text style={styles.meta}>Coin: {state.character.coin_talents.toFixed(1)} talents</Text>
              <Text style={styles.meta}>Weather: {state.world.weather}</Text>
            </View>

            <View style={styles.card}>
              <View style={styles.rowBetween}>
                <Text style={styles.cardTitle}>Scene</Text>
                {!openScene ? (
                  <TouchableOpacity
                    disabled={submitting}
                    style={[styles.primaryButtonSmall, submitting && styles.disabled]}
                    onPress={() => runAction(async () => { await temerantRpgService.openScene(); }, 'Scene opened.')}
                  >
                    <Text style={styles.primaryButtonText}>Open</Text>
                  </TouchableOpacity>
                ) : null}
              </View>

              {!openScene ? (
                <Text style={styles.meta}>No open scene.</Text>
              ) : (
                <>
                  <Text style={styles.sceneTitle}>Scene {openScene.scene_number}: {openScene.title}</Text>
                  <Text style={styles.sceneText}>{openScene.opening_text}</Text>
                  {lastTurn ? (
                    <View style={styles.lastTurnCard}>
                      <Text style={styles.lastTurnOutcome}>{lastTurn.outcome} ({lastTurn.total} vs {lastTurn.difficulty})</Text>
                      <Text style={styles.sceneText}>{lastTurn.response_text}</Text>
                    </View>
                  ) : null}

                  <Text style={styles.fieldLabel}>Attribute</Text>
                  <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginBottom: 10 }}>
                    <View style={styles.pillRow}>
                      {ATTRIBUTE_OPTIONS.map((option) => (
                        <TouchableOpacity
                          key={option}
                          style={[styles.pill, attribute === option && styles.pillActive]}
                          onPress={() => setAttribute(option)}
                        >
                          <Text style={[styles.pillText, attribute === option && styles.pillTextActive]}>{option}</Text>
                        </TouchableOpacity>
                      ))}
                    </View>
                  </ScrollView>

                  <TextInput
                    style={styles.input}
                    value={skill}
                    onChangeText={setSkill}
                    placeholder="Skill (optional)"
                    placeholderTextColor={colors.textMuted}
                  />
                  <TextInput
                    style={[styles.input, styles.multiline]}
                    value={action}
                    onChangeText={setAction}
                    placeholder="What does Daveth do right now?"
                    placeholderTextColor={colors.textMuted}
                    multiline
                  />

                  <TouchableOpacity
                    disabled={submitting || !action.trim()}
                    style={[styles.primaryButton, (submitting || !action.trim()) && styles.disabled]}
                    onPress={() =>
                      runAction(async () => {
                        const turn = await temerantRpgService.actInScene(openScene.id, {
                          action: action.trim(),
                          attribute: attribute || undefined,
                          skill: skill.trim() || undefined,
                        });
                        setLastTurn(turn);
                        setAction('');
                      })
                    }
                  >
                    <Text style={styles.primaryButtonText}>Resolve Action</Text>
                  </TouchableOpacity>

                  <TextInput
                    style={styles.input}
                    value={closeSummary}
                    onChangeText={setCloseSummary}
                    placeholder="Scene summary (optional)"
                    placeholderTextColor={colors.textMuted}
                  />

                  <View style={styles.row}>
                    <TouchableOpacity
                      disabled={submitting}
                      style={[styles.secondaryButtonFlex, submitting && styles.disabled]}
                      onPress={() =>
                        runAction(async () => {
                          await temerantRpgService.closeScene(openScene.id, closeSummary || undefined);
                          setCloseSummary('');
                          setLastTurn(null);
                        }, 'Scene closed.')
                      }
                    >
                      <Text style={styles.secondaryButtonText}>Close Scene</Text>
                    </TouchableOpacity>
                    <TouchableOpacity
                      disabled={submitting || !!openScene}
                      style={[styles.secondaryButtonFlex, (submitting || !!openScene) && styles.disabled]}
                      onPress={() => runAction(async () => { await temerantRpgService.advanceTime(1); }, 'Time advanced.')}
                    >
                      <Text style={styles.secondaryButtonText}>Advance Slot</Text>
                    </TouchableOpacity>
                  </View>
                </>
              )}
            </View>

            <View style={styles.card}>
              <View style={styles.rowBetween}>
                <Text style={styles.cardTitle}>Admissions</Text>
                <TouchableOpacity
                  disabled={submitting}
                  style={[styles.secondaryButtonSmall, submitting && styles.disabled]}
                  onPress={() => runAction(async () => { await temerantRpgService.runAdmissions(); }, 'Admissions resolved.')}
                >
                  <Text style={styles.secondaryButtonText}>Run</Text>
                </TouchableOpacity>
              </View>
              {terms.length === 0 ? <Text style={styles.meta}>No admissions records yet.</Text> : null}
              {terms.map((term) => (
                <View key={term.id} style={styles.listCard}>
                  <Text style={styles.meta}>Term {term.term_index} | {term.month}</Text>
                  <Text style={styles.sceneText}>{term.admissions_result} - {term.tuition_talents.toFixed(1)} talents</Text>
                </View>
              ))}
            </View>

            <View style={styles.card}>
              <Text style={styles.cardTitle}>Journal</Text>
              {journal.length === 0 ? <Text style={styles.meta}>No journal entries yet.</Text> : null}
              {journal.map((entry) => (
                <View key={entry.id} style={styles.listCard}>
                  <Text style={styles.meta}>{entry.local_date}</Text>
                  <Text style={styles.sceneText}>{entry.summary_markdown}</Text>
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
  container: { flex: 1, backgroundColor: colors.background },
  content: { padding: 16, paddingBottom: 28 },
  loadingContainer: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  loadingText: { color: colors.textMuted, marginTop: 12 },
  title: { color: colors.text, fontSize: fontSizes.xxl, fontWeight: '700' },
  subtitle: { color: colors.textMuted, marginTop: 4, marginBottom: 12 },
  card: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 12,
    padding: 14,
    marginBottom: 12,
  },
  infoCard: {
    backgroundColor: '#1e293b',
    borderColor: '#334155',
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    marginBottom: 12,
  },
  infoTitle: { color: '#e2e8f0', fontWeight: '700', marginTop: 4 },
  infoText: { color: '#cbd5e1', marginTop: 2 },
  cardTitle: { color: colors.text, fontWeight: '700', fontSize: fontSizes.lg, marginBottom: 6 },
  meta: { color: colors.textMuted, marginBottom: 4 },
  sceneTitle: { color: colors.text, fontWeight: '600', marginBottom: 6 },
  sceneText: { color: colors.text, lineHeight: 20 },
  rowBetween: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  row: { flexDirection: 'row', gap: 8 },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.background,
    borderRadius: 10,
    color: colors.text,
    paddingHorizontal: 12,
    paddingVertical: 10,
    marginBottom: 10,
  },
  multiline: { minHeight: 80, textAlignVertical: 'top' },
  fieldLabel: { color: colors.textMuted, marginBottom: 6, marginTop: 4 },
  pillRow: { flexDirection: 'row', gap: 8 },
  pill: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 6,
    backgroundColor: colors.background,
  },
  pillActive: { backgroundColor: colors.primary, borderColor: colors.primary },
  pillText: { color: colors.textMuted, fontSize: 12, textTransform: 'capitalize' },
  pillTextActive: { color: '#fff' },
  primaryButton: {
    backgroundColor: colors.primary,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: 'center',
    marginBottom: 8,
  },
  primaryButtonSmall: {
    backgroundColor: colors.primary,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  primaryButtonText: { color: '#fff', fontWeight: '700' },
  secondaryButton: {
    backgroundColor: colors.surfaceLight,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    alignSelf: 'flex-start',
    marginBottom: 10,
  },
  secondaryButtonSmall: {
    backgroundColor: colors.surfaceLight,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  secondaryButtonFlex: {
    flex: 1,
    backgroundColor: colors.surfaceLight,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    paddingVertical: 10,
    alignItems: 'center',
  },
  secondaryButtonText: { color: colors.text, fontWeight: '600' },
  disabled: { opacity: 0.5 },
  error: { color: colors.error, marginBottom: 10 },
  status: { color: colors.success, marginBottom: 10 },
  lastTurnCard: {
    borderWidth: 1,
    borderColor: '#0f766e',
    backgroundColor: '#042f2e',
    borderRadius: 10,
    padding: 10,
    marginBottom: 10,
  },
  lastTurnOutcome: { color: '#99f6e4', marginBottom: 6, fontWeight: '700' },
  listCard: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 10,
    backgroundColor: colors.background,
    padding: 10,
    marginTop: 8,
  },
});
