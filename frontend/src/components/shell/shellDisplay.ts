export const WEATHER_EMOJI: Record<string, string> = {
  'clear-day': '\u2600\ufe0f', 'clear-night': '\ud83c\udf19', cloudy: '\u2601\ufe0f',
  'partly-cloudy-day': '\u26c5', 'partly-cloudy-night': '\ud83c\udf24\ufe0f',
  rain: '\ud83c\udf27\ufe0f', snow: '\u2744\ufe0f', wind: '\ud83c\udf2c\ufe0f',
  fog: '\ud83c\udf2b\ufe0f', thunderstorm: '\u26c8\ufe0f',
  '01d': '\u2600\ufe0f', '01n': '\ud83c\udf19',
  '02d': '\u26c5', '02n': '\ud83c\udf24\ufe0f',
  '03d': '\u2601\ufe0f', '03n': '\u2601\ufe0f',
  '04d': '\u2601\ufe0f', '04n': '\u2601\ufe0f',
  '09d': '\ud83c\udf27\ufe0f', '09n': '\ud83c\udf27\ufe0f',
  '10d': '\ud83c\udf27\ufe0f', '10n': '\ud83c\udf27\ufe0f',
  '11d': '\u26c8\ufe0f', '11n': '\u26c8\ufe0f',
  '13d': '\u2744\ufe0f', '13n': '\u2744\ufe0f',
  '50d': '\ud83c\udf2b\ufe0f', '50n': '\ud83c\udf2b\ufe0f',
}

export const EMOTION_EMOJI: Record<string, string> = {
  neutral: '\ud83d\ude10',
  curious: '\ud83e\uddd0',
  concerned: '\ud83d\ude1f',
  pleased: '\ud83d\ude0a',
  alert: '\u26a0\ufe0f',
  reflective: '\ud83d\udcad',
  focused: '\ud83c\udfaf',
  calm: '\ud83e\uddd8',
  energetic: '\u26a1',
}

export function getGreeting() {
  const hour = new Date().getHours()
  if (hour < 12) return 'Good morning'
  if (hour < 17) return 'Good afternoon'
  return 'Good evening'
}

export function formatRelativeTime(ts: string) {
  const diff = Date.now() - new Date(ts).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}
