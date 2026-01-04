/**
 * Date utility functions for consistent local date handling
 */

/**
 * Get today's date in YYYY-MM-DD format using local timezone
 * This is different from toISOString().split('T')[0] which uses UTC
 */
export function getLocalDateString(date: Date = new Date()): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

/**
 * Get yesterday's date in YYYY-MM-DD format using local timezone
 */
export function getYesterdayDateString(): string {
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  return getLocalDateString(yesterday);
}

/**
 * Get a date N days ago in YYYY-MM-DD format using local timezone
 */
export function getDaysAgoDateString(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return getLocalDateString(date);
}

/**
 * Parse a YYYY-MM-DD string to a Date object at midnight local time
 */
export function parseLocalDateString(dateStr: string): Date {
  const [year, month, day] = dateStr.split('-').map(Number);
  return new Date(year, month - 1, day);
}

/**
 * Check if a date string matches today's local date
 */
export function isToday(dateStr: string): boolean {
  return dateStr === getLocalDateString();
}

/**
 * Check if a date string matches yesterday's local date
 */
export function isYesterday(dateStr: string): boolean {
  return dateStr === getYesterdayDateString();
}

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
