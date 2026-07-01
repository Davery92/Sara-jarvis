import React from 'react';
import { Text, View, StyleSheet, Platform, Linking } from 'react-native';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface SimpleMarkdownProps {
  children: string;
  style?: any;
  linkStyle?: any;
}

export default function SimpleMarkdown({ children, style, linkStyle }: SimpleMarkdownProps) {
  const renderContent = () => {
    const lines = children.split('\n');
    const elements: JSX.Element[] = [];
    let key = 0;

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];

      // Skip empty lines
      if (line.trim() === '') {
        elements.push(<View key={key++} style={styles.spacing} />);
        continue;
      }

      // Headers
      if (line.startsWith('### ')) {
        elements.push(
          <Text key={key++} style={[styles.text, styles.h3, style]}>
            {renderInlineMarkdown(line.substring(4))}
          </Text>
        );
      } else if (line.startsWith('## ')) {
        elements.push(
          <Text key={key++} style={[styles.text, styles.h2, style]}>
            {renderInlineMarkdown(line.substring(3))}
          </Text>
        );
      } else if (line.startsWith('# ')) {
        elements.push(
          <Text key={key++} style={[styles.text, styles.h1, style]}>
            {renderInlineMarkdown(line.substring(2))}
          </Text>
        );
      }
      // Bullet list
      else if (line.trim().startsWith('- ') || line.trim().startsWith('* ')) {
        const content = line.trim().substring(2);
        elements.push(
          <View key={key++} style={styles.listItem}>
            <Text style={[styles.text, style]}>{'\u2022 '}{renderInlineMarkdown(content)}</Text>
          </View>
        );
      }
      // Numbered list
      else if (/^\d+\.\s/.test(line.trim())) {
        const content = line.trim().replace(/^\d+\.\s/, '');
        const number = line.trim().match(/^(\d+)\./)?.[1];
        elements.push(
          <View key={key++} style={styles.listItem}>
            <Text style={[styles.text, style]}>{number}. {renderInlineMarkdown(content)}</Text>
          </View>
        );
      }
      // Code block
      else if (line.trim().startsWith('```')) {
        const codeLines: string[] = [];
        i++; // Skip the opening ```
        while (i < lines.length && !lines[i].trim().startsWith('```')) {
          codeLines.push(lines[i]);
          i++;
        }
        elements.push(
          <View key={key++} style={styles.codeBlock}>
            <Text style={styles.codeText}>{codeLines.join('\n')}</Text>
          </View>
        );
      }
      // Regular paragraph
      else {
        elements.push(
          <Text key={key++} style={[styles.text, style]}>
            {renderInlineMarkdown(line)}
          </Text>
        );
      }
    }

    return elements;
  };

  const handleInternalLink = (path: string) => {
    const API_URL = __DEV__
      ? 'http://10.185.1.180:8000'
      : 'https://sara-api.avery.cloud';
    // Open in browser which will handle the download natively
    Linking.openURL(`${API_URL}${path}`);
  };

  // Single-pass inline markdown: markdown links, bare URLs, bold, inline code
  const renderInlineMarkdown = (text: string): any => {
    // Combined regex matching (in priority order):
    // 1. Markdown links: [text](url) — supports both http and internal /paths
    // 2. Bare URLs: https?://...
    // 3. Bold: **text**
    // 4. Inline code: `code`
    const combinedRegex = /(\[([^\]]+)\]\(([^)]+)\))|(https?:\/\/[^\s<]+[^\s<.,;:!?)}\]'"])|((?<!\*)\*\*(.+?)\*\*(?!\*))|(`([^`]+)`)/g;

    const parts: any[] = [];
    let lastIndex = 0;
    let match;
    let key = 0;

    while ((match = combinedRegex.exec(text)) !== null) {
      // Add plain text before this match
      if (match.index > lastIndex) {
        parts.push(text.substring(lastIndex, match.index));
      }

      if (match[1]) {
        // Markdown link: [text](url)
        const linkText = match[2];
        const url = match[3];

        if (url.startsWith('/email/') || url.startsWith('/api/')) {
          // Internal API link — download with auth
          parts.push(
            <Text
              key={`ilink-${key++}`}
              style={[styles.internalLink, linkStyle]}
              onPress={() => handleInternalLink(url)}
            >
              📎 {linkText}
            </Text>
          );
        } else if (url.startsWith('http')) {
          parts.push(
            <Text
              key={`link-${key++}`}
              style={[styles.link, linkStyle]}
              onPress={() => Linking.openURL(url)}
            >
              {linkText}
            </Text>
          );
        } else {
          // Non-http, non-internal link — just show as text
          parts.push(
            <Text key={`text-${key++}`} style={[styles.link, linkStyle]}>
              {linkText}
            </Text>
          );
        }
      } else if (match[4]) {
        // Bare URL — strip trailing punctuation
        let url = match[4];
        let trailing = '';
        const trailingMatch = url.match(/([.,;:!?)}\]'"]+)$/);
        if (trailingMatch) {
          trailing = trailingMatch[1];
          url = url.substring(0, url.length - trailing.length);
        }
        parts.push(
          <Text
            key={`url-${key++}`}
            style={[styles.link, linkStyle]}
            onPress={() => Linking.openURL(url)}
          >
            {url}
          </Text>
        );
        if (trailing) {
          parts.push(trailing);
        }
      } else if (match[5]) {
        // Bold: **text**
        parts.push(
          <Text key={`bold-${key++}`} style={styles.bold}>
            {match[6]}
          </Text>
        );
      } else if (match[7]) {
        // Inline code: `code`
        parts.push(
          <Text key={`code-${key++}`} style={styles.inlineCode}>
            {match[8]}
          </Text>
        );
      }

      lastIndex = match.index + match[0].length;
    }

    // Add remaining text
    if (lastIndex < text.length) {
      parts.push(text.substring(lastIndex));
    }

    return parts.length > 0 ? parts : text;
  };

  return <View>{renderContent()}</View>;
}

const styles = StyleSheet.create({
  text: {
    color: colors.text,
    fontSize: fontSizes.md,
    lineHeight: fontSizes.md * 1.5,
  },
  h1: {
    fontSize: fontSizes.xl,
    fontWeight: 'bold',
    marginVertical: spacing.xs,
  },
  h2: {
    fontSize: fontSizes.lg,
    fontWeight: 'bold',
    marginVertical: spacing.xs,
  },
  h3: {
    fontSize: fontSizes.md,
    fontWeight: 'bold',
    marginVertical: spacing.xs,
  },
  bold: {
    fontWeight: 'bold',
  },
  link: {
    color: colors.accent,
    textDecorationLine: 'underline',
  },
  internalLink: {
    color: colors.hues.sky,
    textDecorationLine: 'underline',
    fontWeight: '500',
  },
  listItem: {
    marginLeft: spacing.sm,
    marginVertical: 2,
  },
  codeBlock: {
    backgroundColor: 'rgba(0, 0, 0, 0.1)',
    padding: spacing.sm,
    borderRadius: borderRadius.md,
    marginVertical: spacing.xs,
  },
  codeText: {
    fontFamily: Platform.OS === 'ios' ? 'Courier' : 'monospace',
    fontSize: fontSizes.sm,
    color: colors.text,
  },
  inlineCode: {
    fontFamily: Platform.OS === 'ios' ? 'Courier' : 'monospace',
    backgroundColor: 'rgba(0, 0, 0, 0.1)',
    paddingHorizontal: 4,
    paddingVertical: 2,
    borderRadius: 4,
    fontSize: fontSizes.sm,
  },
  spacing: {
    height: spacing.xs,
  },
});
