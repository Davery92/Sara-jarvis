/**
 * LLMStatusPanel - Displays LLM backend status
 */

export function LLMStatusPanel({ state }) {
  if (!state || state.message) {
    return (
      <div class="card llm-panel">
        <div class="card-header">
          <span class="card-title">LLM Status</span>
        </div>
        <div class="empty-state">
          No status available
        </div>
      </div>
    );
  }

  // Extract hostname from URL for display
  const formatUrl = (url) => {
    if (!url) return 'Not configured';
    try {
      const parsed = new URL(url);
      return `${parsed.hostname}:${parsed.port}`;
    } catch {
      return url;
    }
  };

  const getStatusClass = (status) => {
    if (!status) return '';
    switch (status.toLowerCase()) {
      case 'online':
        return 'online';
      case 'offline':
        return 'offline';
      case 'slow':
        return 'slow';
      default:
        return '';
    }
  };

  const getStatusLabel = (status) => {
    if (!status) return 'Unknown';
    return status.charAt(0).toUpperCase() + status.slice(1);
  };

  return (
    <div class="card llm-panel">
      <div class="card-header">
        <span class="card-title">LLM Status</span>
      </div>
      <div class="llm-content">
        <div class="llm-status">
          <div class={`status-indicator ${getStatusClass(state.llm_primary_status)}`} />
          <span class="llm-label">Primary</span>
          <span class="llm-value">{getStatusLabel(state.llm_primary_status)}</span>
        </div>
        <div class="llm-status">
          <div class={`status-indicator ${getStatusClass(state.llm_failover_status)}`} />
          <span class="llm-label">Failover</span>
          <span class="llm-value">{getStatusLabel(state.llm_failover_status)}</span>
        </div>

        <div class="active-backend">
          <div class="active-backend-label">Active Backend:</div>
          <div class="active-backend-value">
            {state.llm_active_backend === 'none_available'
              ? 'None available'
              : formatUrl(state.llm_active_backend)}
          </div>
        </div>

        {state.service_health && (
          <div class="llm-status" style={{ marginTop: '12px' }}>
            <div class={`status-indicator ${state.service_health.backend === 'healthy' ? 'online' : 'offline'}`} />
            <span class="llm-label">Backend API</span>
            <span class="llm-value">{state.service_health.backend || 'Unknown'}</span>
          </div>
        )}
      </div>
    </div>
  );
}
