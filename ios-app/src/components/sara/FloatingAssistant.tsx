/**
 * FloatingAssistant
 *
 * Replaces PushToTalkButton. Shows a floating Sara orb on non-Sara screens.
 * Tap to expand to mini-chat, long-press for voice. Hidden on Sara tab.
 */

import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  Animated,
  Pressable,
  FlatList,
  TextInput,
  KeyboardAvoidingView,
  Platform,
  Dimensions,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import { useSaraOverlay } from '../../context/SaraOverlayContext';
import { useSaraChat } from '../../hooks/useSaraChat';
import { useSaraPresence } from '../../hooks/useSaraPresence';
import { voiceService } from '../../services/voice';
import MessageBubble from '../chat/MessageBubble';
import StreamingIndicator from '../chat/StreamingIndicator';
import { colors, shadows } from '../../styles/theme';
import { navigateToChat } from '../../services/navigation';

const SCREEN_HEIGHT = Dimensions.get('window').height;
const MINI_CHAT_HEIGHT = SCREEN_HEIGHT * 0.55;

export default function FloatingAssistant() {
  const { mode, currentScreen, setMode } = useSaraOverlay();
  const chat = useSaraChat({ source: 'ios_overlay', currentScreen });
  const presence = useSaraPresence();

  const [inputText, setInputText] = useState('');
  const [isRecording, setIsRecording] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);

  // Animations
  const breatheAnim = useRef(new Animated.Value(1)).current;
  const miniChatAnim = useRef(new Animated.Value(0)).current;
  const backdropAnim = useRef(new Animated.Value(0)).current;
  const pulseAnim = useRef(new Animated.Value(1)).current;
  const reactionPop = useRef(new Animated.Value(1)).current;

  const flatListRef = useRef<FlatList>(null);
  const breatheAnimRef = useRef<Animated.CompositeAnimation | null>(null);
  const pulseAnimRef = useRef<Animated.CompositeAnimation | null>(null);

  // Emphatic daemon reactions (focus_set / notify_david) give the orb a heartbeat —
  // the "she just noticed something" moment, mirroring the web presence chip.
  useEffect(() => {
    if (presence.emphatic && mode === 'orb') {
      const animation = Animated.loop(
        Animated.sequence([
          Animated.timing(reactionPop, { toValue: 1.18, duration: 450, useNativeDriver: true }),
          Animated.timing(reactionPop, { toValue: 1, duration: 450, useNativeDriver: true }),
        ])
      );
      animation.start();
      return () => animation.stop();
    }
    reactionPop.setValue(1);
  }, [presence.emphatic, mode]);

  // Load history when mini-chat opens
  useEffect(() => {
    if (mode === 'mini') {
      chat.loadHistory();
      chat.initVoice();
    }
  }, [mode]);

  // Breathing animation for orb
  useEffect(() => {
    if (mode === 'orb') {
      const animation = Animated.loop(
        Animated.sequence([
          Animated.timing(breatheAnim, {
            toValue: 1.05,
            duration: 2000,
            useNativeDriver: true,
          }),
          Animated.timing(breatheAnim, {
            toValue: 1,
            duration: 2000,
            useNativeDriver: true,
          }),
        ])
      );
      breatheAnimRef.current = animation;
      animation.start();
      return () => animation.stop();
    } else {
      breatheAnim.setValue(1);
    }
  }, [mode]);

  // Mini-chat expand/collapse animation
  useEffect(() => {
    if (mode === 'mini') {
      Animated.parallel([
        Animated.spring(miniChatAnim, {
          toValue: 1,
          tension: 65,
          friction: 11,
          useNativeDriver: true,
        }),
        Animated.timing(backdropAnim, {
          toValue: 1,
          duration: 200,
          useNativeDriver: true,
        }),
      ]).start();
    } else {
      Animated.parallel([
        Animated.timing(miniChatAnim, {
          toValue: 0,
          duration: 200,
          useNativeDriver: true,
        }),
        Animated.timing(backdropAnim, {
          toValue: 0,
          duration: 200,
          useNativeDriver: true,
        }),
      ]).start();
    }
  }, [mode]);

  // Recording pulse animation
  useEffect(() => {
    if (isRecording) {
      const animation = Animated.loop(
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
      );
      pulseAnimRef.current = animation;
      animation.start();
      return () => animation.stop();
    } else {
      pulseAnim.setValue(1);
    }
  }, [isRecording]);

  const handleOrbTap = useCallback(() => {
    try { Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium); } catch {}
    setMode('mini');
  }, [setMode]);

  const handleOrbLongPress = useCallback(async () => {
    if (isProcessing) return;
    try { Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy); } catch {}

    const initialized = await voiceService.initialize();
    if (!initialized) return;

    setIsRecording(true);
    await voiceService.startRecording();
  }, [isProcessing]);

  const handleOrbPressOut = useCallback(async () => {
    if (!isRecording) return;

    setIsRecording(false);
    setIsProcessing(true);

    try {
      const audioUri = await voiceService.stopRecording();
      if (audioUri) {
        // Switch to mini-chat to show the response
        setMode('mini');
        await chat.handleVoiceMessage(audioUri);
      }
    } catch (error) {
      console.error('[FloatingAssistant] Voice error:', error);
    } finally {
      setIsProcessing(false);
    }
  }, [isRecording, chat, setMode]);

  const handleCollapse = useCallback(() => {
    setMode('orb');
    setInputText('');
  }, [setMode]);

  const handleExpand = useCallback(() => {
    setMode('orb');
    navigateToChat();
  }, [setMode]);

  const handleSend = useCallback(() => {
    const text = inputText.trim();
    if (!text || chat.isStreaming) return;
    setInputText('');
    chat.sendMessage(text);
  }, [inputText, chat]);

  const handleMiniVoice = useCallback(async () => {
    if (isRecording) {
      setIsRecording(false);
      setIsProcessing(true);
      try {
        const audioUri = await voiceService.stopRecording();
        if (audioUri) {
          await chat.handleVoiceMessage(audioUri);
        }
      } catch {} finally {
        setIsProcessing(false);
      }
    } else {
      const initialized = await voiceService.initialize();
      if (!initialized) return;
      try { Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium); } catch {}
      setIsRecording(true);
      await voiceService.startRecording();
    }
  }, [isRecording, chat]);

  // Don't render when hidden
  if (mode === 'hidden') return null;

  const emoji = presence.emoji;

  // Get last 20 messages for mini-chat
  const recentMessages = chat.messages.slice(-20);

  return (
    <>
      {/* Backdrop for mini-chat */}
      {mode === 'mini' && (
        <Animated.View
          style={[
            styles.backdrop,
            { opacity: backdropAnim },
          ]}
        >
          <Pressable style={StyleSheet.absoluteFill} onPress={handleCollapse} />
        </Animated.View>
      )}

      {/* Orb */}
      {mode === 'orb' && (
        <Animated.View
          style={[
            styles.orbContainer,
            {
              transform: [
                { scale: isRecording ? pulseAnim : (presence.emphatic ? reactionPop : breatheAnim) },
              ],
            },
          ]}
        >
          <Pressable
            onPress={handleOrbTap}
            onLongPress={handleOrbLongPress}
            onPressOut={handleOrbPressOut}
            delayLongPress={300}
            style={[
              styles.orb,
              !isRecording && !isProcessing && { backgroundColor: presence.color },
              isRecording && styles.orbRecording,
              isProcessing && styles.orbProcessing,
            ]}
          >
            {isRecording ? (
              <Ionicons name="mic" size={24} color="#fff" />
            ) : isProcessing ? (
              <Ionicons name="hourglass" size={22} color="#fff" />
            ) : (
              <Text style={styles.orbEmoji}>{emoji}</Text>
            )}
          </Pressable>
        </Animated.View>
      )}

      {/* Mini-chat panel */}
      {mode === 'mini' && (
        <Animated.View
          style={[
            styles.miniChatContainer,
            {
              transform: [
                {
                  translateY: miniChatAnim.interpolate({
                    inputRange: [0, 1],
                    outputRange: [MINI_CHAT_HEIGHT, 0],
                  }),
                },
              ],
              opacity: miniChatAnim,
            },
          ]}
        >
          <KeyboardAvoidingView
            style={styles.miniChatInner}
            behavior={Platform.OS === 'ios' ? 'padding' : undefined}
            keyboardVerticalOffset={20}
          >
            {/* Header */}
            <View style={styles.miniHeader}>
              <TouchableOpacity onPress={handleExpand} style={styles.miniExpandBtn}>
                <Ionicons name="expand-outline" size={18} color={colors.textMuted} />
              </TouchableOpacity>
              <Text style={styles.miniTitle}>Sara</Text>
              <TouchableOpacity onPress={handleCollapse} style={styles.miniCloseBtn}>
                <Ionicons name="close" size={20} color={colors.textMuted} />
              </TouchableOpacity>
            </View>

            {/* Messages */}
            <FlatList
              ref={flatListRef}
              data={recentMessages}
              renderItem={({ item }) => (
                <MessageBubble message={item} />
              )}
              keyExtractor={(item) => item.id}
              contentContainerStyle={styles.miniMessages}
              ListFooterComponent={
                chat.isStreaming ? (
                  <View>
                    {chat.streamingMessage ? (
                      <MessageBubble
                        message={{
                          id: 'streaming',
                          role: 'assistant',
                          content: chat.streamingMessage,
                          created_at: new Date().toISOString(),
                        }}
                      />
                    ) : (
                      <StreamingIndicator />
                    )}
                  </View>
                ) : null
              }
              ListEmptyComponent={
                <View style={styles.miniEmpty}>
                  <Text style={styles.miniEmptyText}>Ask Sara anything...</Text>
                </View>
              }
              onContentSizeChange={() => {
                flatListRef.current?.scrollToEnd({ animated: true });
              }}
            />

            {/* Input row */}
            <View style={styles.miniInputRow}>
              <TextInput
                style={styles.miniInput}
                value={inputText}
                onChangeText={setInputText}
                placeholder="Message Sara..."
                placeholderTextColor={colors.textMuted}
                onSubmitEditing={handleSend}
                returnKeyType="send"
                editable={!chat.isStreaming}
              />
              {inputText.trim() ? (
                <TouchableOpacity
                  onPress={handleSend}
                  style={styles.miniSendBtn}
                  disabled={chat.isStreaming}
                >
                  <Ionicons name="send" size={18} color={colors.primary} />
                </TouchableOpacity>
              ) : (
                <TouchableOpacity
                  onPress={handleMiniVoice}
                  style={[
                    styles.miniMicBtn,
                    isRecording && styles.miniMicBtnRecording,
                  ]}
                  disabled={isProcessing}
                >
                  <Ionicons
                    name={isRecording ? 'mic' : 'mic-outline'}
                    size={20}
                    color={isRecording ? '#fff' : colors.textMuted}
                  />
                </TouchableOpacity>
              )}
            </View>
          </KeyboardAvoidingView>
        </Animated.View>
      )}
    </>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(0, 0, 0, 0.4)',
    zIndex: 998,
  },

  // Orb styles
  orbContainer: {
    position: 'absolute',
    bottom: 100,
    right: 16,
    zIndex: 999,
    ...shadows.lg,
  },
  orb: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: colors.primary,
    justifyContent: 'center',
    alignItems: 'center',
    ...shadows.md,
  },
  orbRecording: {
    backgroundColor: colors.error,
  },
  orbProcessing: {
    backgroundColor: colors.textMuted,
  },
  orbEmoji: {
    fontSize: 24,
  },

  // Mini-chat styles
  miniChatContainer: {
    position: 'absolute',
    bottom: 100,
    left: 12,
    right: 12,
    height: MINI_CHAT_HEIGHT,
    backgroundColor: colors.surface,
    borderRadius: 20,
    overflow: 'hidden',
    zIndex: 999,
    ...shadows.lg,
    borderWidth: 1,
    borderColor: colors.border,
  },
  miniChatInner: {
    flex: 1,
  },
  miniHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  miniExpandBtn: {
    padding: 4,
  },
  miniTitle: {
    color: colors.text,
    fontSize: 15,
    fontWeight: '600',
  },
  miniCloseBtn: {
    padding: 4,
  },
  miniMessages: {
    paddingVertical: 8,
    paddingHorizontal: 4,
    flexGrow: 1,
  },
  miniEmpty: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingVertical: 40,
  },
  miniEmptyText: {
    color: colors.textMuted,
    fontSize: 14,
  },
  miniInputRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 10,
    paddingVertical: 8,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    gap: 8,
  },
  miniInput: {
    flex: 1,
    backgroundColor: colors.background,
    borderRadius: 20,
    paddingHorizontal: 14,
    paddingVertical: 8,
    color: colors.text,
    fontSize: 14,
    maxHeight: 80,
  },
  miniSendBtn: {
    padding: 8,
  },
  miniMicBtn: {
    width: 36,
    height: 36,
    borderRadius: 18,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: colors.background,
  },
  miniMicBtnRecording: {
    backgroundColor: colors.error,
  },
});
