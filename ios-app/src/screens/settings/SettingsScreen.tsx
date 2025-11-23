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
import { apiClient } from '../../services/api';
import ProfileSection from '../../components/settings/ProfileSection';
import MemoryListItem from '../../components/settings/MemoryListItem';
import { colors, spacing, fontSizes, borderRadius } from '../../styles/theme';

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
  const [aiProvider, setAiProvider] = useState<'local' | 'gemini'>('local');
  const [localUrl, setLocalUrl] = useState<string>('http://100.104.68.115:11434/v1');
  const [selectedModel, setSelectedModel] = useState<string>('gpt-oss:120b');
  const [savingAISettings, setSavingAISettings] = useState(false);

  useEffect(() => {
    loadData();
    loadAISettings();
  }, []);

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
        // Update state from backend
        if (backendSettings.ai_provider) {
          setAiProvider(backendSettings.ai_provider as 'local' | 'gemini');
        }
        if (backendSettings.openai_base_url) {
          setLocalUrl(backendSettings.openai_base_url);
        }
        if (backendSettings.openai_model) {
          setSelectedModel(backendSettings.openai_model);
        }

        // Also save to AsyncStorage for quick access
        if (backendSettings.ai_provider) {
          await AsyncStorage.setItem('@sara_ai_provider', backendSettings.ai_provider);
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

        if (savedProvider) setAiProvider(savedProvider as 'local' | 'gemini');
        if (savedUrl) setLocalUrl(savedUrl);
        if (savedModel) setSelectedModel(savedModel);
      } catch (storageError) {
        console.error('Failed to load AI settings from AsyncStorage:', storageError);
      }
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    await loadData();
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

  const handleProviderChange = async (provider: 'local' | 'gemini') => {
    setAiProvider(provider);
    await AsyncStorage.setItem('@sara_ai_provider', provider);

    let newModel: string;
    let newUrl: string | undefined;

    // Auto-set defaults based on provider
    if (provider === 'gemini') {
      newModel = 'gemini-2.5-flash-lite';
      newUrl = 'https://generativelanguage.googleapis.com/v1beta/openai/';
    } else {
      // Reset to default local model based on current URL
      newModel = localUrl.includes('100.104.68.115') ? 'gpt-oss:120b' : 'gpt-oss:20b';
      newUrl = localUrl;
    }

    setSelectedModel(newModel);
    await AsyncStorage.setItem('@sara_model', newModel);

    // Save to backend immediately
    await saveSettingsToBackend({
      ai_provider: provider,
      openai_model: newModel,
      openai_base_url: newUrl,
    });
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
      return ['gemini-2.5-flash-lite'];
    }

    if (localUrl.includes('100.104.68.115')) {
      return ['gpt-oss:120b'];
    } else {
      return ['gpt-oss:20b', 'gemini-3-pro-preview:latest'];
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
                <Picker.Item key={model} label={model} value={model} color={colors.text} />
              ))}
            </Picker>
          </View>
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
});
