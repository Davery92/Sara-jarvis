/**
 * Jarvis Sprite Component - Phase 3 TODO
 * 
 * This component displays the animated Jarvis sprite that shows system state:
 * - idle: Gentle breathing animation
 * - listening: Focused attention (keyboard focus)
 * - thinking: Processing animation (LLM streaming)
 * - tooling: Tool execution indicator
 * - working: Background task activity
 * - notify: New inbox item pulse
 * - error: Error state indication
 * 
 * TODO: Implement in Phase 3
 */

import React, { useEffect, useState } from 'react';

type SpriteState = 'idle' | 'listening' | 'thinking' | 'tooling' | 'working' | 'notify' | 'error';

interface JarvisSpriteProps {
  className?: string;
  size?: 'sm' | 'md' | 'lg';
}

export const JarvisSprite: React.FC<JarvisSpriteProps> = ({ 
  className, 
  size = 'md' 
}) => {
  const [state, setState] = useState<SpriteState>('idle');
  const [isConnected, setIsConnected] = useState(false);

  // TODO: Implement SSE connection to /api/presence/stream
  useEffect(() => {
    // TODO: Subscribe to presence events
    // TODO: Handle state transitions
    // TODO: Cleanup on unmount
    
    return () => {
      // TODO: Close SSE connection
    };
  }, []);

  const getSpriteClasses = () => {
    const baseClasses = 'jarvis-sprite transition-all duration-300';
    const sizeClasses = {
      sm: 'w-8 h-8',
      md: 'w-12 h-12', 
      lg: 'w-16 h-16'
    };
    const stateClasses = {
      idle: 'animate-pulse opacity-70',
      listening: 'animate-ping opacity-90',
      thinking: 'animate-spin opacity-100',
      tooling: 'animate-bounce opacity-100',
      working: 'animate-pulse opacity-100 ring-2 ring-blue-400',
      notify: 'animate-ping opacity-100 ring-2 ring-yellow-400',
      error: 'animate-pulse opacity-100 ring-2 ring-red-400'
    };

    return `${baseClasses} ${sizeClasses[size]} ${stateClasses[state]} ${className || ''}`;
  };

  return (
    <div className={getSpriteClasses()} title={`Jarvis is ${state}`}>
      {/* TODO: Replace with actual sprite graphics */}
      <div className="w-full h-full rounded-full bg-gradient-to-br from-blue-400 to-purple-600 flex items-center justify-center text-white font-bold">
        J
      </div>
      
      {/* Connection status indicator */}
      {!isConnected && (
        <div className="absolute -top-1 -right-1 w-3 h-3 bg-red-500 rounded-full" 
             title="Disconnected from presence service" />
      )}
    </div>
  );
};

export default JarvisSprite;