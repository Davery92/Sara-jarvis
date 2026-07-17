declare module 'react-native-math-view' {
  import * as React from 'react';
  import { StyleProp, TextStyle, ViewProps, ViewStyle } from 'react-native';

  export interface MathViewProps extends ViewProps {
    math: string;
    color?: string;
    resizeMode?: 'cover' | 'contain';
    style?: StyleProp<ViewStyle & Pick<TextStyle, 'color'>>;
    config?: Record<string, unknown>;
    debug?: boolean;
  }

  const MathView: React.ComponentType<MathViewProps>;
  export default MathView;
}
