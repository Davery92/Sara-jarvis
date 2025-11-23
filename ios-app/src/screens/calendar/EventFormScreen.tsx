import React, { useState } from 'react';
import {
  View,
  ScrollView,
  StyleSheet,
  TouchableOpacity,
  Text,
  TextInput,
  Alert,
  Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import DateTimePicker from '@react-native-community/datetimepicker';
import { calendarService, CalendarEvent } from '../../services/calendar';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface EventFormScreenProps {
  route?: {
    params?: {
      event?: CalendarEvent;
      onSave?: () => void;
    };
  };
  navigation: any;
}

export default function EventFormScreen({ route, navigation }: EventFormScreenProps) {
  const existingEvent = route?.params?.event;
  const onSave = route?.params?.onSave;

  const [title, setTitle] = useState(existingEvent?.title || '');
  const [description, setDescription] = useState(existingEvent?.description || '');
  const [location, setLocation] = useState(existingEvent?.location || '');

  // Initialize dates
  const now = new Date();
  now.setMinutes(0, 0, 0);
  const defaultStart = existingEvent?.start_time ? new Date(existingEvent.start_time) : now;
  const defaultEnd = existingEvent?.end_time
    ? new Date(existingEvent.end_time)
    : new Date(now.getTime() + 60 * 60 * 1000);

  const [startDate, setStartDate] = useState(defaultStart);
  const [endDate, setEndDate] = useState(defaultEnd);
  const [allDay, setAllDay] = useState(existingEvent?.all_day || false);

  const [showStartDatePicker, setShowStartDatePicker] = useState(false);
  const [showStartTimePicker, setShowStartTimePicker] = useState(false);
  const [showEndDatePicker, setShowEndDatePicker] = useState(false);
  const [showEndTimePicker, setShowEndTimePicker] = useState(false);

  const [saving, setSaving] = useState(false);

  const handleStartDateChange = (event: any, selectedDate?: Date) => {
    setShowStartDatePicker(Platform.OS === 'ios');
    if (selectedDate) {
      const newStart = new Date(selectedDate);
      newStart.setHours(startDate.getHours(), startDate.getMinutes());
      setStartDate(newStart);

      // Adjust end date if needed
      if (newStart >= endDate) {
        setEndDate(new Date(newStart.getTime() + 60 * 60 * 1000));
      }
    }
  };

  const handleStartTimeChange = (event: any, selectedTime?: Date) => {
    setShowStartTimePicker(Platform.OS === 'ios');
    if (selectedTime) {
      const newStart = new Date(startDate);
      newStart.setHours(selectedTime.getHours(), selectedTime.getMinutes());
      setStartDate(newStart);

      // Adjust end date if needed
      if (newStart >= endDate) {
        setEndDate(new Date(newStart.getTime() + 60 * 60 * 1000));
      }
    }
  };

  const handleEndDateChange = (event: any, selectedDate?: Date) => {
    setShowEndDatePicker(Platform.OS === 'ios');
    if (selectedDate) {
      const newEnd = new Date(selectedDate);
      newEnd.setHours(endDate.getHours(), endDate.getMinutes());
      if (newEnd > startDate) {
        setEndDate(newEnd);
      } else {
        Alert.alert('Invalid Date', 'End date must be after start date');
      }
    }
  };

  const handleEndTimeChange = (event: any, selectedTime?: Date) => {
    setShowEndTimePicker(Platform.OS === 'ios');
    if (selectedTime) {
      const newEnd = new Date(endDate);
      newEnd.setHours(selectedTime.getHours(), selectedTime.getMinutes());
      if (newEnd > startDate) {
        setEndDate(newEnd);
      } else {
        Alert.alert('Invalid Time', 'End time must be after start time');
      }
    }
  };

  const handleSave = async () => {
    if (!title.trim()) {
      Alert.alert('Missing Title', 'Please enter an event title');
      return;
    }

    try {
      setSaving(true);

      const eventData = {
        title: title.trim(),
        description: description.trim(),
        start_time: startDate.toISOString(),
        end_time: endDate.toISOString(),
        location: location.trim(),
        all_day: allDay,
      };

      if (existingEvent) {
        await calendarService.updateEvent(existingEvent.id, eventData);
      } else {
        await calendarService.createEvent(eventData);
      }

      Alert.alert('Success', 'Event saved successfully', [
        {
          text: 'OK',
          onPress: () => {
            onSave?.();
            navigation.goBack();
          },
        },
      ]);
    } catch (error) {
      console.error('Failed to save event:', error);
      Alert.alert('Error', 'Failed to save event');
    } finally {
      setSaving(false);
    }
  };

  const formatDate = (date: Date) => {
    return date.toLocaleDateString('en-US', {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  };

  const formatTime = (date: Date) => {
    return date.toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
    });
  };

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.goBack()}>
          <Text style={styles.cancelButton}>Cancel</Text>
        </TouchableOpacity>
        <Text style={styles.title}>
          {existingEvent ? 'Edit Event' : 'New Event'}
        </Text>
        <TouchableOpacity onPress={handleSave} disabled={saving}>
          <Text style={[styles.saveButton, saving && styles.saveButtonDisabled]}>
            {saving ? 'Saving...' : 'Save'}
          </Text>
        </TouchableOpacity>
      </View>

      <ScrollView style={styles.content}>
        {/* Title */}
        <View style={styles.formGroup}>
          <Text style={styles.label}>Title *</Text>
          <TextInput
            style={styles.input}
            value={title}
            onChangeText={setTitle}
            placeholder="Event title"
            placeholderTextColor={colors.textMuted}
          />
        </View>

        {/* All Day Toggle */}
        <View style={styles.formGroup}>
          <TouchableOpacity
            style={styles.toggleRow}
            onPress={() => setAllDay(!allDay)}
          >
            <Text style={styles.label}>All Day Event</Text>
            <View style={[styles.toggle, allDay && styles.toggleActive]}>
              <View style={[styles.toggleThumb, allDay && styles.toggleThumbActive]} />
            </View>
          </TouchableOpacity>
        </View>

        {/* Start Date & Time */}
        <View style={styles.formGroup}>
          <Text style={styles.label}>Starts</Text>
          <View style={styles.dateTimeRow}>
            <TouchableOpacity
              style={[styles.dateTimeButton, { flex: 1.5 }]}
              onPress={() => setShowStartDatePicker(true)}
            >
              <Text style={styles.dateTimeText}>{formatDate(startDate)}</Text>
            </TouchableOpacity>
            {!allDay && (
              <TouchableOpacity
                style={[styles.dateTimeButton, { flex: 1 }]}
                onPress={() => setShowStartTimePicker(true)}
              >
                <Text style={styles.dateTimeText}>{formatTime(startDate)}</Text>
              </TouchableOpacity>
            )}
          </View>
        </View>

        {/* End Date & Time */}
        <View style={styles.formGroup}>
          <Text style={styles.label}>Ends</Text>
          <View style={styles.dateTimeRow}>
            <TouchableOpacity
              style={[styles.dateTimeButton, { flex: 1.5 }]}
              onPress={() => setShowEndDatePicker(true)}
            >
              <Text style={styles.dateTimeText}>{formatDate(endDate)}</Text>
            </TouchableOpacity>
            {!allDay && (
              <TouchableOpacity
                style={[styles.dateTimeButton, { flex: 1 }]}
                onPress={() => setShowEndTimePicker(true)}
              >
                <Text style={styles.dateTimeText}>{formatTime(endDate)}</Text>
              </TouchableOpacity>
            )}
          </View>
        </View>

        {/* Location */}
        <View style={styles.formGroup}>
          <Text style={styles.label}>Location (Optional)</Text>
          <TextInput
            style={styles.input}
            value={location}
            onChangeText={setLocation}
            placeholder="Add location"
            placeholderTextColor={colors.textMuted}
          />
        </View>

        {/* Description */}
        <View style={styles.formGroup}>
          <Text style={styles.label}>Description (Optional)</Text>
          <TextInput
            style={[styles.input, styles.descriptionInput]}
            value={description}
            onChangeText={setDescription}
            placeholder="Add description"
            placeholderTextColor={colors.textMuted}
            multiline
            numberOfLines={4}
            textAlignVertical="top"
          />
        </View>
      </ScrollView>

      {/* Date/Time Pickers */}
      {showStartDatePicker && (
        <DateTimePicker
          value={startDate}
          mode="date"
          display={Platform.OS === 'ios' ? 'spinner' : 'default'}
          onChange={handleStartDateChange}
        />
      )}
      {showStartTimePicker && (
        <DateTimePicker
          value={startDate}
          mode="time"
          display={Platform.OS === 'ios' ? 'spinner' : 'default'}
          onChange={handleStartTimeChange}
        />
      )}
      {showEndDatePicker && (
        <DateTimePicker
          value={endDate}
          mode="date"
          display={Platform.OS === 'ios' ? 'spinner' : 'default'}
          onChange={handleEndDateChange}
        />
      )}
      {showEndTimePicker && (
        <DateTimePicker
          value={endDate}
          mode="time"
          display={Platform.OS === 'ios' ? 'spinner' : 'default'}
          onChange={handleEndTimeChange}
        />
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.surface,
  },
  title: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '600',
  },
  cancelButton: {
    color: colors.textSecondary,
    fontSize: fontSizes.md,
  },
  saveButton: {
    color: colors.primary,
    fontSize: fontSizes.md,
    fontWeight: '600',
  },
  saveButtonDisabled: {
    color: colors.textMuted,
  },
  content: {
    flex: 1,
    padding: spacing.md,
  },
  formGroup: {
    marginBottom: spacing.lg,
  },
  label: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '600',
    marginBottom: spacing.sm,
  },
  input: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    color: colors.text,
    fontSize: fontSizes.md,
  },
  descriptionInput: {
    minHeight: 100,
  },
  toggleRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  toggle: {
    width: 50,
    height: 30,
    borderRadius: 15,
    backgroundColor: colors.surface,
    padding: 2,
  },
  toggleActive: {
    backgroundColor: colors.primary,
  },
  toggleThumb: {
    width: 26,
    height: 26,
    borderRadius: 13,
    backgroundColor: colors.textMuted,
  },
  toggleThumbActive: {
    backgroundColor: colors.text,
    transform: [{ translateX: 20 }],
  },
  dateTimeRow: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  dateTimeButton: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    alignItems: 'center',
  },
  dateTimeText: {
    color: colors.text,
    fontSize: fontSizes.md,
  },
});
