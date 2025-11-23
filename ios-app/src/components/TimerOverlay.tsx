import React, { useState, useEffect, useRef } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  Animated,
  PanResponder,
} from 'react-native';
import { Timer } from '../services/timer';
import { showTimerCompleteAlert } from '../utils/notifications';
import { colors, spacing, borderRadius, fontSizes } from '../styles/theme';

interface TimerOverlayProps {
  timer: Timer;
  onStop: () => void;
  onPress?: () => void;
}

export default function TimerOverlay({ timer, onStop, onPress }: TimerOverlayProps) {
  const [remainingSeconds, setRemainingSeconds] = useState(0);
  const [position] = useState(new Animated.ValueXY({ x: 0, y: 0 }));
  const hasAlteredRef = useRef(false);

  useEffect(() => {
    const calculateRemaining = () => {
      const now = new Date().getTime();
      const endTime = new Date(timer.end_time).getTime();
      const remaining = Math.max(0, Math.floor((endTime - now) / 1000));
      setRemainingSeconds(remaining);

      // Show alert when timer completes (only once)
      if (remaining === 0 && !hasAlteredRef.current) {
        hasAlteredRef.current = true;
        showTimerCompleteAlert(timer.title);
        onStop(); // Auto-stop the timer
      }
    };

    calculateRemaining();
    const interval = setInterval(calculateRemaining, 1000);

    return () => clearInterval(interval);
  }, [timer.end_time, timer.title, onStop]);

  const panResponder = PanResponder.create({
    onStartShouldSetPanResponder: () => true,
    onMoveShouldSetPanResponder: () => true,
    onPanResponderGrant: () => {
      position.setOffset({
        x: (position.x as any)._value,
        y: (position.y as any)._value,
      });
      position.setValue({ x: 0, y: 0 });
    },
    onPanResponderMove: Animated.event(
      [null, { dx: position.x, dy: position.y }],
      { useNativeDriver: false }
    ),
    onPanResponderRelease: () => {
      position.flattenOffset();
    },
  });

  const formatTime = (seconds: number) => {
    const hrs = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;

    if (hrs > 0) {
      return `${hrs}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    }
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <Animated.View
      style={[
        styles.container,
        {
          transform: position.getTranslateTransform(),
        },
      ]}
      {...panResponder.panHandlers}
    >
      <TouchableOpacity
        style={styles.bubble}
        onPress={onPress}
        activeOpacity={0.8}
      >
        <View style={styles.content}>
          <Text style={styles.title} numberOfLines={1}>
            {timer.title}
          </Text>
          <Text style={styles.time}>{formatTime(remainingSeconds)}</Text>
        </View>
        <TouchableOpacity
          style={styles.stopButton}
          onPress={(e) => {
            e.stopPropagation();
            onStop();
          }}
        >
          <Text style={styles.stopText}>✕</Text>
        </TouchableOpacity>
      </TouchableOpacity>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: {
    position: 'absolute',
    top: 100,
    right: 20,
    zIndex: 9999,
  },
  bubble: {
    backgroundColor: colors.primary,
    borderRadius: borderRadius.xl,
    padding: spacing.md,
    flexDirection: 'row',
    alignItems: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
    elevation: 8,
    minWidth: 140,
  },
  content: {
    flex: 1,
    marginRight: spacing.sm,
  },
  title: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
    marginBottom: 2,
  },
  time: {
    color: colors.text,
    fontSize: fontSizes.xl,
    fontWeight: '700',
    fontVariant: ['tabular-nums'],
  },
  stopButton: {
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: 'rgba(255, 255, 255, 0.2)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  stopText: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '700',
  },
});
