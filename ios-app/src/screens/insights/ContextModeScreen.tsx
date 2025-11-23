import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  ActivityIndicator,
  StyleSheet,
} from 'react-native';
import { apiClient } from '../../services/api';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface ContextMode {
  mode: string;
  name: string;
  description: string;
  icon: string;
}

const CONTEXT_MODES: ContextMode[] = [
  {
    mode: 'full',
    name: 'Full Context',
    description: 'Complete access to all memories, notes, documents, and data.',
    icon: '🧠'
  },
  {
    mode: 'recent',
    name: 'Recent Only',
    description: 'Access only to recent conversations and current session.',
    icon: '⚡'
  },
  {
    mode: 'minimal',
    name: 'Minimal Context',
    description: 'No memory retrieval for ultra-fast responses.',
    icon: '💬'
  },
  {
    mode: 'fitness',
    name: 'Fitness Focus',
    description: 'Prioritizes workout logs, recovery data, and nutrition.',
    icon: '💪'
  },
  {
    mode: 'work',
    name: 'Work Mode',
    description: 'Focuses on productivity, calendar, tasks, and professional context.',
    icon: '💼'
  },
  {
    mode: 'learning',
    name: 'Learning Mode',
    description: 'Emphasizes notes, documents, and knowledge-building.',
    icon: '📚'
  }
];

export default function ContextModeScreen() {
  const [currentMode, setCurrentMode] = useState<string>('full');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [stats, setStats] = useState<any>(null);

  useEffect(() => {
    loadCurrentMode();
    loadContextStats();
  }, []);

  const loadCurrentMode = async () => {
    try {
      const data = await apiClient.getContextMode();
      setCurrentMode(data.mode || 'full');
    } catch (error) {
      console.error('Failed to load context mode:', error);
    } finally {
      setLoading(false);
    }
  };

  const loadContextStats = async () => {
    try {
      const data = await apiClient.getContextStats();
      setStats(data);
    } catch (error) {
      console.error('Failed to load context stats:', error);
    }
  };

  const switchMode = async (mode: string) => {
    setSaving(true);
    try {
      await apiClient.setContextMode(mode);
      setCurrentMode(mode);
      await loadContextStats();
    } catch (error) {
      console.error('Failed to switch context mode:', error);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  const activeMode = CONTEXT_MODES.find(m => m.mode === currentMode) || CONTEXT_MODES[0];

  return (
    <ScrollView style={styles.container}>
      <View style={styles.header}>
        <View style={styles.currentMode}>
          <Text style={styles.currentModeIcon}>{activeMode.icon}</Text>
          <View>
            <Text style={styles.currentModeLabel}>Current Mode</Text>
            <Text style={styles.currentModeName}>{activeMode.name}</Text>
          </View>
        </View>
      </View>

      {stats && (
        <View style={styles.statsContainer}>
          <Text style={styles.sectionTitle}>Available Context</Text>
          <View style={styles.statsGrid}>
            <View style={styles.statCard}>
              <Text style={styles.statValue}>{stats.total_episodes || 0}</Text>
              <Text style={styles.statLabel}>Memories</Text>
            </View>
            <View style={styles.statCard}>
              <Text style={styles.statValue}>{stats.total_notes || 0}</Text>
              <Text style={styles.statLabel}>Notes</Text>
            </View>
            <View style={styles.statCard}>
              <Text style={styles.statValue}>{stats.total_documents || 0}</Text>
              <Text style={styles.statLabel}>Documents</Text>
            </View>
            <View style={styles.statCard}>
              <Text style={styles.statValue}>{stats.total_events || 0}</Text>
              <Text style={styles.statLabel}>Events</Text>
            </View>
          </View>
        </View>
      )}

      <View style={styles.modesContainer}>
        <Text style={styles.sectionTitle}>Select Mode</Text>
        {CONTEXT_MODES.map((mode) => {
          const isActive = currentMode === mode.mode;
          return (
            <TouchableOpacity
              key={mode.mode}
              onPress={() => switchMode(mode.mode)}
              disabled={saving}
              style={[
                styles.modeCard,
                isActive && styles.modeCardActive
              ]}
            >
              <View style={styles.modeHeader}>
                <Text style={styles.modeIcon}>{mode.icon}</Text>
                {isActive && <Text style={styles.checkmark}>✓</Text>}
              </View>
              <Text style={styles.modeName}>{mode.name}</Text>
              <Text style={styles.modeDescription}>{mode.description}</Text>
            </TouchableOpacity>
          );
        })}
      </View>
    </ScrollView>
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
    backgroundColor: colors.surface,
    padding: spacing.lg,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  currentMode: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  currentModeIcon: {
    fontSize: 48,
  },
  currentModeLabel: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
  },
  currentModeName: {
    fontSize: fontSizes.xl,
    fontWeight: 'bold',
    color: colors.text,
  },
  statsContainer: {
    padding: spacing.lg,
  },
  sectionTitle: {
    fontSize: fontSizes.lg,
    fontWeight: '600',
    color: colors.text,
    marginBottom: spacing.md,
  },
  statsGrid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.md,
  },
  statCard: {
    flex: 1,
    minWidth: '45%',
    backgroundColor: colors.surface,
    padding: spacing.md,
    borderRadius: borderRadius.md,
    alignItems: 'center',
  },
  statValue: {
    fontSize: fontSizes.xxl,
    fontWeight: 'bold',
    color: colors.primary,
  },
  statLabel: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
    marginTop: spacing.xs,
  },
  modesContainer: {
    padding: spacing.lg,
  },
  modeCard: {
    backgroundColor: colors.surface,
    padding: spacing.lg,
    borderRadius: borderRadius.lg,
    marginBottom: spacing.md,
    borderWidth: 2,
    borderColor: colors.border,
  },
  modeCardActive: {
    borderColor: colors.primary,
    backgroundColor: `${colors.primary}15`,
  },
  modeHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.sm,
  },
  modeIcon: {
    fontSize: 32,
  },
  checkmark: {
    fontSize: 24,
    color: colors.primary,
  },
  modeName: {
    fontSize: fontSizes.lg,
    fontWeight: '600',
    color: colors.text,
    marginBottom: spacing.xs,
  },
  modeDescription: {
    fontSize: fontSizes.sm,
    color: colors.textMuted,
    lineHeight: 20,
  },
});
