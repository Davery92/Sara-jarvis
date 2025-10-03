import { useState, useEffect } from 'react';

export interface MobileDetection {
  isMobile: boolean;
  isTablet: boolean;
  isDesktop: boolean;
  orientation: 'portrait' | 'landscape';
  screenWidth: number;
  screenHeight: number;
  isTouchDevice: boolean;
}

export const useMobileDetection = (): MobileDetection => {
  const [detection, setDetection] = useState<MobileDetection>(() => ({
    isMobile: window.innerWidth < 768,
    isTablet: window.innerWidth >= 768 && window.innerWidth < 1024,
    isDesktop: window.innerWidth >= 1024,
    orientation: window.innerWidth < window.innerHeight ? 'portrait' : 'landscape',
    screenWidth: window.innerWidth,
    screenHeight: window.innerHeight,
    isTouchDevice: 'ontouchstart' in window || navigator.maxTouchPoints > 0,
  }));

  useEffect(() => {
    const handleResize = () => {
      const width = window.innerWidth;
      const height = window.innerHeight;

      setDetection({
        isMobile: width < 768,
        isTablet: width >= 768 && width < 1024,
        isDesktop: width >= 1024,
        orientation: width < height ? 'portrait' : 'landscape',
        screenWidth: width,
        screenHeight: height,
        isTouchDevice: 'ontouchstart' in window || navigator.maxTouchPoints > 0,
      });
    };

    window.addEventListener('resize', handleResize);
    window.addEventListener('orientationchange', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      window.removeEventListener('orientationchange', handleResize);
    };
  }, []);

  return detection;
};
