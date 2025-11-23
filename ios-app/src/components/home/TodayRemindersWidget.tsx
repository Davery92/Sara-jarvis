import React, { useState, useEffect } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, ActivityIndicator } from 'react-native';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import { calendarService, Reminder } from '../../services/calendar';

export default function TodayRemindersWidget() {
  const [reminders, setReminders] = useState<Reminder[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchReminders();
  }, []);

  const fetchReminders = async () => {
    try {
      setLoading(true);
      const data = await calendarService.getReminders();
      // Filter for today or overdue
      const today = new Date();
      today.setHours(0, 0, 0, 0);
      const filtered = data.filter((r) => {
        if (r.is_completed) return false;
        const dueDate = new Date(r.reminder_time);
        dueDate.setHours(0, 0, 0, 0);
        return dueDate <= today;
      });
      setReminders(filtered.slice(0, 3));
    } catch (error) {
      console.error('Failed to fetch reminders:', error);
    } finally {
      setLoading(false);
    }
  };

  const toggleReminder = async (id: string) => {
    // TODO: Implement toggle completion
    console.log('Toggle reminder:', id);
  };

  if (loading) {
    return (
      <View style={styles.container}>
        <View style={styles.header}>
          <Text style={styles.icon}>🔔</Text>
          <Text style={styles.title}>Today's Reminders</Text>
        </View>
        <ActivityIndicator color={colors.primary} style={styles.loader} />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.icon}>🔔</Text>
        <Text style={styles.title}>Today's Reminders</Text>
      </View>

      {reminders.length === 0 ? (
        <Text style={styles.emptyText}>All caught up!</Text>
      ) : (
        reminders.map((reminder) => (
          <TouchableOpacity
            key={reminder.id}
            style={styles.reminderCard}
            onPress={() => toggleReminder(reminder.id)}
            activeOpacity={0.7}
          >
            <Text style={styles.checkbox}>
              {reminder.is_completed ? '✅' : '⬜'}
            </Text>
            <Text style={[styles.reminderText, reminder.is_completed && styles.completedText]}>
              {reminder.title}
            </Text>
          </TouchableOpacity>
        ))
      )}
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
  checkbox: {
    fontSize: 20,
    marginRight: spacing.md,
  },
  loader: {
    paddingVertical: spacing.lg,
  },
  emptyText: {
    color: colors.textMuted,
    textAlign: 'center',
    paddingVertical: spacing.lg,
  },
  reminderCard: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: spacing.md,
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
    marginBottom: spacing.sm,
  },
  reminderText: {
    fontSize: fontSizes.md,
    color: colors.text,
    marginLeft: spacing.md,
    flex: 1,
  },
  completedText: {
    textDecorationLine: 'line-through',
    color: colors.textMuted,
  },
});
