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
import Markdown from 'react-native-markdown-display';
import { notesService } from '../../services/notes';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface NoteEditorScreenProps {
  route?: {
    params?: {
      noteId?: string | number;
      folderId?: string | number;
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
  const [isEditing, setIsEditing] = useState(!noteId);

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

      onSave?.();
      if (noteId) {
        setIsEditing(false);
      } else {
        navigation.goBack();
      }
    } catch (error) {
      console.error('Failed to save note:', error);
      Alert.alert('Error', 'Failed to save note');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.container} edges={['top', 'bottom']}>
        <View style={styles.loadingContainer}>
          <Text style={styles.loadingText}>Loading...</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={['top', 'bottom']}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.container}
      >
        {/* Header */}
        <View style={styles.header}>
          <TouchableOpacity
            onPress={() => {
              if (isEditing && noteId) {
                // Cancel edit — reload original content
                loadNote();
                setIsEditing(false);
              } else {
                navigation.goBack();
              }
            }}
          >
            <Text style={styles.cancelButton}>
              {isEditing && noteId ? 'Cancel' : 'Close'}
            </Text>
          </TouchableOpacity>
          <Text style={styles.headerTitle}>
            {isEditing ? (noteId ? 'Edit Note' : 'New Note') : title}
          </Text>
          {isEditing ? (
            <TouchableOpacity onPress={handleSave} disabled={saving}>
              <Text style={[styles.saveButton, saving && styles.saveButtonDisabled]}>
                {saving ? 'Saving...' : 'Save'}
              </Text>
            </TouchableOpacity>
          ) : (
            <TouchableOpacity onPress={() => setIsEditing(true)}>
              <Text style={styles.saveButton}>Edit</Text>
            </TouchableOpacity>
          )}
        </View>

        {isEditing ? (
          /* Editor */
          <ScrollView style={styles.content} keyboardShouldPersistTaps="handled">
            <TextInput
              style={styles.titleInput}
              placeholder="Note Title"
              placeholderTextColor={colors.textMuted}
              value={title}
              onChangeText={setTitle}
              autoFocus={!noteId}
            />
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
        ) : (
          /* Rendered markdown view */
          <ScrollView style={styles.content}>
            <Text style={styles.viewTitle}>{title}</Text>
            <Markdown style={markdownStyles}>{content || ' '}</Markdown>
          </ScrollView>
        )}
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
  viewTitle: {
    color: colors.text,
    fontSize: fontSizes.xl,
    fontWeight: '600',
    marginBottom: spacing.md,
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
    fontWeight: 'bold' as const,
    color: colors.text,
    marginTop: spacing.lg,
    marginBottom: spacing.md,
  },
  heading2: {
    fontSize: fontSizes.xl,
    fontWeight: '600' as const,
    color: colors.text,
    marginTop: spacing.md,
    marginBottom: spacing.sm,
  },
  heading3: {
    fontSize: fontSizes.lg,
    fontWeight: '600' as const,
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
    fontWeight: 'bold' as const,
    color: colors.text,
  },
  code_inline: {
    backgroundColor: colors.surface,
    color: colors.primary,
    borderRadius: 4,
    paddingHorizontal: 4,
  },
  fence: {
    backgroundColor: colors.surface,
    borderRadius: 8,
    padding: spacing.sm,
    color: colors.text,
  },
  link: {
    color: colors.primary,
  },
  blockquote: {
    borderLeftColor: colors.primary,
    borderLeftWidth: 3,
    paddingLeft: spacing.sm,
    backgroundColor: colors.surface,
    borderRadius: 4,
    marginVertical: spacing.sm,
  },
  hr: {
    backgroundColor: colors.border,
    height: 1,
    marginVertical: spacing.md,
  },
};
