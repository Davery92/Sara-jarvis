import React, { useState, useEffect } from 'react';
import {
  View,
  ScrollView,
  StyleSheet,
  TouchableOpacity,
  Text,
  Alert,
  ActivityIndicator,
  RefreshControl,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { MainTabScreenProps } from '../../types/navigation';
import {
  calendarService,
  CalendarEvent,
  Reminder,
} from '../../services/calendar';
import EventListItem from '../../components/calendar/EventListItem';
import ReminderListItem from '../../components/calendar/ReminderListItem';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import { Ionicons } from '@expo/vector-icons';
import { navigateToChat } from '../../services/navigation';

type Props = MainTabScreenProps<'Calendar'>;

type ViewMode = 'events' | 'reminders';

export default function CalendarScreen({ navigation }: Props) {
  const [viewMode, setViewMode] = useState<ViewMode>('events');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  // Data states
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [reminders, setReminders] = useState<Reminder[]>([]);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      setLoading(true);
      const today = new Date().toISOString().split('T')[0];
      const monthFromNow = new Date(Date.now() + 30 * 24 * 60 * 60 * 1000)
        .toISOString()
        .split('T')[0];

      const [eventsData, remindersData] = await Promise.all([
        calendarService.getEvents(today, monthFromNow),
        calendarService.getReminders(),
      ]);

      setEvents(eventsData);
      setReminders(remindersData);
    } catch (error) {
      console.error('Failed to load calendar data:', error);
      Alert.alert('Error', 'Failed to load calendar data');
    } finally {
      setLoading(false);
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    await loadData();
    setRefreshing(false);
  };

  // Event handlers
  const handleCreateEvent = () => {
    navigation.navigate('EventForm', {
      onSave: loadData,
    });
  };

  const handleEventPress = (event: CalendarEvent) => {
    Alert.alert(
      event.title,
      `${calendarService.formatDateTime(event.start_time)} - ${calendarService.formatTime(event.end_time)}\n\n${event.description || 'No description'}`,
      [{ text: 'OK' }]
    );
  };

  const handleEventLongPress = (event: CalendarEvent) => {
    // iOS calendar events are read-only
    if (event.read_only || event.source === 'ios_calendar') {
      Alert.alert(
        event.title,
        `This event is synced from iOS Calendar${event.ios_calendar_name ? ` (${event.ios_calendar_name})` : ''} and cannot be edited here.`,
        [{ text: 'OK' }]
      );
      return;
    }

    Alert.alert(
      event.title,
      'What would you like to do?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Edit',
          onPress: () => {
            navigation.navigate('EventForm', {
              event,
              onSave: loadData,
            });
          },
        },
        {
          text: 'Delete',
          style: 'destructive',
          onPress: async () => {
            try {
              await calendarService.deleteEvent(event.id);
              loadData();
            } catch (error) {
              Alert.alert('Error', 'Failed to delete event');
            }
          },
        },
      ]
    );
  };

  // Reminder handlers
  const handleCreateReminder = () => {
    navigation.navigate('ReminderForm', {
      onSave: loadData,
    });
  };

  const handleReminderPress = (reminder: Reminder) => {
    Alert.alert(
      reminder.title,
      `Due: ${calendarService.formatDateTime(reminder.reminder_time)}\n\n${reminder.description || 'No description'}`,
      [{ text: 'OK' }]
    );
  };

  const handleReminderLongPress = (reminder: Reminder) => {
    Alert.alert(
      reminder.title,
      'What would you like to do?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Edit',
          onPress: () => {
            navigation.navigate('ReminderForm', {
              reminder,
              onSave: loadData,
            });
          },
        },
        {
          text: 'Delete',
          style: 'destructive',
          onPress: async () => {
            try {
              await calendarService.deleteReminder(reminder.id);
              loadData();
            } catch (error) {
              Alert.alert('Error', 'Failed to delete reminder');
            }
          },
        },
      ]
    );
  };

  const handleToggleReminderComplete = async (reminder: Reminder) => {
    try {
      await calendarService.toggleReminderComplete(reminder.id, !reminder.is_completed);
      loadData();
    } catch (error) {
      Alert.alert('Error', 'Failed to update reminder');
    }
  };

  if (loading) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  // Group events by date
  const groupedEvents = events.reduce((acc, event) => {
    const dateKey = calendarService.formatDate(event.start_time);
    if (!acc[dateKey]) {
      acc[dateKey] = [];
    }
    acc[dateKey].push(event);
    return acc;
  }, {} as Record<string, CalendarEvent[]>);

  const eventSections = Object.entries(groupedEvents).map(([date, items]) => ({
    title: date,
    data: items,
  }));

  // Separate completed and pending reminders
  const pendingReminders = reminders.filter((r) => !r.is_completed);
  const completedReminders = reminders.filter((r) => r.is_completed);
  const nextEvent = [...events].sort((a, b) => new Date(a.start_time).getTime() - new Date(b.start_time).getTime())[0];
  const nextReminder = [...pendingReminders].sort(
    (a, b) => new Date(a.reminder_time).getTime() - new Date(b.reminder_time).getTime()
  )[0];

  const openCalendarPrompt = () => {
    const message = nextReminder
      ? `Help me plan around my next reminder, "${nextReminder.title}", and organize the rest of today.`
      : nextEvent
        ? `Help me prepare for "${nextEvent.title}" and organize my calendar around it.`
        : 'Help me plan my day and suggest the next calendar event or reminder I should add.';

    navigateToChat({
      quickReply: {
        title: 'Calendar',
        message,
        nudgeType: 'calendar_planning',
      },
    });
  };

  const renderPlannerCard = () => {
    const title = nextReminder
      ? `Next move: clear "${nextReminder.title}"`
      : nextEvent
        ? `Next move: prepare for "${nextEvent.title}"`
        : 'Nothing scheduled yet';

    const body = nextReminder
      ? `${pendingReminders.length} reminder${pendingReminders.length === 1 ? '' : 's'} still need attention.`
      : nextEvent
        ? `${events.length} upcoming event${events.length === 1 ? '' : 's'} are on your calendar.`
        : 'Add the next commitment or let Sara help you shape the day before things pile up.';

    return (
      <View style={styles.plannerCard}>
        <View style={styles.plannerHeader}>
          <View style={styles.plannerIcon}>
            <Ionicons name="today-outline" size={18} color={colors.primary} />
          </View>
          <View style={styles.plannerCopy}>
            <Text style={styles.plannerEyebrow}>What can I do next?</Text>
            <Text style={styles.plannerTitle}>{title}</Text>
            <Text style={styles.plannerBody}>{body}</Text>
          </View>
        </View>

        <View style={styles.plannerActions}>
          <TouchableOpacity
            style={[styles.plannerButton, styles.plannerButtonPrimary]}
            onPress={openCalendarPrompt}
          >
            <Text style={styles.plannerButtonPrimaryText}>Ask Sara</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.plannerButton, styles.plannerButtonSecondary]}
            onPress={() => setViewMode(nextReminder ? 'reminders' : 'events')}
          >
            <Text style={styles.plannerButtonSecondaryText}>
              {nextReminder ? 'Open Reminders' : 'Open Events'}
            </Text>
          </TouchableOpacity>
        </View>
      </View>
    );
  };

  const renderEventsView = () => (
    <ScrollView
      style={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} />}
    >
      {eventSections.length > 0 ? (
        eventSections.map((section) => (
          <View key={section.title} style={styles.section}>
            <Text style={styles.sectionTitle}>{section.title}</Text>
            {section.data.map((event) => (
              <EventListItem
                key={event.id}
                event={event}
                onPress={handleEventPress}
                onLongPress={handleEventLongPress}
              />
            ))}
          </View>
        ))
      ) : (
        <View style={styles.emptyContainer}>
          <Text style={styles.emptyText}>No upcoming events</Text>
        </View>
      )}
    </ScrollView>
  );

  const renderRemindersView = () => (
    <ScrollView
      style={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} />}
    >
      {/* Pending Reminders */}
      {pendingReminders.length > 0 && (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Pending ({pendingReminders.length})</Text>
          {pendingReminders.map((reminder) => (
            <ReminderListItem
              key={reminder.id}
              reminder={reminder}
              onPress={handleReminderPress}
              onLongPress={handleReminderLongPress}
              onToggleComplete={handleToggleReminderComplete}
            />
          ))}
        </View>
      )}

      {/* Completed Reminders */}
      {completedReminders.length > 0 && (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Completed ({completedReminders.length})</Text>
          {completedReminders.map((reminder) => (
            <ReminderListItem
              key={reminder.id}
              reminder={reminder}
              onPress={handleReminderPress}
              onLongPress={handleReminderLongPress}
              onToggleComplete={handleToggleReminderComplete}
            />
          ))}
        </View>
      )}

      {reminders.length === 0 && (
        <View style={styles.emptyContainer}>
          <Text style={styles.emptyText}>No reminders yet</Text>
        </View>
      )}
    </ScrollView>
  );

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      {renderPlannerCard()}

      {/* Navigation Tabs */}
      <View style={styles.tabs}>
        <TouchableOpacity
          style={[styles.tab, viewMode === 'events' && styles.tabActive]}
          onPress={() => setViewMode('events')}
        >
          <Ionicons
            name="calendar-outline"
            size={16}
            color={viewMode === 'events' ? colors.text : colors.textSecondary}
          />
          <Text style={[styles.tabText, viewMode === 'events' && styles.tabTextActive]}>
            Events
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.tab, viewMode === 'reminders' && styles.tabActive]}
          onPress={() => setViewMode('reminders')}
        >
          <Ionicons
            name="checkmark-circle-outline"
            size={16}
            color={viewMode === 'reminders' ? colors.text : colors.textSecondary}
          />
          <Text style={[styles.tabText, viewMode === 'reminders' && styles.tabTextActive]}>
            Reminders
          </Text>
        </TouchableOpacity>
      </View>

      {/* Action Button */}
      <View style={styles.actionBar}>
        <TouchableOpacity
          style={styles.addButton}
          onPress={viewMode === 'events' ? handleCreateEvent : handleCreateReminder}
        >
          <Text style={styles.addButtonText}>
            + New {viewMode === 'events' ? 'Event' : 'Reminder'}
          </Text>
        </TouchableOpacity>
      </View>

      {/* Content */}
      {viewMode === 'events' ? renderEventsView() : renderRemindersView()}
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
    gap: spacing.sm,
  },
  tab: {
    flex: 1,
    flexDirection: 'row',
    justifyContent: 'center',
    gap: spacing.xs,
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
  plannerCard: {
    marginHorizontal: spacing.md,
    marginTop: spacing.md,
    marginBottom: spacing.sm,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  plannerHeader: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.sm,
  },
  plannerIcon: {
    width: 34,
    height: 34,
    borderRadius: borderRadius.full,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: `${colors.primary}1a`,
  },
  plannerCopy: {
    flex: 1,
  },
  plannerEyebrow: {
    color: colors.primary,
    fontSize: fontSizes.xs,
    fontWeight: '700',
    textTransform: 'uppercase',
    marginBottom: 2,
  },
  plannerTitle: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '600',
    marginBottom: spacing.xs,
  },
  plannerBody: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    lineHeight: 20,
  },
  plannerActions: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  plannerButton: {
    flex: 1,
    borderRadius: borderRadius.md,
    paddingVertical: spacing.sm,
    alignItems: 'center',
  },
  plannerButtonPrimary: {
    backgroundColor: colors.primary,
  },
  plannerButtonSecondary: {
    backgroundColor: colors.background,
    borderWidth: 1,
    borderColor: colors.border,
  },
  plannerButtonPrimaryText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  plannerButtonSecondaryText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  actionBar: {
    padding: spacing.md,
  },
  addButton: {
    backgroundColor: colors.primary,
    borderRadius: borderRadius.md,
    paddingVertical: spacing.md,
    alignItems: 'center',
  },
  addButtonText: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
  },
  content: {
    flex: 1,
  },
  section: {
    marginBottom: spacing.lg,
  },
  sectionTitle: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    fontWeight: '600',
    textTransform: 'uppercase',
    paddingHorizontal: spacing.md,
    marginBottom: spacing.sm,
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
});
