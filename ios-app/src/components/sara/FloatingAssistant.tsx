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
  Keyboard,
  Platform,
  Dimensions,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import { useSaraOverlay } from '../../context/SaraOverlayContext';
import { useSaraChat } from '../../hooks/useSaraChat';
import { useSaraPresence } from '../../hooks/useSaraPresence';
import SaraOrb from './SaraOrb';
import { voiceService } from '../../services/voice';
import MessageBubble from '../chat/MessageBubble';
import StreamingIndicator from '../chat/StreamingIndicator';
import { colors, shadows } from '../../styles/theme';
import { navigateToChat, handleSaraUiCommand } from '../../services/navigation';

const SCREEN_HEIGHT = Dimensions.get('window').height;
const MINI_CHAT_HEIGHT = SCREEN_HEIGHT * 0.55;
const MINI_CHAT_BOTTOM = 100; // matches styles.miniChatContainer.bottom

export default function FloatingAssistant() {
  const { mode, currentScreen, setMode } = useSaraOverlay();
  const handleUiCommand = useCallback((command: any) => {
    // Collapse the mini-chat so the screen Sara just opened is visible.
    if (handleSaraUiCommand(command)) {
      setTimeout(() => setMode('orb'), 600);
    }
  }, [setMode]);
  const chat = useSaraChat({ source: 'ios_overlay', currentScreen, onUiCommand: handleUiCommand });
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
  const keyboardShift = useRef(new Animated.Value(0)).current;

  // KeyboardAvoidingView can't handle an absolutely-positioned panel, so
  // translate the mini-chat above the keyboard ourselves. The panel already
  // sits MINI_CHAT_BOTTOM px off the screen bottom — only shift the overlap.
  useEffect(() => {
    const showEvent = Platform.OS === 'ios' ? 'keyboardWillShow' : 'keyboardDidShow';
    const hideEvent = Platform.OS === 'ios' ? 'keyboardWillHide' : 'keyboardDidHide';

    // Never push the panel header under the status bar / dynamic island.
    const maxShift = Math.max(0, SCREEN_HEIGHT - MINI_CHAT_BOTTOM - MINI_CHAT_HEIGHT - 64);

    const showSub = Keyboard.addListener(showEvent, (e) => {
      const overlap = Math.max(0, e.endCoordinates.height - MINI_CHAT_BOTTOM + 8);
      Animated.timing(keyboardShift, {
        toValue: -Math.min(overlap, maxShift),
        duration: e.duration || 250,
        useNativeDriver: true,
      }).start();
    });
    const hideSub = Keyboard.addListener(hideEvent, (e) => {
      Animated.timing(keyboardShift, {
        toValue: 0,
        duration: e?.duration || 250,
        useNativeDriver: true,
      }).start();
    });
    return () => {
      showSub.remove();
      hideSub.remove();
    };
  }, [keyboardShift]);

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
            style={styles.orb}
          >
            <SaraOrb size={56} />
            {(isRecording || isProcessing) && (
              <View style={styles.orbIconOverlay} pointerEvents="none">
                <Ionicons
                  name={isRecording ? 'mic' : 'hourglass'}
                  size={isRecording ? 24 : 22}
                  color={colors.text}
                />
              </View>
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
                  translateY: Animated.add(
                    miniChatAnim.interpolate({
                      inputRange: [0, 1],
                      outputRange: [MINI_CHAT_HEIGHT, 0],
                    }),
                    keyboardShift,
                  ),
                },
              ],
              opacity: miniChatAnim,
            },
          ]}
        >
          <View style={styles.miniChatInner}>
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
                    color={isRecording ? colors.text : colors.textMuted}
                  />
                </TouchableOpacity>
              )}
            </View>
          </View>
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
    justifyContent: 'center',
    alignItems: 'center',
    overflow: 'hidden',
    ...shadows.md,
  },
  orbIconOverlay: {
    ...StyleSheet.absoluteFillObject,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: 'rgba(0,0,0,0.25)',
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
