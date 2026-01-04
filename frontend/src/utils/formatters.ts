/**
 * Formatting utilities
 */

/**
 * Format decimal hours as "Xh Ym" format
 * e.g., 7.07 -> "7h 4m", 8.5 -> "8h 30m"
 */
export function formatSleepHours(decimalHours: number | null | undefined): string {
  if (decimalHours === null || decimalHours === undefined) return '';

  const hours = Math.floor(decimalHours);
  const minutes = Math.round((decimalHours - hours) * 60);

  if (minutes === 0) {
    return `${hours}h`;
  }
  return `${hours}h ${minutes}m`;
}
