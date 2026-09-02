/**
 * FloatingTaskPill
 *
 * The answer to "nothing on iOS showed a task was running". Mounted in
 * AuthenticatedOverlays, so it floats above every screen: the moment Sara
 * dispatches anything — research plan, agent task, code mode — a pill slides
 * down and stays until the work ends. Tapping it opens the full task sheet.
 *
 * Failures are as loud as activity: a task that failed in the last hour turns
 * the pill red and keeps it on screen until acknowledged, because silence after
 * a dead research plan is exactly what burned us on 2026-09-01.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  Animated,
  Easing,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { BackgroundTask } from '../types/api';
import { backgroundTaskService, recentFailure } from '../services/backgroundTasks';
import { colors, spacing, borderRadius, fontSizes } from '../styles/theme';
import TaskActivitySheet from './TaskActivitySheet';

const ACTIVE_STATUSES = ['pending', 'running', 'needs_clarification'];

interface FloatingTaskPillProps {
  onNavigateToNote?: (noteId: string) => void;
}

export default function FloatingTaskPill({ onNavigateToNote }: FloatingTaskPillProps) {
  const insets = useSafeAreaInsets();
  const [tasks, setTasks] = useState<BackgroundTask[]>([]);
  const [sheetOpen, setSheetOpen] = useState(false);
  // A failure the user has already looked at stops shouting; a *new* failure
  // (different task id) starts shouting again.
  const [ackedFailureId, setAckedFailureId] = useState<string | null>(null);
  // hasPendingDispatch() is time-based, so re-render on the service's ticks
  // rather than trusting a value captured at subscribe time.
  const [, forceTick] = useState(0);

  const slide = useRef(new Animated.Value(0)).current;
  const spinValue = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    const unsubscribe = backgroundTaskService.subscribe((next) => {
      setTasks(next);
      forceTick(n => n + 1);
    });
    return () => unsubscribe();
  }, []);

  const activeTasks = useMemo(
    () => tasks.filter(t => ACTIVE_STATUSES.includes(t.status)),
    [tasks],
  );
  const failure = useMemo(() => recentFailure(tasks), [tasks]);
  const optimisticLabel = backgroundTaskService.getPendingDispatchLabel();

  const showFailure = !!failure && failure.id !== ackedFailureId && activeTasks.length === 0;
  const visible = activeTasks.length > 0 || !!optimisticLabel || showFailure;

  // Slide/fade in and out.
  useEffect(() => {
    Animated.timing(slide, {
      toValue: visible ? 1 : 0,
      duration: 260,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: true,
    }).start();
  }, [visible, slide]);

  // Spinner only while something is genuinely in flight.
  useEffect(() => {
    if (activeTasks.length > 0 || optimisticLabel) {
      spinValue.setValue(0);
      const spin = Animated.loop(
        Animated.timing(spinValue, {
          toValue: 1,
          duration: 1600,
          easing: Easing.linear,
          useNativeDriver: true,
        })
      );
      spin.start();
      return () => spin.stop();
    }
    spinValue.setValue(0);
    return undefined;
  }, [activeTasks.length, optimisticLabel, spinValue]);

  const openSheet = useCallback(() => {
    if (failure) setAckedFailureId(failure.id);
    setSheetOpen(true);
  }, [failure]);

  const spin = spinValue.interpolate({
    inputRange: [0, 1],
    outputRange: ['0deg', '360deg'],
  });

  // What the pill says. Priority: failure > live step label > generic.
  let label: string;
  if (showFailure) {
    label = `${failure!.task_type === 'research_plan' ? 'Research' : 'Task'} failed — tap for details`;
  } else if (activeTasks.length > 0) {
    const lead = activeTasks[0];
    label = lead.status_label || lead.original_query || 'Working…';
  } else {
    label = optimisticLabel || 'Working…';
  }

  const accent = showFailure ? colors.error : colors.primary;

  return (
    <>
      {visible && (
        <Animated.View
          pointerEvents="box-none"
          style={[
            styles.wrapper,
            { top: insets.top + spacing.xs },
            {
              opacity: slide,
              transform: [{
                translateY: slide.interpolate({ inputRange: [0, 1], outputRange: [-24, 0] }),
              }],
            },
          ]}
        >
          <TouchableOpacity
            activeOpacity={0.85}
            onPress={openSheet}
            style={[styles.pill, { borderColor: accent }]}
          >
            {showFailure ? (
              <Text style={[styles.glyph, { color: accent }]}>⚠️</Text>
            ) : (
              <Animated.Text style={[styles.glyph, { transform: [{ rotate: spin }] }]}>
                🔄
              </Animated.Text>
            )}
            <Text style={styles.label} numberOfLines={1}>
              {label}
            </Text>
            {activeTasks.length > 1 && (
              <View style={[styles.badge, { backgroundColor: accent }]}>
                <Text style={styles.badgeText}>{activeTasks.length}</Text>
              </View>
            )}
          </TouchableOpacity>
        </Animated.View>
      )}

      <TaskActivitySheet
        visible={sheetOpen}
        tasks={tasks}
        onClose={() => setSheetOpen(false)}
        onNavigateToNote={onNavigateToNote}
      />
    </>
  );
}

const styles = StyleSheet.create({
  wrapper: {
    position: 'absolute',
    left: spacing.md,
    right: spacing.md,
    alignItems: 'center',
    // Above the timer overlay (9999 at top:100) is unnecessary — this sits
    // higher on screen — but it must clear ordinary screen chrome.
    zIndex: 1000,
  },
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    maxWidth: '100%',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.full,
    borderWidth: 1,
    backgroundColor: colors.surface,
    shadowColor: '#000',
    shadowOpacity: 0.35,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 6,
  },
  glyph: {
    fontSize: 14,
    marginRight: spacing.sm,
  },
  label: {
    flexShrink: 1,
    color: colors.text,
    fontSize: fontSizes.sm,
  },
  badge: {
    marginLeft: spacing.sm,
    minWidth: 20,
    height: 20,
    borderRadius: 10,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 5,
  },
  badgeText: {
    color: colors.text,
    fontSize: 11,
    fontWeight: 'bold',
  },
});
