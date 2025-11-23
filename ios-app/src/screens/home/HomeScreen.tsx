import React, { useState } from 'react';
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

  const { startTimer } = useTimer();

  const handleRefresh = async () => {
    setRefreshing(true);
    // Give widgets time to refresh
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

  const handleSaveNote = () => {
    if (!noteText.trim()) {
      Alert.alert('Error', 'Please enter a note');
      return;
    }
    // TODO: Implement quick note saving to backend
    Alert.alert('Success', 'Note saved');
    setNoteText('');
    setShowQuickNoteModal(false);
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
