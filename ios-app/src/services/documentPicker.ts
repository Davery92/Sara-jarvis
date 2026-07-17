import * as DocumentPicker from 'expo-document-picker';
import { Alert } from 'react-native';

export interface DocumentAttachment {
  uri: string;
  base64: string;
  name: string;
  mimeType: string;
  size?: number;
}

// File types the backend can extract text from (see DocumentProcessor.supported_types).
const SUPPORTED_TYPES = [
  'application/pdf',
  'application/msword',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'text/plain',
  'text/markdown',
  'text/csv',
];

// Cap attachment size — base64 is sent inline in the chat JSON payload.
const MAX_BYTES = 20 * 1024 * 1024; // 20 MB

/**
 * Read a local file URI into a base64 string (no data: prefix).
 * Uses fetch + FileReader so we don't need expo-file-system as a dependency.
 */
async function uriToBase64(uri: string): Promise<string> {
  const response = await fetch(uri);
  const blob = await response.blob();
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const result = reader.result as string;
      // result looks like "data:application/pdf;base64,XXXX"
      resolve(result.split(',')[1] || '');
    };
    reader.onerror = () => reject(new Error('Failed to read file'));
    reader.readAsDataURL(blob);
  });
}

class DocumentPickerService {
  /**
   * Let the user pick a document (PDF, Word, text) and return it base64-encoded.
   */
  async pickDocument(): Promise<DocumentAttachment | null> {
    try {
      const result = await DocumentPicker.getDocumentAsync({
        type: SUPPORTED_TYPES,
        copyToCacheDirectory: true,
        multiple: false,
      });

      if (result.canceled || !result.assets || !result.assets[0]) {
        return null;
      }

      const asset = result.assets[0];

      if (asset.size && asset.size > MAX_BYTES) {
        Alert.alert(
          'File Too Large',
          'Please choose a file under 20 MB.',
          [{ text: 'OK' }]
        );
        return null;
      }

      const base64 = await uriToBase64(asset.uri);
      if (!base64) {
        Alert.alert('Error', 'Could not read the selected file.');
        return null;
      }

      return {
        uri: asset.uri,
        base64,
        name: asset.name || 'attachment',
        mimeType: asset.mimeType || 'application/octet-stream',
        size: asset.size ?? undefined,
      };
    } catch (error) {
      console.error('Error picking document:', error);
      Alert.alert('Error', 'Failed to pick document.');
      return null;
    }
  }
}

export const documentPickerService = new DocumentPickerService();
export default documentPickerService;
