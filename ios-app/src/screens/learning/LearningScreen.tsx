import React, { useState, useEffect, useRef } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  FlatList,
  TextInput,
  ActivityIndicator,
  Alert,
  Animated,
  RefreshControl,
  Modal,
  Switch,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import { apiClient } from '../../services/api';
import { voiceService } from '../../services/voice';
import { chatService } from '../../services/chat';

type TabType = 'topics' | 'flashcards' | 'chat';

interface Topic {
  id: string;
  title: string;
  description: string;
  mastery_level: number;
  status: string;
  priority: number;
}

interface Flashcard {
  id: string;
  front: string;
  back: string;
  hint?: string;
  topic_id?: string;
  topic_title?: string;
}

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
}

export default function LearningScreen() {
  const [activeTab, setActiveTab] = useState<TabType>('topics');
  const [topics, setTopics] = useState<Topic[]>([]);
  const [selectedTopic, setSelectedTopic] = useState<Topic | null>(null);
  const [flashcards, setFlashcards] = useState<Flashcard[]>([]);
  const [currentCardIndex, setCurrentCardIndex] = useState(0);
  const [showAnswer, setShowAnswer] = useState(false);
  const [scratchpadContent, setScratchpadContent] = useState('');
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  // Chat state
  const [messages, setMessages] = useState<Message[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingMessage, setStreamingMessage] = useState('');

  // New topic creation state
  const [showNewTopicModal, setShowNewTopicModal] = useState(false);
  const [newTopicTitle, setNewTopicTitle] = useState('');
  const [newTopicDescription, setNewTopicDescription] = useState('');
  const [autoResearch, setAutoResearch] = useState(true);
  const [creatingTopic, setCreatingTopic] = useState(false);

  // Voice state
  const [voiceInitialized, setVoiceInitialized] = useState(false);
  const [ambientMode, setAmbientMode] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [isPlayingAudio, setIsPlayingAudio] = useState(false);
  const shouldResumeListening = useRef(false);
  const streamingMessageRef = useRef('');
  const scaleAnim = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    loadTopics();
    initVoice();
    return () => {
      voiceService.cleanup();
    };
  }, []);

  const initVoice = async () => {
    const initialized = await voiceService.initialize();
    setVoiceInitialized(initialized);
  };

  const loadTopics = async () => {
    try {
      setLoading(true);
      const response = await apiClient.get<Topic[]>('/api/learn/topics?status=active');
      // apiClient.get already returns response.data, not wrapped in a .data property
      setTopics(response || []);
    } catch (error) {
      console.error('Failed to load topics:', error);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const loadFlashcards = async (topicId: string) => {
    try {
      setLoading(true);
      const response = await apiClient.post<{flashcards: Flashcard[], has_sources?: boolean}>(`/api/learn/topics/${topicId}/flashcards`, {
        card_count: 10
      });
      if (response?.flashcards) {
        setFlashcards(response.flashcards);
        setCurrentCardIndex(0);
        setShowAnswer(false);
        if (response.has_sources === false) {
          Alert.alert('Note', 'Flashcards generated from general knowledge. Add sources in the web app for more targeted content.');
        }
      }
    } catch (error) {
      console.error('Failed to load flashcards:', error);
      Alert.alert('Error', 'Failed to generate flashcards. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  const loadScratchpad = async (topicId: string) => {
    try {
      const response = await apiClient.get<{content: string}>(`/api/learn/topics/${topicId}/scratchpad`);
      setScratchpadContent(response?.content || '');
    } catch (error) {
      console.error('Failed to load scratchpad:', error);
    }
  };

  const saveScratchpad = async () => {
    if (!selectedTopic) return;
    try {
      await apiClient.put(`/api/learn/topics/${selectedTopic.id}/scratchpad`, {
        content: scratchpadContent
      });
    } catch (error) {
      console.error('Failed to save scratchpad:', error);
    }
  };

  const selectTopic = (topic: Topic) => {
    setSelectedTopic(topic);
    loadScratchpad(topic.id);
    setMessages([]);
  };

  const createTopic = async () => {
    if (!newTopicTitle.trim()) {
      Alert.alert('Error', 'Please enter a topic title');
      return;
    }

    try {
      setCreatingTopic(true);

      // Create the topic
      const topic = await apiClient.post<Topic>('/api/learn/topics', {
        title: newTopicTitle.trim(),
        description: newTopicDescription.trim() || null,
        priority: 5
      });

      // If auto-research is enabled, trigger it
      if (autoResearch && topic?.id) {
        try {
          const researchResult = await apiClient.post<{sources_added: number, sources_fetched: number}>(
            `/api/learn/topics/${topic.id}/auto-research`
          );
          Alert.alert(
            'Topic Created',
            `"${newTopicTitle}" created with ${researchResult.sources_added || 0} sources found and ${researchResult.sources_fetched || 0} processed.`
          );
        } catch (researchError) {
          console.error('Auto-research failed:', researchError);
          Alert.alert('Topic Created', `"${newTopicTitle}" created. Auto-research encountered an error, but the topic is ready.`);
        }
      } else {
        Alert.alert('Topic Created', `"${newTopicTitle}" has been created.`);
      }

      // Reset and refresh
      setShowNewTopicModal(false);
      setNewTopicTitle('');
      setNewTopicDescription('');
      loadTopics();

    } catch (error) {
      console.error('Failed to create topic:', error);
      Alert.alert('Error', 'Failed to create topic. Please try again.');
    } finally {
      setCreatingTopic(false);
    }
  };

  // Chat functions
  const sendMessage = async (text: string) => {
    if (!text.trim() || isStreaming) return;

    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: text.trim(),
    };

    setMessages(prev => [...prev, userMessage]);
    setChatInput('');
    setIsStreaming(true);
    setStreamingMessage('');
    streamingMessageRef.current = '';

    try {
      // Get auth token for the request
      const token = await apiClient.getToken();

      // Use learning chat endpoint
      const response = await fetch(`${apiClient.baseURL}/api/learn/chat/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          message: text.trim(),
          topic_id: selectedTopic?.id,
        }),
      });

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          const chunk = decoder.decode(value);
          const lines = chunk.split('\n');

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const data = JSON.parse(line.slice(6));
                if (data.type === 'token' && data.data?.content) {
                  streamingMessageRef.current += data.data.content;
                  setStreamingMessage(streamingMessageRef.current);
                } else if (data.type === 'final_response') {
                  streamingMessageRef.current = data.data?.content || streamingMessageRef.current;
                }
              } catch (e) {
                // Ignore parse errors
              }
            }
          }
        }
      }

      const assistantMessage: Message = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: streamingMessageRef.current,
      };
      setMessages(prev => [...prev, assistantMessage]);

      // Speak in ambient mode
      if (ambientMode && streamingMessageRef.current) {
        setIsPlayingAudio(true);
        await voiceService.speak(streamingMessageRef.current);
        setIsPlayingAudio(false);

        if (shouldResumeListening.current) {
          startContinuousListening();
        }
      }
    } catch (error) {
      console.error('Chat error:', error);
      Alert.alert('Error', 'Failed to send message');
    } finally {
      setIsStreaming(false);
      setStreamingMessage('');
      streamingMessageRef.current = '';
    }
  };

  // Voice functions
  const startContinuousListening = async () => {
    try {
      setIsListening(true);
      Animated.loop(
        Animated.sequence([
          Animated.timing(scaleAnim, { toValue: 1.3, duration: 600, useNativeDriver: true }),
          Animated.timing(scaleAnim, { toValue: 1, duration: 600, useNativeDriver: true }),
        ])
      ).start();

      await voiceService.startContinuousRecording(async () => {
        setIsListening(false);
        scaleAnim.stopAnimation();
        scaleAnim.setValue(1);

        const audioUri = await voiceService.stopRecording();
        if (audioUri) {
          const transcribed = await voiceService.transcribeAudio(audioUri);
          if (transcribed?.trim()) {
            await sendMessage(transcribed);
          } else if (shouldResumeListening.current) {
            startContinuousListening();
          }
        }
      });
    } catch (error) {
      console.error('Failed to start listening:', error);
      setIsListening(false);
    }
  };

  const toggleAmbientMode = async () => {
    if (ambientMode) {
      shouldResumeListening.current = false;
      setAmbientMode(false);
      setIsListening(false);
      try {
        await voiceService.stopRecording();
      } catch (e) {}
    } else {
      setAmbientMode(true);
      shouldResumeListening.current = true;
      await startContinuousListening();
    }
  };

  const getMasteryColor = (level: number) => {
    if (level >= 0.85) return '#10B981';
    if (level >= 0.6) return '#14B8A6';
    if (level >= 0.3) return '#F59E0B';
    return '#F97316';
  };

  const renderTopicsList = () => (
    <ScrollView
      style={styles.tabContent}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); loadTopics(); }} />
      }
    >
      {selectedTopic ? (
        <View>
          {/* Selected Topic Header */}
          <TouchableOpacity style={styles.backButton} onPress={() => setSelectedTopic(null)}>
            <Text style={styles.backButtonText}>← All Topics</Text>
          </TouchableOpacity>

          <View style={styles.topicHeader}>
            <Text style={styles.topicTitle}>{selectedTopic.title}</Text>
            <View style={styles.masteryBadge}>
              <View style={[styles.masteryDot, { backgroundColor: getMasteryColor(selectedTopic.mastery_level) }]} />
              <Text style={styles.masteryText}>{Math.round(selectedTopic.mastery_level * 100)}% mastery</Text>
            </View>
            {selectedTopic.description && (
              <Text style={styles.topicDescription}>{selectedTopic.description}</Text>
            )}
          </View>

          {/* Actions */}
          <View style={styles.actionsRow}>
            <TouchableOpacity
              style={styles.actionButton}
              onPress={() => { loadFlashcards(selectedTopic.id); setActiveTab('flashcards'); }}
            >
              <Text style={styles.actionIcon}>🎴</Text>
              <Text style={styles.actionText}>Flashcards</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.actionButton}
              onPress={() => setActiveTab('chat')}
            >
              <Text style={styles.actionIcon}>💬</Text>
              <Text style={styles.actionText}>Study Chat</Text>
            </TouchableOpacity>
          </View>

          {/* Scratchpad */}
          <View style={styles.scratchpadSection}>
            <Text style={styles.sectionTitle}>Notes</Text>
            <TextInput
              style={styles.scratchpad}
              value={scratchpadContent}
              onChangeText={setScratchpadContent}
              onBlur={saveScratchpad}
              placeholder="Take notes while studying..."
              placeholderTextColor={colors.textMuted}
              multiline
              textAlignVertical="top"
            />
          </View>
        </View>
      ) : (
        <View>
          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle}>Your Learning Topics</Text>
            <TouchableOpacity
              style={styles.addButton}
              onPress={() => setShowNewTopicModal(true)}
            >
              <Text style={styles.addButtonText}>+ New</Text>
            </TouchableOpacity>
          </View>
          {loading ? (
            <ActivityIndicator color={colors.primary} style={{ marginTop: 40 }} />
          ) : topics.length === 0 ? (
            <View style={styles.emptyState}>
              <Text style={styles.emptyIcon}>📚</Text>
              <Text style={styles.emptyText}>No topics yet</Text>
              <Text style={styles.emptySubtext}>Tap "+ New" above to create your first learning topic</Text>
              <TouchableOpacity
                style={styles.createTopicButton}
                onPress={() => setShowNewTopicModal(true)}
              >
                <Text style={styles.createTopicButtonText}>Create Topic</Text>
              </TouchableOpacity>
            </View>
          ) : (
            topics.map(topic => (
              <TouchableOpacity
                key={topic.id}
                style={styles.topicCard}
                onPress={() => selectTopic(topic)}
              >
                <View style={styles.topicCardContent}>
                  <Text style={styles.topicCardTitle}>{topic.title}</Text>
                  {topic.description && (
                    <Text style={styles.topicCardDesc} numberOfLines={2}>{topic.description}</Text>
                  )}
                  <View style={styles.topicCardMeta}>
                    <View style={[styles.masteryBar, { backgroundColor: colors.border }]}>
                      <View style={[
                        styles.masteryFill,
                        { width: `${topic.mastery_level * 100}%`, backgroundColor: getMasteryColor(topic.mastery_level) }
                      ]} />
                    </View>
                    <Text style={styles.masteryPercent}>{Math.round(topic.mastery_level * 100)}%</Text>
                  </View>
                </View>
                <Text style={styles.chevron}>›</Text>
              </TouchableOpacity>
            ))
          )}
        </View>
      )}
    </ScrollView>
  );

  const renderFlashcards = () => {
    const currentCard = flashcards[currentCardIndex];

    return (
      <View style={styles.tabContent}>
        {selectedTopic && (
          <TouchableOpacity style={styles.backButton} onPress={() => setActiveTab('topics')}>
            <Text style={styles.backButtonText}>← Back to {selectedTopic.title}</Text>
          </TouchableOpacity>
        )}

        {loading ? (
          <ActivityIndicator color={colors.primary} style={{ marginTop: 100 }} />
        ) : flashcards.length === 0 ? (
          <View style={styles.emptyState}>
            <Text style={styles.emptyIcon}>🎴</Text>
            <Text style={styles.emptyText}>No flashcards</Text>
            <Text style={styles.emptySubtext}>Select a topic to generate flashcards</Text>
          </View>
        ) : currentCard ? (
          <View style={styles.flashcardContainer}>
            <Text style={styles.cardProgress}>
              Card {currentCardIndex + 1} of {flashcards.length}
            </Text>

            <TouchableOpacity
              style={[styles.flashcard, showAnswer && styles.flashcardFlipped]}
              onPress={() => setShowAnswer(!showAnswer)}
              activeOpacity={0.9}
            >
              <Text style={styles.flashcardLabel}>{showAnswer ? 'ANSWER' : 'QUESTION'}</Text>
              <Text style={styles.flashcardText}>
                {showAnswer ? currentCard.back : currentCard.front}
              </Text>
              {!showAnswer && currentCard.hint && (
                <Text style={styles.flashcardHint}>Hint: {currentCard.hint}</Text>
              )}
              <Text style={styles.tapHint}>Tap to {showAnswer ? 'see question' : 'reveal answer'}</Text>
            </TouchableOpacity>

            <View style={styles.cardNavigation}>
              <TouchableOpacity
                style={[styles.navButton, currentCardIndex === 0 && styles.navButtonDisabled]}
                onPress={() => { setCurrentCardIndex(i => i - 1); setShowAnswer(false); }}
                disabled={currentCardIndex === 0}
              >
                <Text style={styles.navButtonText}>← Previous</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.navButton, currentCardIndex === flashcards.length - 1 && styles.navButtonDisabled]}
                onPress={() => { setCurrentCardIndex(i => i + 1); setShowAnswer(false); }}
                disabled={currentCardIndex === flashcards.length - 1}
              >
                <Text style={styles.navButtonText}>Next →</Text>
              </TouchableOpacity>
            </View>
          </View>
        ) : null}
      </View>
    );
  };

  const renderChat = () => (
    <KeyboardAvoidingView
      style={styles.chatContainer}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={0}
    >
      {selectedTopic && (
        <View style={styles.chatHeader}>
          <TouchableOpacity onPress={() => setActiveTab('topics')}>
            <Text style={styles.backButtonText}>← {selectedTopic.title}</Text>
          </TouchableOpacity>
        </View>
      )}

      {/* Ambient Mode Button */}
      {voiceInitialized && (
        <TouchableOpacity
          style={[styles.ambientButton, ambientMode && styles.ambientButtonActive]}
          onPress={toggleAmbientMode}
        >
          <View style={styles.ambientContent}>
            {ambientMode && isListening && (
              <Animated.View style={[styles.listeningPulse, { transform: [{ scale: scaleAnim }] }]} />
            )}
            <Text style={styles.ambientIcon}>{ambientMode ? '🎧' : '🎤'}</Text>
            <View style={styles.ambientTextContainer}>
              <Text style={[styles.ambientTitle, ambientMode && styles.ambientTitleActive]}>
                {ambientMode ? 'Ambient Learning Active' : 'Start Ambient Learning'}
              </Text>
              <Text style={styles.ambientSubtitle}>
                {ambientMode
                  ? (isListening ? 'Listening...' : isPlayingAudio ? 'Speaking...' : 'Processing...')
                  : 'Voice-to-voice study with Sara'}
              </Text>
            </View>
          </View>
        </TouchableOpacity>
      )}

      {/* Messages */}
      <FlatList
        data={messages}
        keyExtractor={(item) => item.id}
        style={styles.messagesList}
        contentContainerStyle={styles.messagesContent}
        renderItem={({ item }) => (
          <View style={[styles.messageBubble, item.role === 'user' ? styles.userBubble : styles.assistantBubble]}>
            <Text style={[styles.messageText, item.role === 'user' && styles.userMessageText]}>
              {item.content}
            </Text>
          </View>
        )}
        ListFooterComponent={
          streamingMessage ? (
            <View style={[styles.messageBubble, styles.assistantBubble]}>
              <Text style={styles.messageText}>{streamingMessage}</Text>
            </View>
          ) : null
        }
        ListEmptyComponent={
          <View style={styles.chatEmpty}>
            <Text style={styles.chatEmptyText}>
              {selectedTopic
                ? `Ask Sara about ${selectedTopic.title}`
                : 'Select a topic or start chatting'}
            </Text>
          </View>
        }
      />

      {/* Text Input */}
      <View style={styles.chatInputContainer}>
        <TextInput
          style={styles.chatInput}
          value={chatInput}
          onChangeText={setChatInput}
          placeholder="Ask a question..."
          placeholderTextColor={colors.textMuted}
          multiline
          editable={!isStreaming && !ambientMode}
        />
        <TouchableOpacity
          style={[styles.sendButton, (!chatInput.trim() || isStreaming) && styles.sendButtonDisabled]}
          onPress={() => sendMessage(chatInput)}
          disabled={!chatInput.trim() || isStreaming || ambientMode}
        >
          <Text style={styles.sendButtonText}>➤</Text>
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );

  return (
    <SafeAreaView style={styles.container} edges={['top', 'bottom']}>
      {/* Tab Bar */}
      <View style={styles.tabBar}>
        {(['topics', 'flashcards', 'chat'] as TabType[]).map(tab => (
          <TouchableOpacity
            key={tab}
            style={[styles.tab, activeTab === tab && styles.activeTab]}
            onPress={() => setActiveTab(tab)}
          >
            <Text style={[styles.tabText, activeTab === tab && styles.activeTabText]}>
              {tab === 'topics' ? '📚 Topics' : tab === 'flashcards' ? '🎴 Cards' : '💬 Chat'}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {/* Content */}
      {activeTab === 'topics' && renderTopicsList()}
      {activeTab === 'flashcards' && renderFlashcards()}
      {activeTab === 'chat' && renderChat()}

      {/* New Topic Modal */}
      <Modal
        visible={showNewTopicModal}
        animationType="slide"
        transparent={true}
        onRequestClose={() => setShowNewTopicModal(false)}
      >
        <KeyboardAvoidingView
          style={styles.modalOverlay}
          behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        >
          <TouchableOpacity
            style={styles.modalDismiss}
            activeOpacity={1}
            onPress={() => setShowNewTopicModal(false)}
          />
          <View style={styles.modalContent}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>New Learning Topic</Text>
              <TouchableOpacity onPress={() => setShowNewTopicModal(false)}>
                <Text style={styles.modalClose}>✕</Text>
              </TouchableOpacity>
            </View>

            <TextInput
              style={styles.modalInput}
              placeholder="Topic Title (e.g., Machine Learning, Spanish, Photography)"
              placeholderTextColor={colors.textMuted}
              value={newTopicTitle}
              onChangeText={setNewTopicTitle}
              autoFocus
            />

            <TextInput
              style={[styles.modalInput, styles.modalTextArea]}
              placeholder="Description (optional) - What do you want to learn about this topic?"
              placeholderTextColor={colors.textMuted}
              value={newTopicDescription}
              onChangeText={setNewTopicDescription}
              multiline
              numberOfLines={3}
              textAlignVertical="top"
            />

            <View style={styles.switchRow}>
              <View style={styles.switchLabel}>
                <Text style={styles.switchTitle}>Auto-find sources</Text>
                <Text style={styles.switchSubtitle}>Search the web for learning materials</Text>
              </View>
              <Switch
                value={autoResearch}
                onValueChange={setAutoResearch}
                trackColor={{ false: colors.border, true: colors.primary }}
                thumbColor="#fff"
              />
            </View>

            <TouchableOpacity
              style={[styles.modalCreateButton, creatingTopic && styles.modalCreateButtonDisabled]}
              onPress={createTopic}
              disabled={creatingTopic}
            >
              {creatingTopic ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <Text style={styles.modalCreateButtonText}>
                  {autoResearch ? 'Create & Find Sources' : 'Create Topic'}
                </Text>
              )}
            </TouchableOpacity>
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  tabBar: {
    flexDirection: 'row',
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  tab: {
    flex: 1,
    paddingVertical: spacing.md,
    alignItems: 'center',
  },
  activeTab: {
    borderBottomWidth: 2,
    borderBottomColor: colors.primary,
  },
  tabText: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  activeTabText: {
    color: colors.primary,
  },
  tabContent: {
    flex: 1,
    padding: spacing.md,
  },
  sectionTitle: {
    fontSize: fontSizes.lg,
    fontWeight: '700',
    color: colors.text,
    marginBottom: spacing.md,
  },
  backButton: {
    marginBottom: spacing.md,
  },
  backButtonText: {
    color: colors.primary,
    fontSize: fontSizes.md,
  },
  topicCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    marginBottom: spacing.sm,
    flexDirection: 'row',
    alignItems: 'center',
  },
  topicCardContent: {
    flex: 1,
  },
  topicCardTitle: {
    fontSize: fontSizes.md,
    fontWeight: '600',
    color: colors.text,
    marginBottom: 4,
  },
  topicCardDesc: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
    marginBottom: spacing.sm,
  },
  topicCardMeta: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  masteryBar: {
    flex: 1,
    height: 4,
    borderRadius: 2,
    marginRight: spacing.sm,
  },
  masteryFill: {
    height: '100%',
    borderRadius: 2,
  },
  masteryPercent: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    width: 35,
  },
  chevron: {
    fontSize: 24,
    color: colors.textMuted,
  },
  topicHeader: {
    marginBottom: spacing.lg,
  },
  topicTitle: {
    fontSize: fontSizes.xl,
    fontWeight: '700',
    color: colors.text,
    marginBottom: spacing.sm,
  },
  masteryBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: spacing.sm,
  },
  masteryDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginRight: spacing.xs,
  },
  masteryText: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
  },
  topicDescription: {
    fontSize: fontSizes.md,
    color: colors.textSecondary,
  },
  actionsRow: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginBottom: spacing.lg,
  },
  actionButton: {
    flex: 1,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    alignItems: 'center',
  },
  actionIcon: {
    fontSize: 28,
    marginBottom: spacing.xs,
  },
  actionText: {
    fontSize: fontSizes.sm,
    color: colors.text,
    fontWeight: '600',
  },
  scratchpadSection: {
    marginTop: spacing.md,
  },
  scratchpad: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    color: colors.text,
    fontSize: fontSizes.md,
    minHeight: 150,
  },
  emptyState: {
    alignItems: 'center',
    paddingVertical: 60,
  },
  emptyIcon: {
    fontSize: 48,
    marginBottom: spacing.md,
  },
  emptyText: {
    fontSize: fontSizes.lg,
    fontWeight: '600',
    color: colors.text,
    marginBottom: spacing.xs,
  },
  emptySubtext: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
    textAlign: 'center',
  },
  // Flashcards
  flashcardContainer: {
    flex: 1,
    alignItems: 'center',
    paddingTop: spacing.xl,
  },
  cardProgress: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
    marginBottom: spacing.md,
  },
  flashcard: {
    width: '100%',
    backgroundColor: colors.surface,
    borderRadius: borderRadius.xl,
    padding: spacing.xl,
    minHeight: 250,
    justifyContent: 'center',
    alignItems: 'center',
    borderWidth: 2,
    borderColor: colors.border,
  },
  flashcardFlipped: {
    backgroundColor: '#059669' + '15',
    borderColor: '#059669',
  },
  flashcardLabel: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    marginBottom: spacing.md,
    letterSpacing: 1,
  },
  flashcardText: {
    fontSize: fontSizes.lg,
    color: colors.text,
    textAlign: 'center',
    lineHeight: 28,
  },
  flashcardHint: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
    marginTop: spacing.lg,
    fontStyle: 'italic',
  },
  tapHint: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    marginTop: spacing.xl,
  },
  cardNavigation: {
    flexDirection: 'row',
    marginTop: spacing.xl,
    gap: spacing.md,
  },
  navButton: {
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.lg,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
  },
  navButtonDisabled: {
    opacity: 0.4,
  },
  navButtonText: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
  },
  // Chat
  chatContainer: {
    flex: 1,
  },
  chatHeader: {
    padding: spacing.md,
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  ambientButton: {
    margin: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    borderWidth: 2,
    borderColor: colors.border,
    overflow: 'hidden',
  },
  ambientButtonActive: {
    backgroundColor: '#059669' + '15',
    borderColor: '#059669',
  },
  ambientContent: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: spacing.md,
  },
  listeningPulse: {
    position: 'absolute',
    left: spacing.md,
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: '#059669' + '30',
  },
  ambientIcon: {
    fontSize: 28,
    marginRight: spacing.md,
    zIndex: 1,
  },
  ambientTextContainer: {
    flex: 1,
  },
  ambientTitle: {
    fontSize: fontSizes.md,
    fontWeight: '700',
    color: colors.text,
  },
  ambientTitleActive: {
    color: '#059669',
  },
  ambientSubtitle: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    marginTop: 2,
  },
  messagesList: {
    flex: 1,
  },
  messagesContent: {
    padding: spacing.md,
    paddingBottom: spacing.xl,
  },
  messageBubble: {
    maxWidth: '85%',
    padding: spacing.md,
    borderRadius: borderRadius.lg,
    marginBottom: spacing.sm,
  },
  userBubble: {
    backgroundColor: colors.primary,
    alignSelf: 'flex-end',
    borderBottomRightRadius: 4,
  },
  assistantBubble: {
    backgroundColor: colors.surface,
    alignSelf: 'flex-start',
    borderBottomLeftRadius: 4,
  },
  messageText: {
    color: colors.text,
    fontSize: fontSizes.md,
    lineHeight: 22,
  },
  userMessageText: {
    color: '#fff',
  },
  chatEmpty: {
    alignItems: 'center',
    paddingVertical: 60,
  },
  chatEmptyText: {
    color: colors.textMuted,
    fontSize: fontSizes.md,
  },
  chatInputContainer: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    padding: spacing.md,
    backgroundColor: colors.surface,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  chatInput: {
    flex: 1,
    backgroundColor: colors.background,
    borderRadius: borderRadius.lg,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    color: colors.text,
    fontSize: fontSizes.md,
    maxHeight: 100,
  },
  sendButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.primary,
    justifyContent: 'center',
    alignItems: 'center',
    marginLeft: spacing.sm,
  },
  sendButtonDisabled: {
    opacity: 0.4,
  },
  sendButtonText: {
    color: '#fff',
    fontSize: fontSizes.lg,
  },
  // Section header with add button
  sectionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  addButton: {
    backgroundColor: colors.primary,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.md,
  },
  addButtonText: {
    color: '#fff',
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  createTopicButton: {
    backgroundColor: colors.primary,
    paddingHorizontal: spacing.xl,
    paddingVertical: spacing.md,
    borderRadius: borderRadius.lg,
    marginTop: spacing.lg,
  },
  createTopicButtonText: {
    color: '#fff',
    fontSize: fontSizes.md,
    fontWeight: '600',
  },
  // Modal styles
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0, 0, 0, 0.7)',
    justifyContent: 'flex-end',
  },
  modalDismiss: {
    flex: 1,
  },
  modalContent: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: borderRadius.xl,
    borderTopRightRadius: borderRadius.xl,
    padding: spacing.lg,
    paddingBottom: spacing.xl + 20,
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.lg,
  },
  modalTitle: {
    fontSize: fontSizes.lg,
    fontWeight: '700',
    color: colors.text,
  },
  modalClose: {
    fontSize: 24,
    color: colors.textMuted,
    padding: spacing.sm,
  },
  modalInput: {
    backgroundColor: colors.background,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    color: colors.text,
    fontSize: fontSizes.md,
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  modalTextArea: {
    minHeight: 80,
    textAlignVertical: 'top',
  },
  switchRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: spacing.md,
    marginBottom: spacing.md,
  },
  switchLabel: {
    flex: 1,
  },
  switchTitle: {
    fontSize: fontSizes.md,
    fontWeight: '600',
    color: colors.text,
  },
  switchSubtitle: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    marginTop: 2,
  },
  modalCreateButton: {
    backgroundColor: colors.primary,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    alignItems: 'center',
    marginTop: spacing.sm,
  },
  modalCreateButtonDisabled: {
    opacity: 0.6,
  },
  modalCreateButtonText: {
    color: '#fff',
    fontSize: fontSizes.md,
    fontWeight: '700',
  },
});
