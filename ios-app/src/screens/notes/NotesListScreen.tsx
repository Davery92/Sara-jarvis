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
import { useToast } from '../../context/ToastContext';
import { SkeletonList } from '../../components/SkeletonLoader';
import { MainTabScreenProps } from '../../types/navigation';
import { Note, Folder } from '../../types/api';
import { notesService } from '../../services/notes';
import NoteListItem from '../../components/notes/NoteListItem';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

function timeAgo(dateStr: string | undefined): string {
  if (!dateStr) return '';
  const now = new Date();
  const date = new Date(dateStr);
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 1) return 'just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 30) return `${diffDays}d ago`;
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

type Props = MainTabScreenProps<'Notes'>;

export default function NotesListScreen({ navigation }: Props) {
  const { showToast } = useToast();
  const [notes, setNotes] = useState<Note[]>([]);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [folderStack, setFolderStack] = useState<Folder[]>([]); // Navigation stack for back button
  const [searchQuery, setSearchQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [folderNoteCounts, setFolderNoteCounts] = useState<Record<number, number>>({});

  const selectedFolder = folderStack.length > 0 ? folderStack[folderStack.length - 1].id : null;

  // Update header title and back button behavior when navigating folders
  useEffect(() => {
    const currentFolder = folderStack.length > 0 ? folderStack[folderStack.length - 1] : null;
    navigation.setOptions({
      title: currentFolder ? currentFolder.name : 'Notes',
      headerLeft: currentFolder ? () => (
        <TouchableOpacity onPress={handleBackOneLevel} style={{ paddingRight: spacing.md }}>
          <Text style={{ color: colors.primary, fontSize: fontSizes.md }}>← Back</Text>
        </TouchableOpacity>
      ) : undefined,
    });
  }, [folderStack, navigation]);

  useEffect(() => {
    loadData();
  }, [selectedFolder]);

  const loadData = async () => {
    try {
      setLoading(true);
      const [notesData, foldersData, allNotes] = await Promise.all([
        selectedFolder
          ? notesService.getNotesByFolder(selectedFolder)
          : notesService.getRootNotes(),
        notesService.getAllFolders(),
        notesService.getAllNotes(),
      ]);
      setNotes(notesData);
      setFolders(foldersData);

      // Count notes per folder
      const counts: Record<number, number> = {};
      for (const note of allNotes) {
        if (note.folder_id) {
          counts[note.folder_id] = (counts[note.folder_id] || 0) + 1;
        }
      }
      setFolderNoteCounts(counts);
    } catch (error) {
      console.error('Failed to load notes:', error);
      showToast('error', 'Failed to load notes');
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
            showToast('error', 'Failed to create folder');
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
              showToast('error', 'Failed to delete note');
            }
          },
        },
      ]
    );
  };

  const handleFolderPress = (folder: Folder) => {
    setFolderStack(prev => [...prev, folder]);
    setSearchQuery('');
  };

  const handleBackToRoot = () => {
    setFolderStack([]);
    setSearchQuery('');
  };

  const handleBackOneLevel = () => {
    setFolderStack(prev => prev.slice(0, -1));
    setSearchQuery('');
  };

  const filteredNotes = notes;

  const renderNote = ({ item }: { item: Note }) => (
    <NoteListItem
      note={item}
      onPress={handleNotePress}
      onLongPress={handleNoteLongPress}
    />
  );

  if (loading) {
    return (
      <SafeAreaView style={styles.container} edges={['bottom']}>
        <SkeletonList count={8} />
      </SafeAreaView>
    );
  }

  // Get folders to display based on current location
  const foldersToShow = selectedFolder
    ? folders.filter((f) => f.parent_id === selectedFolder) // Sub-folders when inside a folder
    : folders.filter((f) => !f.parent_id); // Root folders when at root
  const currentFolder = folderStack.length > 0 ? folderStack[folderStack.length - 1] : null;

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

      {/* Breadcrumb trail when deep in folder hierarchy */}
      {folderStack.length > 1 && (
        <View style={styles.breadcrumb}>
          <TouchableOpacity onPress={handleBackToRoot}>
            <Text style={styles.breadcrumbText}>All Notes</Text>
          </TouchableOpacity>
          {folderStack.slice(0, -1).map((f) => (
            <Text key={f.id} style={styles.breadcrumbCurrent}> / {f.name}</Text>
          ))}
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

      {/* Single FlatList with folders as header */}
      <FlatList
        data={filteredNotes}
        renderItem={renderNote}
        keyExtractor={(item) => `note-${item.id}`}
        onRefresh={handleRefresh}
        refreshing={refreshing}
        ListHeaderComponent={
          foldersToShow.length > 0 ? (
            <View style={styles.foldersSection}>
              <Text style={styles.sectionTitle}>Folders</Text>
              {foldersToShow.map((folder) => (
                <TouchableOpacity
                  key={`folder-${folder.id}`}
                  style={styles.folderItem}
                  onPress={() => handleFolderPress(folder)}
                >
                  <Text style={styles.folderIcon}>📁</Text>
                  <View style={styles.folderInfo}>
                    <Text style={styles.folderName}>{folder.name}</Text>
                    {folder.updated_at && (
                      <Text style={styles.folderDate}>{timeAgo(folder.updated_at)}</Text>
                    )}
                  </View>
                  {(folderNoteCounts[folder.id] || 0) > 0 && (
                    <Text style={styles.folderCount}>({folderNoteCounts[folder.id]})</Text>
                  )}
                  <Text style={styles.chevron}>›</Text>
                </TouchableOpacity>
              ))}
              <Text style={[styles.sectionTitle, { marginTop: spacing.md }]}>
                Notes ({filteredNotes.length})
              </Text>
            </View>
          ) : (
            <Text style={styles.sectionTitle}>
              Notes ({filteredNotes.length})
            </Text>
          )
        }
        ListEmptyComponent={
          <View style={styles.emptyContainer}>
            <Text style={styles.emptyText}>
              {searchQuery
                ? 'No notes found'
                : 'No notes yet. Create your first note!'}
            </Text>
          </View>
        }
        contentContainerStyle={styles.listContent}
      />

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
  foldersSection: {
    marginBottom: spacing.sm,
  },
  listContent: {
    paddingBottom: spacing.xl,
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
  folderInfo: {
    flex: 1,
  },
  folderName: {
    color: colors.text,
    fontSize: fontSizes.md,
    fontWeight: '500',
  },
  folderDate: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginTop: 2,
  },
  folderCount: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
    marginRight: spacing.sm,
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
