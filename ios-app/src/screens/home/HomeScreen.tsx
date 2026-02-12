import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  ScrollView,
  StyleSheet,
  RefreshControl,
  Modal,
  TouchableOpacity,
  Text,
  TextInput,
  Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { MainTabScreenProps } from '../../types/navigation';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import apiClient from '../../services/api';
import { useToast } from '../../context/ToastContext';

// Import widgets
import HeaderWidget from '../../components/home/HeaderWidget';
import QuickActionsGrid from '../../components/home/QuickActionsGrid';
import TodayEventsWidget from '../../components/home/TodayEventsWidget';
import TodayRemindersWidget from '../../components/home/TodayRemindersWidget';
import TimersWidget from '../../components/home/TimersWidget';
import RecentFoodWidget from '../../components/home/RecentFoodWidget';
import RecentWorkoutsWidget from '../../components/home/RecentWorkoutsWidget';
import RecoveryWidget from '../../components/home/RecoveryWidget';
import WeatherWidget from '../../components/home/WeatherWidget';

// Import modals
import FoodLogModal from '../../components/fitness/FoodLogModal';
import WorkoutLogModal from '../../components/fitness/WorkoutLogModal';
import RecoveryLogModal from '../../components/fitness/RecoveryLogModal';

// Import contexts and services
import { useTimer } from '../../context/TimerContext';

// --- Sara Status Card ---
const EMOTION_EMOJI: Record<string, string> = {
  curious: '\uD83E\uDD14', calm: '\uD83D\uDE0C', alert: '\u26A1', concerned: '\uD83D\uDE1F',
  happy: '\uD83D\uDE0A', focused: '\uD83C\uDFAF', neutral: '\uD83D\uDE10', reflective: '\uD83E\uDE9E', attentive: '\uD83D\uDC40',
};

function SaraStatusCard() {
  const [status, setStatus] = useState<any>(null);
  const [expanded, setExpanded] = useState(false);

  const fetchStatus = useCallback(async () => {
    try {
      const data = await apiClient.get('/api/sara/status');
      setStatus(data);
    } catch {}
  }, []);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 60000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  if (!status) return null;

  const emoji = EMOTION_EMOJI[status.emotional_state] || '\uD83E\uDD16';

  return (
    <TouchableOpacity
      onPress={() => setExpanded(!expanded)}
      style={saraStyles.card}
      activeOpacity={0.7}
    >
      <View style={saraStyles.topRow}>
        <Text style={saraStyles.emoji}>{emoji}</Text>
        <View style={saraStyles.textCol}>
          <Text style={saraStyles.stateLabel}>Sara is {status.emotional_state}</Text>
          {status.watching_for && (
            <Text style={saraStyles.watching} numberOfLines={1}>Watching for: {status.watching_for}</Text>
          )}
        </View>
        {status.david_energy != null && (
          <View style={saraStyles.energyBadge}>
            <Text style={saraStyles.energyText}>{Math.round(status.david_energy * 100)}%</Text>
          </View>
        )}
      </View>
      {expanded && (
        <View style={saraStyles.expandedSection}>
          {status.latest_thought && (
            <Text style={saraStyles.thought}>{status.latest_thought}</Text>
          )}
          {status.last_action && (
            <Text style={saraStyles.detail}>Last: {status.last_action.slice(0, 100)}</Text>
          )}
          {status.pending_observations > 0 && (
            <Text style={saraStyles.detail}>{status.pending_observations} pending observations</Text>
          )}
          {status.pkg_facts_count > 0 && (
            <Text style={saraStyles.detail}>{status.pkg_facts_count} facts about you</Text>
          )}
        </View>
      )}
    </TouchableOpacity>
  );
}

const saraStyles = StyleSheet.create({
  card: {
    marginHorizontal: spacing.md,
    marginBottom: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  topRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  emoji: { fontSize: 28 },
  textCol: { flex: 1 },
  stateLabel: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
  },
  watching: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginTop: 2,
  },
  energyBadge: {
    backgroundColor: 'rgba(16, 185, 129, 0.15)',
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 8,
  },
  energyText: {
    color: colors.success,
    fontSize: fontSizes.xs,
    fontWeight: '600',
  },
  expandedSection: {
    marginTop: spacing.sm,
    paddingTop: spacing.sm,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    gap: 4,
  },
  thought: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontStyle: 'italic',
  },
  detail: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
  },
});

type Props = MainTabScreenProps<'Home'>;

export default function HomeScreen({ navigation }: Props) {
  const [refreshing, setRefreshing] = useState(false);
  const [showFoodModal, setShowFoodModal] = useState(false);
  const [showWorkoutModal, setShowWorkoutModal] = useState(false);
  const [showRecoveryModal, setShowRecoveryModal] = useState(false);
  const [showQuickNoteModal, setShowQuickNoteModal] = useState(false);
  const [showTimerModal, setShowTimerModal] = useState(false);
  const [noteText, setNoteText] = useState('');
  const [timerTitle, setTimerTitle] = useState('');
  const [timerMinutes, setTimerMinutes] = useState('25');
  const [refreshKey, setRefreshKey] = useState(0);

  const { startTimer } = useTimer();
  const { showToast } = useToast();

  const handleRefresh = async () => {
    setRefreshing(true);
    setRefreshKey(k => k + 1);
    await new Promise((resolve) => setTimeout(resolve, 1000));
    setRefreshing(false);
  };

  const handleLogFood = () => {
    setShowFoodModal(true);
  };

  const handleLogWorkout = () => {
    setShowWorkoutModal(true);
  };

  const handleLogRecovery = () => {
    setShowRecoveryModal(true);
  };

  const handleQuickNote = () => {
    setShowQuickNoteModal(true);
  };

  const handleStartTimer = () => {
    setShowTimerModal(true);
  };

  const handleSaveNote = async () => {
    if (!noteText.trim()) {
      Alert.alert('Error', 'Please enter a note');
      return;
    }
    try {
      await apiClient.post('/notes', { title: 'Quick Note', content: noteText.trim() });
      setNoteText('');
      setShowQuickNoteModal(false);
      showToast('success', 'Note saved');
    } catch {
      showToast('error', 'Failed to save note');
    }
  };

  const handleCreateTimer = async () => {
    if (!timerTitle.trim()) {
      Alert.alert('Error', 'Please enter a timer title');
      return;
    }

    const minutes = parseInt(timerMinutes, 10);
    if (isNaN(minutes) || minutes <= 0) {
      Alert.alert('Error', 'Please enter a valid duration');
      return;
    }

    await startTimer(timerTitle, minutes * 60);
    setTimerTitle('');
    setTimerMinutes('25');
    setShowTimerModal(false);
  };

  return (
    <SafeAreaView style={styles.container} edges={['top', 'left', 'right']}>
      <ScrollView
        style={styles.scrollView}
        contentContainerStyle={styles.scrollContent}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={handleRefresh}
            tintColor={colors.primary}
          />
        }
      >
        <HeaderWidget />
        <SaraStatusCard key={`sara-${refreshKey}`} />
        <QuickActionsGrid
          onLogFood={handleLogFood}
          onLogWorkout={handleLogWorkout}
          onLogRecovery={handleLogRecovery}
          onQuickNote={handleQuickNote}
          onStartTimer={handleStartTimer}
        />
        <WeatherWidget />
        <TodayEventsWidget />
        <TodayRemindersWidget />
        <TimersWidget />
        <RecentFoodWidget />
        <RecentWorkoutsWidget />
        <RecoveryWidget />
      </ScrollView>

      {/* Food Log Modal */}
      <FoodLogModal
        visible={showFoodModal}
        onClose={() => setShowFoodModal(false)}
        onComplete={() => {
          setShowFoodModal(false);
          handleRefresh();
        }}
      />

      {/* Workout Log Modal */}
      <WorkoutLogModal
        visible={showWorkoutModal}
        onClose={() => setShowWorkoutModal(false)}
        onComplete={() => {
          setShowWorkoutModal(false);
          handleRefresh();
        }}
      />

      {/* Recovery Log Modal */}
      <RecoveryLogModal
        visible={showRecoveryModal}
        onClose={() => setShowRecoveryModal(false)}
        onComplete={() => {
          setShowRecoveryModal(false);
          handleRefresh();
        }}
      />

      {/* Quick Note Modal */}
      <Modal
        visible={showQuickNoteModal}
        animationType="slide"
        presentationStyle="pageSheet"
        onRequestClose={() => setShowQuickNoteModal(false)}
      >
        <SafeAreaView style={styles.modalContainer} edges={['top', 'left', 'right']}>
          <View style={styles.modalHeader}>
            <TouchableOpacity onPress={() => setShowQuickNoteModal(false)}>
              <Text style={styles.modalCancel}>Cancel</Text>
            </TouchableOpacity>
            <Text style={styles.modalTitle}>Quick Note</Text>
            <TouchableOpacity onPress={handleSaveNote}>
              <Text style={styles.modalSave}>Save</Text>
            </TouchableOpacity>
          </View>
          <View style={styles.modalContent}>
            <TextInput
              style={styles.noteInput}
              placeholder="What's on your mind?"
              placeholderTextColor={colors.textMuted}
              value={noteText}
              onChangeText={setNoteText}
              multiline
              autoFocus
            />
          </View>
        </SafeAreaView>
      </Modal>

      {/* Timer Modal */}
      <Modal
        visible={showTimerModal}
        animationType="slide"
        presentationStyle="pageSheet"
        onRequestClose={() => setShowTimerModal(false)}
      >
        <SafeAreaView style={styles.modalContainer} edges={['top', 'left', 'right']}>
          <View style={styles.modalHeader}>
            <TouchableOpacity onPress={() => setShowTimerModal(false)}>
              <Text style={styles.modalCancel}>Cancel</Text>
            </TouchableOpacity>
            <Text style={styles.modalTitle}>Start Timer</Text>
            <TouchableOpacity onPress={handleCreateTimer}>
              <Text style={styles.modalSave}>Start</Text>
            </TouchableOpacity>
          </View>
          <View style={styles.modalContent}>
            <Text style={styles.label}>Timer Title</Text>
            <TextInput
              style={styles.input}
              placeholder="e.g., Focus Session"
              placeholderTextColor={colors.textMuted}
              value={timerTitle}
              onChangeText={setTimerTitle}
              autoFocus
            />
            <Text style={styles.label}>Duration (minutes)</Text>
            <TextInput
              style={styles.input}
              placeholder="25"
              placeholderTextColor={colors.textMuted}
              value={timerMinutes}
              onChangeText={setTimerMinutes}
              keyboardType="number-pad"
            />
          </View>
        </SafeAreaView>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  scrollView: {
    flex: 1,
  },
  scrollContent: {
    paddingBottom: spacing.xl,
  },
  modalContainer: {
    flex: 1,
    backgroundColor: colors.background,
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  modalTitle: {
    fontSize: fontSizes.lg,
    fontWeight: '600',
    color: colors.text,
  },
  modalCancel: {
    fontSize: fontSizes.md,
    color: colors.error,
  },
  modalSave: {
    fontSize: fontSizes.md,
    color: colors.primary,
    fontWeight: '600',
  },
  modalContent: {
    flex: 1,
    padding: spacing.lg,
  },
  noteInput: {
    flex: 1,
    fontSize: fontSizes.md,
    color: colors.text,
    textAlignVertical: 'top',
  },
  label: {
    fontSize: fontSizes.md,
    fontWeight: '600',
    color: colors.text,
    marginBottom: spacing.sm,
    marginTop: spacing.md,
  },
  input: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    fontSize: fontSizes.md,
    color: colors.text,
    borderWidth: 1,
    borderColor: colors.border,
  },
});
