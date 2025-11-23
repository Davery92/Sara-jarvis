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
import { calendarService, Reminder } from '../../services/calendar';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface ReminderFormScreenProps {
  route?: {
    params?: {
      reminder?: Reminder;
      onSave?: () => void;
    };
  };
  navigation: any;
}

export default function ReminderFormScreen({ route, navigation }: ReminderFormScreenProps) {
  const existingReminder = route?.params?.reminder;
  const onSave = route?.params?.onSave;

  const [title, setTitle] = useState(existingReminder?.title || '');
  const [description, setDescription] = useState(existingReminder?.description || '');

  // Initialize date
  const now = new Date();
  now.setHours(12, 0, 0, 0);
  const defaultDate = existingReminder?.reminder_time
    ? new Date(existingReminder.reminder_time)
    : new Date(now.getTime() + 24 * 60 * 60 * 1000); // Tomorrow at noon

  const [reminderDate, setReminderDate] = useState(defaultDate);

  const [showDatePicker, setShowDatePicker] = useState(false);
  const [showTimePicker, setShowTimePicker] = useState(false);

  const [saving, setSaving] = useState(false);

  const handleDateChange = (event: any, selectedDate?: Date) => {
    setShowDatePicker(Platform.OS === 'ios');
    if (selectedDate) {
      const newDate = new Date(selectedDate);
      newDate.setHours(reminderDate.getHours(), reminderDate.getMinutes());
      setReminderDate(newDate);
    }
  };

  const handleTimeChange = (event: any, selectedTime?: Date) => {
    setShowTimePicker(Platform.OS === 'ios');
    if (selectedTime) {
      const newDate = new Date(reminderDate);
      newDate.setHours(selectedTime.getHours(), selectedTime.getMinutes());
      setReminderDate(newDate);
    }
  };

  const handleSave = async () => {
    if (!title.trim()) {
      Alert.alert('Missing Title', 'Please enter a reminder title');
      return;
    }

    try {
      setSaving(true);

      const reminderData = {
        title: title.trim(),
        description: description.trim(),
        reminder_time: reminderDate.toISOString(),
      };

      if (existingReminder) {
        await calendarService.updateReminder(existingReminder.id, reminderData);
      } else {
        await calendarService.createReminder(reminderData);
      }

      Alert.alert('Success', 'Reminder saved successfully', [
        {
          text: 'OK',
          onPress: () => {
            onSave?.();
            navigation.goBack();
          },
        },
      ]);
    } catch (error) {
      console.error('Failed to save reminder:', error);
      Alert.alert('Error', 'Failed to save reminder');
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
          {existingReminder ? 'Edit Reminder' : 'New Reminder'}
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
            placeholder="Reminder title"
            placeholderTextColor={colors.textMuted}
          />
        </View>

        {/* Date & Time */}
        <View style={styles.formGroup}>
          <Text style={styles.label}>When</Text>
          <View style={styles.dateTimeRow}>
            <TouchableOpacity
              style={[styles.dateTimeButton, { flex: 1.5 }]}
              onPress={() => setShowDatePicker(true)}
            >
              <Text style={styles.dateTimeText}>{formatDate(reminderDate)}</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.dateTimeButton, { flex: 1 }]}
              onPress={() => setShowTimePicker(true)}
            >
              <Text style={styles.dateTimeText}>{formatTime(reminderDate)}</Text>
            </TouchableOpacity>
          </View>
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
      {showDatePicker && (
        <DateTimePicker
          value={reminderDate}
          mode="date"
          display={Platform.OS === 'ios' ? 'spinner' : 'default'}
          onChange={handleDateChange}
        />
      )}
      {showTimePicker && (
        <DateTimePicker
          value={reminderDate}
          mode="time"
          display={Platform.OS === 'ios' ? 'spinner' : 'default'}
          onChange={handleTimeChange}
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
