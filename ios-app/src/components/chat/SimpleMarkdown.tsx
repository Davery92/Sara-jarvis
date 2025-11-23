import React from 'react';
import { Text, View, StyleSheet, Platform } from 'react-native';
import { colors, spacing, borderRadius, fontSizes } from '../../styles/theme';

interface SimpleMarkdownProps {
  children: string;
  style?: any;
}

export default function SimpleMarkdown({ children, style }: SimpleMarkdownProps) {
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
            {line.substring(4)}
          </Text>
        );
      } else if (line.startsWith('## ')) {
        elements.push(
          <Text key={key++} style={[styles.text, styles.h2, style]}>
            {line.substring(3)}
          </Text>
        );
      } else if (line.startsWith('# ')) {
        elements.push(
          <Text key={key++} style={[styles.text, styles.h1, style]}>
            {line.substring(2)}
          </Text>
        );
      }
      // Bullet list
      else if (line.trim().startsWith('- ') || line.trim().startsWith('* ')) {
        const content = line.trim().substring(2);
        elements.push(
          <View key={key++} style={styles.listItem}>
            <Text style={[styles.text, style]}>• {renderInlineMarkdown(content)}</Text>
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

  const renderInlineMarkdown = (text: string): any => {
    const parts: any[] = [];
    let currentText = text;
    let key = 0;

    // Handle **bold**
    const boldRegex = /\*\*(.+?)\*\*/g;
    let lastIndex = 0;
    let match;

    while ((match = boldRegex.exec(currentText)) !== null) {
      // Add text before bold
      if (match.index > lastIndex) {
        parts.push(
          <Text key={key++} style={styles.text}>
            {currentText.substring(lastIndex, match.index)}
          </Text>
        );
      }
      // Add bold text
      parts.push(
        <Text key={key++} style={styles.bold}>
          {match[1]}
        </Text>
      );
      lastIndex = match.index + match[0].length;
    }

    // Add remaining text
    if (lastIndex < currentText.length) {
      parts.push(
        <Text key={key++} style={styles.text}>
          {currentText.substring(lastIndex)}
        </Text>
      );
    }

    // Handle `code`
    const codeRegex = /`(.+?)`/g;
    const finalParts: any[] = [];
    parts.forEach((part, index) => {
      if (typeof part.props.children === 'string') {
        const str = part.props.children;
        let lastIdx = 0;
        let codeMatch;
        const subParts: any[] = [];

        while ((codeMatch = codeRegex.exec(str)) !== null) {
          if (codeMatch.index > lastIdx) {
            subParts.push(str.substring(lastIdx, codeMatch.index));
          }
          subParts.push(
            <Text key={`${index}-${subParts.length}`} style={styles.inlineCode}>
              {codeMatch[1]}
            </Text>
          );
          lastIdx = codeMatch.index + codeMatch[0].length;
        }

        if (lastIdx < str.length) {
          subParts.push(str.substring(lastIdx));
        }

        if (subParts.length > 0) {
          finalParts.push(...subParts);
        } else {
          finalParts.push(part);
        }
      } else {
        finalParts.push(part);
      }
    });

    return finalParts.length > 0 ? finalParts : text;
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
