import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { Reminder } from '../../services/calendar';
import { calendarService } from '../../services/calendar';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface ReminderListItemProps {
  reminder: Reminder;
  onPress: (reminder: Reminder) => void;
  onLongPress?: (reminder: Reminder) => void;
  onToggleComplete?: (reminder: Reminder) => void;
}

export default function ReminderListItem({
  reminder,
  onPress,
  onLongPress,
  onToggleComplete,
}: ReminderListItemProps) {
  const dueDate = calendarService.formatDateTime(reminder.reminder_time);
  const isOverdue = !reminder.is_completed && calendarService.isOverdue(reminder.reminder_time);

  return (
    <TouchableOpacity
      style={[
        styles.container,
        reminder.is_completed && styles.completedContainer,
        isOverdue && styles.overdueContainer,
      ]}
      onPress={() => onPress(reminder)}
      onLongPress={() => onLongPress?.(reminder)}
      activeOpacity={0.7}
    >
      {/* Checkbox */}
      <TouchableOpacity
        style={styles.checkbox}
        onPress={() => onToggleComplete?.(reminder)}
      >
        <View
          style={[
            styles.checkboxBox,
            reminder.is_completed && styles.checkboxBoxChecked,
          ]}
        >
          {reminder.is_completed && (
            <Text style={styles.checkboxCheck}>✓</Text>
          )}
        </View>
      </TouchableOpacity>

      {/* Reminder Info */}
      <View style={styles.content}>
        <View style={styles.header}>
          <Text
            style={[
              styles.title,
              reminder.is_completed && styles.titleCompleted,
            ]}
            numberOfLines={1}
          >
            {reminder.title}
          </Text>
        </View>

        <Text
          style={[
            styles.dueDate,
            isOverdue && styles.overdueDueDate,
            reminder.is_completed && styles.completedDueDate,
          ]}
        >
          {isOverdue && !reminder.is_completed ? '⚠️ Overdue: ' : '📅 '}
          {dueDate}
        </Text>

        {reminder.description && (
          <Text
            style={[
              styles.description,
              reminder.is_completed && styles.descriptionCompleted,
            ]}
            numberOfLines={2}
          >
            {reminder.description}
          </Text>
        )}
      </View>

      {/* Chevron */}
      <View style={styles.chevron}>
        <Text style={styles.chevronText}>›</Text>
      </View>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    marginHorizontal: spacing.md,
    marginBottom: spacing.sm,
  },
  completedContainer: {
    opacity: 0.6,
  },
  overdueContainer: {
    borderLeftWidth: 4,
    borderLeftColor: colors.error,
  },
  checkbox: {
    marginRight: spacing.md,
  },
  checkboxBox: {
    width: 24,
    height: 24,
    borderRadius: borderRadius.sm,
    borderWidth: 2,
    borderColor: colors.textMuted,
    justifyContent: 'center',
    alignItems: 'center',
  },
  checkboxBoxChecked: {
    backgroundColor: colors.success,
    borderColor: colors.success,
  },
  checkboxCheck: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '700',
  },
  content: {
    flex: 1,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: spacing.xs,
  },
  priorityEmoji: {
    fontSize: fontSizes.md,
    marginRight: spacing.xs,
  },
  title: {
    flex: 1,
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
  },
  titleCompleted: {
    textDecorationLine: 'line-through',
    color: colors.textMuted,
  },
  dueDate: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    marginBottom: spacing.xs,
  },
  overdueDueDate: {
    color: colors.error,
    fontWeight: '600',
  },
  completedDueDate: {
    color: colors.textMuted,
  },
  description: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: fontSizes.sm * 1.4,
    marginBottom: spacing.xs,
  },
  descriptionCompleted: {
    color: colors.textMuted,
  },
  priorityBadge: {
    alignSelf: 'flex-start',
  },
  priorityText: {
    fontSize: fontSizes.xs,
    fontWeight: '700',
  },
  chevron: {
    marginLeft: spacing.sm,
  },
  chevronText: {
    color: colors.textMuted,
    fontSize: fontSizes.xl,
  },
});
