import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  StyleSheet,
  Switch,
} from 'react-native';
import { apiClient } from '../../services/api';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import Markdown from 'react-native-markdown-display';

interface DailyBriefing {
  id: string;
  user_id: string;
  briefing_type: 'morning' | 'evening';
  briefing_date: string;
  content: string;
  delivered: boolean;
  delivered_at?: string;
  read: boolean;
  read_at?: string;
  created_at: string;
}

interface BriefingSettings {
  id: string;
  user_id: string;
  morning_enabled: boolean;
  morning_time: string;
  evening_enabled: boolean;
  evening_time: string;
  include_recovery: boolean;
  include_schedule: boolean;
  include_goals: boolean;
  include_suggestions: boolean;
  include_workout_rec: boolean;
  include_accomplishments: boolean;
  include_insights: boolean;
  include_reflection: boolean;
}

export default function BriefingsScreen() {
  const [briefings, setBriefings] = useState<DailyBriefing[]>([]);
  const [settings, setSettings] = useState<BriefingSettings | null>(null);
  const [selectedBriefing, setSelectedBriefing] = useState<DailyBriefing | null>(null);
  const [loading, setLoading] = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    loadBriefings();
    loadSettings();
  }, []);

  const loadBriefings = async () => {
    try {
      const data = await apiClient.getDailyBriefings();
      setBriefings(data);
      // Auto-select today's morning briefing if available
      const today = new Date().toISOString().split('T')[0];
      const todayMorning = data.find((b: DailyBriefing) =>
        b.briefing_date === today && b.briefing_type === 'morning'
      );
      if (todayMorning && !selectedBriefing) {
        setSelectedBriefing(todayMorning);
        markAsRead(todayMorning.id);
      }
    } catch (error) {
      console.error('Failed to load briefings:', error);
    } finally {
      setLoading(false);
    }
  };

  const loadSettings = async () => {
    try {
      const data = await apiClient.getBriefingSettings();
      setSettings(data);
    } catch (error) {
      console.error('Failed to load settings:', error);
    }
  };

  const markAsRead = async (briefingId: string) => {
    try {
      await apiClient.markBriefingRead(briefingId);
      setBriefings(prev => prev.map(b =>
        b.id === briefingId ? { ...b, read: true, read_at: new Date().toISOString() } : b
      ));
    } catch (error) {
      console.error('Failed to mark as read:', error);
    }
  };

  const generateBriefing = async (type: 'morning' | 'evening') => {
    setGenerating(true);
    try {
      const newBriefing = await apiClient.generateBriefing(type);
      setBriefings(prev => [newBriefing, ...prev]);
      setSelectedBriefing(newBriefing);
    } catch (error) {
      console.error('Failed to generate briefing:', error);
    } finally {
      setGenerating(false);
    }
  };

  const updateSettings = async (newSettings: Partial<BriefingSettings>) => {
    try {
      const updated = await apiClient.updateBriefingSettings(newSettings);
      setSettings(updated);
    } catch (error) {
      console.error('Failed to update settings:', error);
    }
  };

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', {
      weekday: 'short',
      month: 'short',
      day: 'numeric'
    });
  };

  if (loading) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  if (settingsOpen && settings) {
    return (
      <ScrollView style={styles.container}>
        <View style={styles.header}>
          <Text style={styles.title}>Briefing Settings</Text>
          <TouchableOpacity onPress={() => setSettingsOpen(false)}>
            <Text style={styles.doneButton}>Done</Text>
          </TouchableOpacity>
        </View>

        <View style={styles.settingsSection}>
          <Text style={styles.sectionTitle}>Morning Briefing</Text>
          <View style={styles.settingRow}>
            <Text style={styles.settingLabel}>Enable Morning Briefings</Text>
            <Switch
              value={settings.morning_enabled}
              onValueChange={(value) => updateSettings({ morning_enabled: value })}
              trackColor={{ false: colors.border, true: colors.primary }}
            />
          </View>
          <View style={styles.settingRow}>
            <Text style={styles.settingLabel}>Include Recovery Status</Text>
            <Switch
              value={settings.include_recovery}
              onValueChange={(value) => updateSettings({ include_recovery: value })}
              trackColor={{ false: colors.border, true: colors.primary }}
            />
          </View>
          <View style={styles.settingRow}>
            <Text style={styles.settingLabel}>Include Schedule</Text>
            <Switch
              value={settings.include_schedule}
              onValueChange={(value) => updateSettings({ include_schedule: value })}
              trackColor={{ false: colors.border, true: colors.primary }}
            />
          </View>
          <View style={styles.settingRow}>
            <Text style={styles.settingLabel}>Include Goals</Text>
            <Switch
              value={settings.include_goals}
              onValueChange={(value) => updateSettings({ include_goals: value })}
              trackColor={{ false: colors.border, true: colors.primary }}
            />
          </View>
          <View style={styles.settingRow}>
            <Text style={styles.settingLabel}>Include Suggestions</Text>
            <Switch
              value={settings.include_suggestions}
              onValueChange={(value) => updateSettings({ include_suggestions: value })}
              trackColor={{ false: colors.border, true: colors.primary }}
            />
          </View>
          <View style={styles.settingRow}>
            <Text style={styles.settingLabel}>Include Workout Rec</Text>
            <Switch
              value={settings.include_workout_rec}
              onValueChange={(value) => updateSettings({ include_workout_rec: value })}
              trackColor={{ false: colors.border, true: colors.primary }}
            />
          </View>
        </View>

        <View style={styles.settingsSection}>
          <Text style={styles.sectionTitle}>Evening Briefing</Text>
          <View style={styles.settingRow}>
            <Text style={styles.settingLabel}>Enable Evening Briefings</Text>
            <Switch
              value={settings.evening_enabled}
              onValueChange={(value) => updateSettings({ evening_enabled: value })}
              trackColor={{ false: colors.border, true: colors.primary }}
            />
          </View>
          <View style={styles.settingRow}>
            <Text style={styles.settingLabel}>Include Accomplishments</Text>
            <Switch
              value={settings.include_accomplishments}
              onValueChange={(value) => updateSettings({ include_accomplishments: value })}
              trackColor={{ false: colors.border, true: colors.primary }}
            />
          </View>
          <View style={styles.settingRow}>
            <Text style={styles.settingLabel}>Include Insights</Text>
            <Switch
              value={settings.include_insights}
              onValueChange={(value) => updateSettings({ include_insights: value })}
              trackColor={{ false: colors.border, true: colors.primary }}
            />
          </View>
          <View style={styles.settingRow}>
            <Text style={styles.settingLabel}>Include Reflection</Text>
            <Switch
              value={settings.include_reflection}
              onValueChange={(value) => updateSettings({ include_reflection: value })}
              trackColor={{ false: colors.border, true: colors.primary }}
            />
          </View>
        </View>
      </ScrollView>
    );
  }

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <View>
          <Text style={styles.title}>Daily Briefings</Text>
          <Text style={styles.subtitle}>Personalized summaries</Text>
        </View>
        <TouchableOpacity
          onPress={() => setSettingsOpen(true)}
          style={styles.settingsButton}
        >
          <Text style={styles.settingsIcon}>⚙️</Text>
        </TouchableOpacity>
      </View>

      <View style={styles.actionButtons}>
        <TouchableOpacity
          onPress={() => generateBriefing('morning')}
          disabled={generating}
          style={[styles.generateButton, styles.morningButton]}
        >
          <Text style={styles.generateButtonIcon}>🌅</Text>
          <Text style={styles.generateButtonText}>Morning</Text>
        </TouchableOpacity>
        <TouchableOpacity
          onPress={() => generateBriefing('evening')}
          disabled={generating}
          style={[styles.generateButton, styles.eveningButton]}
        >
          <Text style={styles.generateButtonIcon}>🌙</Text>
          <Text style={styles.generateButtonText}>Evening</Text>
        </TouchableOpacity>
      </View>

      {selectedBriefing ? (
        <ScrollView style={styles.contentArea}>
          <View style={styles.briefingHeader}>
            <Text style={styles.briefingIcon}>
              {selectedBriefing.briefing_type === 'morning' ? '🌅' : '🌙'}
            </Text>
            <View style={styles.briefingHeaderText}>
              <Text style={styles.briefingType}>
                {selectedBriefing.briefing_type.charAt(0).toUpperCase() +
                 selectedBriefing.briefing_type.slice(1)} Briefing
              </Text>
              <Text style={styles.briefingDate}>
                {formatDate(selectedBriefing.briefing_date)}
              </Text>
            </View>
          </View>

          <Markdown style={markdownStyles}>
            {selectedBriefing.content}
          </Markdown>
        </ScrollView>
      ) : (
        <View style={styles.emptyState}>
          <Text style={styles.emptyIcon}>📋</Text>
          <Text style={styles.emptyText}>No briefings yet</Text>
          <Text style={styles.emptySubtext}>Generate your first briefing</Text>
        </View>
      )}

      {briefings.length > 0 && (
        <View style={styles.briefingsList}>
          <Text style={styles.listTitle}>Recent</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false}>
            {briefings.slice(0, 10).map((briefing) => (
              <TouchableOpacity
                key={briefing.id}
                onPress={() => {
                  setSelectedBriefing(briefing);
                  if (!briefing.read) markAsRead(briefing.id);
                }}
                style={[
                  styles.briefingCard,
                  selectedBriefing?.id === briefing.id && styles.briefingCardActive
                ]}
              >
                <Text style={styles.briefingCardIcon}>
                  {briefing.briefing_type === 'morning' ? '🌅' : '🌙'}
                </Text>
                <Text style={styles.briefingCardType}>
                  {briefing.briefing_type}
                </Text>
                <Text style={styles.briefingCardDate}>
                  {formatDate(briefing.briefing_date)}
                </Text>
                {!briefing.read && <View style={styles.unreadDot} />}
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
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: spacing.lg,
    backgroundColor: colors.surface,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  title: {
    fontSize: fontSizes.xxl,
    fontWeight: 'bold',
    color: colors.text,
  },
  subtitle: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
    marginTop: spacing.xs,
  },
  settingsButton: {
    padding: spacing.sm,
  },
  settingsIcon: {
    fontSize: 24,
  },
  doneButton: {
    fontSize: fontSizes.md,
    color: colors.primary,
    fontWeight: '600',
  },
  actionButtons: {
    flexDirection: 'row',
    padding: spacing.lg,
    gap: spacing.md,
  },
  generateButton: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    padding: spacing.md,
    borderRadius: borderRadius.lg,
    gap: spacing.sm,
  },
  morningButton: {
    backgroundColor: '#f59e0b',
  },
  eveningButton: {
    backgroundColor: '#6366f1',
  },
  generateButtonIcon: {
    fontSize: 20,
  },
  generateButtonText: {
    color: '#fff',
    fontWeight: '600',
    fontSize: fontSizes.md,
  },
  contentArea: {
    flex: 1,
    padding: spacing.lg,
  },
  briefingHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: spacing.lg,
    paddingBottom: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  briefingIcon: {
    fontSize: 40,
    marginRight: spacing.md,
  },
  briefingHeaderText: {
    flex: 1,
  },
  briefingType: {
    fontSize: fontSizes.xl,
    fontWeight: 'bold',
    color: colors.text,
  },
  briefingDate: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
    marginTop: spacing.xs,
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
  briefingsList: {
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
    paddingHorizontal: spacing.xs,
  },
  briefingCard: {
    width: 100,
    padding: spacing.md,
    marginRight: spacing.sm,
    backgroundColor: colors.background,
    borderRadius: borderRadius.md,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: 'center',
    position: 'relative',
  },
  briefingCardActive: {
    borderColor: colors.primary,
    borderWidth: 2,
  },
  briefingCardIcon: {
    fontSize: 28,
    marginBottom: spacing.xs,
  },
  briefingCardType: {
    fontSize: fontSizes.xs,
    fontWeight: '600',
    color: colors.text,
    textTransform: 'capitalize',
  },
  briefingCardDate: {
    fontSize: fontSizes.xs,
    color: colors.textMuted,
    marginTop: spacing.xs,
  },
  unreadDot: {
    position: 'absolute',
    top: 8,
    right: 8,
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.primary,
  },
  settingsSection: {
    backgroundColor: colors.surface,
    marginHorizontal: spacing.lg,
    marginBottom: spacing.lg,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
  },
  sectionTitle: {
    fontSize: fontSizes.lg,
    fontWeight: '600',
    color: colors.text,
    marginBottom: spacing.md,
  },
  settingRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  settingLabel: {
    fontSize: fontSizes.md,
    color: colors.text,
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
    fontWeight: 'bold',
    color: colors.text,
    marginTop: spacing.lg,
    marginBottom: spacing.md,
  },
  heading2: {
    fontSize: fontSizes.xl,
    fontWeight: '600',
    color: colors.text,
    marginTop: spacing.md,
    marginBottom: spacing.sm,
  },
  heading3: {
    fontSize: fontSizes.lg,
    fontWeight: '600',
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
    fontWeight: 'bold',
    color: colors.text,
  },
  code_inline: {
    backgroundColor: colors.surface,
    color: colors.primary,
    paddingHorizontal: spacing.xs,
    borderRadius: borderRadius.sm,
  },
  blockquote: {
    backgroundColor: colors.surface,
    borderLeftWidth: 4,
    borderLeftColor: colors.primary,
    paddingLeft: spacing.md,
    paddingVertical: spacing.sm,
    marginVertical: spacing.sm,
  },
};
