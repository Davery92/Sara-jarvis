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
  Image,
  ScrollView,
  ActionSheetIOS,
  Alert,
} from 'react-native';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import { voiceService } from '../../services/voice';
import { imagePickerService, ImageAttachment } from '../../services/imagePicker';

interface ChatInputProps {
  onSend: (message: string, images?: ImageAttachment[]) => void;
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
  const [attachedImages, setAttachedImages] = useState<ImageAttachment[]>([]);
  const scaleAnim = useState(new Animated.Value(1))[0];

  // Show recording indicator for both manual and continuous modes
  const showRecording = isRecording || isListeningContinuous;

  const handleSend = () => {
    if ((message.trim() || attachedImages.length > 0) && !disabled) {
      onSend(message.trim(), attachedImages.length > 0 ? attachedImages : undefined);
      setMessage('');
      setAttachedImages([]);
    }
  };

  const handleAddImage = () => {
    if (Platform.OS === 'ios') {
      ActionSheetIOS.showActionSheetWithOptions(
        {
          options: ['Cancel', 'Choose from Gallery', 'Take a Photo'],
          cancelButtonIndex: 0,
        },
        async (buttonIndex) => {
          if (buttonIndex === 1) {
            const image = await imagePickerService.pickFromGallery();
            if (image) {
              setAttachedImages(prev => [...prev, image]);
            }
          } else if (buttonIndex === 2) {
            const image = await imagePickerService.takePhoto();
            if (image) {
              setAttachedImages(prev => [...prev, image]);
            }
          }
        }
      );
    } else {
      // Android fallback - show Alert with options
      Alert.alert(
        'Add Image',
        'Choose an option',
        [
          { text: 'Cancel', style: 'cancel' },
          {
            text: 'Choose from Gallery',
            onPress: async () => {
              const image = await imagePickerService.pickFromGallery();
              if (image) {
                setAttachedImages(prev => [...prev, image]);
              }
            },
          },
          {
            text: 'Take a Photo',
            onPress: async () => {
              const image = await imagePickerService.takePhoto();
              if (image) {
                setAttachedImages(prev => [...prev, image]);
              }
            },
          },
        ]
      );
    }
  };

  const removeImage = (index: number) => {
    setAttachedImages(prev => prev.filter((_, i) => i !== index));
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

        {/* Attached Images Preview */}
        {attachedImages.length > 0 && (
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            style={styles.imagePreviewContainer}
            contentContainerStyle={styles.imagePreviewContent}
          >
            {attachedImages.map((img, index) => (
              <View key={index} style={styles.imagePreviewWrapper}>
                <Image source={{ uri: img.uri }} style={styles.imagePreview} />
                <TouchableOpacity
                  style={styles.removeImageButton}
                  onPress={() => removeImage(index)}
                >
                  <Text style={styles.removeImageText}>×</Text>
                </TouchableOpacity>
              </View>
            ))}
          </ScrollView>
        )}

        <View style={styles.inputContainer}>
          {/* Add image button */}
          <TouchableOpacity
            style={styles.imageButton}
            onPress={handleAddImage}
            disabled={disabled}
          >
            <Text style={styles.imageButtonText}>📎</Text>
          </TouchableOpacity>

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
          {voiceEnabled && onVoiceMessage && !message.trim() && attachedImages.length === 0 && !continuousVoiceMode ? (
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
          ) : (message.trim() || attachedImages.length > 0) && !continuousVoiceMode ? (
            <TouchableOpacity
              style={[
                styles.sendButton,
                ((!message.trim() && attachedImages.length === 0) || disabled) && styles.sendButtonDisabled,
              ]}
              onPress={handleSend}
              disabled={(!message.trim() && attachedImages.length === 0) || disabled}
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
  imageButton: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: colors.background,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: spacing.xs,
  },
  imageButtonText: {
    fontSize: 18,
  },
  imagePreviewContainer: {
    marginBottom: spacing.sm,
    maxHeight: 80,
  },
  imagePreviewContent: {
    paddingHorizontal: spacing.xs,
  },
  imagePreviewWrapper: {
    marginRight: spacing.sm,
    position: 'relative',
  },
  imagePreview: {
    width: 60,
    height: 60,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  removeImageButton: {
    position: 'absolute',
    top: -6,
    right: -6,
    width: 20,
    height: 20,
    borderRadius: 10,
    backgroundColor: colors.error,
    justifyContent: 'center',
    alignItems: 'center',
  },
  removeImageText: {
    color: colors.text,
    fontSize: 14,
    fontWeight: 'bold',
    lineHeight: 18,
  },
});
