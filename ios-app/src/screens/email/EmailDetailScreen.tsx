import React, { useState, useEffect } from 'react';
import {
  View,
  ScrollView,
  StyleSheet,
  TouchableOpacity,
  Text,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import apiClient from '../../services/api';
import { useToast } from '../../context/ToastContext';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface Attachment {
  id: string;
  filename: string;
  content_type: string;
  size: number;
}

interface EmailDetail {
  id: string;
  sender_name: string;
  sender_email: string;
  subject: string;
  body_text: string;
  body_preview: string;
  received_at: string;
  importance: string;
  is_read: boolean;
  has_attachments: boolean;
  attachments: Attachment[];
  action_required: boolean;
}

function formatDate(dateStr: string): string {
  if (!dateStr) return '';
  const date = new Date(dateStr);
  return date.toLocaleDateString(undefined, {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  }) + ' at ' + date.toLocaleTimeString(undefined, {
    hour: 'numeric',
    minute: '2-digit',
  });
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface EmailDetailScreenProps {
  route?: {
    params?: {
      emailId: string;
    };
  };
  navigation: any;
}

export default function EmailDetailScreen({ route, navigation }: EmailDetailScreenProps) {
  const { showToast } = useToast();
  const emailId = route?.params?.emailId;
  const [email, setEmail] = useState<EmailDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [markingRead, setMarkingRead] = useState(false);

  useEffect(() => {
    if (emailId) {
      loadEmail();
    }
  }, [emailId]);

  const loadEmail = async () => {
    try {
      setLoading(true);
      const response = await fetch(`${apiClient.baseURL}/api/email/${emailId}`, {
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
      });

      if (!response.ok) {
        throw new Error(`Failed to fetch email: ${response.status}`);
      }

      const data: EmailDetail = await response.json();
      setEmail(data);
    } catch (error) {
      console.error('Failed to load email:', error);
      showToast('error', 'Failed to load email');
    } finally {
      setLoading(false);
    }
  };

  const handleMarkRead = async () => {
    if (!email || email.is_read) return;

    try {
      setMarkingRead(true);
      const response = await fetch(`${apiClient.baseURL}/api/email/${emailId}/mark-read`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
      });

      if (!response.ok) {
        throw new Error(`Failed to mark as read: ${response.status}`);
      }

      setEmail(prev => prev ? { ...prev, is_read: true } : null);
    } catch (error) {
      console.error('Failed to mark email as read:', error);
      showToast('error', 'Failed to mark email as read');
    } finally {
      setMarkingRead(false);
    }
  };

  const handleAskSara = () => {
    if (!email) return;
    navigation.navigate('Main', {
      screen: 'Sara',
      params: {
        quickReply: {
          message: `I want to discuss this email from ${email.sender_name}: "${email.subject}"`,
          title: email.subject,
        },
      },
    });
  };

  if (loading) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  if (!email) {
    return (
      <SafeAreaView style={styles.container} edges={['bottom']}>
        <View style={styles.emptyContainer}>
          <Text style={styles.emptyText}>Email not found</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <ScrollView style={styles.scrollContent} contentContainerStyle={styles.scrollContentContainer}>
        {/* Header */}
        <View style={styles.header}>
          <View style={styles.senderRow}>
            <View style={styles.senderInfo}>
              <Text style={styles.senderName}>{email.sender_name}</Text>
              <Text style={styles.senderEmail}>{email.sender_email}</Text>
            </View>
            {email.importance === 'high' && (
              <View style={styles.importanceBadge}>
                <Text style={styles.importanceBadgeText}>High</Text>
              </View>
            )}
          </View>
          <Text style={styles.receivedAt}>{formatDate(email.received_at)}</Text>
        </View>

        {/* Subject */}
        <Text style={styles.subject}>{email.subject}</Text>

        {/* Divider */}
        <View style={styles.divider} />

        {/* Body */}
        <Text style={styles.bodyText}>{email.body_text}</Text>

        {/* Attachments */}
        {email.has_attachments && email.attachments && email.attachments.length > 0 && (
          <View style={styles.attachmentsSection}>
            <Text style={styles.attachmentsTitle}>
              Attachments ({email.attachments.length})
            </Text>
            {email.attachments.map((attachment) => (
              <View key={attachment.id} style={styles.attachmentItem}>
                <View style={styles.attachmentInfo}>
                  <Text style={styles.attachmentName} numberOfLines={1}>
                    {attachment.filename}
                  </Text>
                  <Text style={styles.attachmentSize}>
                    {formatFileSize(attachment.size)}
                  </Text>
                </View>
              </View>
            ))}
          </View>
        )}
      </ScrollView>

      {/* Action Buttons */}
      <View style={styles.actionBar}>
        {!email.is_read && (
          <TouchableOpacity
            style={styles.actionButton}
            onPress={handleMarkRead}
            disabled={markingRead}
          >
            {markingRead ? (
              <ActivityIndicator size="small" color={colors.text} />
            ) : (
              <Text style={styles.actionButtonText}>Mark Read</Text>
            )}
          </TouchableOpacity>
        )}
        <TouchableOpacity
          style={[styles.actionButton, styles.actionButtonPrimary]}
          onPress={handleAskSara}
        >
          <Text style={styles.actionButtonPrimaryText}>Ask Sara</Text>
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: colors.background,
  },
  emptyContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  emptyText: {
    color: colors.textMuted,
    fontSize: fontSizes.md,
  },
  scrollContent: {
    flex: 1,
  },
  scrollContentContainer: {
    padding: spacing.md,
    paddingBottom: spacing.xl,
  },
  header: {
    marginBottom: spacing.md,
  },
  senderRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: spacing.xs,
  },
  senderInfo: {
    flex: 1,
  },
  senderName: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '600',
  },
  senderEmail: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    marginTop: 2,
  },
  importanceBadge: {
    backgroundColor: colors.error,
    borderRadius: borderRadius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
    marginLeft: spacing.sm,
  },
  importanceBadgeText: {
    color: colors.text,
    fontSize: fontSizes.xs,
    fontWeight: '600',
  },
  receivedAt: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    marginTop: spacing.xs,
  },
  subject: {
    color: colors.text,
    fontSize: fontSizes.xl,
    fontWeight: '700',
    marginBottom: spacing.md,
  },
  divider: {
    height: 1,
    backgroundColor: colors.border,
    marginBottom: spacing.md,
  },
  bodyText: {
    color: colors.text,
    fontSize: fontSizes.md,
    lineHeight: 24,
  },
  attachmentsSection: {
    marginTop: spacing.lg,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
  },
  attachmentsTitle: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    fontWeight: '600',
    textTransform: 'uppercase',
    marginBottom: spacing.sm,
  },
  attachmentItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  attachmentInfo: {
    flex: 1,
  },
  attachmentName: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '500',
  },
  attachmentSize: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginTop: 2,
  },
  actionBar: {
    flexDirection: 'row',
    padding: spacing.md,
    gap: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.surface,
  },
  actionButton: {
    flex: 1,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    alignItems: 'center',
    justifyContent: 'center',
  },
  actionButtonPrimary: {
    backgroundColor: colors.primary,
  },
  actionButtonText: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
  },
  actionButtonPrimaryText: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
  },
});
