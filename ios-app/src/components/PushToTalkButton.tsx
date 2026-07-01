/**
 * PushToTalkButton Component
 *
 * Floating button for voice input - hold to record, release to send.
 */

import React, { useState, useCallback } from 'react';
import {
  View,
  TouchableOpacity,
  StyleSheet,
  Animated,
  Platform,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { voiceService } from '../services/voice';
import { chatService } from '../services/chat';
import { colors } from '../styles/theme';

interface PushToTalkButtonProps {
  onTranscription?: (text: string) => void;
}

export const PushToTalkButton: React.FC<PushToTalkButtonProps> = ({ onTranscription }) => {
  const [isRecording, setIsRecording] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const pulseAnim = useState(new Animated.Value(1))[0];

  // Start pulse animation when recording
  const startPulse = useCallback(() => {
    Animated.loop(
      Animated.sequence([
        Animated.timing(pulseAnim, {
          toValue: 1.2,
          duration: 500,
          useNativeDriver: true,
        }),
        Animated.timing(pulseAnim, {
          toValue: 1,
          duration: 500,
          useNativeDriver: true,
        }),
      ])
    ).start();
  }, [pulseAnim]);

  const stopPulse = useCallback(() => {
    pulseAnim.stopAnimation();
    pulseAnim.setValue(1);
  }, [pulseAnim]);

  const handlePressIn = useCallback(async () => {
    if (isProcessing) return;

    try {
      await voiceService.initialize();
      await voiceService.startRecording();
      setIsRecording(true);
      startPulse();
    } catch (error) {
      console.error('[PushToTalk] Failed to start recording:', error);
    }
  }, [isProcessing, startPulse]);

  const handlePressOut = useCallback(async () => {
    if (!isRecording) return;

    setIsRecording(false);
    stopPulse();
    setIsProcessing(true);

    try {
      const audioUri = await voiceService.stopRecording();

      if (audioUri) {
        // Transcribe the audio
        const transcription = await voiceService.transcribeAudio(audioUri);

        if (transcription && transcription.trim()) {
          onTranscription?.(transcription);

          // Send to chat
          // The chat screen will handle this through navigation params
          console.log('[PushToTalk] Transcription:', transcription);
        }
      }
    } catch (error) {
      console.error('[PushToTalk] Failed to process recording:', error);
    } finally {
      setIsProcessing(false);
    }
  }, [isRecording, stopPulse, onTranscription]);

  return (
    <View style={styles.container}>
      <Animated.View style={[styles.buttonWrapper, { transform: [{ scale: pulseAnim }] }]}>
        <TouchableOpacity
          style={[
            styles.button,
            isRecording && styles.buttonRecording,
            isProcessing && styles.buttonProcessing,
          ]}
          onPressIn={handlePressIn}
          onPressOut={handlePressOut}
          activeOpacity={0.8}
          disabled={isProcessing}
        >
          <Ionicons
            name={isRecording ? 'mic' : isProcessing ? 'hourglass' : 'mic-outline'}
            size={28}
            color={colors.text}
          />
        </TouchableOpacity>
      </Animated.View>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    position: 'absolute',
    bottom: Platform.OS === 'ios' ? 100 : 80,
    right: 20,
    zIndex: 1000,
  },
  buttonWrapper: {
    shadowColor: colors.shadow,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
    elevation: 8,
  },
  button: {
    width: 60,
    height: 60,
    borderRadius: 30,
    backgroundColor: colors.primary,
    justifyContent: 'center',
    alignItems: 'center',
  },
  buttonRecording: {
    backgroundColor: colors.error,
  },
  buttonProcessing: {
    backgroundColor: colors.textMuted,
  },
});

export default PushToTalkButton;
