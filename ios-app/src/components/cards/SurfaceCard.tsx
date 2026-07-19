import React, { useState, useEffect } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, ActivityIndicator, Linking } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import { apiClient } from '../../services/api';
import { surfacesService, SurfaceModel } from '../../services/surfaces';
import { useTimer } from '../../context/TimerContext';
import SimpleMarkdown from '../chat/SimpleMarkdown';

interface SurfaceCardProps {
  card: any;
  onAction: (action: any) => void;
}

/**
 * Renders an interactive surface (checklist / steps / buttons / file_list /
 * progress) inline in chat and posts interaction events to the backend.
 */
export default function SurfaceCard({ card }: SurfaceCardProps) {
  const [surface, setSurface] = useState<SurfaceModel | null>(card.surface || null);

  if (!surface) return null;
  const state = surface.state || {};

  const applyOptimistic = (mutate: (s: Record<string, any>) => void) => {
    setSurface((prev) => {
      if (!prev) return prev;
      const next = { ...prev, state: JSON.parse(JSON.stringify(prev.state || {})) };
      mutate(next.state);
      return next;
    });
  };

  const send = async (payload: any) => {
    if (!surface) return;
    try {
      const res = await surfacesService.postEvent(surface.id, payload);
      if (res?.state) setSurface((prev) => (prev ? { ...prev, state: res.state } : prev));
    } catch {
      // optimistic state already applied
    }
  };

  const renderComponent = (comp: any, idx: number) => {
    const node = state[comp.id] || {};
    switch (comp.type) {
      case 'markdown':
        return (
          <View key={idx} style={styles.block}>
            <SimpleMarkdown>{comp.text}</SimpleMarkdown>
          </View>
        );

      case 'checklist':
        return (
          <View key={idx} style={styles.block}>
            {comp.items.map((item: any) => {
              const checked = node.checked?.[item.id] ?? item.checked ?? false;
              return (
                <TouchableOpacity
                  key={item.id}
                  style={styles.row}
                  onPress={() => {
                    applyOptimistic((s) => {
                      s[comp.id] = s[comp.id] || {};
                      s[comp.id].checked = s[comp.id].checked || {};
                      s[comp.id].checked[item.id] = !checked;
                    });
                    send({ component_id: comp.id, event: 'check', value: { item_id: item.id, checked: !checked } });
                  }}
                >
                  <Ionicons
                    name={checked ? 'checkbox' : 'square-outline'}
                    size={22}
                    color={checked ? colors.primary : colors.textSecondary}
                  />
                  <Text style={[styles.rowLabel, checked && styles.done]}>{item.label}</Text>
                </TouchableOpacity>
              );
            })}
          </View>
        );

      case 'steps':
        return (
          <View key={idx} style={styles.block}>
            {comp.steps.map((step: any, i: number) => {
              const isDone = node.done?.[step.id] ?? step.done ?? false;
              return (
                <TouchableOpacity
                  key={step.id}
                  style={styles.row}
                  onPress={() => {
                    applyOptimistic((s) => {
                      s[comp.id] = s[comp.id] || {};
                      s[comp.id].done = s[comp.id].done || {};
                      s[comp.id].done[step.id] = !isDone;
                    });
                    send({ component_id: comp.id, event: 'step', value: { step_id: step.id, done: !isDone } });
                  }}
                >
                  <View style={[styles.stepDot, isDone && styles.stepDotDone]}>
                    <Text style={styles.stepDotText}>{isDone ? '✓' : i + 1}</Text>
                  </View>
                  <Text style={[styles.rowLabel, isDone && styles.done]}>{step.text}</Text>
                </TouchableOpacity>
              );
            })}
          </View>
        );

      case 'timer':
        return <TimerBlock key={idx} label={comp.label} durationSeconds={comp.duration_seconds} />;

      case 'buttons':
        return (
          <View key={idx} style={[styles.block, styles.buttonsRow]}>
            {comp.buttons.map((b: any) => (
              <TouchableOpacity
                key={b.id}
                style={[styles.button, b.style === 'primary' && styles.buttonPrimary, b.style === 'danger' && styles.buttonDanger]}
                onPress={() => send({ component_id: comp.id, event: 'click', value: { button_id: b.id } })}
              >
                <Text style={[styles.buttonText, (b.style === 'primary' || b.style === 'danger') && styles.buttonTextStrong]}>
                  {b.label}
                </Text>
              </TouchableOpacity>
            ))}
          </View>
        );

      case 'file_list':
        return (
          <View key={idx} style={styles.block}>
            {comp.files.map((f: any, i: number) => {
              const url = f.artifact_id
                ? `${apiClient.baseURL}/api/artifacts/${f.artifact_id}/download`
                : f.job_id
                ? `${apiClient.baseURL}/api/workspace/files/${f.job_id}/${encodeURIComponent(f.filename || f.name)}`
                : undefined;
              return (
                <TouchableOpacity
                  key={i}
                  style={styles.fileRow}
                  onPress={async () => {
                    if (!url) return;
                    const token = await apiClient.getToken();
                    Linking.openURL(token ? `${url}?token=${encodeURIComponent(token)}` : url);
                  }}
                >
                  <Ionicons name="document-outline" size={18} color={colors.textSecondary} />
                  <Text style={styles.rowLabel} numberOfLines={1}>{f.name}</Text>
                  <Ionicons name="download-outline" size={18} color={colors.primary} />
                </TouchableOpacity>
              );
            })}
          </View>
        );

      case 'progress': {
        const value = node.value ?? comp.value ?? 0;
        const max = comp.max ?? 100;
        const pct = Math.min(100, Math.max(0, (value / max) * 100));
        return (
          <View key={idx} style={styles.block}>
            {comp.label ? <Text style={styles.progressLabel}>{comp.label}</Text> : null}
            <View style={styles.progressTrack}>
              <View style={[styles.progressFill, { width: `${pct}%` }]} />
            </View>
          </View>
        );
      }

      default:
        return null;
    }
  };

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Ionicons name="apps" size={16} color={colors.primary} />
        <Text style={styles.title}>{surface.title}</Text>
      </View>
      {surface.spec.components.map((c: any, i: number) => renderComponent(c, i))}
    </View>
  );
}

function TimerBlock({ label, durationSeconds }: { label?: string; durationSeconds: number }) {
  // Route through the shared TimerContext so Start creates a real timer AND
  // drives the iOS Live Activity (lock screen / Dynamic Island countdown), the
  // same as the app's native timers — not just an in-card visual.
  const { activeTimer, startTimer, stopTimer } = useTimer();
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(Date.now());

  const title = label || 'Timer';
  const isThisActive = !!activeTimer && activeTimer.title === title;
  const endMs = isThisActive ? new Date(activeTimer!.end_time).getTime() : 0;

  // Tick the displayed countdown while this timer owns the active slot.
  useEffect(() => {
    if (!isThisActive) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [isThisActive]);

  const remaining = isThisActive
    ? Math.max(0, Math.round((endMs - now) / 1000))
    : durationSeconds;
  const done = isThisActive && remaining <= 0;
  const mm = String(Math.floor(remaining / 60)).padStart(2, '0');
  const ss = String(remaining % 60).padStart(2, '0');

  const onStart = async () => {
    setBusy(true);
    try {
      await startTimer(title, durationSeconds);
    } finally {
      setBusy(false);
    }
  };

  const onCancel = async () => {
    setBusy(true);
    try {
      await stopTimer();
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.timerRow}>
      <Ionicons name="timer-outline" size={18} color={done ? colors.primary : colors.textSecondary} />
      <Text style={styles.timerLabel} numberOfLines={1}>{title}</Text>
      <Text style={[styles.timerClock, done && { color: colors.primary }]}>{done ? 'Done' : `${mm}:${ss}`}</Text>
      <TouchableOpacity style={styles.timerBtn} disabled={busy} onPress={isThisActive ? onCancel : onStart}>
        {busy ? (
          <ActivityIndicator size="small" color="#fff" />
        ) : (
          <Ionicons name={isThisActive ? 'close' : 'play'} size={16} color="#fff" />
        )}
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { padding: spacing.md },
  header: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs, marginBottom: spacing.sm },
  title: { color: colors.text, fontSize: fontSizes.sm, fontWeight: '600' },
  block: { marginBottom: spacing.sm },
  row: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingVertical: 4 },
  rowLabel: { color: colors.text, fontSize: fontSizes.sm, flex: 1 },
  done: { color: colors.textSecondary, textDecorationLine: 'line-through' },
  stepDot: {
    width: 24, height: 24, borderRadius: 12, borderWidth: 1, borderColor: colors.border,
    alignItems: 'center', justifyContent: 'center',
  },
  stepDotDone: { backgroundColor: colors.primary, borderColor: colors.primary },
  stepDotText: { color: colors.text, fontSize: fontSizes.xs },
  buttonsRow: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  button: {
    paddingHorizontal: spacing.md, paddingVertical: spacing.xs,
    borderRadius: borderRadius.md, borderWidth: 1, borderColor: colors.border,
  },
  buttonPrimary: { backgroundColor: colors.primary, borderColor: colors.primary },
  buttonDanger: { backgroundColor: '#dc2626', borderColor: '#dc2626' },
  buttonText: { color: colors.text, fontSize: fontSizes.sm },
  buttonTextStrong: { color: '#fff', fontWeight: '600' },
  fileRow: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
    paddingVertical: spacing.xs, paddingHorizontal: spacing.sm,
    borderRadius: borderRadius.md, borderWidth: 1, borderColor: colors.border, marginBottom: 4,
  },
  progressLabel: { color: colors.textSecondary, fontSize: fontSizes.xs, marginBottom: 4 },
  progressTrack: { height: 8, borderRadius: 4, backgroundColor: colors.border, overflow: 'hidden' },
  progressFill: { height: '100%', backgroundColor: colors.primary },
  timerRow: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.sm, marginBottom: spacing.sm,
    paddingVertical: spacing.xs, paddingHorizontal: spacing.sm,
    borderRadius: borderRadius.md, borderWidth: 1, borderColor: colors.border,
    backgroundColor: 'rgba(20, 184, 166, 0.06)',
  },
  timerLabel: { color: colors.text, fontSize: fontSizes.sm, flex: 1 },
  timerClock: { color: colors.text, fontSize: fontSizes.md, fontVariant: ['tabular-nums'], fontWeight: '600' },
  timerBtn: {
    width: 30, height: 30, borderRadius: 15, backgroundColor: colors.primary,
    alignItems: 'center', justifyContent: 'center',
  },
});
