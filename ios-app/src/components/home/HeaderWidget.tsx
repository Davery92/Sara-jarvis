import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { colors, spacing, fontSizes } from '../../styles/theme';
import BackgroundTasksIndicator from '../BackgroundTasksIndicator';

export default function HeaderWidget() {
  const [currentTime, setCurrentTime] = useState(new Date());

  useEffect(() => {
    const timer = setInterval(() => {
      setCurrentTime(new Date());
    }, 1000);

    return () => clearInterval(timer);
  }, []);

  const getGreeting = () => {
    const hour = currentTime.getHours();
    if (hour < 12) return 'Good morning';
    if (hour < 18) return 'Good afternoon';
    return 'Good evening';
  };

  const formatTime = () => {
    return currentTime.toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    });
  };

  const formatDate = () => {
    return currentTime.toLocaleDateString('en-US', {
      weekday: 'long',
      month: 'long',
      day: 'numeric',
    });
  };

  return (
    <View style={styles.container}>
      {/* Background Tasks Indicator in top-right */}
      <View style={styles.indicatorContainer}>
        <BackgroundTasksIndicator />
      </View>

      <Text style={styles.greeting}>{getGreeting()}</Text>
      <Text style={styles.time}>{formatTime()}</Text>
      <Text style={styles.date}>{formatDate()}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    padding: spacing.lg,
    alignItems: 'center',
    position: 'relative',
  },
  indicatorContainer: {
    position: 'absolute',
    top: spacing.md,
    right: spacing.md,
    zIndex: 10,
  },
  greeting: {
    fontSize: fontSizes.lg,
    color: colors.textSecondary,
    marginBottom: spacing.xs,
  },
  time: {
    fontSize: 48,
    fontWeight: '700',
    color: colors.text,
    marginBottom: spacing.xs,
  },
  date: {
    fontSize: fontSizes.md,
    color: colors.textMuted,
  },
});
