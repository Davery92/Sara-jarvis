import React from 'react';
import { TextInput, StyleSheet } from 'react-native';
import { colors, spacing, fontSizes } from '../../styles/theme';

interface MarkdownEditorProps {
  value: string;
  onChangeText: (text: string) => void;
  placeholder?: string;
  editable?: boolean;
}

export default function MarkdownEditor({
  value,
  onChangeText,
  placeholder = 'Start writing...',
  editable = true,
}: MarkdownEditorProps) {
  return (
    <TextInput
      style={styles.editor}
      value={value}
      onChangeText={onChangeText}
      placeholder={placeholder}
      placeholderTextColor={colors.textMuted}
      multiline
      editable={editable}
      textAlignVertical="top"
    />
  );
}

const styles = StyleSheet.create({
  editor: {
    flex: 1,
    color: colors.text,
    fontSize: fontSizes.md,
    lineHeight: fontSizes.md * 1.6,
    padding: spacing.md,
    fontFamily: 'monospace',
  },
});
