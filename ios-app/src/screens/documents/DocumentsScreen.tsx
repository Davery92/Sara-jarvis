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
  Modal,
  Platform,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { MainTabScreenProps } from '../../types/navigation';
import { Document, documentsService } from '../../services/documents';
import DocumentListItem from '../../components/documents/DocumentListItem';
import DocumentViewer from '../../components/documents/DocumentViewer';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';
import { useToast } from '../../context/ToastContext';
import * as DocumentPicker from 'expo-document-picker';

type Props = MainTabScreenProps<'Documents'>;

export default function DocumentsScreen({ navigation }: Props) {
  const { showToast } = useToast();
  const [documents, setDocuments] = useState<Document[]>([]);
  const [filteredDocuments, setFilteredDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedDocument, setSelectedDocument] = useState<Document | null>(null);
  const [viewerVisible, setViewerVisible] = useState(false);

  useEffect(() => {
    loadData();
  }, []);

  useEffect(() => {
    filterDocuments();
  }, [searchQuery, documents]);

  const loadData = async () => {
    try {
      setLoading(true);
      const docsData = await documentsService.getAllDocuments();
      setDocuments(docsData);
    } catch (error) {
      console.error('Failed to load documents:', error);
      showToast('error', 'Failed to load documents');
    } finally {
      setLoading(false);
    }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    await loadData();
    setRefreshing(false);
  };

  const filterDocuments = () => {
    let filtered = documents;

    // Filter by search query (filename or title or content)
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(
        (doc) =>
          doc.original_filename.toLowerCase().includes(query) ||
          doc.title?.toLowerCase().includes(query) ||
          doc.content_text?.toLowerCase().includes(query)
      );
    }

    setFilteredDocuments(filtered);
  };

  const handleUploadDocument = async () => {
    try {
      const result = await DocumentPicker.getDocumentAsync({
        type: '*/*',
        copyToCacheDirectory: true,
      });

      if (result.canceled) {
        return;
      }

      const file = result.assets[0];

      // Upload the document
      Alert.alert(
        'Upload Document',
        `Upload ${file.name}?`,
        [
          { text: 'Cancel', style: 'cancel' },
          {
            text: 'Upload',
            onPress: async () => {
              try {
                setLoading(true);

                // Create file object for upload
                const uploadFile = {
                  uri: file.uri,
                  type: file.mimeType || 'application/octet-stream',
                  name: file.name,
                } as any;

                await documentsService.uploadDocument({
                  file: uploadFile,
                  filename: file.name,
                });

                showToast('success', 'Document uploaded successfully');
                await loadData();
              } catch (error) {
                console.error('Upload error:', error);
                showToast('error', 'Failed to upload document');
              } finally {
                setLoading(false);
              }
            },
          },
        ]
      );
    } catch (error) {
      console.error('Document picker error:', error);
      showToast('error', 'Failed to select document');
    }
  };

  const handleDocumentPress = (document: Document) => {
    setSelectedDocument(document);
    setViewerVisible(true);
  };

  const handleDocumentLongPress = (document: Document) => {
    Alert.alert(
      document.original_filename,
      'What would you like to do?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Rename',
          onPress: () => handleRenameDocument(document),
        },
        {
          text: 'Delete',
          style: 'destructive',
          onPress: async () => {
            try {
              await documentsService.deleteDocument(document.id);
              await loadData();
            } catch (error) {
              showToast('error', 'Failed to delete document');
            }
          },
        },
      ]
    );
  };

  const handleRenameDocument = (document: Document) => {
    Alert.prompt(
      'Rename Document',
      'Enter a new name for this document:',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Save',
          onPress: async (newTitle) => {
            if (!newTitle?.trim()) {
              showToast('error', 'Document name cannot be empty');
              return;
            }
            try {
              await documentsService.updateDocument(document.id, { title: newTitle.trim() });
              await loadData();
              showToast('success', 'Document renamed successfully');
            } catch (error) {
              console.error('Rename error:', error);
              showToast('error', 'Failed to rename document');
            }
          },
        },
      ],
      'plain-text',
      document.title || document.original_filename
    );
  };

  if (loading) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      {/* Search Bar */}
      <View style={styles.searchContainer}>
        <TextInput
          style={styles.searchInput}
          placeholder="Search documents..."
          placeholderTextColor={colors.textMuted}
          value={searchQuery}
          onChangeText={setSearchQuery}
        />
        <TouchableOpacity style={styles.uploadButton} onPress={handleUploadDocument}>
          <Text style={styles.uploadButtonText}>📤 Upload</Text>
        </TouchableOpacity>
      </View>

      {/* Document List */}
      <View style={styles.listHeader}>
        <Text style={styles.listTitle}>Documents ({filteredDocuments.length})</Text>
      </View>
      <FlatList
        data={filteredDocuments}
        renderItem={({ item }) => (
          <DocumentListItem
            document={item}
            onPress={handleDocumentPress}
            onLongPress={handleDocumentLongPress}
          />
        )}
        keyExtractor={(item) => `doc-${item.id}`}
        onRefresh={handleRefresh}
        refreshing={refreshing}
        ListEmptyComponent={
          <View style={styles.emptyContainer}>
            <Text style={styles.emptyText}>
              {searchQuery
                ? 'No documents found'
                : 'No documents yet. Upload your first document!'}
            </Text>
          </View>
        }
      />

      {/* Document Viewer Modal */}
      <Modal
        visible={viewerVisible}
        animationType="slide"
        presentationStyle="pageSheet"
        onRequestClose={() => setViewerVisible(false)}
      >
        <SafeAreaView style={styles.modalContainer}>
          <View style={styles.modalHeader}>
            <TouchableOpacity
              style={styles.closeButton}
              onPress={() => setViewerVisible(false)}
            >
              <Text style={styles.closeButtonText}>✕ Close</Text>
            </TouchableOpacity>
          </View>
          {selectedDocument && <DocumentViewer document={selectedDocument} />}
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
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: colors.background,
  },
  searchContainer: {
    flexDirection: 'row',
    padding: spacing.md,
    gap: spacing.sm,
  },
  searchInput: {
    flex: 1,
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.md,
    color: colors.text,
    fontSize: fontSizes.md,
  },
  uploadButton: {
    backgroundColor: colors.primary,
    borderRadius: borderRadius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    justifyContent: 'center',
  },
  uploadButtonText: {
    color: colors.text,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
  listHeader: {
    paddingHorizontal: spacing.md,
    marginBottom: spacing.sm,
  },
  listTitle: {
    color: colors.textSecondary,
    fontSize: fontSizes.xs,
    fontWeight: '600',
    textTransform: 'uppercase',
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
    justifyContent: 'flex-end',
    padding: spacing.md,
    backgroundColor: colors.surface,
  },
  closeButton: {
    padding: spacing.sm,
  },
  closeButtonText: {
    color: colors.primary,
    fontSize: fontSizes.md,
    fontWeight: '600',
  },
});
