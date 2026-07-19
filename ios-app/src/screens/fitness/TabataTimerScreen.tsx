import React, { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import {
  View, Text, StyleSheet, TouchableOpacity, Pressable, Alert, ScrollView,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { Audio } from 'expo-av';
import * as Haptics from 'expo-haptics';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import Ring from '../../components/fitness/ui/Ring';
import {
  buildTabataSequence, tabataTotalSeconds, TabataPhase, TabataPhaseKind,
  cardioService, activityMeta,
} from '../../services/cardio';
import { TICK_WAV, WORK_WAV, REST_WAV, DONE_WAV } from '../../utils/tabataSounds';
import { RootStackParamList } from '../../types/navigation';

type Nav = any;
type TabataRoute = RouteProp<RootStackParamList, 'TabataTimer'>;

const PHASE_COLOR: Record<TabataPhaseKind, string> = {
  prepare: '#fbbf24',
  work: '#ef4444',
  rest: '#34d399',
  rest_set: '#38bdf8',
  done: colors.accent,
};

const PHASE_TITLE: Record<TabataPhaseKind, string> = {
  prepare: 'GET READY',
  work: 'WORK',
  rest: 'REST',
  rest_set: 'SET BREAK',
  done: 'DONE',
};

function fmt(sec: number): string {
  const s = Math.max(0, Math.ceil(sec));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return m > 0 ? `${m}:${r.toString().padStart(2, '0')}` : `${r}`;
}

export default function TabataTimerScreen() {
  const navigation = useNavigation<Nav>();
  const route = useRoute<TabataRoute>();
  const preset = route.params?.preset;

  const sequence = useMemo<TabataPhase[]>(
    () => (preset ? buildTabataSequence(preset) : []),
    [preset],
  );
  const totalSeconds = useMemo(() => (preset ? tabataTotalSeconds(preset) : 0), [preset]);

  const [phaseIndex, setPhaseIndex] = useState(0);
  const [secondsLeft, setSecondsLeft] = useState(sequence[0]?.seconds ?? 0);
  const [running, setRunning] = useState(false);
  const [finished, setFinished] = useState(false);
  const [muted, setMuted] = useState(false);
  const [logged, setLogged] = useState(false);

  // Mutable refs driving the tick loop (avoid stale closures).
  const phaseIndexRef = useRef(0);
  const phaseEndRef = useRef<number>(0);        // Date.now() ms when current phase ends
  const remainingRef = useRef<number>(sequence[0]?.seconds ?? 0);  // seconds left (for pause)
  const lastTickSecondRef = useRef<number>(-1);
  const tickIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const soundsRef = useRef<Record<string, Audio.Sound | null>>({});
  const mutedRef = useRef(false);
  useEffect(() => { mutedRef.current = muted; }, [muted]);

  const phase = sequence[phaseIndex];
  const phaseKind: TabataPhaseKind = finished ? 'done' : (phase?.kind ?? 'done');
  const accent = PHASE_COLOR[phaseKind];

  // ---- audio setup ----
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await Audio.setAudioModeAsync({ playsInSilentModeIOS: true, staysActiveInBackground: false });
        const defs: [string, string][] = [
          ['tick', TICK_WAV], ['work', WORK_WAV], ['rest', REST_WAV], ['done', DONE_WAV],
        ];
        for (const [key, uri] of defs) {
          const { sound } = await Audio.Sound.createAsync({ uri }, { shouldPlay: false });
          if (cancelled) { await sound.unloadAsync(); return; }
          soundsRef.current[key] = sound;
        }
      } catch { /* audio best-effort */ }
    })();
    return () => {
      cancelled = true;
      Object.values(soundsRef.current).forEach(s => { s?.unloadAsync().catch(() => {}); });
      soundsRef.current = {};
    };
  }, []);

  const play = useCallback((key: string) => {
    if (mutedRef.current) return;
    const s = soundsRef.current[key];
    if (s) s.replayAsync().catch(() => {});
  }, []);

  // ---- cue for entering a phase ----
  const cuePhase = useCallback((kind: TabataPhaseKind) => {
    if (kind === 'work') {
      play('work');
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy).catch(() => {});
    } else if (kind === 'rest' || kind === 'rest_set') {
      play('rest');
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => {});
    } else if (kind === 'prepare') {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
    }
  }, [play]);

  // ---- finish ----
  const finish = useCallback(() => {
    if (tickIntervalRef.current) { clearInterval(tickIntervalRef.current); tickIntervalRef.current = null; }
    setRunning(false);
    setFinished(true);
    setSecondsLeft(0);
    // triple beep + success haptic
    play('done');
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
    setTimeout(() => play('done'), 260);
    setTimeout(() => play('done'), 520);
  }, [play]);

  // ---- advance to next phase ----
  const advance = useCallback(() => {
    const next = phaseIndexRef.current + 1;
    if (next >= sequence.length) { finish(); return; }
    phaseIndexRef.current = next;
    const ph = sequence[next];
    remainingRef.current = ph.seconds;
    phaseEndRef.current = Date.now() + ph.seconds * 1000;
    lastTickSecondRef.current = -1;
    setPhaseIndex(next);
    setSecondsLeft(ph.seconds);
    cuePhase(ph.kind);
  }, [sequence, finish, cuePhase]);

  // ---- the tick loop ----
  const tick = useCallback(() => {
    const remainingMs = phaseEndRef.current - Date.now();
    const remaining = remainingMs / 1000;
    remainingRef.current = remaining;
    if (remaining <= 0.05) {
      advance();
      return;
    }
    setSecondsLeft(remaining);
    // 3-2-1 countdown ticks (once per whole second)
    const whole = Math.ceil(remaining);
    if (whole <= 3 && whole !== lastTickSecondRef.current) {
      lastTickSecondRef.current = whole;
      play('tick');
      Haptics.selectionAsync().catch(() => {});
    }
  }, [advance, play]);

  // Single owner of the tick interval: runs iff `running`. `tick` is ref-driven and
  // stable across renders, so this effect doesn't thrash.
  useEffect(() => {
    if (running) {
      tickIntervalRef.current = setInterval(tick, 100);
      return () => {
        if (tickIntervalRef.current) { clearInterval(tickIntervalRef.current); tickIntervalRef.current = null; }
      };
    }
    return undefined;
  }, [running, tick]);

  useEffect(() => () => {
    if (tickIntervalRef.current) clearInterval(tickIntervalRef.current);
  }, []);

  // ---- controls ----
  const handleStartPause = useCallback(() => {
    if (finished) return;
    if (running) {
      // pause
      setRunning(false);
      if (tickIntervalRef.current) { clearInterval(tickIntervalRef.current); tickIntervalRef.current = null; }
      remainingRef.current = Math.max(0, (phaseEndRef.current - Date.now()) / 1000);
    } else {
      // start / resume
      const cur = sequence[phaseIndexRef.current];
      if (!cur) return;
      phaseEndRef.current = Date.now() + remainingRef.current * 1000;
      if (remainingRef.current === cur.seconds && lastTickSecondRef.current === -1) {
        cuePhase(cur.kind);  // cue the very first phase on initial start
      }
      setRunning(true);
    }
  }, [running, finished, sequence, cuePhase]);

  const handleSkip = useCallback(() => {
    if (finished) return;
    advance();
  }, [advance, finished]);

  const handleReset = useCallback(() => {
    if (tickIntervalRef.current) { clearInterval(tickIntervalRef.current); tickIntervalRef.current = null; }
    phaseIndexRef.current = 0;
    remainingRef.current = sequence[0]?.seconds ?? 0;
    lastTickSecondRef.current = -1;
    setPhaseIndex(0);
    setSecondsLeft(sequence[0]?.seconds ?? 0);
    setRunning(false);
    setFinished(false);
    setLogged(false);
  }, [sequence]);

  const handleQuit = useCallback(() => {
    if (finished || !running) { navigation.goBack(); return; }
    Alert.alert('Quit timer?', 'Your interval session will end.', [
      { text: 'Keep going', style: 'cancel' },
      { text: 'Quit', style: 'destructive', onPress: () => navigation.goBack() },
    ]);
  }, [finished, running, navigation]);

  // ---- log the finished session ----
  const logSession = useCallback(async () => {
    if (!preset || logged) return;
    try {
      const minutes = Math.round((totalSeconds / 60) * 10) / 10;
      await cardioService.createLog({
        activity_type: preset.activity_type || 'tabata',
        title: preset.name,
        duration_minutes: minutes,
        source: 'tabata',
        tabata_detail: {
          work: preset.work_seconds,
          rest: preset.rest_seconds,
          rounds: preset.rounds,
          sets: preset.sets,
          completed_rounds: preset.rounds * preset.sets,
          preset_name: preset.name,
        },
      });
      setLogged(true);
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
    } catch (e) {
      Alert.alert('Could not log', 'Saving the cardio session failed. Try again.');
    }
  }, [preset, logged, totalSeconds]);

  if (!preset) {
    return (
      <View style={[styles.container, styles.center]}>
        <Text style={styles.subtle}>No timer selected.</Text>
        <TouchableOpacity style={styles.secondaryBtn} onPress={() => navigation.goBack()}>
          <Text style={styles.secondaryBtnText}>Back</Text>
        </TouchableOpacity>
      </View>
    );
  }

  const meta = activityMeta(preset.activity_type || 'tabata');
  const phaseTotal = finished ? 1 : (phase?.seconds ?? 1);
  const progress = finished ? 1 : 1 - secondsLeft / phaseTotal;
  const totalRounds = preset.rounds * preset.sets;
  const workProgress = finished
    ? totalRounds
    : Math.min(sequence.slice(0, phaseIndex + 1).filter(p => p.kind === 'work').length, totalRounds);

  return (
    <View style={[styles.container, { backgroundColor: finished ? colors.background : `${accent}0D` }]}>
      {/* Top bar */}
      <View style={styles.topBar}>
        <TouchableOpacity onPress={handleQuit} hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}>
          <Ionicons name="chevron-back" size={26} color={colors.text} />
        </TouchableOpacity>
        <View style={styles.titlePill}>
          <Ionicons name={meta.icon as any} size={14} color={accent} />
          <Text style={styles.titlePillText} numberOfLines={1}>{preset.name}</Text>
        </View>
        <TouchableOpacity onPress={() => setMuted(m => !m)} hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}>
          <Ionicons name={muted ? 'volume-mute' : 'volume-high'} size={22} color={colors.textSecondary} />
        </TouchableOpacity>
      </View>

      {!finished ? (
        <View style={styles.stage}>
          <Text style={[styles.phaseTitle, { color: accent }]}>{PHASE_TITLE[phaseKind]}</Text>

          <Ring size={260} strokeWidth={16} progress={progress} color={accent} trackColor={`${accent}22`}>
            <Text style={[styles.countdown, { color: accent }]}>{fmt(secondsLeft)}</Text>
            <Text style={styles.countdownUnit}>{Math.ceil(secondsLeft) >= 60 ? 'min' : 'sec'}</Text>
          </Ring>

          {/* Round / set counters */}
          <View style={styles.countersRow}>
            <View style={styles.counterBox}>
              <Text style={styles.counterValue}>{Math.max(1, workProgress)}/{totalRounds}</Text>
              <Text style={styles.counterLabel}>Round</Text>
            </View>
            {preset.sets > 1 && (
              <View style={styles.counterBox}>
                <Text style={styles.counterValue}>{phase?.set ?? 1}/{preset.sets}</Text>
                <Text style={styles.counterLabel}>Set</Text>
              </View>
            )}
            <View style={styles.counterBox}>
              <Text style={styles.counterValue}>{Math.round(totalSeconds / 60)}</Text>
              <Text style={styles.counterLabel}>Total min</Text>
            </View>
          </View>

          {/* Up next */}
          <Text style={styles.upNext}>
            {phaseIndex + 1 < sequence.length
              ? `Up next · ${PHASE_TITLE[sequence[phaseIndex + 1].kind]} ${fmt(sequence[phaseIndex + 1].seconds)}s`
              : 'Last interval'}
          </Text>
        </View>
      ) : (
        <View style={styles.stage}>
          <View style={[styles.doneBadge, { borderColor: accent }]}>
            <Ionicons name="checkmark" size={48} color={accent} />
          </View>
          <Text style={styles.doneTitle}>Complete</Text>
          <Text style={styles.doneSub}>
            {preset.name} · {totalRounds} rounds · ~{Math.round(totalSeconds / 60)} min
          </Text>
          <TouchableOpacity
            style={[styles.logBtn, logged && styles.logBtnDone]}
            onPress={logSession}
            disabled={logged}
          >
            <Ionicons name={logged ? 'checkmark-circle' : 'add-circle'} size={20} color={logged ? colors.success : colors.background} />
            <Text style={[styles.logBtnText, logged && styles.logBtnTextDone]}>
              {logged ? 'Logged to cardio' : 'Log this session'}
            </Text>
          </TouchableOpacity>
        </View>
      )}

      {/* Controls */}
      <View style={styles.controls}>
        {!finished ? (
          <>
            <TouchableOpacity style={styles.ctrlSecondary} onPress={handleReset}>
              <Ionicons name="refresh" size={24} color={colors.textSecondary} />
            </TouchableOpacity>
            <TouchableOpacity style={[styles.ctrlPrimary, { backgroundColor: accent }]} onPress={handleStartPause}>
              <Ionicons name={running ? 'pause' : 'play'} size={38} color={colors.background} />
            </TouchableOpacity>
            <TouchableOpacity style={styles.ctrlSecondary} onPress={handleSkip}>
              <Ionicons name="play-skip-forward" size={24} color={colors.textSecondary} />
            </TouchableOpacity>
          </>
        ) : (
          <>
            <TouchableOpacity style={styles.ctrlSecondary} onPress={handleReset}>
              <Ionicons name="refresh" size={24} color={colors.textSecondary} />
            </TouchableOpacity>
            <TouchableOpacity style={[styles.ctrlPrimary, { backgroundColor: colors.surfaceLight }]} onPress={() => navigation.goBack()}>
              <Ionicons name="checkmark" size={38} color={colors.text} />
            </TouchableOpacity>
            <View style={styles.ctrlSecondary} />
          </>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background, paddingTop: 56, paddingBottom: 40 },
  center: { alignItems: 'center', justifyContent: 'center' },
  subtle: { color: colors.textSecondary, fontSize: fontSizes.md },
  topBar: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
  },
  titlePill: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.xs,
    maxWidth: '70%', backgroundColor: colors.surface, borderRadius: borderRadius.full,
    paddingHorizontal: spacing.md, paddingVertical: 6, borderWidth: 1, borderColor: colors.border,
  },
  titlePillText: { color: colors.text, fontSize: fontSizes.sm, fontWeight: '600' },
  stage: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: spacing.lg },
  phaseTitle: { fontSize: fontSizes.xl, fontWeight: '800', letterSpacing: 3 },
  countdown: { fontSize: 76, fontWeight: '800', fontVariant: ['tabular-nums'] },
  countdownUnit: { color: colors.textMuted, fontSize: fontSizes.sm, marginTop: -6 },
  countersRow: { flexDirection: 'row', gap: spacing.xl },
  counterBox: { alignItems: 'center' },
  counterValue: { color: colors.text, fontSize: fontSizes.xl, fontWeight: '700', fontVariant: ['tabular-nums'] },
  counterLabel: { color: colors.textMuted, fontSize: fontSizes.xs, textTransform: 'uppercase', letterSpacing: 0.5, marginTop: 2 },
  upNext: { color: colors.textSecondary, fontSize: fontSizes.sm },
  doneBadge: {
    width: 96, height: 96, borderRadius: 48, borderWidth: 3,
    alignItems: 'center', justifyContent: 'center',
  },
  doneTitle: { color: colors.text, fontSize: fontSizes.xxxl, fontWeight: '800' },
  doneSub: { color: colors.textSecondary, fontSize: fontSizes.md },
  logBtn: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
    backgroundColor: colors.accent, paddingHorizontal: spacing.xl, paddingVertical: spacing.md,
    borderRadius: borderRadius.full, marginTop: spacing.md,
  },
  logBtnDone: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.success },
  logBtnText: { color: colors.background, fontSize: fontSizes.md, fontWeight: '700' },
  logBtnTextDone: { color: colors.success },
  controls: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: spacing.xl,
    paddingHorizontal: spacing.lg,
  },
  ctrlPrimary: {
    width: 84, height: 84, borderRadius: 42, alignItems: 'center', justifyContent: 'center',
  },
  ctrlSecondary: {
    width: 56, height: 56, borderRadius: 28, alignItems: 'center', justifyContent: 'center',
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
  },
  secondaryBtn: {
    marginTop: spacing.lg, paddingHorizontal: spacing.xl, paddingVertical: spacing.md,
    backgroundColor: colors.surface, borderRadius: borderRadius.md,
  },
  secondaryBtnText: { color: colors.text, fontSize: fontSizes.md },
});
