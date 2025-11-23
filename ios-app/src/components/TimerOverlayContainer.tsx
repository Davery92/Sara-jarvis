import React from 'react';
import { useTimer } from '../context/TimerContext';
import TimerOverlay from './TimerOverlay';

export default function TimerOverlayContainer() {
  const { activeTimer, stopTimer } = useTimer();

  if (!activeTimer) {
    return null;
  }

  return <TimerOverlay timer={activeTimer} onStop={stopTimer} />;
}
