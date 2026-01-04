import * as ImagePicker from 'expo-image-picker';
import { Alert, Platform } from 'react-native';

export interface ImageAttachment {
  uri: string;
  base64: string;
  type: string;
  width: number;
  height: number;
}

class ImagePickerService {
  /**
   * Request camera permissions
   */
  async requestCameraPermission(): Promise<boolean> {
    if (Platform.OS === 'web') {
      return true;
    }

    const { status } = await ImagePicker.requestCameraPermissionsAsync();
    if (status !== 'granted') {
      Alert.alert(
        'Camera Permission Required',
        'Please enable camera access in your device settings to take photos.',
        [{ text: 'OK' }]
      );
      return false;
    }
    return true;
  }

  /**
   * Request media library permissions
   */
  async requestMediaLibraryPermission(): Promise<boolean> {
    if (Platform.OS === 'web') {
      return true;
    }

    const { status } = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (status !== 'granted') {
      Alert.alert(
        'Photo Library Permission Required',
        'Please enable photo library access in your device settings to select images.',
        [{ text: 'OK' }]
      );
      return false;
    }
    return true;
  }

  /**
   * Pick image from camera roll/photo library
   */
  async pickFromGallery(): Promise<ImageAttachment | null> {
    try {
      const hasPermission = await this.requestMediaLibraryPermission();
      if (!hasPermission) {
        return null;
      }

      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ImagePicker.MediaTypeOptions.Images,
        allowsEditing: true,
        quality: 0.8,
        base64: true,
      });

      if (result.canceled || !result.assets || !result.assets[0]) {
        return null;
      }

      const asset = result.assets[0];

      if (!asset.base64) {
        console.error('Failed to get base64 from selected image');
        return null;
      }

      return {
        uri: asset.uri,
        base64: asset.base64,
        type: asset.mimeType || 'image/jpeg',
        width: asset.width,
        height: asset.height,
      };
    } catch (error) {
      console.error('Error picking image from gallery:', error);
      Alert.alert('Error', 'Failed to pick image from gallery');
      return null;
    }
  }

  /**
   * Take photo with camera
   */
  async takePhoto(): Promise<ImageAttachment | null> {
    try {
      const hasPermission = await this.requestCameraPermission();
      if (!hasPermission) {
        return null;
      }

      const result = await ImagePicker.launchCameraAsync({
        allowsEditing: true,
        quality: 0.8,
        base64: true,
      });

      if (result.canceled || !result.assets || !result.assets[0]) {
        return null;
      }

      const asset = result.assets[0];

      if (!asset.base64) {
        console.error('Failed to get base64 from camera image');
        return null;
      }

      return {
        uri: asset.uri,
        base64: asset.base64,
        type: asset.mimeType || 'image/jpeg',
        width: asset.width,
        height: asset.height,
      };
    } catch (error) {
      console.error('Error taking photo:', error);
      Alert.alert('Error', 'Failed to take photo');
      return null;
    }
  }
}

export const imagePickerService = new ImagePickerService();
export default imagePickerService;
