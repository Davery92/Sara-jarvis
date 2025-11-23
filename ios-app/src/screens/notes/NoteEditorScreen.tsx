import React, { useState, useEffect } from 'react';
import {
  View,
  TextInput,
  StyleSheet,
  TouchableOpacity,
  Text,
  Alert,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { notesService } from '../../services/notes';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface NoteEditorScreenProps {
  route?: {
    params?: {
      noteId?: number;
      folderId?: number;
      onSave?: () => void;
    };
  };
  navigation: any;
}

export default function NoteEditorScreen({ route, navigation }: NoteEditorScreenProps) {
  const noteId = route?.params?.noteId;
  const folderId = route?.params?.folderId;
  const onSave = route?.params?.onSave;

  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [loading, setLoading] = useState(!!noteId);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (noteId) {
      loadNote();
    }
  }, [noteId]);

  const loadNote = async () => {
    try {
      const note = await notesService.getNote(noteId!);
      setTitle(note.title || '');
      setContent(note.content || '');
    } catch (error) {
      console.error('Failed to load note:', error);
      Alert.alert('Error', 'Failed to load note');
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    if (!title.trim()) {
      Alert.alert('Missing Title', 'Please enter a note title');
      return;
    }

    try {
      setSaving(true);

      if (noteId) {
        // Update existing note
        await notesService.updateNote(noteId, {
          title: title.trim(),
          content: content.trim(),
        });
      } else {
        // Create new note
        await notesService.createNote({
          title: title.trim(),
          content: content.trim(),
          folder_id: folderId,
        });
      }

      Alert.alert('Success', 'Note saved successfully', [
        {
          text: 'OK',
          onPress: () => {
            onSave?.();
            navigation.goBack();
          },
        },
      ]);
    } catch (error) {
      console.error('Failed to save note:', error);
      Alert.alert('Error', 'Failed to save note');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.container} edges={['bottom']}>
        <View style={styles.loadingContainer}>
          <Text style={styles.loadingText}>Loading...</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.container}
      >
        {/* Header */}
        <View style={styles.header}>
          <TouchableOpacity onPress={() => navigation.goBack()}>
            <Text style={styles.cancelButton}>Cancel</Text>
          </TouchableOpacity>
          <Text style={styles.headerTitle}>
            {noteId ? 'Edit Note' : 'New Note'}
          </Text>
          <TouchableOpacity onPress={handleSave} disabled={saving}>
            <Text style={[styles.saveButton, saving && styles.saveButtonDisabled]}>
              {saving ? 'Saving...' : 'Save'}
            </Text>
          </TouchableOpacity>
        </View>

        {/* Editor */}
        <ScrollView style={styles.content} keyboardShouldPersistTaps="handled">
          {/* Title Input */}
          <TextInput
            style={styles.titleInput}
            placeholder="Note Title"
            placeholderTextColor={colors.textMuted}
            value={title}
            onChangeText={setTitle}
            autoFocus={!noteId}
          />

          {/* Content Input */}
          <TextInput
            style={styles.contentInput}
            placeholder="Start writing..."
            placeholderTextColor={colors.textMuted}
            value={content}
            onChangeText={setContent}
            multiline
            textAlignVertical="top"
          />
        </ScrollView>
      </KeyboardAvoidingView>
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
  },
  loadingText: {
    color: colors.text,
    fontSize: fontSizes.md,
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
  headerTitle: {
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
  titleInput: {
    color: colors.text,
    fontSize: fontSizes.xl,
    fontWeight: '600',
    marginBottom: spacing.md,
    padding: 0,
  },
  contentInput: {
    color: colors.text,
    fontSize: fontSizes.md,
    lineHeight: 24,
    flex: 1,
    minHeight: 400,
    padding: 0,
  },
});
