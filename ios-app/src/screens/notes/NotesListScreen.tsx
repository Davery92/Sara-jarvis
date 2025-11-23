import React, { useState, useEffect } from 'react';
import {
  View,
  FlatList,
  StyleSheet,
  TouchableOpacity,
  Text,
  TextInput,
  Alert,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { MainTabScreenProps } from '../../types/navigation';
import { Note, Folder } from '../../types/api';
import { notesService } from '../../services/notes';
import NoteListItem from '../../components/notes/NoteListItem';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

type Props = MainTabScreenProps<'Notes'>;

export default function NotesListScreen({ navigation }: Props) {
  const [notes, setNotes] = useState<Note[]>([]);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [selectedFolder, setSelectedFolder] = useState<number | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  useEffect(() => {
    loadData();
  }, [selectedFolder]);

  const loadData = async () => {
    try {
      setLoading(true);
      const [notesData, foldersData] = await Promise.all([
        selectedFolder
          ? notesService.getNotesByFolder(selectedFolder)
          : notesService.getRootNotes(), // Only show root-level notes when not in a folder
        notesService.getAllFolders(),
      ]);
      setNotes(notesData);
      setFolders(foldersData);
    } catch (error) {
      console.error('Failed to load notes:', error);
      Alert.alert('Error', 'Failed to load notes');
    } finally {
      setLoading(false);
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    await loadData();
    setRefreshing(false);
  };

  const handleSearch = async (query: string) => {
    setSearchQuery(query);
    if (!query.trim()) {
      loadData(); // Reload filtered by current folder
      return;
    }

    try {
      const results = await notesService.searchNotes({
        query,
        folder_id: selectedFolder || undefined, // Search within current folder only
      });
      setNotes(results);
    } catch (error) {
      console.error('Search failed:', error);
    }
  };

  const handleCreateNote = () => {
    navigation.navigate('NoteEditor', {
      folderId: selectedFolder || undefined,
      onSave: loadData,
    });
  };

  const handleCreateFolder = () => {
    Alert.prompt(
      'New Folder',
      'Enter folder name',
      async (name) => {
        if (name?.trim()) {
          try {
            await notesService.createFolder(name.trim(), selectedFolder || undefined);
            loadData();
          } catch (error) {
            Alert.alert('Error', 'Failed to create folder');
          }
        }
      }
    );
  };

  const handleNotePress = (note: Note) => {
    navigation.navigate('NoteEditor', {
      noteId: note.id,
      onSave: loadData,
    });
  };

  const handleNoteLongPress = (note: Note) => {
    Alert.alert(
      note.title || 'Untitled',
      'What would you like to do?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Delete',
          style: 'destructive',
          onPress: async () => {
            try {
              await notesService.deleteNote(note.id);
              loadData();
            } catch (error) {
              Alert.alert('Error', 'Failed to delete note');
            }
          },
        },
      ]
    );
  };

  const handleFolderPress = (folder: Folder) => {
    setSelectedFolder(folder.id);
    setSearchQuery('');
  };

  const handleBackToRoot = () => {
    setSelectedFolder(null);
    setSearchQuery('');
  };

  const filteredNotes = notes;

  const renderFolder = ({ item }: { item: Folder }) => (
    <TouchableOpacity
      style={styles.folderItem}
      onPress={() => handleFolderPress(item)}
    >
      <Text style={styles.folderIcon}>📁</Text>
      <Text style={styles.folderName}>{item.name}</Text>
      <Text style={styles.chevron}>›</Text>
    </TouchableOpacity>
  );

  const renderNote = ({ item }: { item: Note }) => (
    <NoteListItem
      note={item}
      onPress={handleNotePress}
      onLongPress={handleNoteLongPress}
    />
  );

  if (loading) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  // Get folders to display based on current location
  const foldersToShow = selectedFolder
    ? folders.filter((f) => f.parent_id === selectedFolder) // Sub-folders when inside a folder
    : folders.filter((f) => !f.parent_id); // Root folders when at root
  const currentFolder = folders.find((f) => f.id === selectedFolder);

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      {/* Search Bar */}
      <View style={styles.searchContainer}>
        <TextInput
          style={styles.searchInput}
          placeholder="Search notes..."
          placeholderTextColor={colors.textMuted}
          value={searchQuery}
          onChangeText={handleSearch}
        />
      </View>

      {/* Folder Navigation */}
      {selectedFolder && (
        <View style={styles.breadcrumb}>
          <TouchableOpacity onPress={handleBackToRoot}>
            <Text style={styles.breadcrumbText}>← All Notes</Text>
          </TouchableOpacity>
          {currentFolder && (
            <Text style={styles.breadcrumbCurrent}> / {currentFolder.name}</Text>
          )}
        </View>
      )}

      {/* Action Buttons */}
      <View style={styles.actions}>
        <TouchableOpacity style={styles.actionButton} onPress={handleCreateNote}>
          <Text style={styles.actionButtonText}>+ New Note</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.actionButton, styles.actionButtonSecondary]}
          onPress={handleCreateFolder}
        >
          <Text style={styles.actionButtonTextSecondary}>+ New Folder</Text>
        </TouchableOpacity>
      </View>

      {/* Folders (show root folders at root, sub-folders when inside a folder) */}
      {foldersToShow.length > 0 && (
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Folders</Text>
          <FlatList
            data={foldersToShow}
            renderItem={renderFolder}
            keyExtractor={(item) => `folder-${item.id}`}
            scrollEnabled={false}
          />
        </View>
      )}

      {/* Notes List */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>
          Notes ({filteredNotes.length})
        </Text>
        <FlatList
          data={filteredNotes}
          renderItem={renderNote}
          keyExtractor={(item) => `note-${item.id}`}
          onRefresh={handleRefresh}
          refreshing={refreshing}
          ListEmptyComponent={
            <View style={styles.emptyContainer}>
              <Text style={styles.emptyText}>
                {searchQuery
                  ? 'No notes found'
                  : 'No notes yet. Create your first note!'}
              </Text>
            </View>
          }
        />
      </View>

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
  searchContainer: {
    padding: spacing.md,
  },
  searchInput: {
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    color: colors.text,
    fontSize: fontSizes.md,
  },
  breadcrumb: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.sm,
  },
  breadcrumbText: {
    color: colors.primary,
    fontSize: fontSizes.sm,
  },
  breadcrumbCurrent: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
  },
  actions: {
    flexDirection: 'row',
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    marginBottom: spacing.md,
  },
  actionButton: {
    flex: 1,
    backgroundColor: colors.primary,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    alignItems: 'center',
  },
  actionButtonSecondary: {
    backgroundColor: colors.surface,
  },
  actionButtonText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  actionButtonTextSecondary: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  section: {
    flex: 1,
  },
  sectionTitle: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    fontWeight: '600',
    textTransform: 'uppercase',
    paddingHorizontal: spacing.md,
    marginBottom: spacing.sm,
  },
  folderItem: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    marginHorizontal: spacing.md,
    marginBottom: spacing.sm,
  },
  folderIcon: {
    fontSize: fontSizes.lg,
    marginRight: spacing.sm,
  },
  folderName: {
    flex: 1,
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '500',
  },
  chevron: {
    color: colors.textMuted,
    fontSize: fontSizes.xl,
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
  modalContainer: {
    flex: 1,
    backgroundColor: colors.background,
  },
  modalHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: colors.surface,
  },
  modalTitle: {
    flex: 1,
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '600',
  },
  closeButton: {
    padding: spacing.sm,
  },
  closeButtonText: {
    color: colors.primary,
    fontSize: fontSizes.md,
    fontWeight: '600',
  },
  modalContent: {
    flex: 1,
    padding: spacing.md,
  },
  noteContent: {
    color: colors.text,
    fontSize: fontSizes.md,
    lineHeight: 24,
  },
});
