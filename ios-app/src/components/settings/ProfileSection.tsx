import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { User } from '../../services/settings';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface ProfileSectionProps {
  user: User;
  onEditPress: () => void;
}

export default function ProfileSection({ user, onEditPress }: ProfileSectionProps) {
  const initials = user.username
    ? user.username
        .split(' ')
        .map((n) => n[0])
        .join('')
        .toUpperCase()
        .slice(0, 2)
    : user.email[0].toUpperCase();

  const memberSince = new Date(user.created_at).toLocaleDateString('en-US', {
    month: 'long',
    year: 'numeric',
  });

  return (
    <View style={styles.container}>
      {/* Avatar */}
      <View style={styles.avatar}>
        <Text style={styles.avatarText}>{initials}</Text>
      </View>

      {/* User Info */}
      <View style={styles.info}>
        <Text style={styles.username}>{user.username || 'User'}</Text>
        <Text style={styles.email}>{user.email}</Text>
        <Text style={styles.memberSince}>Member since {memberSince}</Text>
      </View>

      {/* Edit Button */}
      <TouchableOpacity style={styles.editButton} onPress={onEditPress}>
        <Text style={styles.editButtonText}>Edit</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.surface,
    borderRadius: borderRadius.md,
    padding: spacing.lg,
    marginHorizontal: spacing.md,
    marginBottom: spacing.md,
  },
  avatar: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: colors.primary,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: spacing.md,
  },
  avatarText: {
    color: colors.text,
    fontSize: fontSizes.xxl,
    fontWeight: '700',
  },
  info: {
    flex: 1,
  },
  username: {
    color: colors.text,
    fontSize: fontSizes.lg,
    fontWeight: '700',
    marginBottom: spacing.xs,
  },
  email: {
    color: colors.textSecondary,
    fontSize: fontSizes.sm,
    marginBottom: spacing.xs,
  },
  memberSince: {
    color: colors.textMuted,
    fontSize: fontSizes.xs,
  },
  editButton: {
    backgroundColor: colors.background,
    borderRadius: borderRadius.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  editButtonText: {
    color: colors.primary,
    fontSize: fontSizes.sm,
    fontWeight: '600',
  },
});
