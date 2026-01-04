import { useState, useEffect } from 'react'
import { APP_CONFIG } from '../../config'

interface WeatherCurrent {
  temperature: number
  feels_like: number
  humidity: number
  description: string
  icon: string
  wind_speed: number
}

interface WeatherForecast {
  date: string
  temp_high: number
  temp_low: number
  description: string
  icon: string
  pop: number
}

interface WeatherData {
  location: string
  current: WeatherCurrent
  forecast: WeatherForecast[]
  fetched_at: string
}

// OpenWeatherMap icon to emoji mapping
const iconToEmoji: Record<string, string> = {
  '01d': '☀️', '01n': '🌙',
  '02d': '⛅', '02n': '☁️',
  '03d': '☁️', '03n': '☁️',
  '04d': '☁️', '04n': '☁️',
  '09d': '🌧️', '09n': '🌧️',
  '10d': '🌦️', '10n': '🌧️',
  '11d': '⛈️', '11n': '⛈️',
  '13d': '❄️', '13n': '❄️',
  '50d': '🌫️', '50n': '🌫️',
}

export function WeatherWidget() {
  const [weather, setWeather] = useState<WeatherData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    fetchWeather()
    // Refresh every 30 minutes
    const interval = setInterval(fetchWeather, 30 * 60 * 1000)
    return () => clearInterval(interval)
  }, [])

  const fetchWeather = async () => {
    try {
      const response = await fetch(`${APP_CONFIG.apiUrl}/api/morning-brief/weather`, {
        credentials: 'include'
      })
      if (!response.ok) {
        throw new Error('Failed to fetch weather')
      }
      const data = await response.json()
      setWeather(data)
      setError(null)
    } catch (err) {
      setError('Weather unavailable')
      console.error('Weather fetch error:', err)
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="bg-gray-800/50 rounded-lg p-3 animate-pulse">
        <div className="h-6 bg-gray-700 rounded w-24 mb-2"></div>
        <div className="h-8 bg-gray-700 rounded w-16"></div>
      </div>
    )
  }

  if (error || !weather) {
    return (
      <div className="bg-gray-800/50 rounded-lg p-3 text-gray-400 text-sm">
        {error || 'No weather data'}
      </div>
    )
  }

  const emoji = iconToEmoji[weather.current.icon] || '🌡️'

  return (
    <div
      className="bg-gray-800/50 rounded-lg p-3 cursor-pointer hover:bg-gray-800/70 transition-colors"
      onClick={() => setExpanded(!expanded)}
    >
      {/* Compact view */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-2xl">{emoji}</span>
          <div>
            <div className="text-lg font-semibold text-white">
              {Math.round(weather.current.temperature)}°F
            </div>
            <div className="text-xs text-gray-400 capitalize">
              {weather.current.description}
            </div>
          </div>
        </div>
        <div className="text-right text-xs text-gray-500">
          {weather.location.split(',')[0]}
          <div className="text-gray-600">
            Feels {Math.round(weather.current.feels_like)}°
          </div>
        </div>
      </div>

      {/* Expanded forecast */}
      {expanded && weather.forecast.length > 0 && (
        <div className="mt-3 pt-3 border-t border-gray-700">
          <div className="grid grid-cols-5 gap-2">
            {weather.forecast.slice(0, 5).map((day, idx) => {
              const dayEmoji = iconToEmoji[day.icon] || '🌡️'
              const dayName = idx === 0
                ? 'Today'
                : new Date(day.date).toLocaleDateString('en-US', { weekday: 'short' })

              return (
                <div key={day.date} className="text-center">
                  <div className="text-xs text-gray-400">{dayName}</div>
                  <div className="text-lg">{dayEmoji}</div>
                  <div className="text-xs">
                    <span className="text-white">{Math.round(day.temp_high)}°</span>
                    <span className="text-gray-500"> / {Math.round(day.temp_low)}°</span>
                  </div>
                  {day.pop > 0.2 && (
                    <div className="text-xs text-blue-400">
                      {Math.round(day.pop * 100)}%💧
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          {/* Wind and humidity */}
          <div className="mt-2 flex gap-4 text-xs text-gray-500">
            <span>💨 {Math.round(weather.current.wind_speed)} mph</span>
            <span>💧 {weather.current.humidity}%</span>
          </div>
        </div>
      )}
    </div>
  )
}

export default WeatherWidget
