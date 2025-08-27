import React from 'react';

interface GTKYInterviewTestProps {
  onComplete?: () => void;
  onSpriteStateChange?: (state: string) => void;
}

export function GTKYInterviewTest({ onComplete, onSpriteStateChange }: GTKYInterviewTestProps) {
  return (
    <div className="bg-gray-800 border border-gray-600 rounded-lg p-6 text-white">
      <h3 className="text-xl font-bold text-white mb-4">GTKY Interview Test Component</h3>
      <p className="text-gray-300 mb-4">This is a minimal test component to verify rendering works.</p>
      <button 
        onClick={() => onComplete?.()}
        className="bg-teal-600 text-white px-4 py-2 rounded hover:bg-teal-700"
      >
        Test Complete
      </button>
    </div>
  );
}