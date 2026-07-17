import React, { useState } from 'react';
import { View, Text, StyleSheet, Pressable, Animated, Image } from 'react-native';
import * as Clipboard from 'expo-clipboard';
import * as Haptics from 'expo-haptics';
import { Message } from '../../types/api';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import SimpleMarkdown from './SimpleMarkdown';
import StarRating from './StarRating';
import ContentCard from '../cards/ContentCard';

interface MessageBubbleProps {
  message: Message;
  onCardAction?: (action: any) => void;
}

export default function MessageBubble({ message, onCardAction }: MessageBubbleProps) {
  const isUser = message.role === 'user';
  const isAssistant = message.role === 'assistant';
  const isSystem = message.role === 'system';
  const contentLength = typeof message.content === 'string' ? message.content.length : 100;
  const canRate = isAssistant && message.episode_id && contentLength > 50;
  const [showCopied, setShowCopied] = useState(false);

  const getTextContent = (): string => {
    if (typeof message.content === 'string') return message.content;
    if (Array.isArray(message.content)) {
      return (message.content as any[])
        .filter((p: any) => p.type === 'text')
        .map((p: any) => p.text)
        .join('\n');
    }
    return '';
  };

  const handleLongPress = async () => {
    try {
      await Clipboard.setStringAsync(getTextContent());
      await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      setShowCopied(true);
      setTimeout(() => setShowCopied(false), 1500);
    } catch (error) {
      console.error('Failed to copy:', error);
    }
  };

  // System messages (ambient observations) render differently
  if (isSystem) {
    return (
      <View style={styles.systemContainer}>
        <View style={styles.systemDivider}>
          <View style={styles.systemLine} />
          <Text style={styles.systemIcon}>{'✦'}</Text>
          <View style={styles.systemLine} />
        </View>
        <Text style={styles.systemText}>{message.content}</Text>
        {message.created_at && (
          <Text style={styles.systemTimestamp}>{formatTimestamp(message.created_at)}</Text>
        )}
      </View>
    );
  }

  return (
    <View style={[styles.container, isUser && styles.userContainer]}>
      <Pressable
        onLongPress={handleLongPress}
        delayLongPress={300}
        style={({ pressed }) => [
          styles.bubble,
          isUser && styles.userBubble,
          isAssistant && styles.assistantBubble,
          pressed && styles.bubblePressed,
        ]}
      >
        {/* Copied indicator */}
        {showCopied && (
          <View style={styles.copiedBadge}>
            <Text style={styles.copiedText}>Copied!</Text>
          </View>
        )}

        {/* Message content — handle multimodal array format */}
        {Array.isArray(message.content) ? (
          <View>
            {(message.content as any[]).map((part: any, idx: number) => {
              if (part.type === 'image_url' || part.type === 'image') {
                const uri = part.image_url?.url || part.data
                  ? (part.data?.startsWith('data:') ? part.data : `data:${part.media_type || 'image/jpeg'};base64,${part.data}`)
                  : part.image_url?.url;
                return uri ? (
                  <Image
                    key={idx}
                    source={{ uri }}
                    style={styles.inlineImage}
                    resizeMode="contain"
                  />
                ) : null;
              }
              if (part.type === 'text') {
                return isAssistant ? (
                  <SimpleMarkdown key={idx} style={styles.text}>{part.text}</SimpleMarkdown>
                ) : (
                  <SimpleMarkdown key={idx} style={[styles.text, isUser && styles.userText]} linkStyle={{ color: colors.hues.sky }}>{part.text}</SimpleMarkdown>
                );
              }
              return null;
            })}
          </View>
        ) : isAssistant ? (
          <SimpleMarkdown style={styles.text}>{message.content}</SimpleMarkdown>
        ) : (
          <SimpleMarkdown style={[styles.text, isUser && styles.userText]} linkStyle={{ color: colors.hues.sky }}>{message.content}</SimpleMarkdown>
        )}

        {/* Star rating for assistant messages */}
        {canRate && (
          <StarRating episodeId={message.episode_id!} size={16} />
        )}

        {/* Timestamp */}
        <Text style={[styles.timestamp, isUser && styles.userTimestamp]}>
          {formatTimestamp(message.created_at)}
        </Text>
      </Pressable>

      {/* Content Cards - rendered below the bubble */}
      {message.cards && message.cards.length > 0 && (
        <View style={styles.cardsContainer}>
          {message.cards.map((card, i) => (
            <ContentCard
              key={`card-${i}`}
              card={card}
              onAction={onCardAction || (() => {})}
              index={i}
            />
          ))}
        </View>
      )}
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
  bubblePressed: {
    opacity: 0.7,
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
  inlineImage: {
    width: 250,
    height: 200,
    borderRadius: borderRadius.md,
    marginVertical: spacing.xs,
  },
  timestamp: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginTop: spacing.xs,
  },
  userTimestamp: {
    color: 'rgba(255, 255, 255, 0.7)',
  },
  copiedBadge: {
    position: 'absolute',
    top: -8,
    right: 8,
    backgroundColor: colors.success,
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 10,
    zIndex: 1,
  },
  copiedText: {
    color: colors.text,
    fontSize: 11,
    fontWeight: '600',
  },
  // System message styles (ambient observations)
  systemContainer: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    marginBottom: spacing.sm,
  },
  systemDivider: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: spacing.xs,
  },
  systemLine: {
    flex: 1,
    height: 1,
    backgroundColor: 'rgba(255, 255, 255, 0.08)',
  },
  systemIcon: {
    color: 'rgba(255, 255, 255, 0.25)',
    fontSize: 10,
    marginHorizontal: spacing.sm,
  },
  systemText: {
    color: 'rgba(255, 255, 255, 0.45)',
    fontSize: fontSizes.sm,
    fontStyle: 'italic',
    lineHeight: fontSizes.sm * 1.5,
  },
  systemTimestamp: {
    color: 'rgba(255, 255, 255, 0.2)',
    fontSize: fontSizes.xs - 1,
    marginTop: 2,
  },
  cardsContainer: {
    marginTop: spacing.xs,
    gap: spacing.xs,
  },
});
