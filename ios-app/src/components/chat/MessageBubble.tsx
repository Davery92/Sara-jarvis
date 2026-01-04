import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Message } from '../../types/api';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import SimpleMarkdown from './SimpleMarkdown';
import StarRating from './StarRating';

interface MessageBubbleProps {
  message: Message;
}

export default function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === 'user';
  const isAssistant = message.role === 'assistant';
  const canRate = isAssistant && message.episode_id && message.content.length > 50;

  return (
    <View style={[styles.container, isUser && styles.userContainer]}>
      <View
        style={[
          styles.bubble,
          isUser && styles.userBubble,
          isAssistant && styles.assistantBubble,
        ]}
      >
        {/* Message content */}
        {isAssistant ? (
          <SimpleMarkdown style={styles.text}>{message.content}</SimpleMarkdown>
        ) : (
          <Text style={[styles.text, isUser && styles.userText]}>
            {message.content}
          </Text>
        )}

        {/* Star rating for assistant messages */}
        {canRate && (
          <StarRating episodeId={message.episode_id!} size={16} />
        )}

        {/* Timestamp */}
        <Text style={[styles.timestamp, isUser && styles.userTimestamp]}>
          {formatTimestamp(message.created_at)}
        </Text>
      </View>
    </View>
  );
}

function formatTimestamp(timestamp: string): string {
  const date = new Date(timestamp);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;

  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;

  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

const styles = StyleSheet.create({
  container: {
    marginBottom: spacing.md,
    paddingHorizontal: spacing.md,
  },
  userContainer: {
    alignItems: 'flex-end',
  },
  bubble: {
    maxWidth: '80%',
    borderRadius: borderRadius.lg,
    padding: spacing.md,
  },
  userBubble: {
    backgroundColor: colors.primary,
  },
  assistantBubble: {
    backgroundColor: colors.surface,
  },
  text: {
    color: colors.text,
    fontSize: fontSizes.md,
    lineHeight: fontSizes.md * 1.5,
  },
  userText: {
    color: colors.text,
  },
  timestamp: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginTop: spacing.xs,
  },
  userTimestamp: {
    color: 'rgba(255, 255, 255, 0.7)',
  },
});
