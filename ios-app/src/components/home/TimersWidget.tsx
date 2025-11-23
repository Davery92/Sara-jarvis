import React, { useState, useEffect } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, ActivityIndicator } from 'react-native';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import { useTimer } from '../../context/TimerContext';

export default function TimersWidget() {
  const { activeTimer, stopTimer } = useTimer();
  const [timeRemaining, setTimeRemaining] = useState<string>('');

  useEffect(() => {
    if (!activeTimer) return;

    const updateTimer = () => {
      const endTime = new Date(activeTimer.end_time).getTime();
      const now = new Date().getTime();
      const remaining = Math.max(0, Math.floor((endTime - now) / 1000));

      if (remaining <= 0) {
        setTimeRemaining('Complete!');
      } else {
        const hours = Math.floor(remaining / 3600);
        const minutes = Math.floor((remaining % 3600) / 60);
        const seconds = remaining % 60;

        if (hours > 0) {
          setTimeRemaining(`${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`);
        } else {
          setTimeRemaining(`${minutes}:${String(seconds).padStart(2, '0')}`);
        }
      }
    };

    updateTimer();
    const interval = setInterval(updateTimer, 1000);
    return () => clearInterval(interval);
  }, [activeTimer]);

  if (!activeTimer) {
    return (
      <View style={styles.container}>
        <View style={styles.header}>
          <Text style={styles.icon}>⏱️</Text>
          <Text style={styles.title}>Active Timers</Text>
        </View>
        <Text style={styles.emptyText}>No active timers</Text>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.icon}>⏱️</Text>
        <Text style={styles.title}>Active Timers</Text>
      </View>

      <View style={styles.timerCard}>
        <View style={styles.timerInfo}>
          <Text style={styles.timerTitle}>{activeTimer.title}</Text>
          <Text style={styles.timerTime}>{timeRemaining}</Text>
        </View>
        <TouchableOpacity
          style={styles.stopButton}
          onPress={stopTimer}
          activeOpacity={0.7}
        >
          <Text style={styles.stopIcon}>⏹️</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    margin: spacing.md,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  icon: {
    fontSize: 20,
    marginRight: spacing.xs,
  },
  title: {
    fontSize: fontSizes.lg,
    fontWeight: '600',
    color: colors.text,
    marginLeft: spacing.xs,
  },
  stopIcon: {
    fontSize: 20,
  },
  emptyText: {
    color: colors.textMuted,
    textAlign: 'center',
    paddingVertical: spacing.lg,
  },
  timerCard: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: spacing.md,
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
  },
  timerInfo: {
    flex: 1,
  },
  timerTitle: {
    fontSize: fontSizes.md,
    color: colors.text,
    marginBottom: spacing.xs,
  },
  timerTime: {
    fontSize: fontSizes.xl,
    fontWeight: '700',
    color: colors.warning,
  },
  stopButton: {
    padding: spacing.sm,
  },
});
