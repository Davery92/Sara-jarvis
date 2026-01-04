/**
 * StatePanel - Displays the mental model state
 */

export function StatePanel({ state }) {
  if (!state || state.message) {
    return (
      <div class="card state-panel">
        <div class="card-header">
          <span class="card-title">Current State</span>
        </div>
        <div class="empty-state">
          No state data available yet
        </div>
      </div>
    );
  }

  // Format hours since meal
  const formatMealTime = () => {
    if (!state.hours_since_meal) return 'Unknown';
    const hours = state.hours_since_meal;
    if (hours < 1) return `${Math.round(hours * 60)} min ago`;
    return `${hours.toFixed(1)}h ago`;
  };

  // Get meal status class
  const getMealClass = () => {
    if (!state.hours_since_meal) return '';
    if (state.hours_since_meal > 5) return 'warning';
    return 'good';
  };

  // Format energy level
  const formatEnergy = () => {
    if (state.inferred_energy_level === null || state.inferred_energy_level === undefined) {
      return 'Unknown';
    }
    const level = state.inferred_energy_level;
    if (level >= 0.7) return 'High';
    if (level >= 0.4) return 'Moderate';
    return 'Low';
  };

  // Get energy class
  const getEnergyClass = () => {
    if (state.inferred_energy_level === null) return '';
    if (state.inferred_energy_level >= 0.7) return 'good';
    if (state.inferred_energy_level >= 0.4) return '';
    return 'warning';
  };

  // Format sleep
  const formatSleep = () => {
    if (!state.last_sleep_hours) return 'Unknown';
    const hours = state.last_sleep_hours;
    const quality = state.last_sleep_quality || '';
    return `${hours.toFixed(1)}h (${quality})`;
  };

  // Get sleep class
  const getSleepClass = () => {
    if (!state.last_sleep_hours) return '';
    if (state.last_sleep_hours >= 7) return 'good';
    if (state.last_sleep_hours >= 6) return '';
    return 'warning';
  };

  // Format focus areas
  const formatFocus = () => {
    if (!state.current_focus_areas || state.current_focus_areas.length === 0) {
      return 'None detected';
    }
    return state.current_focus_areas.slice(0, 3).join(', ');
  };

  return (
    <div class="card state-panel">
      <div class="card-header">
        <span class="card-title">Current State</span>
      </div>
      <div class="state-content">
        <div class="state-item">
          <span class="state-label">Last Meal</span>
          <span class={`state-value ${getMealClass()}`}>
            {state.last_meal_type || 'None'} ({formatMealTime()})
          </span>
        </div>
        <div class="state-item">
          <span class="state-label">Energy</span>
          <span class={`state-value ${getEnergyClass()}`}>
            {formatEnergy()}
          </span>
        </div>
        <div class="state-item">
          <span class="state-label">Mood</span>
          <span class="state-value">
            {state.inferred_mood || 'Unknown'}
          </span>
        </div>
        <div class="state-item">
          <span class="state-label">Sleep</span>
          <span class={`state-value ${getSleepClass()}`}>
            {formatSleep()}
          </span>
        </div>
        <div class="state-item">
          <span class="state-label">Focus</span>
          <span class="state-value">
            {formatFocus()}
          </span>
        </div>
      </div>
    </div>
  );
}
