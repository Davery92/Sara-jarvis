/**
 * Local-date helpers, mirroring ios-app/src/utils/dateUtils.ts.
 *
 * `new Date().toISOString().split('T')[0]` derives the calendar date in
 * UTC, not the browser's local time - after ~8pm ET it's already tomorrow
 * in UTC, so a meal or weigh-in logged that evening files under the wrong
 * day. Use these instead anywhere a "today" or "this date" string feeds a
 * nutrition/weight-log write (SARA_INTELLIGENT_FOOD_LOGGING_PLAN_2026_08_16
 * Stage A, principle #8).
 */

/** Today's (or a given Date's) calendar date in YYYY-MM-DD, local time. */
export function getLocalDateString(date: Date = new Date()): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

/** Parse a YYYY-MM-DD string to a Date at local midnight (not UTC midnight). */
export function parseLocalDateString(dateStr: string): Date {
  const [year, month, day] = dateStr.split('-').map(Number)
  return new Date(year, month - 1, day)
}
