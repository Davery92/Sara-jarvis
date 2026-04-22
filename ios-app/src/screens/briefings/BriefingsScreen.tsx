import React, { useState, useEffect, useRef } from 'react';
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  StyleSheet,
  Modal,
} from 'react-native';
import { Audio } from 'expo-av';
import * as ExpoClipboard from 'expo-clipboard';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { apiClient } from '../../services/api';
import { colors, spacing, borderRadius, fontSizes, shadows } from '../../styles/theme';
import Markdown from 'react-native-markdown-display';

interface BriefSummary {
  id: string;
  brief_date: string;
  has_audio: boolean;
  audio_duration_seconds: number | null;
  generated_at: string | null;
  viewed_at: string | null;
}

interface BriefDetail {
  id: string;
  brief_date: string;
  news_summary: string | null;
  weather_summary: string | null;
  calendar_summary: string | null;
  full_text: string | null;
  has_audio: boolean;
  audio_duration_seconds: number | null;
  recovery_text: string | null;
  has_recovery_audio: boolean;
  generated_at: string | null;
}

interface WeatherData {
  location: string;
  current: {
    temperature: number;
    feels_like: number;
    humidity: number;
    description: string;
    icon: string;
    wind_speed: number;
  };
  forecast: Array<{
    date: string;
    temp_high: number;
    temp_low: number;
    description: string;
    pop: number;
  }>;
}

// OpenWeatherMap icon to emoji mapping
const iconToEmoji: Record<string, string> = {
  '01d': '☀️', '01n': '🌙',
  '02d': '⛅', '02n': '☁️',
  '03d': '☁️', '03n': '☁️',
  '04d': '☁️', '04n': '☁️',
  '09d': '🌧️', '09n': '🌧️',
  '10d': '🌦️', '10n': '🌧️',
  '11d': '⛈️', '11n': '⛈️',
  '13d': '❄️', '13n': '❄️',
  '50d': '🌫️', '50n': '🌫️',
};

const normalizeReaderText = (text?: string | null) => (text || '').replace(/\r\n/g, '\n').trim();

const splitReaderBlocks = (text?: string | null) =>
  normalizeReaderText(text)
    .split(/\n{2,}/)
    .map((block) => block.trim())
    .filter(Boolean);

// Helper to get auth headers
const getAuthHeaders = async () => {
  const token = await apiClient.getToken();
  console.log('[Briefings] Auth token:', token ? `${token.substring(0, 20)}...` : 'NULL');
  return {
    'Content-Type': 'application/json',
    ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
  };
};

export default function BriefingsScreen() {
  const insets = useSafeAreaInsets();
  const [briefs, setBriefs] = useState<BriefSummary[]>([]);
  const [selectedBrief, setSelectedBrief] = useState<BriefDetail | null>(null);
  const [weather, setWeather] = useState<WeatherData | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [paused, setPaused] = useState(false);
  const [audioProgress, setAudioProgress] = useState<{ positionMs: number; durationMs: number } | null>(null);
  const [readerVisible, setReaderVisible] = useState(false);
  const soundRef = useRef<Audio.Sound | null>(null);
  const progressTimerRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    loadBriefs();
    loadWeather();
    return () => {
      if (soundRef.current) {
        soundRef.current.unloadAsync();
      }
      if (progressTimerRef.current) {
        clearInterval(progressTimerRef.current);
      }
    };
  }, []);

  const loadBriefs = async () => {
    try {
      const headers = await getAuthHeaders();
      console.log('[Briefings] Loading briefs from:', `${apiClient.baseURL}/api/morning-brief/history?limit=14`);
      const response = await fetch(`${apiClient.baseURL}/api/morning-brief/history?limit=14`, {
        headers,
      });
      console.log('[Briefings] Response status:', response.status);
      if (response.ok) {
        const data = await response.json();
        console.log('[Briefings] Loaded', data.length, 'briefs');
        setBriefs(data);
        if (data.length > 0) {
          await loadBriefDetail(data[0].brief_date);
        }
      } else {
        console.error('[Briefings] Failed to load briefs:', response.status, await response.text());
      }
    } catch (error) {
      console.error('Failed to load briefs:', error);
    } finally {
      setLoading(false);
    }
  };

  const loadWeather = async () => {
    try {
      const headers = await getAuthHeaders();
      const response = await fetch(`${apiClient.baseURL}/api/morning-brief/weather`, {
        headers,
      });
      if (response.ok) {
        const data = await response.json();
        setWeather(data);
      }
    } catch (error) {
      console.error('Failed to load weather:', error);
    }
  };

  const loadBriefDetail = async (briefDate: string) => {
    try {
      const headers = await getAuthHeaders();
      const response = await fetch(
        `${apiClient.baseURL}/api/morning-brief/${briefDate}?include_recovery=true`,
        { headers }
      );
      if (response.ok) {
        const data = await response.json();
        setSelectedBrief(data);
      }
    } catch (error) {
      console.error('Failed to load brief detail:', error);
    }
  };

  const generateBrief = async () => {
    setGenerating(true);
    try {
      const headers = await getAuthHeaders();
      const response = await fetch(`${apiClient.baseURL}/api/morning-brief/generate`, {
        method: 'POST',
        headers,
      });
      if (response.ok) {
        await loadBriefs();
      }
    } catch (error) {
      console.error('Failed to generate brief:', error);
    } finally {
      setGenerating(false);
    }
  };

  const playAudio = async () => {
    if (!selectedBrief?.has_audio) {
      console.log('[Briefings] No audio available for brief');
      return;
    }

    try {
      // If currently playing, pause the audio
      if (playing && soundRef.current) {
        console.log('[Briefings] Pausing audio');
        try {
          await soundRef.current.pauseAsync();
          setPlaying(false);
          setPaused(true);
        } catch (pauseError) {
          console.error('[Briefings] Error pausing:', pauseError);
          // If pause fails, try to stop instead
          try {
            await soundRef.current.stopAsync();
          } catch (stopError) {
            console.error('[Briefings] Error stopping:', stopError);
          }
          setPlaying(false);
          setPaused(false);
        }
        return;
      }

      // If paused, resume playback
      if (paused && soundRef.current) {
        console.log('[Briefings] Resuming audio');
        try {
          await soundRef.current.playAsync();
          setPlaying(true);
          setPaused(false);
        } catch (resumeError) {
          console.error('[Briefings] Error resuming:', resumeError);
          // Reset state and let user try again
          setPaused(false);
        }
        return;
      }

      // Unload any previous sound before creating new one
      if (soundRef.current) {
        console.log('[Briefings] Unloading previous sound');
        try {
          await soundRef.current.unloadAsync();
        } catch (unloadError) {
          console.error('[Briefings] Error unloading:', unloadError);
        }
        soundRef.current = null;
      }

      // Configure audio mode for playback
      await Audio.setAudioModeAsync({
        allowsRecordingIOS: false,
        playsInSilentModeIOS: true,
        staysActiveInBackground: false,
        shouldDuckAndroid: true,
      });

      const token = await apiClient.getToken();
      const authHeaders = token ? { 'Authorization': `Bearer ${token}` } : {};

      // Use the selected brief's date for the audio endpoint
      const briefDate = selectedBrief.brief_date;
      const audioUrl = `${apiClient.baseURL}/api/morning-brief/${briefDate}/audio`;

      console.log('[Briefings] Loading audio from:', audioUrl);

      // Play main brief audio
      const { sound, status } = await Audio.Sound.createAsync(
        {
          uri: audioUrl,
          headers: authHeaders
        },
        { shouldPlay: true }
      );

      console.log('[Briefings] Audio loaded, status:', JSON.stringify(status));

      soundRef.current = sound;
      setPlaying(true);
      setPaused(false);

      // Start progress polling
      if (progressTimerRef.current) clearInterval(progressTimerRef.current);
      progressTimerRef.current = setInterval(async () => {
        if (soundRef.current) {
          try {
            const st = await soundRef.current.getStatusAsync();
            if (st.isLoaded) {
              setAudioProgress({
                positionMs: st.positionMillis,
                durationMs: st.durationMillis || 0,
              });
            }
          } catch {}
        }
      }, 1000);

      sound.setOnPlaybackStatusUpdate(async (playbackStatus) => {
        if (!playbackStatus.isLoaded) {
          // Handle unloaded state
          if (playbackStatus.error) {
            console.error('[Briefings] Playback error:', playbackStatus.error);
            setPlaying(false);
            setPaused(false);
          }
          return;
        }

        if (playbackStatus.didJustFinish) {
          // Main brief finished - check if there's recovery audio to play
          if (selectedBrief?.has_recovery_audio) {
            try {
              // Unload main brief audio
              await sound.unloadAsync();

              // Load and play recovery audio
              const { sound: recoverySound } = await Audio.Sound.createAsync(
                {
                  uri: `${apiClient.baseURL}/api/morning-brief/${briefDate}/recovery-audio`,
                  headers: authHeaders
                },
                { shouldPlay: true }
              );
              soundRef.current = recoverySound;

              recoverySound.setOnPlaybackStatusUpdate((recoveryStatus) => {
                if (recoveryStatus.isLoaded && recoveryStatus.didJustFinish) {
                  setPlaying(false);
                  setPaused(false);
                }
              });
            } catch (error) {
              console.error('Failed to play recovery audio:', error);
              setPlaying(false);
              setPaused(false);
            }
          } else {
            setPlaying(false);
            setPaused(false);
          }
        }
      });
    } catch (error) {
      console.error('Failed to play audio:', error);
      setPlaying(false);
      setPaused(false);
      setAudioProgress(null);
      if (progressTimerRef.current) clearInterval(progressTimerRef.current);
    }
  };

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr + 'T12:00:00');
    const today = new Date();
    const yesterday = new Date(today);
    yesterday.setDate(yesterday.getDate() - 1);

    if (dateStr === today.toISOString().split('T')[0]) {
      return 'Today';
    } else if (dateStr === yesterday.toISOString().split('T')[0]) {
      return 'Yesterday';
    }
    return date.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
  };

  const formatDuration = (seconds: number | null) => {
    if (!seconds) return '';
    const mins = Math.floor(seconds / 60);
    const secs = Math.round(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const briefReaderText = selectedBrief
    ? normalizeReaderText(
        selectedBrief.full_text ||
        [selectedBrief.weather_summary, selectedBrief.calendar_summary, selectedBrief.news_summary]
          .filter(Boolean)
          .join('\n\n')
      )
    : '';

  const recoveryReaderText = normalizeReaderText(selectedBrief?.recovery_text);
  const briefPreview = splitReaderBlocks(briefReaderText)[0] || 'Generate or open a brief to see the current morning summary.';
  const weatherSummary = weather
    ? `${iconToEmoji[weather.current.icon] || '🌤️'} ${Math.round(weather.current.temperature)}° in ${weather.location}`
    : 'Weather unavailable';
  const briefMetaLabel = selectedBrief?.generated_at
    ? `Generated ${new Date(selectedBrief.generated_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`
    : 'No generation timestamp yet';
  const hasRecovery = Boolean(selectedBrief?.recovery_text);

  const copyReaderText = async () => {
    const combined = [briefReaderText, recoveryReaderText].filter(Boolean).join('\n\n');
    if (!combined) return;

    try {
      await ExpoClipboard.setStringAsync(combined);
    } catch (error) {
      console.error('Failed to copy brief:', error);
    }
  };

  if (loading) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <View style={styles.heroWrap}>
        <View style={styles.heroCard}>
          <Text style={styles.heroEyebrow}>Morning Brief</Text>
          <Text style={styles.heroTitle}>
            {selectedBrief ? `${formatDate(selectedBrief.brief_date)} overview` : 'Start your day with Sara'}
          </Text>
          <Text style={styles.heroSubtitle} numberOfLines={3}>
            {briefPreview}
          </Text>

          <View style={styles.heroStatsRow}>
            <View style={styles.heroStatCard}>
              <Text style={styles.heroStatLabel}>Weather</Text>
              <Text style={styles.heroStatValue}>
                {weather ? `${Math.round(weather.current.temperature)}°` : '—'}
              </Text>
              <Text style={styles.heroStatMeta}>{weatherSummary}</Text>
            </View>
            <View style={styles.heroStatCard}>
              <Text style={styles.heroStatLabel}>Audio</Text>
              <Text style={styles.heroStatValue}>
                {selectedBrief?.has_audio ? formatDuration(selectedBrief.audio_duration_seconds) || 'Ready' : 'None'}
              </Text>
              <Text style={styles.heroStatMeta}>
                {selectedBrief?.has_audio ? 'spoken version available' : 'text only right now'}
              </Text>
            </View>
            <View style={styles.heroStatCard}>
              <Text style={styles.heroStatLabel}>Recovery</Text>
              <Text style={styles.heroStatValue}>{hasRecovery ? 'Included' : 'Off'}</Text>
              <Text style={styles.heroStatMeta}>{briefMetaLabel}</Text>
            </View>
          </View>

          <View style={styles.heroActions}>
            <TouchableOpacity
              onPress={generateBrief}
              disabled={generating}
              style={[styles.heroActionButton, styles.heroActionPrimary, generating && styles.heroActionDisabled]}
            >
              {generating ? (
                <ActivityIndicator size="small" color="#fff" />
              ) : (
                <Text style={styles.heroActionPrimaryText}>Refresh Brief</Text>
              )}
            </TouchableOpacity>
            {briefReaderText ? (
              <TouchableOpacity
                onPress={() => setReaderVisible(true)}
                style={[styles.heroActionButton, styles.heroActionSecondary]}
              >
                <Text style={styles.heroActionSecondaryText}>Open Full Brief</Text>
              </TouchableOpacity>
            ) : null}
            {selectedBrief?.has_audio ? (
              <TouchableOpacity
                onPress={playAudio}
                style={[styles.heroActionButton, styles.heroActionSecondary]}
              >
                <Text style={styles.heroActionSecondaryText}>
                  {playing ? 'Pause Audio' : paused ? 'Resume Audio' : 'Play Audio'}
                </Text>
              </TouchableOpacity>
            ) : null}
          </View>
        </View>
      </View>

      {/* Brief Content */}
      {selectedBrief ? (
        <ScrollView style={styles.contentArea}>
          {/* Header with audio controls */}
          <View style={styles.briefHeader}>
            <View>
              <Text style={styles.briefTitle}>
                {formatDate(selectedBrief.brief_date)} Brief
              </Text>
              {selectedBrief.generated_at && (
                <Text style={styles.briefTime}>
                  Generated {new Date(selectedBrief.generated_at).toLocaleTimeString()}
                </Text>
              )}
            </View>
            {selectedBrief.has_audio && (
              <View>
                <TouchableOpacity
                  onPress={playAudio}
                  style={[styles.playButton, playing && styles.playButtonActive]}
                >
                  <Text style={styles.playIcon}>{playing ? '⏸' : (paused ? '▶️' : '▶️')}</Text>
                  <Text style={styles.playText}>
                    {playing ? 'Pause' : (paused ? 'Resume' : 'Play')}
                  </Text>
                </TouchableOpacity>
                {(playing || paused) && audioProgress && audioProgress.durationMs > 0 && (
                  <Text style={styles.audioProgressText}>
                    {formatDuration(Math.floor(audioProgress.positionMs / 1000))} / {formatDuration(Math.floor(audioProgress.durationMs / 1000))}
                  </Text>
                )}
              </View>
            )}
          </View>

          {briefReaderText ? (
            <View style={styles.readerActions}>
              <TouchableOpacity
                onPress={() => setReaderVisible(true)}
                style={[styles.readerActionButton, styles.readerActionPrimary]}
              >
                <Text style={styles.readerActionText}>Open Full Brief</Text>
              </TouchableOpacity>
              <TouchableOpacity
                onPress={copyReaderText}
                style={[styles.readerActionButton, styles.readerActionSecondary]}
              >
                <Text style={styles.readerActionText}>Copy Text</Text>
              </TouchableOpacity>
            </View>
          ) : null}

          {/* Brief Content */}
          {selectedBrief.full_text ? (
            <View style={styles.briefContent}>
              <Markdown style={markdownStyles}>
                {selectedBrief.full_text}
              </Markdown>
            </View>
          ) : (
            <View style={styles.briefContent}>
              {selectedBrief.weather_summary && (
                <Markdown style={markdownStyles}>
                  {selectedBrief.weather_summary}
                </Markdown>
              )}
              {selectedBrief.calendar_summary && (
                <Markdown style={markdownStyles}>
                  {selectedBrief.calendar_summary}
                </Markdown>
              )}
              {selectedBrief.news_summary && (
                <>
                  <Text style={styles.sectionTitle}>Tech News</Text>
                  <Markdown style={markdownStyles}>
                    {selectedBrief.news_summary}
                  </Markdown>
                </>
              )}
            </View>
          )}

          {/* Recovery Section */}
          {selectedBrief.recovery_text && (
            <View style={styles.recoverySection}>
              <Markdown style={markdownStyles}>
                {selectedBrief.recovery_text}
              </Markdown>
            </View>
          )}
        </ScrollView>
      ) : (
        <View style={styles.emptyState}>
          <Text style={styles.emptyIcon}>☀️</Text>
          <Text style={styles.emptyText}>No brief selected</Text>
          <Text style={styles.emptySubtext}>Generate a brief or select one below</Text>
        </View>
      )}

      <Modal
        visible={readerVisible}
        animationType="slide"
        presentationStyle="fullScreen"
        onRequestClose={() => setReaderVisible(false)}
      >
        <SafeAreaView style={styles.readerModal} edges={['bottom']}>
          <View style={[styles.readerModalHeader, { paddingTop: insets.top + spacing.sm }]}>
            <TouchableOpacity onPress={() => setReaderVisible(false)}>
              <Text style={styles.readerModalControl}>Close</Text>
            </TouchableOpacity>
            <Text style={styles.readerModalTitle}>
              {selectedBrief ? `${formatDate(selectedBrief.brief_date)} Brief` : 'Full Brief'}
            </Text>
            <TouchableOpacity onPress={copyReaderText}>
              <Text style={styles.readerModalControl}>Copy</Text>
            </TouchableOpacity>
          </View>

          <ScrollView
            style={styles.readerScroll}
            contentContainerStyle={styles.readerScrollContent}
            showsVerticalScrollIndicator
          >
            {splitReaderBlocks(briefReaderText).map((block, index) => (
              <Text key={`brief-block-${index}`} selectable style={styles.readerParagraph}>
                {block}
              </Text>
            ))}

            {recoveryReaderText ? (
              <View style={styles.readerRecoverySection}>
                <Text style={styles.readerSectionLabel}>Recovery</Text>
                {splitReaderBlocks(recoveryReaderText).map((block, index) => (
                  <Text key={`recovery-block-${index}`} selectable style={styles.readerParagraph}>
                    {block}
                  </Text>
                ))}
              </View>
            ) : null}
          </ScrollView>
        </SafeAreaView>
      </Modal>

      {/* Recent Briefs List */}
      {briefs.length > 0 && (
        <View style={styles.briefsList}>
          <Text style={styles.listTitle}>Recent Briefs</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false}>
            {briefs.map((brief) => (
              <TouchableOpacity
                key={brief.id}
                onPress={() => loadBriefDetail(brief.brief_date)}
                style={[
                  styles.briefCard,
                  selectedBrief?.brief_date === brief.brief_date && styles.briefCardActive,
                ]}
              >
                <Text style={styles.briefCardDate}>{formatDate(brief.brief_date)}</Text>
                {brief.has_audio && (
                  <Text style={styles.briefCardDuration}>
                    🔊 {formatDuration(brief.audio_duration_seconds)}
                  </Text>
                )}
                {brief.viewed_at && <Text style={styles.briefCardRead}>✓ Read</Text>}
              </TouchableOpacity>
            ))}
          </ScrollView>
        </View>
      )}
    </View>
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
  heroWrap: {
    paddingHorizontal: spacing.md,
    paddingTop: spacing.md,
    paddingBottom: spacing.sm,
  },
  heroCard: {
    backgroundColor: colors.assistant.panel,
    borderRadius: borderRadius.xl,
    borderWidth: 1,
    borderColor: colors.assistant.borderStrong,
    padding: spacing.lg,
    ...shadows.sm,
  },
  heroEyebrow: {
    color: colors.accent,
    fontSize: fontSizes.xs,
    fontWeight: '700',
    letterSpacing: 0.8,
    textTransform: 'uppercase',
    marginBottom: spacing.xs,
  },
  heroTitle: {
    color: colors.text,
    fontSize: fontSizes.xxl,
    fontWeight: '700',
  },
  heroSubtitle: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: 20,
    marginTop: spacing.xs,
  },
  heroStatsRow: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: spacing.md,
    flexWrap: 'wrap',
  },
  heroStatCard: {
    flex: 1,
    minWidth: 96,
    backgroundColor: colors.assistant.panelRaised,
    borderRadius: borderRadius.lg,
    borderWidth: 1,
    borderColor: colors.assistant.border,
    padding: spacing.md,
  },
  heroStatLabel: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    fontWeight: '700',
    letterSpacing: 0.6,
    textTransform: 'uppercase',
  },
  heroStatValue: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '700',
    marginTop: 2,
  },
  heroStatMeta: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    lineHeight: 16,
    marginTop: 2,
  },
  heroActions: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  heroActionButton: {
    borderRadius: borderRadius.full,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderWidth: 1,
  },
  heroActionPrimary: {
    backgroundColor: colors.assistant.action,
    borderColor: colors.assistant.action,
  },
  heroActionSecondary: {
    backgroundColor: colors.assistant.panelRaised,
    borderColor: colors.assistant.border,
  },
  heroActionDisabled: {
    opacity: 0.7,
  },
  heroActionPrimaryText: {
    color: '#fff',
    fontSize: fontSizes.sm,
    fontWeight: '700',
  },
  heroActionSecondaryText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  contentArea: {
    flex: 1,
    paddingHorizontal: spacing.md,
  },
  briefHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    marginBottom: spacing.md,
  },
  briefTitle: {
    fontSize: fontSizes.lg,
    fontWeight: 'bold',
    color: colors.text,
  },
  briefTime: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    marginTop: spacing.xs,
  },
  playButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.primary,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderRadius: borderRadius.md,
    gap: spacing.xs,
  },
  playButtonActive: {
    backgroundColor: colors.error,
  },
  playIcon: {
    fontSize: 16,
  },
  playText: {
    color: '#fff',
    fontWeight: '600',
    fontSize: fontSizes.sm,
  },
  audioProgressText: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    textAlign: 'center',
    marginTop: 4,
  },
  briefContent: {
    paddingBottom: spacing.lg,
  },
  readerActions: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginBottom: spacing.md,
  },
  readerActionButton: {
    borderRadius: borderRadius.full,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  readerActionPrimary: {
    backgroundColor: colors.primary,
  },
  readerActionSecondary: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
  },
  readerActionText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  sectionTitle: {
    fontSize: fontSizes.lg,
    fontWeight: '600',
    color: colors.text,
    marginTop: spacing.md,
    marginBottom: spacing.sm,
  },
  recoverySection: {
    marginTop: spacing.lg,
    paddingTop: spacing.lg,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  emptyState: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: spacing.xl,
  },
  emptyIcon: {
    fontSize: 64,
    marginBottom: spacing.md,
  },
  emptyText: {
    fontSize: fontSizes.lg,
    color: colors.textMuted,
    fontWeight: '600',
  },
  emptySubtext: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
    marginTop: spacing.xs,
  },
  readerModal: {
    flex: 1,
    backgroundColor: colors.background,
  },
  readerModalHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    backgroundColor: colors.surface,
  },
  readerModalControl: {
    color: colors.primary,
    fontSize: fontSizes.md,
    fontWeight: '600',
  },
  readerModalTitle: {
    flex: 1,
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '700',
    textAlign: 'center',
    marginHorizontal: spacing.md,
  },
  readerScroll: {
    flex: 1,
  },
  readerScrollContent: {
    padding: spacing.lg,
    paddingBottom: spacing.xxl,
  },
  readerParagraph: {
    color: colors.text,
    fontSize: fontSizes.md,
    lineHeight: 26,
    marginBottom: spacing.md,
  },
  readerRecoverySection: {
    marginTop: spacing.lg,
    paddingTop: spacing.lg,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  readerSectionLabel: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    fontWeight: '700',
    textTransform: 'uppercase',
    letterSpacing: 0.6,
    marginBottom: spacing.md,
  },
  briefsList: {
    backgroundColor: colors.surface,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    padding: spacing.md,
  },
  listTitle: {
    fontSize: fontSizes.sm,
    fontWeight: '600',
    color: colors.textMuted,
    marginBottom: spacing.sm,
  },
  briefCard: {
    width: 100,
    padding: spacing.md,
    marginRight: spacing.sm,
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: 'center',
  },
  briefCardActive: {
    borderColor: colors.primary,
    borderWidth: 2,
  },
  briefCardDate: {
    fontSize: fontSizes.sm,
    fontWeight: '600',
    color: colors.text,
    marginBottom: spacing.xs,
  },
  briefCardDuration: {
    fontSize: fontSizes.xs,
    color: colors.primary,
  },
  briefCardRead: {
    fontSize: fontSizes.xs,
    color: colors.success,
    marginTop: spacing.xs,
  },
});

const markdownStyles = {
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
  code_inline: {
    color: colors.primary,
    backgroundColor: 'transparent',
    fontSize: fontSizes.md - 1,
    fontFamily: undefined,
  },
  code_block: {
    color: colors.text,
    backgroundColor: 'rgba(255,255,255,0.06)',
    borderColor: 'rgba(255,255,255,0.1)',
    borderRadius: 8,
    padding: spacing.sm,
    fontSize: fontSizes.md - 2,
  },
  fence: {
    color: colors.text,
    backgroundColor: 'rgba(255,255,255,0.06)',
    borderColor: 'rgba(255,255,255,0.1)',
    borderRadius: 8,
    padding: spacing.sm,
    fontSize: fontSizes.md - 2,
  },
  hr: {
    backgroundColor: colors.border,
    height: 1,
    marginVertical: spacing.md,
  },
};
