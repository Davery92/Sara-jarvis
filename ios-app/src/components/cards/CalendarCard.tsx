import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface CalendarCardProps {
  card: any;
  onAction: (action: any) => void;
}

function formatEventTime(dateString: string): string {
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

export default function CalendarCard({ card }: CalendarCardProps) {
  const items = card.items || [];

  return (
    <View style={styles.container}>
      {card.title && (
        <Text style={styles.title}>{card.title}</Text>
      )}

      {items.length === 0 ? (
        <Text style={styles.emptyText}>No events</Text>
      ) : (
        items.map((event: any, index: number) => (
          <View key={event.id ?? index} style={styles.row}>
            <View style={styles.timeColumn}>
              <View style={styles.dot} />
              <Text style={styles.timeText}>
                {event.all_day ? 'All day' : formatEventTime(event.start_time)}
              </Text>
            </View>
            <View style={styles.infoColumn}>
              <Text style={styles.eventTitle} numberOfLines={1}>
                {event.title}
              </Text>
              {event.location ? (
                <Text style={styles.location} numberOfLines={1}>
                  {event.location}
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
  timeColumn: {
    flexDirection: 'row',
    alignItems: 'center',
    width: 100,
    marginRight: spacing.sm,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: '#14b8a6', // teal
    marginRight: spacing.sm,
  },
  timeText: {
    fontSize: fontSizes.xs,
    fontWeight: '600',
    color: colors.textSecondary,
  },
  infoColumn: {
    flex: 1,
  },
  eventTitle: {
    fontSize: fontSizes.sm,
    color: colors.text,
  },
  location: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    marginTop: 2,
  },
  summary: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    marginTop: spacing.sm,
  },
});
