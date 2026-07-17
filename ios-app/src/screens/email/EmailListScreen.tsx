import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  FlatList,
  StyleSheet,
  TouchableOpacity,
  Text,
  TextInput,
  ActivityIndicator,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useToast } from '../../context/ToastContext';
import { SkeletonList } from '../../components/SkeletonLoader';
import apiClient from '../../services/api';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface Email {
  id: string;
  sender_name: string;
  sender_email: string;
  subject: string;
  body_preview: string;
  received_at: string;
  importance: string;
  is_read: boolean;
  has_attachments: boolean;
  action_required: boolean;
}

interface EmailListResponse {
  emails: Email[];
  total: number;
  page: number;
  page_size: number;
}

type FilterTab = 'all' | 'unread' | 'action_required';

function timeAgo(dateStr: string): string {
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
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

interface EmailListScreenProps {
  navigation: any;
}

export default function EmailListScreen({ navigation }: EmailListScreenProps) {
  const { showToast } = useToast();
  const [emails, setEmails] = useState<Email[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeFilter, setActiveFilter] = useState<FilterTab>('all');
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);

  useEffect(() => {
    loadEmails(true);
  }, [activeFilter]);

  const loadEmails = async (reset: boolean = false) => {
    try {
      if (reset) {
        setLoading(true);
        setPage(1);
      }

      const currentPage = reset ? 1 : page;
      let url = `/api/email?page=${currentPage}&page_size=20`;

      if (activeFilter === 'unread') {
        url += '&unread_only=true';
      } else if (activeFilter === 'action_required') {
        url += '&action_required_only=true';
      }

      if (searchQuery.trim()) {
        url += `&search=${encodeURIComponent(searchQuery.trim())}`;
      }

      const response = await fetch(`${apiClient.baseURL}${url}`, {
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
      });

      if (!response.ok) {
        throw new Error(`Failed to fetch emails: ${response.status}`);
      }

      const data: EmailListResponse = await response.json();

      if (reset) {
        setEmails(data.emails);
      } else {
        setEmails(prev => [...prev, ...data.emails]);
      }

      setHasMore(data.emails.length === data.page_size);
      setPage(currentPage + 1);
    } catch (error) {
      console.error('Failed to load emails:', error);
      showToast('error', 'Failed to load emails');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const handleRefresh = useCallback(() => {
    setRefreshing(true);
    loadEmails(true);
  }, [activeFilter, searchQuery]);

  const handleSearch = useCallback((query: string) => {
    setSearchQuery(query);
  }, []);

  const handleSearchSubmit = useCallback(() => {
    loadEmails(true);
  }, [activeFilter, searchQuery]);

  const handleFilterChange = useCallback((filter: FilterTab) => {
    setActiveFilter(filter);
  }, []);

  const handleEmailPress = useCallback((email: Email) => {
    navigation.navigate('EmailDetail', { emailId: email.id });
  }, [navigation]);

  const renderFilterTabs = () => {
    const tabs: { key: FilterTab; label: string }[] = [
      { key: 'all', label: 'All' },
      { key: 'unread', label: 'Unread' },
      { key: 'action_required', label: 'Action Required' },
    ];

    return (
      <View style={styles.filterContainer}>
        {tabs.map((tab) => (
          <TouchableOpacity
            key={tab.key}
            style={[
              styles.filterTab,
              activeFilter === tab.key && styles.filterTabActive,
            ]}
            onPress={() => handleFilterChange(tab.key)}
          >
            <Text
              style={[
                styles.filterTabText,
                activeFilter === tab.key && styles.filterTabTextActive,
              ]}
            >
              {tab.label}
            </Text>
          </TouchableOpacity>
        ))}
      </View>
    );
  };

  const renderEmail = ({ item }: { item: Email }) => (
    <TouchableOpacity
      style={styles.emailItem}
      onPress={() => handleEmailPress(item)}
      activeOpacity={0.7}
    >
      <View style={styles.emailRow}>
        <View style={styles.emailLeft}>
          {item.importance === 'high' && <View style={styles.importanceDot} />}
          <View style={styles.emailContent}>
            <Text
              style={[
                styles.senderName,
                !item.is_read && styles.unreadText,
              ]}
              numberOfLines={1}
            >
              {item.sender_name}
            </Text>
            <Text
              style={[
                styles.subject,
                !item.is_read && styles.unreadText,
              ]}
              numberOfLines={1}
            >
              {item.subject}
            </Text>
            <Text style={styles.bodyPreview} numberOfLines={1}>
              {item.body_preview}
            </Text>
          </View>
        </View>
        <View style={styles.emailRight}>
          <Text style={styles.timestamp}>{timeAgo(item.received_at)}</Text>
          {item.has_attachments && (
            <Text style={styles.attachmentIcon}>@</Text>
          )}
        </View>
      </View>
    </TouchableOpacity>
  );

  if (loading) {
    return (
      <SafeAreaView style={styles.container} edges={['bottom']}>
        <SkeletonList count={8} />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      {/* Search Bar */}
      <View style={styles.searchContainer}>
        <View style={styles.searchInputWrapper}>
          <Text style={styles.searchIcon}>Search</Text>
          <TextInput
            style={styles.searchInput}
            placeholder="Search emails..."
            placeholderTextColor={colors.textMuted}
            value={searchQuery}
            onChangeText={handleSearch}
            onSubmitEditing={handleSearchSubmit}
            returnKeyType="search"
          />
        </View>
      </View>

      {/* Filter Tabs */}
      {renderFilterTabs()}

      {/* Email List */}
      <FlatList
        data={emails}
        renderItem={renderEmail}
        keyExtractor={(item) => `email-${item.id}`}
        onRefresh={handleRefresh}
        refreshing={refreshing}
        onEndReached={() => {
          if (hasMore && !loading) {
            loadEmails(false);
          }
        }}
        onEndReachedThreshold={0.5}
        ListEmptyComponent={
          <View style={styles.emptyContainer}>
            <Text style={styles.emptyText}>
              {searchQuery
                ? 'No emails found matching your search'
                : activeFilter === 'unread'
                ? 'No unread emails'
                : activeFilter === 'action_required'
                ? 'No emails requiring action'
                : 'No emails yet'}
            </Text>
          </View>
        }
        contentContainerStyle={styles.listContent}
        ItemSeparatorComponent={() => <View style={styles.separator} />}
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
    paddingBottom: spacing.sm,
  },
  searchInputWrapper: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    paddingHorizontal: spacing.md,
  },
  searchIcon: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginRight: spacing.sm,
  },
  searchInput: {
    flex: 1,
    paddingVertical: spacing.md,
    color: colors.text,
    fontSize: fontSizes.md,
  },
  filterContainer: {
    flexDirection: 'row',
    paddingHorizontal: spacing.md,
    paddingBottom: spacing.md,
    gap: spacing.sm,
  },
  filterTab: {
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    borderRadius: borderRadius.full,
    backgroundColor: colors.surface,
  },
  filterTabActive: {
    backgroundColor: colors.primary,
  },
  filterTabText: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    fontWeight: '500',
  },
  filterTabTextActive: {
    color: colors.text,
    fontWeight: '600',
  },
  listContent: {
    paddingBottom: spacing.xl,
  },
  emailItem: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    backgroundColor: colors.background,
  },
  emailRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  emailLeft: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'flex-start',
    marginRight: spacing.md,
  },
  importanceDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.error,
    marginTop: 6,
    marginRight: spacing.sm,
  },
  emailContent: {
    flex: 1,
  },
  senderName: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    marginBottom: 2,
  },
  subject: {
    color: colors.text,
    fontSize: fontSizes.md,
    marginBottom: 4,
  },
  unreadText: {
    fontWeight: '700',
    color: colors.text,
  },
  bodyPreview: {
    color: colors.textMuted,
    fontSize: fontSizes.sm,
  },
  emailRight: {
    alignItems: 'flex-end',
  },
  timestamp: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
    marginBottom: 4,
  },
  attachmentIcon: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
  },
  separator: {
    height: 1,
    backgroundColor: colors.divider,
    marginHorizontal: spacing.md,
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
