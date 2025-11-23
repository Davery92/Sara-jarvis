import React, { useState, useEffect } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, ActivityIndicator } from 'react-native';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import { calendarService, CalendarEvent } from '../../services/calendar';

export default function TodayEventsWidget() {
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchTodayEvents();
  }, []);

  const fetchTodayEvents = async () => {
    try {
      setLoading(true);
      const today = new Date().toISOString().split('T')[0];
      const data = await calendarService.getEvents(today, today);
      setEvents(data.slice(0, 3)); // Show max 3 events
    } catch (error) {
      console.error('Failed to fetch events:', error);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <View style={styles.container}>
        <View style={styles.header}>
          <Text style={styles.icon}>📅</Text>
          <Text style={styles.title}>Today's Events</Text>
        </View>
        <ActivityIndicator color={colors.primary} style={styles.loader} />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.icon}>📅</Text>
        <Text style={styles.title}>Today's Events</Text>
      </View>

      {events.length === 0 ? (
        <Text style={styles.emptyText}>No events today</Text>
      ) : (
        events.map((event) => (
          <TouchableOpacity key={event.id} style={styles.eventCard} activeOpacity={0.7}>
            <View style={styles.eventTime}>
              <Text style={styles.timeText}>
                {new Date(event.start_time).toLocaleTimeString('en-US', {
                  hour: 'numeric',
                  minute: '2-digit',
                })}
              </Text>
            </View>
            <View style={styles.eventInfo}>
              <Text style={styles.eventTitle} numberOfLines={1}>
                {event.title}
              </Text>
              {event.location && <Text style={styles.eventType}>{event.location}</Text>}
            </View>
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
  loader: {
    paddingVertical: spacing.lg,
  },
  emptyText: {
    color: colors.textMuted,
    textAlign: 'center',
    paddingVertical: spacing.lg,
  },
  eventCard: {
    flexDirection: 'row',
    padding: spacing.sm,
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
    marginBottom: spacing.sm,
  },
  eventTime: {
    marginRight: spacing.md,
    justifyContent: 'center',
  },
  timeText: {
    fontSize: fontSizes.sm,
    color: colors.primary,
    fontWeight: '600',
  },
  eventInfo: {
    flex: 1,
    justifyContent: 'center',
  },
  eventTitle: {
    fontSize: fontSizes.md,
    color: colors.text,
    marginBottom: 2,
  },
  eventType: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
  },
});
