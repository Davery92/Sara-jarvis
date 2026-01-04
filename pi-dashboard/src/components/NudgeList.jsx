/**
 * NudgeList - Displays pending nudges from the subconscious
 */

export function NudgeList({ nudges, onAcknowledge }) {
  if (!nudges || nudges.length === 0) {
    return (
      <div class="card nudges-panel">
        <div class="card-header">
          <span class="card-title">Nudges</span>
        </div>
        <div class="empty-state">
          No pending nudges - all clear!
        </div>
      </div>
    );
  }

  // Get icon based on nudge type
  const getIcon = (nudgeType) => {
    switch (nudgeType) {
      case 'missed_meal':
      case 'late_breakfast':
      case 'late_lunch':
      case 'late_dinner':
        return '🍽️';
      case 'bedtime':
        return '🌙';
      case 'sleep_deficit':
        return '😴';
      case 'focus_break':
        return '☕';
      case 'hydration':
        return '💧';
      default:
        return '💡';
    }
  };

  return (
    <div class="card nudges-panel">
      <div class="card-header">
        <span class="card-title">Nudges ({nudges.length})</span>
      </div>
      <div class="nudges-list">
        {nudges.map((nudge) => (
          <div
            key={nudge.id}
            class={`nudge-item severity-${nudge.severity}`}
            onClick={() => onAcknowledge(nudge.id)}
          >
            <span class="nudge-icon">{getIcon(nudge.nudge_type)}</span>
            <div class="nudge-content">
              <div class="nudge-title">{nudge.title}</div>
              <div class="nudge-message">{nudge.message}</div>
              {nudge.action_suggestion && (
                <div class="nudge-action" style={{ marginTop: '4px', fontSize: '0.85rem', color: 'var(--accent-blue)' }}>
                  → {nudge.action_suggestion}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
