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

class WeatherService {
  private API_KEY = '06a4130ca3b58bd11b4cba02ddbc98e2';
  private BASE_URL = 'https://api.openweathermap.org/data/2.5/weather';

  async getCurrentWeather(): Promise<WeatherData | null> {
    try {
      // Request location permission
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (status !== 'granted') {
        console.log('Location permission denied');
        return this.getMockWeather();
      }

      // Get current location
      const location = await Location.getCurrentPositionAsync({});
      const { latitude, longitude } = location.coords;

      // Make API call with real weather data
      if (!this.API_KEY) {
        console.log('Weather API key not configured');
        return this.getMockWeather();
      }

      const url = `${this.BASE_URL}?lat=${latitude}&lon=${longitude}&appid=${this.API_KEY}&units=imperial`;
      const response = await fetch(url);

      if (!response.ok) {
        console.error('Weather API request failed:', response.status);
        return this.getMockWeather();
      }

      const data = await response.json();

      return {
        temperature: Math.round(data.main.temp),
        condition: data.weather[0].main,
        description: data.weather[0].description,
        humidity: data.main.humidity,
        windSpeed: Math.round(data.wind.speed),
        icon: data.weather[0].icon,
        location: data.name,
      };
    } catch (error) {
      console.error('Failed to fetch weather:', error);
      return this.getMockWeather();
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
