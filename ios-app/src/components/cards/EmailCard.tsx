import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface EmailCardProps {
  card: any;
  onAction: (action: any) => void;
}

function formatTimestamp(dateString: string): string {
  try {
    const date = new Date(dateString);
    const now = new Date();
    const isToday =
      date.getFullYear() === now.getFullYear() &&
      date.getMonth() === now.getMonth() &&
      date.getDate() === now.getDate();

    if (isToday) {
      return date.toLocaleTimeString('en-US', {
        hour: 'numeric',
        minute: '2-digit',
      });
    }
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
    });
  } catch {
    return dateString;
  }
}

export default function EmailCard({ card }: EmailCardProps) {
  const items = card.items || [];

  return (
    <View style={styles.container}>
      {card.title && (
        <Text style={styles.title}>{card.title}</Text>
      )}

      {items.length === 0 ? (
        <Text style={styles.emptyText}>No emails</Text>
      ) : (
        items.map((email: any, index: number) => {
          const isUnread = !email.is_read;
          return (
            <View
              key={email.id ?? index}
              style={[styles.row, isUnread && styles.rowUnread]}
            >
              <View style={styles.emailContent}>
                <View style={styles.headerRow}>
                  <Text
                    style={[styles.sender, isUnread && styles.unreadText]}
                    numberOfLines={1}
                  >
                    {email.sender}
                  </Text>
                  {email.timestamp ? (
                    <Text style={styles.timestamp}>
                      {formatTimestamp(email.timestamp)}
                    </Text>
                  ) : null}
                </View>
                <Text
                  style={[styles.subject, isUnread && styles.unreadText]}
                  numberOfLines={1}
                >
                  {email.subject}
                </Text>
                {email.snippet ? (
                  <Text style={styles.snippet} numberOfLines={1}>
                    {email.snippet}
                  </Text>
                ) : null}
              </View>
              {isUnread && <View style={styles.unreadDot} />}
            </View>
          );
        })
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
    opacity: 0.7,
  },
  rowUnread: {
    opacity: 1,
  },
  emailContent: {
    flex: 1,
  },
  headerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 2,
  },
  sender: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
    flex: 1,
    marginRight: spacing.sm,
  },
  unreadText: {
    color: colors.text,
    fontWeight: '600',
  },
  timestamp: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
  },
  subject: {
    fontSize: fontSizes.sm,
    color: colors.textSecondary,
    marginBottom: 2,
  },
  snippet: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    lineHeight: 16,
  },
  unreadDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.primary,
    marginLeft: spacing.sm,
  },
  summary: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    marginTop: spacing.sm,
  },
});
