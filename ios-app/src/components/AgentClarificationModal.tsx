import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  Modal,
  KeyboardAvoidingView,
  Platform,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { BackgroundTask } from '../types/api';
import { backgroundTaskService } from '../services/backgroundTasks';
import { colors, spacing, borderRadius, fontSizes } from '../styles/theme';

interface AgentClarificationModalProps {
  visible: boolean;
  task: BackgroundTask | null;
  onClose: () => void;
  onDismiss: () => void;
}

export default function AgentClarificationModal({
  visible,
  task,
  onClose,
  onDismiss,
}: AgentClarificationModalProps) {
  const [response, setResponse] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Reset response when task changes
  useEffect(() => {
    if (task) {
      setResponse('');
    }
  }, [task?.id]);

  const handleSubmit = async () => {
    if (!task || !response.trim()) return;

    setIsSubmitting(true);
    try {
      const success = await backgroundTaskService.submitClarification(task.id, response);
      if (success) {
        setResponse('');
        onClose();
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  if (!task || !visible) {
    return null;
  }

  const queryPreview = task.original_query.length > 80
    ? task.original_query.substring(0, 80) + '...'
    : task.original_query;

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={onClose}
    >
      <SafeAreaView style={styles.container} edges={['top', 'left', 'right']}>
        <KeyboardAvoidingView
          style={styles.keyboardView}
          behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        >
          {/* Header */}
          <View style={styles.header}>
            <TouchableOpacity onPress={onDismiss} style={styles.headerButton}>
              <Text style={styles.dismissText}>Dismiss</Text>
            </TouchableOpacity>
            <View style={styles.headerTitleContainer}>
              <Text style={styles.headerIcon}>🤖</Text>
              <Text style={styles.headerTitle}>Agent Needs Input</Text>
            </View>
            <View style={styles.headerButton} />
          </View>

          {/* Content */}
          <View style={styles.content}>
            {/* Task Context */}
            <View style={styles.contextBox}>
              <Text style={styles.contextLabel}>Task:</Text>
              <Text style={styles.contextText}>{queryPreview}</Text>
            </View>

            {/* Question */}
            <View style={styles.questionBox}>
              <Text style={styles.questionText}>{task.clarification_question}</Text>
            </View>

            {/* Input */}
            <TextInput
              style={styles.input}
              placeholder="Type your response..."
              placeholderTextColor={colors.textMuted}
              value={response}
              onChangeText={setResponse}
              multiline
              autoFocus
              editable={!isSubmitting}
            />

            {/* Buttons */}
            <View style={styles.buttonRow}>
              <TouchableOpacity
                style={styles.skipButton}
                onPress={onDismiss}
                disabled={isSubmitting}
              >
                <Text style={styles.skipButtonText}>Skip</Text>
              </TouchableOpacity>

              <TouchableOpacity
                style={[
                  styles.sendButton,
                  (!response.trim() || isSubmitting) && styles.sendButtonDisabled
                ]}
                onPress={handleSubmit}
                disabled={!response.trim() || isSubmitting}
              >
                {isSubmitting ? (
                  <ActivityIndicator size="small" color={colors.text} />
                ) : (
                  <>
                    <Text style={styles.sendButtonText}>Send</Text>
                    <Text style={styles.sendIcon}>📤</Text>
                  </>
                )}
              </TouchableOpacity>
            </View>
          </View>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  keyboardView: {
    flex: 1,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    backgroundColor: 'rgba(249, 115, 22, 0.1)', // orange tint
  },
  headerButton: {
    width: 70,
  },
  headerTitleContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs,
  },
  headerIcon: {
    fontSize: 20,
  },
  headerTitle: {
    fontSize: fontSizes.lg,
    fontWeight: '600',
    color: '#f97316', // orange
  },
  dismissText: {
    fontSize: fontSizes.md,
    color: colors.textMuted,
  },
  content: {
    flex: 1,
    padding: spacing.lg,
  },
  contextBox: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  contextLabel: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
    marginBottom: 4,
  },
  contextText: {
    fontSize: fontSizes.sm,
    color: colors.text,
  },
  questionBox: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    marginBottom: spacing.lg,
    borderLeftWidth: 3,
    borderLeftColor: '#f97316', // orange
  },
  questionText: {
    fontSize: fontSizes.md,
    color: colors.text,
    lineHeight: 22,
  },
  input: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    fontSize: fontSizes.md,
    color: colors.text,
    borderWidth: 1,
    borderColor: colors.border,
    minHeight: 100,
    textAlignVertical: 'top',
    marginBottom: spacing.lg,
  },
  buttonRow: {
    flexDirection: 'row',
    gap: spacing.md,
  },
  skipButton: {
    flex: 1,
    padding: spacing.md,
    borderRadius: borderRadius.md,
    backgroundColor: colors.surface,
    alignItems: 'center',
    justifyContent: 'center',
  },
  skipButtonText: {
    fontSize: fontSizes.md,
    color: colors.textMuted,
    fontWeight: '600',
  },
  sendButton: {
    flex: 1,
    flexDirection: 'row',
    padding: spacing.md,
    borderRadius: borderRadius.md,
    backgroundColor: '#f97316', // orange
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.xs,
  },
  sendButtonDisabled: {
    backgroundColor: colors.surface,
    opacity: 0.5,
  },
  sendButtonText: {
    fontSize: fontSizes.md,
    color: colors.text,
    fontWeight: '600',
  },
  sendIcon: {
    fontSize: 16,
  },
});
