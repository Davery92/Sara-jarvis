import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { CalendarEvent } from '../../services/calendar';
import { calendarService } from '../../services/calendar';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface EventListItemProps {
  event: CalendarEvent;
  onPress: (event: CalendarEvent) => void;
  onLongPress?: (event: CalendarEvent) => void;
}

export default function EventListItem({ event, onPress, onLongPress }: EventListItemProps) {
  const startDate = calendarService.formatDate(event.start_time);
  const startTime = calendarService.formatTime(event.start_time);
  const endTime = calendarService.formatTime(event.end_time);
  const isToday = calendarService.isToday(event.start_time);
  const isUpcoming = calendarService.isUpcoming(event.start_time);

  return (
    <TouchableOpacity
      style={[
        styles.container,
        isToday && styles.todayContainer,
        isUpcoming && styles.upcomingContainer,
      ]}
      onPress={() => onPress(event)}
      onLongPress={() => onLongPress?.(event)}
      activeOpacity={0.7}
    >
      {/* Date Badge */}
      <View style={[styles.dateBadge, isToday && styles.dateBadgeToday]}>
        <Text style={[styles.dateDay, isToday && styles.dateDayToday]}>
          {new Date(event.start_time).getDate()}
        </Text>
        <Text style={[styles.dateMonth, isToday && styles.dateMonthToday]}>
          {new Date(event.start_time).toLocaleDateString('en-US', { month: 'short' })}
        </Text>
      </View>

      {/* Event Info */}
      <View style={styles.content}>
        <View style={styles.header}>
          <Text style={styles.title} numberOfLines={1}>
            {event.title}
          </Text>
          {event.source === 'ios_calendar' && (
            <View style={styles.iosBadge}>
              <Text style={styles.iosBadgeText}>iOS</Text>
            </View>
          )}
          {event.all_day && (
            <View style={styles.allDayBadge}>
              <Text style={styles.allDayText}>All Day</Text>
            </View>
          )}
        </View>

        {!event.all_day && (
          <Text style={styles.time}>
            {startTime} - {endTime}
          </Text>
        )}

        {event.location && (
          <View style={styles.locationRow}>
            <Text style={styles.locationIcon}>📍</Text>
            <Text style={styles.locationText} numberOfLines={1}>
              {event.location}
            </Text>
          </View>
        )}

        {event.description && (
          <Text style={styles.description} numberOfLines={2}>
            {event.description}
          </Text>
        )}

        {event.reminder_minutes && (
          <View style={styles.reminderBadge}>
            <Text style={styles.reminderText}>
              🔔 {event.reminder_minutes} min before
            </Text>
          </View>
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
  todayContainer: {
    borderLeftWidth: 4,
    borderLeftColor: colors.primary,
  },
  upcomingContainer: {
    borderLeftWidth: 2,
    borderLeftColor: colors.success,
  },
  dateBadge: {
    width: 50,
    height: 50,
    backgroundColor: colors.background,
    borderRadius: borderRadius.sm,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: spacing.md,
  },
  dateBadgeToday: {
    backgroundColor: colors.primary,
  },
  dateDay: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '700',
  },
  dateDayToday: {
    color: colors.text,
  },
  dateMonth: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    textTransform: 'uppercase',
  },
  dateMonthToday: {
    color: colors.text,
  },
  content: {
    flex: 1,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: spacing.xs,
  },
  title: {
    flex: 1,
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
  },
  allDayBadge: {
    backgroundColor: colors.primary,
    borderRadius: borderRadius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    marginLeft: spacing.sm,
  },
  allDayText: {
    color: colors.text,
    fontSize: fontSizes.xs,
    fontWeight: '600',
  },
  iosBadge: {
    backgroundColor: '#555',
    borderRadius: borderRadius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    marginLeft: spacing.sm,
  },
  iosBadgeText: {
    color: colors.text,
    fontSize: fontSizes.xs,
    fontWeight: '600',
  },
  time: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    marginBottom: spacing.xs,
  },
  locationRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: spacing.xs,
  },
  locationIcon: {
    fontSize: fontSizes.sm,
    marginRight: spacing.xs,
  },
  locationText: {
    flex: 1,
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
  },
  description: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: fontSizes.sm * 1.4,
    marginBottom: spacing.xs,
  },
  reminderBadge: {
    alignSelf: 'flex-start',
    backgroundColor: colors.background,
    borderRadius: borderRadius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
  },
  reminderText: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
  },
  chevron: {
    marginLeft: spacing.sm,
  },
  chevronText: {
    color: colors.textMuted,
    fontSize: fontSizes.xl,
  },
});
