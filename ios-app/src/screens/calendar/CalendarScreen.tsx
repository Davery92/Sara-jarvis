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
  SectionList,
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
      {/* Navigation Tabs */}
      <View style={styles.tabs}>
        <TouchableOpacity
          style={[styles.tab, viewMode === 'events' && styles.tabActive]}
          onPress={() => setViewMode('events')}
        >
          <Text style={[styles.tabText, viewMode === 'events' && styles.tabTextActive]}>
            📅 Events
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.tab, viewMode === 'reminders' && styles.tabActive]}
          onPress={() => setViewMode('reminders')}
        >
          <Text style={[styles.tabText, viewMode === 'reminders' && styles.tabTextActive]}>
            ✅ Reminders
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
