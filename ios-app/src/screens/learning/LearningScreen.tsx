import React, { useMemo, useState, useEffect, useRef } from 'react';
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
import Markdown, { MarkdownIt } from 'react-native-markdown-display';
import type { RenderRules } from 'react-native-markdown-display';
import MathView from 'react-native-math-view';
import * as DocumentPicker from 'expo-document-picker';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import { apiClient } from '../../services/api';
import { voiceService } from '../../services/voice';
import { chatService } from '../../services/chat';
import { BlueprintSource, GuideArtifact, GuideGenerationJob, LearningBlueprintSummary, LessonArtifact, learningService } from '../../services/learning';

type TabType = 'topics' | 'flashcards' | 'chat' | 'sources' | 'guides';

interface Topic {
  id: string;
  parent_id?: string | null;
  title: string;
  description: string;
  mastery_level: number;
  status: string;
  priority: number;
}

interface TopicTreeRow {
  topic: Topic;
  depth: number;
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

const MATH_INLINE_TOKEN = 'math_inline';
const MATH_BLOCK_TOKEN = 'math_block';

const markdownMathPlugin = (md: any) => {
  const inlineMathRule = (state: any, silent: boolean): boolean => {
    const src: string = state.src;
    const start: number = state.pos;

    // Handle $...$ inline math.
    if (src[start] === '$' && src[start + 1] !== '$') {
      const nextChar = src[start + 1];
      if (!nextChar || /\s/.test(nextChar)) {
        return false;
      }

      let end = start + 1;
      while ((end = src.indexOf('$', end + 1)) !== -1) {
        if (src[end - 1] === '\\') {
          continue;
        }

        const content = src.slice(start + 1, end).trim();
        if (!content || /\n/.test(content)) {
          continue;
        }

        if (!silent) {
          const token = state.push(MATH_INLINE_TOKEN, 'math', 0);
          token.content = content;
          // Mark as block token so markdown renderer does not nest it in Text.
          token.block = true;
          token.markup = '$';
        }

        state.pos = end + 1;
        return true;
      }

      return false;
    }

    // Handle \( ... \) inline math.
    if (src[start] === '\\' && src[start + 1] === '(') {
      const close = src.indexOf('\\)', start + 2);
      if (close === -1) {
        return false;
      }

      const content = src.slice(start + 2, close).trim();
      if (!content) {
        return false;
      }

      if (!silent) {
        const token = state.push(MATH_INLINE_TOKEN, 'math', 0);
        token.content = content;
        token.block = true;
        token.markup = '\\(\\)';
      }

      state.pos = close + 2;
      return true;
    }

    // Handle \[ ... \] display-style math.
    if (src[start] === '\\' && src[start + 1] === '[') {
      const close = src.indexOf('\\]', start + 2);
      if (close === -1) {
        return false;
      }

      const content = src.slice(start + 2, close).trim();
      if (!content) {
        return false;
      }

      if (!silent) {
        const token = state.push(MATH_BLOCK_TOKEN, 'math', 0);
        token.content = content;
        token.block = true;
        token.markup = '\\[\\]';
      }

      state.pos = close + 2;
      return true;
    }

    return false;
  };

  const blockMathRule = (
    state: any,
    startLine: number,
    endLine: number,
    silent: boolean,
  ): boolean => {
    const start = state.bMarks[startLine] + state.tShift[startLine];
    const max = state.eMarks[startLine];

    if (start + 2 > max || state.src.slice(start, start + 2) !== '$$') {
      return false;
    }

    if (silent) {
      return true;
    }

    let nextLine = startLine;
    let content = '';
    let found = false;

    const firstLine = state.src.slice(start + 2, max);
    const firstLineTrimmed = firstLine.trimEnd();

    if (firstLineTrimmed.endsWith('$$')) {
      content = firstLineTrimmed.slice(0, -2).trim();
      found = true;
    } else {
      const lines: string[] = [];
      if (firstLine.length > 0) {
        lines.push(firstLine);
      }

      while (nextLine + 1 < endLine) {
        nextLine += 1;
        const lineStart = state.bMarks[nextLine] + state.tShift[nextLine];
        const lineMax = state.eMarks[nextLine];
        const line = state.src.slice(lineStart, lineMax);
        const lineTrimmed = line.trimEnd();

        if (lineTrimmed.endsWith('$$')) {
          const maybeContent = lineTrimmed.slice(0, -2);
          if (maybeContent.length > 0) {
            lines.push(maybeContent);
          }
          found = true;
          break;
        }

        lines.push(line);
      }

      if (found) {
        content = lines.join('\n').trim();
      }
    }

    if (!found) {
      return false;
    }

    const token = state.push(MATH_BLOCK_TOKEN, 'math', 0);
    token.block = true;
    token.content = content;
    token.map = [startLine, nextLine + 1];
    token.markup = '$$';
    state.line = nextLine + 1;
    return true;
  };

  md.inline.ruler.before('escape', MATH_INLINE_TOKEN, inlineMathRule);
  md.block.ruler.before('fence', MATH_BLOCK_TOKEN, blockMathRule, {
    alt: ['paragraph', 'reference', 'blockquote', 'list'],
  });
};

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

  // Study guide state
  const [blueprints, setBlueprints] = useState<LearningBlueprintSummary[]>([]);
  const [selectedBlueprintId, setSelectedBlueprintId] = useState<string | null>(null);
  const [guideJobs, setGuideJobs] = useState<GuideGenerationJob[]>([]);
  const [activeGuideJob, setActiveGuideJob] = useState<GuideGenerationJob | null>(null);
  const [guides, setGuides] = useState<GuideArtifact[]>([]);
  const [guidesLoading, setGuidesLoading] = useState(false);
  const [guideBusy, setGuideBusy] = useState(false);
  const [selectedGuide, setSelectedGuide] = useState<GuideArtifact | null>(null);
  const [showGuideModal, setShowGuideModal] = useState(false);
  const [sourceUploading, setSourceUploading] = useState(false);

  // Lesson state
  type GuidesSubTab = 'guides' | 'lessons';
  const [guidesSubTab, setGuidesSubTab] = useState<GuidesSubTab>('guides');
  const [lessons, setLessons] = useState<LessonArtifact[]>([]);
  const [lessonsLoading, setLessonsLoading] = useState(false);
  const [lessonBusy, setLessonBusy] = useState(false);
  const [activeLessonJob, setActiveLessonJob] = useState<GuideGenerationJob | null>(null);
  const [selectedLesson, setSelectedLesson] = useState<LessonArtifact | null>(null);
  const [showLessonModal, setShowLessonModal] = useState(false);

  // Sources tab state
  const [blueprintSources, setBlueprintSources] = useState<BlueprintSource[]>([]);
  const [sourcesLoading, setSourcesLoading] = useState(false);

  const markdownItWithMath = useMemo(
    () => MarkdownIt({ typographer: true }).use(markdownMathPlugin),
    [],
  );

  const markdownMathRules = useMemo<RenderRules>(() => ({
    math_inline: (node) => (
      <View key={node.key} style={styles.mathInlineWrapper}>
        <MathView
          math={node.content}
          resizeMode="contain"
          style={styles.mathInline}
          color={colors.text}
        />
      </View>
    ),
    math_block: (node) => (
      <View key={node.key} style={styles.mathBlockWrapper}>
        <MathView
          math={node.content}
          resizeMode="contain"
          style={styles.mathBlock}
          color={colors.text}
        />
      </View>
    ),
  }), []);

  useEffect(() => {
    loadTopics();
    loadBlueprints();
    initVoice();
    return () => {
      voiceService.cleanup();
    };
  }, []);

  useEffect(() => {
    if (activeTab !== 'guides' || !selectedBlueprintId) return;
    loadGuidesForBlueprint(selectedBlueprintId);
  }, [activeTab, selectedBlueprintId]);

  useEffect(() => {
    if (activeTab !== 'sources' || !selectedBlueprintId) return;
    loadSourcesForBlueprint(selectedBlueprintId);
  }, [activeTab, selectedBlueprintId]);

  useEffect(() => {
    if (!selectedBlueprintId || !activeGuideJob) return;
    if (!['queued', 'running', 'cancelling'].includes(activeGuideJob.status)) return;

    const timer = setTimeout(async () => {
      try {
        const latest = await learningService.getGuideJob(selectedBlueprintId, activeGuideJob.id);
        setActiveGuideJob(latest);
        if (['completed', 'failed', 'cancelled'].includes(latest.status)) {
          await loadGuidesForBlueprint(selectedBlueprintId);
        }
      } catch (error) {
        console.error('Guide job polling failed:', error);
      }
    }, 2500);

    return () => clearTimeout(timer);
  }, [selectedBlueprintId, activeGuideJob]);

  // Load lessons when switching to lessons sub-tab
  useEffect(() => {
    if (activeTab !== 'guides' || guidesSubTab !== 'lessons' || !selectedBlueprintId) return;
    loadLessonsForBlueprint(selectedBlueprintId);
  }, [activeTab, guidesSubTab, selectedBlueprintId]);

  // Poll active lesson job
  useEffect(() => {
    if (!selectedBlueprintId || !activeLessonJob) return;
    if (!['queued', 'running', 'cancelling'].includes(activeLessonJob.status)) return;

    const timer = setTimeout(async () => {
      try {
        const latest = await learningService.getGuideJob(selectedBlueprintId, activeLessonJob.id);
        setActiveLessonJob(latest);
        if (['completed', 'failed', 'cancelled'].includes(latest.status)) {
          await loadLessonsForBlueprint(selectedBlueprintId);
        }
      } catch (error) {
        console.error('Lesson job polling failed:', error);
      }
    }, 2500);

    return () => clearTimeout(timer);
  }, [selectedBlueprintId, activeLessonJob]);

  const initVoice = async () => {
    const initialized = await voiceService.initialize();
    setVoiceInitialized(initialized);
  };

  const loadTopics = async () => {
    try {
      setLoading(true);
      const response = await apiClient.get<Topic[]>('/api/learn/topics?status=active&include_all=true');
      // apiClient.get already returns response.data, not wrapped in a .data property
      setTopics(response || []);
    } catch (error) {
      console.error('Failed to load topics:', error);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const loadBlueprints = async () => {
    try {
      const rows = await learningService.listBlueprints();
      setBlueprints(rows);
      if (rows.length > 0) {
        const preferred = selectedBlueprintId && rows.some((bp) => bp.id === selectedBlueprintId)
          ? selectedBlueprintId
          : rows[0].id;
        setSelectedBlueprintId(preferred);
      } else {
        setSelectedBlueprintId(null);
      }
    } catch (error) {
      console.error('Failed to load blueprints:', error);
    }
  };

  const loadSourcesForBlueprint = async (blueprintId: string) => {
    try {
      setSourcesLoading(true);
      const sources = await learningService.listBlueprintSources(blueprintId);
      setBlueprintSources(sources);
    } catch (error) {
      console.error('Failed to load sources:', error);
    } finally {
      setSourcesLoading(false);
    }
  };

  const loadGuidesForBlueprint = async (blueprintId: string) => {
    try {
      setGuidesLoading(true);
      const [jobs, guideRows] = await Promise.all([
        learningService.listGuideJobs(blueprintId, 20),
        learningService.listGuides(blueprintId),
      ]);
      setGuideJobs(jobs);
      setGuides(guideRows);
      setActiveGuideJob(jobs[0] || null);
    } catch (error) {
      console.error('Failed to load guides:', error);
      Alert.alert('Error', 'Failed to load study guides');
    } finally {
      setGuidesLoading(false);
    }
  };

  const generateGuides = async (forceRegenerate: boolean = false) => {
    if (!selectedBlueprintId || guideBusy) return;
    try {
      setGuideBusy(true);
      const response = await learningService.generateBlueprintGuides(selectedBlueprintId, {
        model: 'gpt-oss:120b',
        force_regenerate: forceRegenerate,
        num_ctx: 32768,
      });

      const queued = await learningService.getGuideJob(selectedBlueprintId, response.job_id);
      setActiveGuideJob(queued);
      Alert.alert(
        'Guide Generation Started',
        forceRegenerate
          ? 'Regeneration queued. New sources will be used to enhance existing guides.'
          : 'Generation queued. You can keep using the app while it runs.'
      );
      await loadGuidesForBlueprint(selectedBlueprintId);
    } catch (error) {
      console.error('Failed to generate guides:', error);
      Alert.alert('Error', 'Failed to start guide generation');
    } finally {
      setGuideBusy(false);
    }
  };

  const discoverResources = async () => {
    if (!selectedBlueprintId) return;
    try {
      setGuideBusy(true);
      await learningService.discoverResources(selectedBlueprintId);
      Alert.alert(
        'Resource Discovery Started',
        'Searching for free versions of textbooks and papers referenced in this blueprint. Sources will be fetched automatically once found.'
      );
    } catch (error) {
      console.error('Failed to discover resources:', error);
      Alert.alert('Error', 'Failed to start resource discovery');
    } finally {
      setGuideBusy(false);
    }
  };

  const cancelGuideGeneration = async () => {
    if (!selectedBlueprintId || !activeGuideJob?.id) return;
    try {
      setGuideBusy(true);
      const updated = await learningService.cancelGuideJob(selectedBlueprintId, activeGuideJob.id);
      if (updated) {
        setActiveGuideJob(updated);
      }
      await loadGuidesForBlueprint(selectedBlueprintId);
    } catch (error) {
      console.error('Failed to cancel guide generation:', error);
      Alert.alert('Error', 'Failed to cancel guide generation');
    } finally {
      setGuideBusy(false);
    }
  };

  const loadLessonsForBlueprint = async (blueprintId: string) => {
    try {
      setLessonsLoading(true);
      const [jobs, lessonRows] = await Promise.all([
        learningService.listLessonJobs(blueprintId, 20),
        learningService.listLessons(blueprintId),
      ]);
      setLessons(lessonRows);
      setActiveLessonJob(jobs[0] || null);
    } catch (error) {
      console.error('Failed to load lessons:', error);
    } finally {
      setLessonsLoading(false);
    }
  };

  const generateLessons = async () => {
    if (!selectedBlueprintId || lessonBusy) return;
    try {
      setLessonBusy(true);
      const response = await learningService.generateBlueprintLessons(selectedBlueprintId, {
        model: 'gpt-oss:120b',
        num_ctx: 65536,
      });
      const queued = await learningService.getGuideJob(selectedBlueprintId, response.job_id);
      setActiveLessonJob(queued);
      Alert.alert('Lesson Generation Started', 'Lessons are being generated. This takes ~10-15 min per module.');
      await loadLessonsForBlueprint(selectedBlueprintId);
    } catch (error) {
      console.error('Failed to generate lessons:', error);
      Alert.alert('Error', 'Failed to start lesson generation');
    } finally {
      setLessonBusy(false);
    }
  };

  const cancelLessonGeneration = async () => {
    if (!selectedBlueprintId || !activeLessonJob?.id) return;
    try {
      setLessonBusy(true);
      const updated = await learningService.cancelGuideJob(selectedBlueprintId, activeLessonJob.id);
      if (updated) setActiveLessonJob(updated);
      await loadLessonsForBlueprint(selectedBlueprintId);
    } catch (error) {
      console.error('Failed to cancel lesson generation:', error);
    } finally {
      setLessonBusy(false);
    }
  };

  const uploadSourceForSelectedTopic = async () => {
    if (!selectedTopic?.id || sourceUploading) {
      if (!selectedTopic?.id) {
        Alert.alert('Select Topic', 'Open a topic first, then upload a source.');
      }
      return;
    }
    try {
      const result = await DocumentPicker.getDocumentAsync({
        type: ['application/pdf', 'text/plain', 'text/markdown'],
        copyToCacheDirectory: true,
      });

      const legacyCancelled = (result as any)?.type === 'cancel';
      if (result.canceled || legacyCancelled) {
        return;
      }

      const asset = result.assets?.[0] || ((result as any)?.uri ? {
        uri: (result as any).uri as string,
        name: ((result as any).name as string) || 'source-upload',
        mimeType: (result as any).mimeType as string | undefined,
      } : null);

      if (!asset?.uri) {
        Alert.alert('Upload Failed', 'Could not read the selected file.');
        return;
      }

      setSourceUploading(true);
      const uploadResult = await learningService.uploadSourceToTopic(selectedTopic.id, asset);
      Alert.alert(
        'Source Uploaded',
        uploadResult.status === 'processing'
          ? `${uploadResult.title} uploaded — processing in the background. You'll get a push notification when it's ready.`
          : `${uploadResult.title} processed with ${uploadResult.chunk_count || 0} chunks.`
      );
    } catch (error) {
      console.error('[Upload] Source upload failed:', error);
      const errStr = error instanceof Error
        ? `${error.name}: ${error.message}`
        : JSON.stringify(error);
      Alert.alert('Upload Failed', errStr);
    } finally {
      setSourceUploading(false);
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

      if (!response.ok) {
        const errorBody = await response.text();
        throw new Error(errorBody || `Chat request failed (${response.status})`);
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      if (!reader) {
        throw new Error('No streaming response body available.');
      }

      let buffer = '';
      let streamError: string | null = null;
      const processSseLine = (line: string) => {
        if (!line.startsWith('data: ')) return;

        const raw = line.slice(6).trim();
        if (!raw || raw === '[DONE]') return;

        let event: any;
        try {
          event = JSON.parse(raw);
        } catch (e) {
          // Keep stream resilient to partial/invalid chunks.
          return;
        }

        if (event?.type === 'error') {
          streamError = event?.message || event?.data?.message || 'Streaming error';
          return;
        }

        if (event?.type === 'text_chunk' || event?.type === 'token') {
          const contentChunk = event?.data?.content || event?.content || '';
          if (contentChunk) {
            streamingMessageRef.current += contentChunk;
            setStreamingMessage(streamingMessageRef.current);
          }
          return;
        }

        if (event?.type === 'final_response') {
          const finalContent = event?.data?.content || event?.content || '';
          if (finalContent) {
            streamingMessageRef.current = finalContent;
            setStreamingMessage(finalContent);
          }
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          processSseLine(line.trim());
          if (streamError) break;
        }
        if (streamError) break;
      }

      if (buffer.trim()) {
        processSseLine(buffer.trim());
      }

      if (streamError) {
        throw new Error(streamError);
      }

      if (!streamingMessageRef.current.trim()) {
        throw new Error('No response content returned.');
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
        try {
          await voiceService.speak(streamingMessageRef.current);
        } catch (ttsError) {
          console.error('[Learning] TTS playback failed:', ttsError);
        } finally {
          setIsPlayingAudio(false);
        }

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

  const buildTopicTreeRows = (): TopicTreeRow[] => {
    const childrenByParent = new Map<string | null, Topic[]>();
    for (const topic of topics) {
      const key = topic.parent_id || null;
      const existing = childrenByParent.get(key);
      if (existing) {
        existing.push(topic);
      } else {
        childrenByParent.set(key, [topic]);
      }
    }

    for (const group of childrenByParent.values()) {
      group.sort((a, b) => {
        if (b.priority !== a.priority) return b.priority - a.priority;
        return a.title.localeCompare(b.title);
      });
    }

    const rows: TopicTreeRow[] = [];
    const visited = new Set<string>();

    const walk = (topic: Topic, depth: number) => {
      if (visited.has(topic.id)) return;
      visited.add(topic.id);
      rows.push({ topic, depth });
      const children = childrenByParent.get(topic.id) || [];
      for (const child of children) {
        walk(child, depth + 1);
      }
    };

    const roots = childrenByParent.get(null) || [];
    for (const root of roots) {
      walk(root, 0);
    }

    for (const topic of topics) {
      if (!visited.has(topic.id)) {
        walk(topic, 0);
      }
    }
    return rows;
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
            <TouchableOpacity
              style={[styles.actionButton, sourceUploading && styles.actionButtonDisabled]}
              onPress={uploadSourceForSelectedTopic}
              disabled={sourceUploading}
            >
              <Text style={styles.actionIcon}>📤</Text>
              <Text style={styles.actionText}>{sourceUploading ? 'Uploading...' : 'Upload Source'}</Text>
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
            buildTopicTreeRows().map(({ topic, depth }) => (
              <TouchableOpacity
                key={topic.id}
                style={[styles.topicCard, depth > 0 ? { marginLeft: Math.min(depth, 5) * 14 } : null]}
                onPress={() => selectTopic(topic)}
              >
                <View style={styles.topicCardContent}>
                  <Text style={styles.topicCardTitle}>
                    {depth > 0 ? `${'↳ '.repeat(Math.min(depth, 3))}${topic.title}` : topic.title}
                  </Text>
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

  const renderGuides = () => (
    <ScrollView
      style={styles.tabContent}
      refreshControl={
        <RefreshControl
          refreshing={guidesSubTab === 'lessons' ? lessonsLoading : guidesLoading}
          onRefresh={() => {
            if (selectedBlueprintId) {
              if (guidesSubTab === 'lessons') {
                loadLessonsForBlueprint(selectedBlueprintId);
              } else {
                loadGuidesForBlueprint(selectedBlueprintId);
              }
            } else {
              loadBlueprints();
            }
          }}
        />
      }
    >
      <View style={styles.sectionHeader}>
        <Text style={styles.sectionTitle}>Study Material</Text>
        <TouchableOpacity style={styles.addButton} onPress={loadBlueprints}>
          <Text style={styles.addButtonText}>Refresh</Text>
        </TouchableOpacity>
      </View>

      {blueprints.length === 0 ? (
        <View style={styles.emptyState}>
          <Text style={styles.emptyIcon}>🧭</Text>
          <Text style={styles.emptyText}>No imported blueprints</Text>
          <Text style={styles.emptySubtext}>Import a learning plan in web first, then generate guides here.</Text>
        </View>
      ) : (
        <>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginBottom: spacing.md }}>
            {blueprints.map((bp) => (
              <TouchableOpacity
                key={bp.id}
                style={[
                  styles.blueprintChip,
                  selectedBlueprintId === bp.id && styles.blueprintChipSelected,
                ]}
                onPress={() => setSelectedBlueprintId(bp.id)}
              >
                <Text
                  style={[
                    styles.blueprintChipText,
                    selectedBlueprintId === bp.id && styles.blueprintChipTextSelected,
                  ]}
                >
                  {bp.title}
                </Text>
              </TouchableOpacity>
            ))}
          </ScrollView>

          {/* Guides | Lessons segment toggle */}
          <View style={styles.segmentToggle}>
            <TouchableOpacity
              style={[styles.segmentOption, guidesSubTab === 'guides' && styles.segmentOptionActive]}
              onPress={() => setGuidesSubTab('guides')}
            >
              <Text style={[styles.segmentOptionText, guidesSubTab === 'guides' && styles.segmentOptionTextActive]}>
                Guides
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.segmentOption, guidesSubTab === 'lessons' && styles.segmentOptionActive]}
              onPress={() => setGuidesSubTab('lessons')}
            >
              <Text style={[styles.segmentOptionText, guidesSubTab === 'lessons' && styles.segmentOptionTextActive]}>
                Lessons
              </Text>
            </TouchableOpacity>
          </View>

          {guidesSubTab === 'guides' ? (
            <>
              {activeGuideJob && (
                <View style={styles.guideJobCard}>
                  <View style={styles.guideJobRow}>
                    <Text style={styles.guideJobTitle}>Latest Job</Text>
                    <Text style={styles.guideJobStatus}>{activeGuideJob.status}</Text>
                  </View>
                  <Text style={styles.guideJobMeta}>
                    {activeGuideJob.progress || 0}% • {activeGuideJob.current_step || 'Working...'}
                  </Text>
                  <Text style={styles.guideJobMeta}>
                    Modules {activeGuideJob.completed_modules || 0}/{activeGuideJob.total_modules || 0} • Artifacts {activeGuideJob.artifacts_created || 0}
                  </Text>
                  {!!activeGuideJob.error_message && (
                    <Text style={styles.guideJobError}>{activeGuideJob.error_message}</Text>
                  )}
                  {['queued', 'running', 'cancelling'].includes(activeGuideJob.status) && (
                    <TouchableOpacity
                      style={[styles.cancelGuideButton, guideBusy && styles.cancelGuideButtonDisabled]}
                      onPress={cancelGuideGeneration}
                      disabled={guideBusy || activeGuideJob.status === 'cancelling'}
                    >
                      <Text style={styles.cancelGuideButtonText}>
                        {activeGuideJob.status === 'cancelling' ? 'Cancelling...' : 'Cancel Generation'}
                      </Text>
                    </TouchableOpacity>
                  )}
                </View>
              )}

              <View style={styles.guideActionsRow}>
                <TouchableOpacity
                  style={[styles.guideActionButton, guideBusy && styles.guideActionButtonDisabled]}
                  onPress={() => generateGuides(false)}
                  disabled={!selectedBlueprintId || guideBusy}
                >
                  <Text style={styles.guideActionButtonText}>Generate Guides</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  style={[styles.guideActionButton, styles.guideActionSecondary, guideBusy && styles.guideActionButtonDisabled]}
                  onPress={() => generateGuides(true)}
                  disabled={!selectedBlueprintId || guideBusy}
                >
                  <Text style={styles.guideActionButtonText}>Regenerate + Enhance</Text>
                </TouchableOpacity>
              </View>

              <TouchableOpacity
                style={[styles.guideActionButton, styles.guideActionSecondary, guideBusy && styles.guideActionButtonDisabled, { marginTop: spacing.xs }]}
                onPress={discoverResources}
                disabled={!selectedBlueprintId || guideBusy}
              >
                <Text style={styles.guideActionButtonText}>Find Free Sources</Text>
              </TouchableOpacity>

              <Text style={styles.guidesHint}>
                "Find Free Sources" searches for free PDFs/papers referenced in the blueprint. Regenerate after to incorporate them.
              </Text>

              {guidesLoading ? (
                <ActivityIndicator color={colors.primary} style={{ marginTop: spacing.md }} />
              ) : guides.length === 0 ? (
                <View style={styles.emptyState}>
                  <Text style={styles.emptyIcon}>📝</Text>
                  <Text style={styles.emptyText}>No guides generated yet</Text>
                  <Text style={styles.emptySubtext}>Tap "Generate Guides" to create Pareto and deep guides.</Text>
                </View>
              ) : (
                guides.map((guide) => (
                  <TouchableOpacity
                    key={guide.id}
                    style={styles.guideCard}
                    onPress={() => {
                      setSelectedGuide(guide);
                      setShowGuideModal(true);
                    }}
                  >
                    <Text style={styles.guideCardTitle}>{guide.title || guide.content?.module_title || 'Study Guide'}</Text>
                    <Text style={styles.guideCardMeta}>
                      {guide.content?.module_code || 'module'} • {(guide.artifact_type || '').replace('study_guide_', '')} • v{guide.version || 1}
                    </Text>
                    <Text numberOfLines={3} style={styles.guideCardPreview}>
                      {guide.content?.guide_markdown || 'No content'}
                    </Text>
                  </TouchableOpacity>
                ))
              )}
            </>
          ) : (
            /* Lessons sub-tab */
            <>
              {activeLessonJob && (
                <View style={styles.guideJobCard}>
                  <View style={styles.guideJobRow}>
                    <Text style={styles.guideJobTitle}>Latest Lesson Job</Text>
                    <Text style={styles.guideJobStatus}>{activeLessonJob.status}</Text>
                  </View>
                  <Text style={styles.guideJobMeta}>
                    {activeLessonJob.progress || 0}% • {activeLessonJob.current_step || 'Working...'}
                  </Text>
                  <Text style={styles.guideJobMeta}>
                    Modules {activeLessonJob.completed_modules || 0}/{activeLessonJob.total_modules || 0} • Lessons {activeLessonJob.artifacts_created || 0}
                  </Text>
                  {!!activeLessonJob.error_message && (
                    <Text style={styles.guideJobError}>{activeLessonJob.error_message}</Text>
                  )}
                  {['queued', 'running', 'cancelling'].includes(activeLessonJob.status) && (
                    <TouchableOpacity
                      style={[styles.cancelGuideButton, lessonBusy && styles.cancelGuideButtonDisabled]}
                      onPress={cancelLessonGeneration}
                      disabled={lessonBusy || activeLessonJob.status === 'cancelling'}
                    >
                      <Text style={styles.cancelGuideButtonText}>
                        {activeLessonJob.status === 'cancelling' ? 'Cancelling...' : 'Cancel Generation'}
                      </Text>
                    </TouchableOpacity>
                  )}
                </View>
              )}

              <TouchableOpacity
                style={[styles.guideActionButton, lessonBusy && styles.guideActionButtonDisabled, { marginBottom: spacing.sm }]}
                onPress={generateLessons}
                disabled={!selectedBlueprintId || lessonBusy}
              >
                <Text style={styles.guideActionButtonText}>Generate Lessons</Text>
              </TouchableOpacity>

              <Text style={styles.guidesHint}>
                Lessons are structured teaching units (~5-12k words) with progressive explanations, worked examples, and exercises. Takes ~10-15 min per module.
              </Text>

              {lessonsLoading ? (
                <ActivityIndicator color={colors.primary} style={{ marginTop: spacing.md }} />
              ) : lessons.length === 0 ? (
                <View style={styles.emptyState}>
                  <Text style={styles.emptyIcon}>📖</Text>
                  <Text style={styles.emptyText}>No lessons generated yet</Text>
                  <Text style={styles.emptySubtext}>Tap "Generate Lessons" to create teaching lessons for each module.</Text>
                </View>
              ) : (
                lessons.map((lesson) => (
                  <TouchableOpacity
                    key={lesson.id}
                    style={styles.guideCard}
                    onPress={() => {
                      setSelectedLesson(lesson);
                      setShowLessonModal(true);
                    }}
                  >
                    <Text style={styles.guideCardTitle}>{lesson.title || lesson.content?.module_title || 'Lesson'}</Text>
                    <Text style={styles.guideCardMeta}>
                      {lesson.content?.module_code || 'module'} • {lesson.content?.word_count || 0} words • ~{lesson.content?.estimated_read_time_minutes || 0} min read • v{lesson.version || 1}
                    </Text>
                    <Text numberOfLines={3} style={styles.guideCardPreview}>
                      {lesson.content?.lesson_markdown || 'No content'}
                    </Text>
                  </TouchableOpacity>
                ))
              )}
            </>
          )}
        </>
      )}
    </ScrollView>
  );

  const renderSources = () => (
    <ScrollView
      style={styles.tabContent}
      refreshControl={
        <RefreshControl
          refreshing={sourcesLoading}
          onRefresh={() => {
            if (selectedBlueprintId) {
              loadSourcesForBlueprint(selectedBlueprintId);
            } else {
              loadBlueprints();
            }
          }}
        />
      }
    >
      <View style={styles.sectionHeader}>
        <Text style={styles.sectionTitle}>Sources</Text>
      </View>

      {blueprints.length === 0 ? (
        <View style={styles.emptyState}>
          <Text style={styles.emptyIcon}>📄</Text>
          <Text style={styles.emptyText}>No blueprints</Text>
          <Text style={styles.emptySubtext}>Import a blueprint first to see its sources.</Text>
        </View>
      ) : (
        <>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginBottom: spacing.md }}>
            {blueprints.map((bp) => (
              <TouchableOpacity
                key={bp.id}
                style={[
                  styles.blueprintChip,
                  selectedBlueprintId === bp.id && styles.blueprintChipSelected,
                ]}
                onPress={() => setSelectedBlueprintId(bp.id)}
              >
                <Text style={[
                  styles.blueprintChipText,
                  selectedBlueprintId === bp.id && styles.blueprintChipTextSelected,
                ]}>
                  {bp.title}
                </Text>
              </TouchableOpacity>
            ))}
          </ScrollView>

          {sourcesLoading ? (
            <ActivityIndicator color={colors.primary} style={{ marginTop: spacing.md }} />
          ) : blueprintSources.length === 0 ? (
            <View style={styles.emptyState}>
              <Text style={styles.emptyIcon}>📄</Text>
              <Text style={styles.emptyText}>No sources yet</Text>
              <Text style={styles.emptySubtext}>Upload PDFs or tap "Find Free Sources" in the Guides tab.</Text>
            </View>
          ) : (
            blueprintSources.map((source) => (
              <View key={source.id} style={styles.sourceCard}>
                <View style={styles.sourceCardHeader}>
                  <Text style={styles.sourceCardTitle} numberOfLines={2}>
                    {source.title || 'Untitled Source'}
                  </Text>
                  <View style={[
                    styles.sourceStatusBadge,
                    source.fetch_status === 'fetched' && styles.sourceStatusFetched,
                    source.fetch_status === 'pending' && styles.sourceStatusPending,
                    source.fetch_status === 'failed' && styles.sourceStatusFailed,
                  ]}>
                    <Text style={styles.sourceStatusText}>
                      {source.fetch_status === 'fetched' ? 'Ready' : source.fetch_status}
                    </Text>
                  </View>
                </View>
                <Text style={styles.sourceCardMeta}>
                  {source.source_type} • {source.topic_title}
                </Text>
                <Text style={styles.sourceCardStats}>
                  {source.chunk_count} chunks
                  {source.has_chapters ? ` • ${source.chapter_count} chapters` : ''}
                </Text>
                {source.url ? (
                  <Text style={styles.sourceCardUrl} numberOfLines={1}>{source.url}</Text>
                ) : null}
              </View>
            ))
          )}
        </>
      )}
    </ScrollView>
  );

  const tabLabels: Record<TabType, string> = {
    topics: '📚 Topics',
    flashcards: '🎴 Cards',
    chat: '💬 Chat',
    sources: '📄 Sources',
    guides: '🧠 Guides',
  };

  return (
    <SafeAreaView style={styles.container} edges={['top', 'bottom']}>
      {/* Tab Bar */}
      <View style={styles.tabBar}>
        {(['topics', 'flashcards', 'chat', 'sources', 'guides'] as TabType[]).map(tab => (
          <TouchableOpacity
            key={tab}
            style={[styles.tab, activeTab === tab && styles.activeTab]}
            onPress={() => setActiveTab(tab)}
          >
            <Text style={[styles.tabText, activeTab === tab && styles.activeTabText]}>
              {tabLabels[tab]}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {/* Content */}
      {activeTab === 'topics' && renderTopicsList()}
      {activeTab === 'flashcards' && renderFlashcards()}
      {activeTab === 'chat' && renderChat()}
      {activeTab === 'sources' && renderSources()}
      {activeTab === 'guides' && renderGuides()}

      <Modal
        visible={showGuideModal}
        animationType="slide"
        presentationStyle="pageSheet"
        onRequestClose={() => setShowGuideModal(false)}
      >
        <View style={[styles.container, { paddingTop: spacing.md }]}>
          <View style={styles.guideModalHeader}>
            <Text style={styles.guideModalTitle}>{selectedGuide?.title || 'Study Guide'}</Text>
            <TouchableOpacity onPress={() => setShowGuideModal(false)}>
              <Text style={styles.modalClose}>✕</Text>
            </TouchableOpacity>
          </View>
          <ScrollView style={styles.guideModalContent}>
            <Text style={styles.guideModalMeta}>
              {selectedGuide?.content?.module_code || 'module'} • model {selectedGuide?.content?.model || 'gpt-oss:120b'} • ctx {selectedGuide?.content?.num_ctx || 16384}
            </Text>
            <Markdown
              style={guideMarkdownStyles}
              markdownit={markdownItWithMath}
              rules={markdownMathRules}
            >
              {selectedGuide?.content?.guide_markdown || 'No content available.'}
            </Markdown>
          </ScrollView>
        </View>
      </Modal>

      {/* Lesson Modal */}
      <Modal
        visible={showLessonModal}
        animationType="slide"
        presentationStyle="pageSheet"
        onRequestClose={() => setShowLessonModal(false)}
      >
        <View style={[styles.container, { paddingTop: spacing.md }]}>
          <View style={styles.guideModalHeader}>
            <Text style={styles.guideModalTitle}>{selectedLesson?.title || 'Lesson'}</Text>
            <TouchableOpacity onPress={() => setShowLessonModal(false)}>
              <Text style={styles.modalClose}>✕</Text>
            </TouchableOpacity>
          </View>
          <ScrollView style={styles.guideModalContent}>
            <Text style={styles.guideModalMeta}>
              {selectedLesson?.content?.module_code || 'module'} • {selectedLesson?.content?.word_count || 0} words • ~{selectedLesson?.content?.estimated_read_time_minutes || 0} min read • model {selectedLesson?.content?.model || 'gpt-oss:120b'}
            </Text>
            <Markdown
              style={guideMarkdownStyles}
              markdownit={markdownItWithMath}
              rules={markdownMathRules}
            >
              {selectedLesson?.content?.lesson_markdown || 'No content available.'}
            </Markdown>
          </ScrollView>
        </View>
      </Modal>

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

const guideMarkdownStyles = {
  body: {
    color: colors.text,
    fontSize: fontSizes.md,
    lineHeight: 24,
  },
  heading1: {
    fontSize: fontSizes.xxl,
    fontWeight: 'bold' as const,
    color: colors.text,
    marginTop: spacing.lg,
    marginBottom: spacing.md,
  },
  heading2: {
    fontSize: fontSizes.xl,
    fontWeight: '600' as const,
    color: colors.text,
    marginTop: spacing.md,
    marginBottom: spacing.sm,
  },
  heading3: {
    fontSize: fontSizes.lg,
    fontWeight: '600' as const,
    color: colors.text,
    marginTop: spacing.sm,
    marginBottom: spacing.xs,
  },
  paragraph: {
    marginBottom: spacing.sm,
    color: colors.text,
  },
  listItem: {
    color: colors.text,
  },
  strong: {
    fontWeight: 'bold' as const,
    color: colors.text,
  },
  em: {
    fontStyle: 'italic' as const,
    color: colors.text,
  },
  code_inline: {
    backgroundColor: colors.surface,
    color: colors.primary,
    paddingHorizontal: 4,
    borderRadius: 4,
    fontSize: fontSizes.sm,
  },
  fence: {
    backgroundColor: colors.surface,
    color: colors.text,
    padding: spacing.sm,
    borderRadius: borderRadius.md,
    fontSize: fontSizes.sm,
    marginVertical: spacing.sm,
  },
  hr: {
    backgroundColor: colors.border,
    height: 1,
    marginVertical: spacing.md,
  },
  blockquote: {
    backgroundColor: colors.surface,
    borderLeftColor: colors.primary,
    borderLeftWidth: 3,
    paddingLeft: spacing.sm,
    paddingVertical: spacing.xs,
    marginVertical: spacing.sm,
  },
};

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
  actionButtonDisabled: {
    opacity: 0.6,
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
  blueprintChip: {
    backgroundColor: colors.surface,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: borderRadius.full,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    marginRight: spacing.sm,
  },
  blueprintChipSelected: {
    backgroundColor: colors.primary + '22',
    borderColor: colors.primary,
  },
  blueprintChipText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  blueprintChipTextSelected: {
    color: colors.primary,
  },
  segmentToggle: {
    flexDirection: 'row',
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: 3,
    marginBottom: spacing.md,
  },
  segmentOption: {
    flex: 1,
    paddingVertical: spacing.sm,
    alignItems: 'center',
    borderRadius: borderRadius.md - 2,
  },
  segmentOptionActive: {
    backgroundColor: colors.primary,
  },
  segmentOptionText: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    fontWeight: '700',
  },
  segmentOptionTextActive: {
    color: '#fff',
  },
  guideJobCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  guideJobRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 4,
  },
  guideJobTitle: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '700',
  },
  guideJobStatus: {
    color: colors.primary,
    fontSize: fontSizes.sm,
    fontWeight: '700',
    textTransform: 'uppercase',
  },
  guideJobMeta: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    marginTop: 2,
  },
  guideJobError: {
    color: '#dc2626',
    fontSize: fontSizes.sm,
    marginTop: spacing.xs,
  },
  cancelGuideButton: {
    marginTop: spacing.sm,
    alignSelf: 'flex-start',
    backgroundColor: '#b91c1c',
    borderRadius: borderRadius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
  },
  cancelGuideButtonDisabled: {
    opacity: 0.6,
  },
  cancelGuideButtonText: {
    color: '#fff',
    fontSize: fontSizes.sm,
    fontWeight: '700',
  },
  guideActionsRow: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  guideActionButton: {
    flex: 1,
    backgroundColor: colors.primary,
    borderRadius: borderRadius.md,
    paddingVertical: spacing.sm,
    alignItems: 'center',
  },
  guideActionSecondary: {
    backgroundColor: '#0f766e',
  },
  guideActionButtonDisabled: {
    opacity: 0.5,
  },
  guideActionButtonText: {
    color: '#fff',
    fontSize: fontSizes.sm,
    fontWeight: '700',
  },
  guidesHint: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginBottom: spacing.md,
  },
  guideCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  guideCardTitle: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '700',
    marginBottom: 4,
  },
  guideCardMeta: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginBottom: spacing.xs,
  },
  guideCardPreview: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: 19,
  },
  guideModalHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  guideModalTitle: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '700',
    flex: 1,
    marginRight: spacing.sm,
  },
  guideModalContent: {
    flex: 1,
    padding: spacing.md,
  },
  mathInlineWrapper: {
    marginHorizontal: 2,
    marginVertical: 2,
    justifyContent: 'center',
  },
  mathInline: {
    minHeight: 22,
    maxWidth: '100%',
  },
  mathBlockWrapper: {
    width: '100%',
    marginVertical: spacing.sm,
    paddingVertical: spacing.xs,
  },
  mathBlock: {
    minHeight: 32,
    maxWidth: '100%',
  },
  guideModalMeta: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginBottom: spacing.sm,
  },
  guideModalBody: {
    color: colors.text,
    fontSize: fontSizes.md,
    lineHeight: 22,
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
  sourceCard: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  sourceCardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: 4,
  },
  sourceCardTitle: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
    flex: 1,
    marginRight: spacing.sm,
  },
  sourceStatusBadge: {
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 10,
    backgroundColor: colors.border,
  },
  sourceStatusFetched: {
    backgroundColor: '#065f46',
  },
  sourceStatusPending: {
    backgroundColor: '#92400e',
  },
  sourceStatusFailed: {
    backgroundColor: '#991b1b',
  },
  sourceStatusText: {
    color: '#fff',
    fontSize: fontSizes.xs,
    fontWeight: '600',
  },
  sourceCardMeta: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    marginBottom: 2,
  },
  sourceCardStats: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
  },
  sourceCardUrl: {
    color: colors.primary,
    fontSize: fontSizes.xs,
    marginTop: 4,
    opacity: 0.8,
  },
});
