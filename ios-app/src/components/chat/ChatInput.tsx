import React, { useState } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  KeyboardAvoidingView,
  Platform,
  Animated,
} from 'react-native';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import { voiceService } from '../../services/voice';

interface ChatInputProps {
  onSend: (message: string) => void;
  onVoiceMessage?: (audioUri: string) => void;
  disabled?: boolean;
  placeholder?: string;
  voiceEnabled?: boolean;
  continuousVoiceMode?: boolean;
  onToggleContinuousVoice?: () => void;
  isListeningContinuous?: boolean;
}

export default function ChatInput({
  onSend,
  onVoiceMessage,
  disabled = false,
  placeholder = 'Ask Sara anything...',
  voiceEnabled = true,
  continuousVoiceMode = false,
  onToggleContinuousVoice,
  isListeningContinuous = false,
}: ChatInputProps) {
  const [message, setMessage] = useState('');
  const [isRecording, setIsRecording] = useState(false);
  const scaleAnim = useState(new Animated.Value(1))[0];

  // Show recording indicator for both manual and continuous modes
  const showRecording = isRecording || isListeningContinuous;

  const handleSend = () => {
    if (message.trim() && !disabled) {
      onSend(message.trim());
      setMessage('');
    }
  };

  const handleVoicePressIn = async () => {
    if (disabled || !onVoiceMessage) return;

    try {
      await voiceService.startRecording();
      setIsRecording(true);

      // Pulse animation
      Animated.loop(
        Animated.sequence([
          Animated.timing(scaleAnim, {
            toValue: 1.2,
            duration: 500,
            useNativeDriver: true,
          }),
          Animated.timing(scaleAnim, {
            toValue: 1,
            duration: 500,
            useNativeDriver: true,
          }),
        ])
      ).start();
    } catch (error) {
      console.error('Failed to start recording:', error);
    }
  };

  const handleVoicePressOut = async () => {
    setIsRecording(false);
    scaleAnim.stopAnimation();
    scaleAnim.setValue(1);

    if (!onVoiceMessage) return;

    try {
      const audioUri = await voiceService.stopRecording();
      if (audioUri) {
        onVoiceMessage(audioUri);
      }
    } catch (error) {
      console.error('Failed to stop recording:', error);
    }
  };

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      keyboardVerticalOffset={Platform.OS === 'ios' ? 90 : 0}
    >
      <View style={styles.container}>
        {/* Continuous Voice Mode Toggle */}
        {voiceEnabled && onToggleContinuousVoice && (
          <TouchableOpacity
            style={[
              styles.continuousModeToggle,
              continuousVoiceMode && styles.continuousModeActive
            ]}
            onPress={onToggleContinuousVoice}
          >
            <Text style={styles.toggleIcon}>{continuousVoiceMode ? '🔊' : '🔇'}</Text>
            <Text style={styles.toggleText}>
              {continuousVoiceMode ? 'Continuous Voice: ON' : 'Continuous Voice: OFF'}
            </Text>
          </TouchableOpacity>
        )}

        {showRecording && (
          <View style={styles.recordingIndicator}>
            <Animated.View style={[styles.recordingDot, { transform: [{ scale: scaleAnim }] }]} />
            <Text style={styles.recordingText}>
              {continuousVoiceMode ? 'Listening... (speak now)' : 'Recording... Release to send'}
            </Text>
          </View>
        )}
        <View style={styles.inputContainer}>
          <TextInput
            style={styles.input}
            value={message}
            onChangeText={setMessage}
            placeholder={placeholder}
            placeholderTextColor={colors.textMuted}
            multiline
            maxLength={2000}
            editable={!disabled && !isRecording && !continuousVoiceMode}
            onSubmitEditing={handleSend}
            blurOnSubmit={false}
          />
          {voiceEnabled && onVoiceMessage && !message.trim() && !continuousVoiceMode ? (
            <TouchableOpacity
              style={[
                styles.voiceButton,
                disabled && styles.voiceButtonDisabled,
                isRecording && styles.voiceButtonActive,
              ]}
              onPressIn={handleVoicePressIn}
              onPressOut={handleVoicePressOut}
              disabled={disabled}
              activeOpacity={1}
            >
              <Text style={styles.voiceButtonText}>
                {isRecording ? '🎙️' : '🎤'}
              </Text>
            </TouchableOpacity>
          ) : message.trim() && !continuousVoiceMode ? (
            <TouchableOpacity
              style={[
                styles.sendButton,
                (!message.trim() || disabled) && styles.sendButtonDisabled,
              ]}
              onPress={handleSend}
              disabled={!message.trim() || disabled}
            >
              <Text style={styles.sendButtonText}>➤</Text>
            </TouchableOpacity>
          ) : null}
        </View>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: colors.surface,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  continuousModeToggle: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
    marginBottom: spacing.sm,
    borderWidth: 2,
    borderColor: colors.border,
  },
  continuousModeActive: {
    backgroundColor: colors.primary + '20',
    borderColor: colors.primary,
  },
  toggleIcon: {
    fontSize: 20,
    marginRight: spacing.sm,
  },
  toggleText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  recordingIndicator: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: spacing.sm,
  },
  recordingDot: {
    width: 12,
    height: 12,
    borderRadius: 6,
    backgroundColor: colors.error,
    marginRight: spacing.sm,
  },
  recordingText: {
    color: colors.error,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  inputContainer: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    backgroundColor: colors.background,
    borderRadius: borderRadius.lg,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    minHeight: 44,
  },
  input: {
    flex: 1,
    color: colors.text,
    fontSize: fontSizes.md,
    maxHeight: 100,
    paddingVertical: spacing.sm,
  },
  sendButton: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: colors.primary,
    justifyContent: 'center',
    alignItems: 'center',
    marginLeft: spacing.sm,
  },
  sendButtonDisabled: {
    opacity: 0.4,
  },
  sendButtonText: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '600',
  },
  voiceButton: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: colors.primary,
    justifyContent: 'center',
    alignItems: 'center',
    marginLeft: spacing.sm,
  },
  voiceButtonActive: {
    backgroundColor: colors.error,
  },
  voiceButtonDisabled: {
    opacity: 0.4,
  },
  voiceButtonText: {
    fontSize: 20,
  },
});
