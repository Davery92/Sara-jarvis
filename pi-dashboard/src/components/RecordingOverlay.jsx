import { useState, useEffect, useRef } from 'preact/hooks';

/**
 * Full-screen recording overlay for continuous voice recording
 * Shows pulsing indicator, duration timer, and handles tap-to-stop
 */
export function RecordingOverlay({
  isActive,
  isProcessing,
  onStop,
  onCancel
}) {
  const [duration, setDuration] = useState(0);
  const [isRecording, setIsRecording] = useState(false);
  const timerRef = useRef(null);

  // Track recording vs processing state
  useEffect(() => {
    if (isActive && !isProcessing) {
      // Starting recording
      setIsRecording(true);
      setDuration(0);
      timerRef.current = setInterval(() => {
        setDuration(d => d + 1);
      }, 1000);
    } else if (isProcessing) {
      // Switched to processing
      setIsRecording(false);
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    } else {
      // Closing
      setIsRecording(false);
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      setDuration(0);
    }

    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
      }
    };
  }, [isActive, isProcessing]);

  if (!isActive && !isProcessing) return null;

  // Format duration as MM:SS
  const formatDuration = (seconds) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  };

  const handleOverlayClick = (e) => {
    // Don't allow interaction while processing
    if (isProcessing) return;
    // Don't trigger stop if clicking cancel button
    if (e.target.closest('.recording-cancel-btn')) return;
    onStop();
  };

  return (
    <div class="recording-overlay" onClick={handleOverlayClick}>
      {!isProcessing && (
        <button
          class="recording-cancel-btn"
          onClick={(e) => {
            e.stopPropagation();
            onCancel();
          }}
        >
          Cancel
        </button>
      )}

      <div class="recording-content">
        {isProcessing ? (
          <>
            <div class="recording-indicator processing">
              <div class="processing-spinner"></div>
            </div>
            <div class="recording-instruction">
              Processing recording...
            </div>
          </>
        ) : (
          <>
            <div class="recording-indicator">
              <div class="recording-pulse-ring"></div>
              <div class="recording-pulse-ring delay-1"></div>
              <div class="recording-pulse-ring delay-2"></div>
              <div class="recording-dot"></div>
            </div>

            <div class="recording-timer">
              {formatDuration(duration)}
            </div>

            <div class="recording-instruction">
              Recording... Tap anywhere to stop
            </div>
          </>
        )}
      </div>
    </div>
  );
}
