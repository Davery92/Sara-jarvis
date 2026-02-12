import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface ReminderCardProps {
  card: any;
  onAction: (action: any) => void;
}

function formatDueTime(dateString: string): string {
  try {
    const date = new Date(dateString);
    return date.toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
    });
  } catch {
    return dateString;
  }
}

export default function ReminderCard({ card }: ReminderCardProps) {
  const items = card.items || [];

  return (
    <View style={styles.container}>
      {card.title && (
        <Text style={styles.title}>{card.title}</Text>
      )}

      {items.length === 0 ? (
        <Text style={styles.emptyText}>No reminders</Text>
      ) : (
        items.map((reminder: any, index: number) => (
          <View key={reminder.id ?? index} style={styles.row}>
            <View style={[styles.checkCircle, reminder.completed && styles.checkCircleCompleted]}>
              {reminder.completed && (
                <Text style={styles.checkmark}>✓</Text>
              )}
            </View>
            <View style={styles.infoColumn}>
              <Text
                style={[styles.reminderTitle, reminder.completed && styles.completedText]}
                numberOfLines={1}
              >
                {reminder.title}
              </Text>
              {reminder.due_at ? (
                <Text style={styles.dueTime}>
                  {formatDueTime(reminder.due_at)}
                </Text>
              ) : null}
            </View>
          </View>
        ))
      )}

      {card.summary ? (
        <Text style={styles.summary}>{card.summary}</Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    padding: spacing.md,
  },
  title: {
    fontSize: fontSizes.md,
    fontWeight: '600',
    color: colors.text,
    marginBottom: spacing.sm,
  },
  emptyText: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    textAlign: 'center',
    paddingVertical: spacing.md,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  checkCircle: {
    width: 22,
    height: 22,
    borderRadius: 11,
    borderWidth: 2,
    borderColor: colors.textMuted,
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: spacing.sm,
  },
  checkCircleCompleted: {
    borderColor: colors.success,
    backgroundColor: colors.success,
  },
  checkmark: {
    fontSize: 12,
    color: colors.text,
    fontWeight: '700',
  },
  infoColumn: {
    flex: 1,
  },
  reminderTitle: {
    fontSize: fontSizes.sm,
    color: colors.text,
  },
  completedText: {
    color: colors.textMuted,
    textDecorationLine: 'line-through',
  },
  dueTime: {
    fontSize: fontSizes.xs,
    color: colors.textSecondary,
    marginTop: 2,
  },
  summary: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    marginTop: spacing.sm,
  },
});
