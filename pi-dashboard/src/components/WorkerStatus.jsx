/**
 * WorkerStatus - Shows status of background workers
 */

export function WorkerStatus({ workerStatus }) {
  if (!workerStatus) {
    return (
      <div class="card worker-status">
        <div class="card-header">
          <span class="card-title">Background Workers</span>
        </div>
        <div class="empty-state">Loading worker status...</div>
      </div>
    );
  }

  const formatTime = (isoString) => {
    if (!isoString) return 'Never';
    const date = new Date(isoString);
    return date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
  };

  const formatRelative = (isoString) => {
    if (!isoString) return '';
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);

    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHours = Math.floor(diffMins / 60);
    return `${diffHours}h ago`;
  };

  const getStatusClass = (lastRun, intervalMins) => {
    if (!lastRun) return 'warning';
    const date = new Date(lastRun);
    const now = new Date();
    const diffMins = (now - date) / 60000;
    // If it's been more than 1.5x the interval, something's wrong
    if (diffMins > intervalMins * 1.5) return 'error';
    return 'good';
  };

  return (
    <div class="card worker-status">
      <div class="card-header">
        <span class="card-title">Background Workers</span>
      </div>
      <div class="worker-list">
        {/* Subconscious Worker */}
        <div class="worker-item">
          <div class="worker-info">
            <span class={`status-dot ${getStatusClass(workerStatus.subconscious?.last_run, 30)}`}></span>
            <span class="worker-name">Subconscious</span>
          </div>
          <div class="worker-times">
            <span class="worker-last">
              {formatRelative(workerStatus.subconscious?.last_run)}
            </span>
            <span class="worker-next">
              → {formatTime(workerStatus.subconscious?.next_run)}
            </span>
          </div>
        </div>

        {/* Orchestrator */}
        <div class="worker-item">
          <div class="worker-info">
            <span class={`status-dot ${getStatusClass(workerStatus.orchestrator?.last_run, 5)}`}></span>
            <span class="worker-name">Orchestrator</span>
          </div>
          <div class="worker-times">
            <span class="worker-last">
              {formatRelative(workerStatus.orchestrator?.last_run)}
            </span>
            <span class="worker-next">
              → {formatTime(workerStatus.orchestrator?.next_run)}
            </span>
          </div>
        </div>

        {/* Context Awareness */}
        {workerStatus.awareness && (
          <div class="worker-item">
            <div class="worker-info">
              <span class={`status-dot ${getStatusClass(workerStatus.awareness?.last_run, 15)}`}></span>
              <span class="worker-name">Awareness</span>
            </div>
            <div class="worker-times">
              <span class="worker-last">
                {formatRelative(workerStatus.awareness?.last_run)}
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
