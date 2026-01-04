import * as Location from 'expo-location';

export interface WeatherData {
  temperature: number;
  condition: string;
  description: string;
  humidity: number;
  windSpeed: number;
  icon: string;
  location: string;
}

// Timeout wrapper for async operations
function withTimeout<T>(promise: Promise<T>, ms: number, errorMessage: string): Promise<T> {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      reject(new Error(errorMessage));
    }, ms);

    promise
      .then((result) => {
        clearTimeout(timeout);
        resolve(result);
      })
      .catch((error) => {
        clearTimeout(timeout);
        reject(error);
      });
  });
}

class WeatherService {
  private API_KEY = '06a4130ca3b58bd11b4cba02ddbc98e2';
  private BASE_URL = 'https://api.openweathermap.org/data/2.5/weather';
  private cachedWeather: WeatherData | null = null;
  private cacheTimestamp: number = 0;
  private CACHE_DURATION_MS = 15 * 60 * 1000; // 15 minutes

  async getCurrentWeather(): Promise<WeatherData | null> {
    try {
      // Check if we have valid cached weather data
      const now = Date.now();
      if (this.cachedWeather && (now - this.cacheTimestamp) < this.CACHE_DURATION_MS) {
        console.log('[Weather] Using cached weather data');
        return this.cachedWeather;
      }

      // Request location permission
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (status !== 'granted') {
        console.log('[Weather] Location permission denied');
        return this.cachedWeather || this.getMockWeather();
      }

      // Try to get last known position first (faster, works after background)
      let coords: { latitude: number; longitude: number } | null = null;

      try {
        const lastKnown = await Location.getLastKnownPositionAsync({
          maxAge: 10 * 60 * 1000, // Accept positions up to 10 minutes old
        });
        if (lastKnown) {
          coords = lastKnown.coords;
          console.log('[Weather] Using last known position');
        }
      } catch (e) {
        console.log('[Weather] Failed to get last known position:', e);
      }

      // If no last known position, try to get current position with timeout
      if (!coords) {
        try {
          const location = await withTimeout(
            Location.getCurrentPositionAsync({
              accuracy: Location.Accuracy.Balanced,
            }),
            8000, // 8 second timeout for location
            'Location request timed out'
          );
          coords = location.coords;
          console.log('[Weather] Got current position');
        } catch (e) {
          console.log('[Weather] Failed to get current position:', e);
          // Return cached data if available, otherwise mock
          return this.cachedWeather || this.getMockWeather();
        }
      }

      const { latitude, longitude } = coords;

      // Make API call with timeout
      if (!this.API_KEY) {
        console.log('[Weather] API key not configured');
        return this.cachedWeather || this.getMockWeather();
      }

      const url = `${this.BASE_URL}?lat=${latitude}&lon=${longitude}&appid=${this.API_KEY}&units=imperial`;

      const response = await withTimeout(
        fetch(url),
        10000, // 10 second timeout for API call
        'Weather API request timed out'
      );

      if (!response.ok) {
        console.error('[Weather] API request failed:', response.status);
        return this.cachedWeather || this.getMockWeather();
      }

      const data = await response.json();

      const weatherData: WeatherData = {
        temperature: Math.round(data.main.temp),
        condition: data.weather[0].main,
        description: data.weather[0].description,
        humidity: data.main.humidity,
        windSpeed: Math.round(data.wind.speed),
        icon: data.weather[0].icon,
        location: data.name,
      };

      // Cache the weather data
      this.cachedWeather = weatherData;
      this.cacheTimestamp = now;
      console.log('[Weather] Weather data fetched and cached');

      return weatherData;
    } catch (error) {
      console.error('[Weather] Failed to fetch weather:', error);
      // Return cached data if available, otherwise mock
      return this.cachedWeather || this.getMockWeather();
    }
  }

  private getMockWeather(): WeatherData {
    return {
      temperature: 72,
      condition: 'Clear',
      description: 'Clear sky',
      humidity: 45,
      windSpeed: 8,
      icon: '01d',
      location: 'Current Location',
    };
  }

  getWeatherEmoji(condition: string): string {
    const emojiMap: { [key: string]: string } = {
      Clear: '☀️',
      Clouds: '☁️',
      Rain: '🌧️',
      Drizzle: '🌦️',
      Thunderstorm: '⛈️',
      Snow: '❄️',
      Mist: '🌫️',
      Smoke: '💨',
      Haze: '🌫️',
      Dust: '💨',
      Fog: '🌫️',
      Sand: '💨',
      Ash: '💨',
      Squall: '💨',
      Tornado: '🌪️',
    };

    return emojiMap[condition] || '🌤️';
  }
}

export const weatherService = new WeatherService();
export default weatherService;
