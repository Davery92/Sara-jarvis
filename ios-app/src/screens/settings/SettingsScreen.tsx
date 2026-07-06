import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  Switch,
  Alert,
  ActivityIndicator,
  RefreshControl,
  TextInput,
  Platform,
  Linking,
} from 'react-native';
import { Picker } from '@react-native-picker/picker';
import { SafeAreaView } from 'react-native-safe-area-context';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { MainTabScreenProps } from '../../types/navigation';
import { useAuth } from '../../context/AuthContext';
import {
  settingsService,
  User,
  UserPreferences,
  Episode,
} from '../../services/settings';
import { apiClient, CodexOAuthStatus } from '../../services/api';
import ProfileSection from '../../components/settings/ProfileSection';
import MemoryListItem from '../../components/settings/MemoryListItem';
import SchedulesSection from '../../components/settings/SchedulesSection';
import TunablesSection from '../../components/settings/TunablesSection';
import { colors, spacing, fontSizes, borderRadius } from '../../styles/theme';
import { iosCalendarSyncService, IOSCalendar } from '../../services/iosCalendarSync';
import { isLocationTrackingEnabled, setLocationTrackingEnabled } from '../../services/locationTracking';

type Props = MainTabScreenProps<'Settings'>;

type ViewMode = 'settings' | 'memory';

export default function SettingsScreen({ navigation }: Props) {
  const { user: authUser, logout } = useAuth();
  const [viewMode, setViewMode] = useState<ViewMode>('settings');
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  // Data states
  const [userProfile, setUserProfile] = useState<User | null>(null);
  const [preferences, setPreferences] = useState<UserPreferences>({});
  const [episodes, setEpisodes] = useState<Episode[]>([]);

  // AI Configuration states
  const [aiProvider, setAiProvider] = useState<'local' | 'gemini' | 'claude' | 'codex'>('local');
  const [localUrl, setLocalUrl] = useState<string>('http://100.104.68.115:11434/v1');
  const [selectedModel, setSelectedModel] = useState<string>('gpt-oss:120b');
  const [apiKey, setApiKey] = useState<string>('');
  const [savingAISettings, setSavingAISettings] = useState(false);
  const [codexOAuthStatus, setCodexOAuthStatus] = useState<CodexOAuthStatus | null>(null);
  const [codexOAuthBusy, setCodexOAuthBusy] = useState(false);

  // Calendar sync states (iOS only)
  const [calendarSyncEnabled, setCalendarSyncEnabled] = useState(false);
  const [locationTrackingEnabled, setLocationTrackingEnabledState] = useState(false);
  const [iosCalendars, setIosCalendars] = useState<IOSCalendar[]>([]);
  const [selectedCalendarIds, setSelectedCalendarIds] = useState<string[]>([]);
  const [lastCalendarSync, setLastCalendarSync] = useState<Date | null>(null);
  const [syncingCalendar, setSyncingCalendar] = useState(false);
  const [loadingCalendars, setLoadingCalendars] = useState(false);

  // Notification preferences
  const [notifPrefs, setNotifPrefs] = useState<Array<{ category: string; enabled: boolean; custom_ban_phrases: string[] }>>([]);
  const [notifPrefsLoading, setNotifPrefsLoading] = useState(false);

  // Claude model options
  const CLAUDE_MODELS = [
    { value: 'claude-opus-4-6', label: 'Claude Opus 4.6' },
    { value: 'claude-sonnet-4-6', label: 'Claude Sonnet 4.6' },
    { value: 'claude-haiku-4-5-20251001', label: 'Claude Haiku 4.5' },
  ];
  const CODEX_MODELS = [
    { value: 'gpt-5.3-codex', label: 'GPT-5.3 Codex' },
    { value: 'gpt-5.3-codex-spark', label: 'GPT-5.3 Codex Spark' },
  ];

  const loadNotifPrefs = async () => {
    try {
      setNotifPrefsLoading(true);
      const result = await apiClient.getNotificationPreferences();
      setNotifPrefs(result.preferences || []);
    } catch (error) {
      console.error('Failed to load notification preferences:', error);
    } finally {
      setNotifPrefsLoading(false);
    }
  };

  const handleNotifPrefToggle = async (category: string, enabled: boolean) => {
    const updated = notifPrefs.map(p =>
      p.category === category ? { ...p, enabled } : p
    );
    setNotifPrefs(updated);
    try {
      await apiClient.updateNotificationPreferences(updated);
    } catch (error) {
      console.error('Failed to update notification preferences:', error);
      // Revert on failure
      setNotifPrefs(notifPrefs);
      Alert.alert('Error', 'Failed to update notification preferences');
    }
  };

  useEffect(() => {
    loadData();
    loadAISettings();
    loadCodexOAuthStatus();
    loadNotifPrefs();
    if (Platform.OS === 'ios') {
      loadCalendarSyncSettings();
    }
    loadLocationTrackingSettings();
  }, []);

  const loadCodexOAuthStatus = async () => {
    try {
      const status = await apiClient.getCodexOAuthStatus();
      setCodexOAuthStatus(status);
    } catch (error) {
      console.error('Failed to load Codex OAuth status:', error);
      setCodexOAuthStatus(null);
    }
  };

  const loadCalendarSyncSettings = async () => {
    try {
      const [enabled, selectedIds, lastSync] = await Promise.all([
        iosCalendarSyncService.isSyncEnabled(),
        iosCalendarSyncService.getSelectedCalendarIds(),
        iosCalendarSyncService.getLastSyncTime(),
      ]);
      setCalendarSyncEnabled(enabled);
      setSelectedCalendarIds(selectedIds);
      setLastCalendarSync(lastSync);

      // If sync is enabled, load available calendars
      if (enabled) {
        await loadIOSCalendars();
      }
    } catch (error) {
      console.error('Failed to load calendar sync settings:', error);
    }
  };

  const loadIOSCalendars = async () => {
    try {
      setLoadingCalendars(true);
      const calendars = await iosCalendarSyncService.getCalendars();
      setIosCalendars(calendars);
    } catch (error) {
      console.error('Failed to load iOS calendars:', error);
    } finally {
      setLoadingCalendars(false);
    }
  };

  const handleCalendarSyncToggle = async (enabled: boolean) => {
    setCalendarSyncEnabled(enabled);
    await iosCalendarSyncService.setSyncEnabled(enabled);

    if (enabled) {
      // Initialize and load calendars
      const initialized = await iosCalendarSyncService.initialize();
      if (initialized) {
        await loadIOSCalendars();
      } else {
        Alert.alert(
          'Calendar Access Required',
          'Please enable calendar access in Settings to sync your iOS calendar with Sara.'
        );
        setCalendarSyncEnabled(false);
        await iosCalendarSyncService.setSyncEnabled(false);
      }
    } else {
      // Clear synced events when disabled
      Alert.alert(
        'Disable Calendar Sync',
        'Do you also want to remove previously synced events from Sara?',
        [
          { text: 'Keep Events', style: 'cancel' },
          {
            text: 'Remove Events',
            style: 'destructive',
            onPress: async () => {
              await iosCalendarSyncService.clearSyncedEvents();
            },
          },
        ]
      );
    }
  };

  const loadLocationTrackingSettings = async () => {
    try {
      const enabled = await isLocationTrackingEnabled();
      setLocationTrackingEnabledState(enabled);
    } catch (error) {
      console.error('Failed to load location tracking settings:', error);
    }
  };

  const handleLocationTrackingToggle = async (enabled: boolean) => {
    setLocationTrackingEnabledState(enabled);
    const ok = await setLocationTrackingEnabled(enabled);
    if (enabled && !ok) {
      setLocationTrackingEnabledState(false);
      Alert.alert(
        'Location Access Required',
        'Please enable location access in Settings for Sara to give location-based reminders.'
      );
    }
  };

  const handleCalendarSelect = async (calendarId: string) => {
    const newSelection = selectedCalendarIds.includes(calendarId)
      ? selectedCalendarIds.filter(id => id !== calendarId)
      : [...selectedCalendarIds, calendarId];

    setSelectedCalendarIds(newSelection);
    await iosCalendarSyncService.setSelectedCalendarIds(newSelection);
  };

  const handleSyncNow = async () => {
    if (selectedCalendarIds.length === 0) {
      Alert.alert('No Calendars Selected', 'Please select at least one calendar to sync.');
      return;
    }

    try {
      setSyncingCalendar(true);
      const result = await iosCalendarSyncService.syncSelectedCalendars();

      if (result.success) {
        setLastCalendarSync(new Date());
        Alert.alert('Sync Complete', `Synced ${result.synced} events from your iOS calendar.`);
      } else {
        Alert.alert('Sync Failed', result.message || 'Failed to sync calendar events.');
      }
    } catch (error: any) {
      Alert.alert('Sync Error', error?.message || 'An error occurred during sync.');
    } finally {
      setSyncingCalendar(false);
    }
  };

  const loadData = async () => {
    try {
      setLoading(true);
      const [profile, prefs, episodesData] = await Promise.all([
        settingsService.getCurrentUser(),
        settingsService.getPreferences(),
        settingsService.getEpisodes(50),
      ]);
      setUserProfile(profile);
      setPreferences(prefs);
      setEpisodes(episodesData);
    } catch (error) {
      console.error('Failed to load settings:', error);
      Alert.alert('Error', 'Failed to load settings');
    } finally {
      setLoading(false);
    }
  };

  const loadAISettings = async () => {
    try {
      // Load from backend API first (source of truth)
      const backendSettings = await apiClient.getAISettings();

      if (backendSettings) {
        const normalizeProvider = (value: any): 'local' | 'gemini' | 'claude' | 'codex' => {
          if (value === 'local' || value === 'gemini' || value === 'claude' || value === 'codex') {
            return value;
          }
          return 'local';
        };

        // Update state from backend
        if (backendSettings.ai_provider) {
          setAiProvider(normalizeProvider(backendSettings.ai_provider));
        }
        if (backendSettings.openai_base_url) {
          setLocalUrl(backendSettings.openai_base_url);
        }
        if (backendSettings.openai_model) {
          setSelectedModel(backendSettings.openai_model);
        }
        // Only set API key if it's not the masked value
        if (backendSettings.openai_api_key && backendSettings.openai_api_key !== '***') {
          setApiKey(backendSettings.openai_api_key);
        }

        // Also save to AsyncStorage for quick access
        if (backendSettings.ai_provider) {
          await AsyncStorage.setItem('@sara_ai_provider', normalizeProvider(backendSettings.ai_provider));
        }
        if (backendSettings.openai_base_url) {
          await AsyncStorage.setItem('@sara_local_url', backendSettings.openai_base_url);
        }
        if (backendSettings.openai_model) {
          await AsyncStorage.setItem('@sara_model', backendSettings.openai_model);
        }
      }
    } catch (error) {
      console.error('Failed to load AI settings from backend:', error);

      // Fallback to AsyncStorage if backend fails
      try {
        const savedProvider = await AsyncStorage.getItem('@sara_ai_provider');
        const savedUrl = await AsyncStorage.getItem('@sara_local_url');
        const savedModel = await AsyncStorage.getItem('@sara_model');

        if (savedProvider === 'local' || savedProvider === 'gemini' || savedProvider === 'claude' || savedProvider === 'codex') {
          setAiProvider(savedProvider);
        } else if (savedProvider) {
          setAiProvider('local');
        }
        if (savedUrl) setLocalUrl(savedUrl);
        if (savedModel) setSelectedModel(savedModel);
      } catch (storageError) {
        console.error('Failed to load AI settings from AsyncStorage:', storageError);
      }
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    await Promise.all([loadData(), loadAISettings(), loadCodexOAuthStatus(), loadNotifPrefs()]);
    setRefreshing(false);
  };

  const handleEditProfile = () => {
    Alert.prompt(
      'Edit Username',
      'Enter new username',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Save',
          onPress: async (username?: string) => {
            if (!username?.trim()) return;
            try {
              const updated = await settingsService.updateUser({
                username: username.trim(),
              });
              setUserProfile(updated);
            } catch (error) {
              Alert.alert('Error', 'Failed to update username');
            }
          },
        },
      ]
    );
  };

  const handleTogglePreference = async (
    key: keyof UserPreferences,
    value: boolean
  ) => {
    try {
      const updated = await settingsService.updatePreferences({ [key]: value });
      setPreferences(updated);
    } catch (error) {
      Alert.alert('Error', 'Failed to update preference');
    }
  };

  const handleEpisodePress = (episode: Episode) => {
    Alert.alert(
      episode.episode_type.replace('_', ' '),
      episode.content,
      [{ text: 'OK' }]
    );
  };

  const handleEpisodeLongPress = (episode: Episode) => {
    Alert.alert(
      'Delete Memory',
      'Are you sure you want to delete this memory?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Delete',
          style: 'destructive',
          onPress: async () => {
            try {
              await settingsService.deleteEpisode(episode.id);
              loadData();
            } catch (error) {
              Alert.alert('Error', 'Failed to delete memory');
            }
          },
        },
      ]
    );
  };

  const handleClearAllMemories = () => {
    Alert.alert(
      'Clear All Memories',
      'This will permanently delete all your conversation history. This cannot be undone.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Clear All',
          style: 'destructive',
          onPress: async () => {
            try {
              await settingsService.clearAllEpisodes();
              loadData();
            } catch (error) {
              Alert.alert('Error', 'Failed to clear memories');
            }
          },
        },
      ]
    );
  };

  const handleLogout = async () => {
    Alert.alert(
      'Log Out',
      'Are you sure you want to log out?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Log Out',
          style: 'destructive',
          onPress: async () => {
            await logout();
          },
        },
      ]
    );
  };

  const saveSettingsToBackend = async (updates: any) => {
    try {
      await apiClient.updateAISettings(updates);
    } catch (error) {
      console.error('Failed to save AI settings to backend:', error);
      // Don't show error to user - local changes still work
    }
  };

  const handleProviderChange = async (provider: 'local' | 'gemini' | 'claude' | 'codex') => {
    // Save current API key to provider-specific storage before switching
    if (apiKey && apiKey !== '***') {
      await AsyncStorage.setItem(`@sara_${aiProvider}_api_key`, apiKey);
    }

    setAiProvider(provider);
    await AsyncStorage.setItem('@sara_ai_provider', provider);

    let newModel: string;
    let newUrl: string | undefined;

    // Auto-set defaults based on provider
    if (provider === 'gemini') {
      newModel = 'gemini-3-flash-preview';
      newUrl = 'https://generativelanguage.googleapis.com/v1beta/openai/';
    } else if (provider === 'claude') {
      newModel = 'claude-sonnet-4-6';
      newUrl = 'https://api.anthropic.com/v1';
    } else if (provider === 'codex') {
      newModel = 'gpt-5.3-codex';
      newUrl = 'https://chatgpt.com/backend-api';
    } else {
      // Reset to default local model based on current URL
      newModel = localUrl.includes('100.104.68.115') ? 'gpt-oss:120b' : 'gpt-oss:20b';
      newUrl = localUrl;
    }

    // Load provider-specific API key
    const savedApiKey = provider === 'codex'
      ? ''
      : (await AsyncStorage.getItem(`@sara_${provider}_api_key`) || '');
    setApiKey(savedApiKey);

    setSelectedModel(newModel);
    await AsyncStorage.setItem('@sara_model', newModel);

    // Save to backend immediately (include API key if we have one)
    const settings: any = {
      ai_provider: provider,
      openai_model: newModel,
      openai_base_url: newUrl,
    };
    if (savedApiKey) {
      settings.openai_api_key = savedApiKey;
    }
    await saveSettingsToBackend(settings);
  };

  const handleUrlChange = async (url: string) => {
    setLocalUrl(url);
    await AsyncStorage.setItem('@sara_local_url', url);

    // Auto-update model based on URL
    const defaultModel = url.includes('100.104.68.115') ? 'gpt-oss:120b' : 'gpt-oss:20b';
    setSelectedModel(defaultModel);
    await AsyncStorage.setItem('@sara_model', defaultModel);

    // Save to backend immediately
    await saveSettingsToBackend({
      ai_provider: aiProvider,
      openai_base_url: url,
      openai_model: defaultModel,
    });
  };

  const handleModelChange = async (model: string) => {
    setSelectedModel(model);
    await AsyncStorage.setItem('@sara_model', model);

    // Save to backend immediately
    const baseUrl = aiProvider === 'gemini'
      ? 'https://generativelanguage.googleapis.com/v1beta/openai/'
      : aiProvider === 'claude'
      ? 'https://api.anthropic.com/v1'
      : aiProvider === 'codex'
      ? 'https://chatgpt.com/backend-api'
      : localUrl;

    await saveSettingsToBackend({
      ai_provider: aiProvider,
      openai_base_url: baseUrl,
      openai_model: model,
    });
  };

  const handleSaveAISettings = async () => {
    try {
      setSavingAISettings(true);

      const settings: any = {
        ai_provider: aiProvider,
        openai_model: selectedModel,
      };

      if (aiProvider === 'local') {
        settings.openai_base_url = localUrl;
      } else if (aiProvider === 'gemini') {
        settings.openai_base_url = 'https://generativelanguage.googleapis.com/v1beta/openai/';
      } else if (aiProvider === 'claude') {
        settings.openai_base_url = 'https://api.anthropic.com/v1';
      } else if (aiProvider === 'codex') {
        settings.openai_base_url = 'https://chatgpt.com/backend-api';
      }

      // Include API key if provided (for Gemini or Claude)
      // Don't send if it's the masked value from backend
      if (apiKey && apiKey !== '***' && (aiProvider === 'gemini' || aiProvider === 'claude')) {
        settings.openai_api_key = apiKey;
      }

      await apiClient.updateAISettings(settings);
      Alert.alert('Success', 'AI settings saved successfully');
    } catch (error) {
      console.error('Failed to save AI settings:', error);
      Alert.alert('Error', 'Failed to save AI settings');
    } finally {
      setSavingAISettings(false);
    }
  };

  const getModelOptions = () => {
    if (aiProvider === 'gemini') {
      return ['gemini-3-flash-preview', 'gemini-3-pro-preview'];
    }

    if (aiProvider === 'claude') {
      return CLAUDE_MODELS.map(m => m.value);
    }

    if (aiProvider === 'codex') {
      return CODEX_MODELS.map(m => m.value);
    }

    if (localUrl.includes('100.104.68.115')) {
      return ['gpt-oss:120b'];
    } else {
      return ['gpt-oss:20b', 'gemini-3-pro-preview:latest'];
    }
  };

  const getModelLabel = (modelValue: string) => {
    if (aiProvider === 'claude') {
      const model = CLAUDE_MODELS.find(m => m.value === modelValue);
      return model ? model.label : modelValue;
    }
    if (aiProvider === 'codex') {
      const model = CODEX_MODELS.find(m => m.value === modelValue);
      return model ? model.label : modelValue;
    }
    return modelValue;
  };

  const handleConnectCodexOAuth = async () => {
    try {
      setCodexOAuthBusy(true);
      const result = await apiClient.startCodexOAuth();
      const authUrl = result?.auth_url;
      const manualFlow = !!result?.requires_manual_code || /localhost:1455|127\.0\.0\.1:1455/.test(result?.redirect_uri || '');
      if (!authUrl) {
        Alert.alert('Error', 'Failed to start ChatGPT OAuth');
        return;
      }
      const canOpen = await Linking.canOpenURL(authUrl);
      if (!canOpen) {
        Alert.alert('Error', 'Could not open browser for ChatGPT OAuth');
        return;
      }
      await Linking.openURL(authUrl);
      if (!manualFlow) {
        Alert.alert('Browser Opened', 'Complete OAuth in browser, then return here and tap Refresh Status.');
        return;
      }

      if (Platform.OS === 'ios' && typeof (Alert as any).prompt === 'function') {
        (Alert as any).prompt(
          'Complete ChatGPT OAuth',
          'After sign-in, copy the full callback URL (http://localhost:1455/auth/callback?...) and paste it here.',
          [
            { text: 'Cancel', style: 'cancel' },
            {
              text: 'Submit',
              onPress: async (value: string) => {
                if (!value || !value.trim()) {
                  return;
                }
                try {
                  await apiClient.completeCodexOAuth({ redirect_url: value.trim() });
                  await loadCodexOAuthStatus();
                  Alert.alert('Connected', 'ChatGPT OAuth connected successfully.');
                } catch (err) {
                  console.error('Failed to complete Codex OAuth:', err);
                  Alert.alert('Error', 'Failed to complete ChatGPT OAuth. Verify the full callback URL and try again.');
                }
              },
            },
          ],
          'plain-text'
        );
      } else {
        Alert.alert(
          'Manual Step Required',
          'After sign-in, copy the full callback URL from browser and paste it into a future update of this screen.'
        );
      }
    } catch (error) {
      console.error('Failed to start Codex OAuth:', error);
      Alert.alert('Error', 'Failed to start ChatGPT OAuth');
    } finally {
      setCodexOAuthBusy(false);
    }
  };

  const handleDisconnectCodexOAuth = async () => {
    try {
      setCodexOAuthBusy(true);
      await apiClient.disconnectCodexOAuth();
      await loadCodexOAuthStatus();
      Alert.alert('Disconnected', 'ChatGPT OAuth has been disconnected.');
    } catch (error) {
      console.error('Failed to disconnect Codex OAuth:', error);
      Alert.alert('Error', 'Failed to disconnect ChatGPT OAuth');
    } finally {
      setCodexOAuthBusy(false);
    }
  };

  if (loading && !userProfile) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  const renderSettingsView = () => (
    <ScrollView
      style={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} />}
    >
      {/* Profile Section */}
      {userProfile && (
        <ProfileSection user={userProfile} onEditPress={handleEditProfile} />
      )}

      {/* AI Configuration Section */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>AI Configuration</Text>

        {/* AI Provider Dropdown */}
        <View style={styles.pickerContainer}>
          <Text style={styles.pickerLabel}>AI Provider</Text>
          <View style={styles.pickerWrapper}>
            <Picker
              selectedValue={aiProvider}
              onValueChange={handleProviderChange}
              style={styles.picker}
              dropdownIconColor={colors.text}
            >
              <Picker.Item label="Local (Ollama)" value="local" color={colors.text} />
              <Picker.Item label="Google Gemini" value="gemini" color={colors.text} />
              <Picker.Item label="Anthropic Claude" value="claude" color={colors.text} />
              <Picker.Item label="ChatGPT Codex (OAuth)" value="codex" color={colors.text} />
            </Picker>
          </View>
        </View>

        {/* URL Dropdown (only show for local) */}
        {aiProvider === 'local' && (
          <View style={styles.pickerContainer}>
            <Text style={styles.pickerLabel}>Local URL</Text>
            <View style={styles.pickerWrapper}>
              <Picker
                selectedValue={localUrl}
                onValueChange={handleUrlChange}
                style={styles.picker}
                dropdownIconColor={colors.text}
              >
                <Picker.Item
                  label="100.104.68.115:11434/v1"
                  value="http://100.104.68.115:11434/v1"
                  color={colors.text}
                />
                <Picker.Item
                  label="10.185.1.8:11434/v1"
                  value="http://10.185.1.8:11434/v1"
                  color={colors.text}
                />
              </Picker>
            </View>
          </View>
        )}

        {/* API Key Input (for Claude and Gemini) */}
        {(aiProvider === 'claude' || aiProvider === 'gemini') && (
          <View style={styles.pickerContainer}>
            <Text style={styles.pickerLabel}>API Key</Text>
            <View style={styles.inputWrapper}>
              <TextInput
                style={styles.textInput}
                value={apiKey}
                onChangeText={(text) => {
                  setApiKey(text);
                  // Save to provider-specific storage
                  if (text && text !== '***') {
                    AsyncStorage.setItem(`@sara_${aiProvider}_api_key`, text);
                  }
                }}
                placeholder={aiProvider === 'claude' ? 'sk-ant-...' : 'Enter API key'}
                placeholderTextColor={colors.textMuted}
                secureTextEntry={true}
                autoCapitalize="none"
                autoCorrect={false}
              />
            </View>
            <Text style={styles.pickerHint}>
              {aiProvider === 'claude'
                ? 'Get key from console.anthropic.com'
                : 'Get key from aistudio.google.com'}
            </Text>
          </View>
        )}

        {aiProvider === 'codex' && (
          <View style={styles.codexCard}>
            <Text style={styles.pickerLabel}>ChatGPT OAuth</Text>
            <Text style={styles.pickerHint}>
              {codexOAuthStatus?.connected
                ? `Connected${codexOAuthStatus.email ? ` as ${codexOAuthStatus.email}` : ''}`
                : 'Not connected. If prompted, paste the localhost callback URL to finish.'}
            </Text>
            {codexOAuthStatus?.expires_at && codexOAuthStatus.connected && (
              <Text style={styles.pickerHint}>
                Token expiry: {new Date(codexOAuthStatus.expires_at).toLocaleString()}
              </Text>
            )}
            <View style={styles.codexActions}>
              {!codexOAuthStatus?.connected ? (
                <TouchableOpacity
                  style={[styles.codexButton, codexOAuthBusy && styles.saveButtonDisabled]}
                  onPress={handleConnectCodexOAuth}
                  disabled={codexOAuthBusy}
                >
                  {codexOAuthBusy ? (
                    <ActivityIndicator size="small" color={colors.text} />
                  ) : (
                    <Text style={styles.codexButtonText}>Connect ChatGPT</Text>
                  )}
                </TouchableOpacity>
              ) : (
                <TouchableOpacity
                  style={[styles.codexButtonSecondary, codexOAuthBusy && styles.saveButtonDisabled]}
                  onPress={handleDisconnectCodexOAuth}
                  disabled={codexOAuthBusy}
                >
                  {codexOAuthBusy ? (
                    <ActivityIndicator size="small" color={colors.text} />
                  ) : (
                    <Text style={styles.codexButtonText}>Disconnect</Text>
                  )}
                </TouchableOpacity>
              )}

              <TouchableOpacity
                style={styles.codexButtonSecondary}
                onPress={loadCodexOAuthStatus}
                disabled={codexOAuthBusy}
              >
                <Text style={styles.codexButtonText}>Refresh Status</Text>
              </TouchableOpacity>
            </View>
          </View>
        )}

        {/* Model Dropdown */}
        <View style={styles.pickerContainer}>
          <Text style={styles.pickerLabel}>Model</Text>
          <View style={styles.pickerWrapper}>
            <Picker
              selectedValue={selectedModel}
              onValueChange={handleModelChange}
              style={styles.picker}
              dropdownIconColor={colors.text}
            >
              {getModelOptions().map((model) => (
                <Picker.Item key={model} label={getModelLabel(model)} value={model} color={colors.text} />
              ))}
            </Picker>
          </View>
          {aiProvider === 'claude' && (
            <Text style={styles.pickerHint}>Opus is most capable, Haiku is fastest</Text>
          )}
        </View>

        {/* Save Button */}
        <TouchableOpacity
          style={[styles.saveButton, savingAISettings && styles.saveButtonDisabled]}
          onPress={handleSaveAISettings}
          disabled={savingAISettings}
        >
          {savingAISettings ? (
            <ActivityIndicator size="small" color={colors.text} />
          ) : (
            <Text style={styles.saveButtonText}>Save AI Settings</Text>
          )}
        </TouchableOpacity>
      </View>

      {/* Preferences Section */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Preferences</Text>

        <View style={styles.settingRow}>
          <Text style={styles.settingLabel}>Enable Notifications</Text>
          <Switch
            value={preferences.notifications_enabled ?? true}
            onValueChange={(value) =>
              handleTogglePreference('notifications_enabled', value)
            }
            trackColor={{ false: colors.background, true: colors.primary }}
          />
        </View>

        <View style={styles.settingRow}>
          <Text style={styles.settingLabel}>Reminder Notifications</Text>
          <Switch
            value={preferences.reminder_notifications ?? true}
            onValueChange={(value) =>
              handleTogglePreference('reminder_notifications', value)
            }
            trackColor={{ false: colors.background, true: colors.primary }}
          />
        </View>

        <View style={styles.settingRow}>
          <Text style={styles.settingLabel}>Email Notifications</Text>
          <Switch
            value={preferences.email_notifications ?? false}
            onValueChange={(value) =>
              handleTogglePreference('email_notifications', value)
            }
            trackColor={{ false: colors.background, true: colors.primary }}
          />
        </View>
      </View>

      {/* Notification Preferences Section */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Notification Categories</Text>
        <Text style={[styles.settingHint, { marginBottom: spacing.sm }]}>
          Control which types of proactive notifications Sara can send.
        </Text>
        {notifPrefsLoading ? (
          <ActivityIndicator size="small" color={colors.primary} />
        ) : (
          notifPrefs.map((pref) => {
            const labels: Record<string, string> = {
              health: 'Health',
              fitness: 'Fitness',
              calendar: 'Calendar',
              email: 'Email',
              security: 'Security',
              home: 'Home',
              general: 'General',
            };
            return (
              <View key={pref.category} style={styles.settingRow}>
                <Text style={styles.settingLabel}>{labels[pref.category] || pref.category}</Text>
                <Switch
                  value={pref.enabled}
                  onValueChange={(value) => handleNotifPrefToggle(pref.category, value)}
                  trackColor={{ false: colors.background, true: colors.primary }}
                />
              </View>
            );
          })
        )}
      </View>

      {/* Scheduled Jobs (DB-backed Celery beat) */}
      <SchedulesSection />

      {/* Behavior Tunables (cooldowns, ACS thresholds, brief tone) */}
      <TunablesSection />

      {/* Location Awareness (iOS only) */}
      {Platform.OS === 'ios' && (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Location</Text>

          <View style={styles.settingRow}>
            <View style={styles.settingLabelContainer}>
              <Text style={styles.settingLabel}>Location Awareness</Text>
              <Text style={styles.settingHint}>
                Let Sara know where you are and trigger reminders when you arrive at or leave places
              </Text>
            </View>
            <Switch
              value={locationTrackingEnabled}
              onValueChange={handleLocationTrackingToggle}
              trackColor={{ false: colors.background, true: colors.primary }}
            />
          </View>
        </View>
      )}

      {/* Calendar Sync Section (iOS only) */}
      {Platform.OS === 'ios' && (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Calendar Sync</Text>

          <View style={styles.settingRow}>
            <View style={styles.settingLabelContainer}>
              <Text style={styles.settingLabel}>Sync iOS Calendar</Text>
              <Text style={styles.settingHint}>Import events from your iPhone calendar</Text>
            </View>
            <Switch
              value={calendarSyncEnabled}
              onValueChange={handleCalendarSyncToggle}
              trackColor={{ false: colors.background, true: colors.primary }}
            />
          </View>

          {calendarSyncEnabled && (
            <>
              {loadingCalendars ? (
                <View style={styles.loadingCalendars}>
                  <ActivityIndicator size="small" color={colors.primary} />
                  <Text style={styles.loadingCalendarsText}>Loading calendars...</Text>
                </View>
              ) : iosCalendars.length > 0 ? (
                <>
                  <Text style={styles.calendarListLabel}>Select calendars to sync:</Text>
                  {iosCalendars.map((calendar) => (
                    <TouchableOpacity
                      key={calendar.id}
                      style={styles.calendarItem}
                      onPress={() => handleCalendarSelect(calendar.id)}
                    >
                      <View style={styles.calendarItemLeft}>
                        <View
                          style={[
                            styles.calendarColorDot,
                            { backgroundColor: calendar.color },
                          ]}
                        />
                        <View style={styles.calendarItemText}>
                          <Text style={styles.calendarName}>{calendar.title}</Text>
                          <Text style={styles.calendarSource}>{calendar.source.name}</Text>
                        </View>
                      </View>
                      <View
                        style={[
                          styles.calendarCheckbox,
                          selectedCalendarIds.includes(calendar.id) &&
                            styles.calendarCheckboxSelected,
                        ]}
                      >
                        {selectedCalendarIds.includes(calendar.id) && (
                          <Text style={styles.calendarCheckmark}>✓</Text>
                        )}
                      </View>
                    </TouchableOpacity>
                  ))}

                  {/* Sync Now Button */}
                  <TouchableOpacity
                    style={[
                      styles.syncButton,
                      (syncingCalendar || selectedCalendarIds.length === 0) &&
                        styles.syncButtonDisabled,
                    ]}
                    onPress={handleSyncNow}
                    disabled={syncingCalendar || selectedCalendarIds.length === 0}
                  >
                    {syncingCalendar ? (
                      <ActivityIndicator size="small" color={colors.text} />
                    ) : (
                      <Text style={styles.syncButtonText}>Sync Now</Text>
                    )}
                  </TouchableOpacity>

                  {/* Last Sync Time */}
                  {lastCalendarSync && (
                    <Text style={styles.lastSyncText}>
                      Last synced: {lastCalendarSync.toLocaleString()}
                    </Text>
                  )}
                </>
              ) : (
                <Text style={styles.noCalendarsText}>
                  No calendars found. Make sure you have calendars set up in the iOS Calendar app.
                </Text>
              )}
            </>
          )}
        </View>
      )}

      {/* About Section */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>About</Text>
        <Text style={styles.aboutText}>Sara iOS App</Text>
        <Text style={styles.aboutSubtext}>Version 1.0.0</Text>
        <Text style={styles.aboutSubtext}>Your Personal AI Hub</Text>
      </View>

      {/* Danger Zone */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Account</Text>
        <TouchableOpacity style={styles.logoutButton} onPress={handleLogout}>
          <Text style={styles.logoutButtonText}>Log Out</Text>
        </TouchableOpacity>
      </View>
    </ScrollView>
  );

  const renderMemoryView = () => (
    <ScrollView
      style={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} />}
    >
      {/* Memory Stats */}
      <View style={styles.memoryStats}>
        <Text style={styles.memoryStatsText}>
          {episodes.length} memories stored
        </Text>
        <TouchableOpacity onPress={handleClearAllMemories}>
          <Text style={styles.clearAllButton}>Clear All</Text>
        </TouchableOpacity>
      </View>

      {/* Memory List */}
      {episodes.length > 0 ? (
        episodes.map((episode) => (
          <MemoryListItem
            key={episode.id}
            episode={episode}
            onPress={handleEpisodePress}
            onLongPress={handleEpisodeLongPress}
          />
        ))
      ) : (
        <View style={styles.emptyContainer}>
          <Text style={styles.emptyText}>No memories yet</Text>
        </View>
      )}
    </ScrollView>
  );

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      {/* Navigation Tabs */}
      <View style={styles.tabs}>
        <TouchableOpacity
          style={[styles.tab, viewMode === 'settings' && styles.tabActive]}
          onPress={() => setViewMode('settings')}
        >
          <Text style={[styles.tabText, viewMode === 'settings' && styles.tabTextActive]}>
            ⚙️ Settings
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.tab, viewMode === 'memory' && styles.tabActive]}
          onPress={() => setViewMode('memory')}
        >
          <Text style={[styles.tabText, viewMode === 'memory' && styles.tabTextActive]}>
            💭 Memory
          </Text>
        </TouchableOpacity>
      </View>

      {/* Content */}
      {viewMode === 'settings' ? renderSettingsView() : renderMemoryView()}
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
  tabs: {
    flexDirection: 'row',
    backgroundColor: colors.surface,
    paddingHorizontal: spacing.sm,
    paddingVertical: spacing.xs,
  },
  tab: {
    flex: 1,
    paddingVertical: spacing.sm,
    alignItems: 'center',
    borderRadius: borderRadius.md,
  },
  tabActive: {
    backgroundColor: colors.primary,
  },
  tabText: {
    color: colors.textSecondary,
    fontSize: fontSizes.md,
    fontWeight: '600',
  },
  tabTextActive: {
    color: colors.text,
  },
  content: {
    flex: 1,
  },
  section: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.lg,
    marginHorizontal: spacing.md,
    marginBottom: spacing.md,
  },
  sectionTitle: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '700',
    marginBottom: spacing.md,
  },
  settingRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: spacing.sm,
  },
  settingLabel: {
    color: colors.text,
    fontSize: fontSizes.md,
  },
  aboutText: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
    marginBottom: spacing.xs,
  },
  aboutSubtext: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    marginBottom: spacing.xs,
  },
  logoutButton: {
    backgroundColor: colors.error,
    padding: spacing.md,
    borderRadius: borderRadius.md,
    alignItems: 'center',
  },
  logoutButtonText: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
  },
  memoryStats: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
  },
  memoryStatsText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  clearAllButton: {
    color: colors.error,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  emptyContainer: {
    padding: spacing.xl,
    alignItems: 'center',
  },
  emptyText: {
    color: colors.textMuted,
    fontSize: fontSizes.md,
    textAlign: 'center',
  },
  pickerContainer: {
    marginBottom: spacing.md,
  },
  pickerLabel: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
    marginBottom: spacing.xs,
  },
  pickerWrapper: {
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.textMuted,
    overflow: 'hidden',
  },
  picker: {
    color: colors.text,
    backgroundColor: 'transparent',
  },
  pickerHint: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    marginTop: spacing.xs,
  },
  inputWrapper: {
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.textMuted,
    overflow: 'hidden',
  },
  textInput: {
    color: colors.text,
    backgroundColor: 'transparent',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    fontSize: fontSizes.md,
  },
  saveButton: {
    backgroundColor: colors.primary,
    padding: spacing.md,
    borderRadius: borderRadius.md,
    alignItems: 'center',
    marginTop: spacing.sm,
  },
  saveButtonDisabled: {
    opacity: 0.6,
  },
  saveButtonText: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
  },
  codexCard: {
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.textMuted,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  codexActions: {
    flexDirection: 'column',
    marginTop: spacing.sm,
  },
  codexButton: {
    flex: 1,
    backgroundColor: colors.primary,
    borderRadius: borderRadius.md,
    paddingVertical: spacing.sm,
    alignItems: 'center',
    justifyContent: 'center',
  },
  codexButtonSecondary: {
    flex: 1,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.textMuted,
    paddingVertical: spacing.sm,
    alignItems: 'center',
    justifyContent: 'center',
  },
  codexButtonText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  // Calendar Sync styles
  settingLabelContainer: {
    flex: 1,
  },
  settingHint: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    marginTop: 2,
  },
  loadingCalendars: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.md,
  },
  loadingCalendarsText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    marginLeft: spacing.sm,
  },
  calendarListLabel: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    marginTop: spacing.md,
    marginBottom: spacing.sm,
  },
  calendarItem: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  calendarItemLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    flex: 1,
  },
  calendarColorDot: {
    width: 12,
    height: 12,
    borderRadius: 6,
    marginRight: spacing.sm,
  },
  calendarItemText: {
    flex: 1,
  },
  calendarName: {
    color: colors.text,
    fontSize: fontSizes.md,
  },
  calendarSource: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
  },
  calendarCheckbox: {
    width: 24,
    height: 24,
    borderRadius: 4,
    borderWidth: 2,
    borderColor: colors.textMuted,
    alignItems: 'center',
    justifyContent: 'center',
  },
  calendarCheckboxSelected: {
    backgroundColor: colors.primary,
    borderColor: colors.primary,
  },
  calendarCheckmark: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '700',
  },
  syncButton: {
    backgroundColor: colors.primary,
    padding: spacing.md,
    borderRadius: borderRadius.md,
    alignItems: 'center',
    marginTop: spacing.md,
  },
  syncButtonDisabled: {
    opacity: 0.6,
  },
  syncButtonText: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
  },
  lastSyncText: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    textAlign: 'center',
    marginTop: spacing.sm,
  },
  noCalendarsText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    textAlign: 'center',
    paddingVertical: spacing.md,
  },
});
