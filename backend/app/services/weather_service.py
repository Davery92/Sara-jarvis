"""
Weather Service
Fetches weather data from OpenWeatherMap API for Allentown, PA.
"""

import aiohttp
import logging
import time
from datetime import datetime
from typing import Dict, Optional
from dataclasses import dataclass, asdict

from app.core.timezone import now as local_now

logger = logging.getLogger(__name__)

# Allentown, PA coordinates (hardcoded)
ALLENTOWN_LAT = 40.6023
ALLENTOWN_LON = -75.4714
LOCATION_NAME = "Allentown, PA"

# OpenWeatherMap API key (from iOS app)
OPENWEATHERMAP_API_KEY = "06a4130ca3b58bd11b4cba02ddbc98e2"


@dataclass
class WeatherCondition:
    """Current weather conditions."""
    temperature: float  # Fahrenheit
    feels_like: float
    humidity: int  # Percentage
    description: str
    icon: str
    wind_speed: float  # mph
    wind_direction: int  # degrees
    clouds: int  # Percentage
    visibility: int  # meters
    pressure: int  # hPa

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class DailyForecast:
    """Daily forecast data."""
    date: str  # YYYY-MM-DD
    temp_high: float
    temp_low: float
    description: str
    icon: str
    pop: float  # Probability of precipitation (0-1)
    humidity: int
    wind_speed: float
    sunrise: str  # HH:MM
    sunset: str  # HH:MM

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class WeatherData:
    """Complete weather data response."""
    location: str
    current: WeatherCondition
    forecast: list[DailyForecast]
    fetched_at: str

    def to_dict(self) -> Dict:
        return {
            "location": self.location,
            "current": self.current.to_dict(),
            "forecast": [f.to_dict() for f in self.forecast],
            "fetched_at": self.fetched_at
        }


# One Call 3.0 needs its own subscription. When the key doesn't have one the
# API returns 401 on EVERY call, and this service is called often enough that
# the "trying free API" warning was ~530 log lines a day — a permanent config
# fact reported as if it were news. Park the endpoint for a day after an auth
# rejection and go straight to the free API; a key that gets subscribed later
# is picked up on the next expiry without a restart.
_ONECALL_AUTH_BACKOFF_SECONDS = 24 * 3600
_onecall_blocked_until: float = 0.0


def _onecall_available() -> bool:
    return time.monotonic() >= _onecall_blocked_until


def _block_onecall(status: int) -> None:
    """Called on an auth rejection; logs once per backoff window, not per call."""
    global _onecall_blocked_until
    if _onecall_available():
        logger.warning(
            "One Call API 3.0 returned %s (key not subscribed?) — using the free 2.5 API "
            "and skipping One Call for %dh",
            status, _ONECALL_AUTH_BACKOFF_SECONDS // 3600,
        )
    _onecall_blocked_until = time.monotonic() + _ONECALL_AUTH_BACKOFF_SECONDS


class WeatherService:
    """Service for fetching weather data from OpenWeatherMap."""

    def __init__(self):
        self.api_key = OPENWEATHERMAP_API_KEY
        self.base_url = "https://api.openweathermap.org/data/3.0"
        self.timeout = aiohttp.ClientTimeout(total=15)

    async def get_weather(self) -> Optional[WeatherData]:
        """
        Fetch current weather and 7-day forecast for Allentown, PA.
        Uses OpenWeatherMap One Call API 3.0.
        """
        if not _onecall_available():
            return await self._get_weather_free_api()
        try:
            url = f"{self.base_url}/onecall"
            params = {
                "lat": ALLENTOWN_LAT,
                "lon": ALLENTOWN_LON,
                "appid": self.api_key,
                "units": "imperial",  # Fahrenheit
                "exclude": "minutely,hourly,alerts"
            }

            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        # Fall back to the free API. An auth rejection is a
                        # standing config fact, not a transient blip — stop
                        # re-asking (and re-logging) for a while. Anything else
                        # may well work on the next call, so only debug-log it.
                        if response.status in (401, 403):
                            _block_onecall(response.status)
                        else:
                            logger.debug(
                                "One Call API returned %s, trying free API", response.status
                            )
                        return await self._get_weather_free_api()

                    data = await response.json()

            return self._parse_onecall_response(data)

        except Exception as e:
            logger.error(f"Error fetching weather from One Call API: {e}")
            # Try free API as fallback
            return await self._get_weather_free_api()

    async def _get_weather_free_api(self) -> Optional[WeatherData]:
        """
        Fallback to free weather API (2.5) if One Call fails.
        """
        try:
            # Current weather
            current_url = "https://api.openweathermap.org/data/2.5/weather"
            params = {
                "lat": ALLENTOWN_LAT,
                "lon": ALLENTOWN_LON,
                "appid": self.api_key,
                "units": "imperial"
            }

            # 5-day forecast
            forecast_url = "https://api.openweathermap.org/data/2.5/forecast"

            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                # Fetch both in parallel
                async with session.get(current_url, params=params) as current_resp:
                    if current_resp.status != 200:
                        error_text = await current_resp.text()
                        logger.error(f"Weather API error: {error_text}")
                        return None
                    current_data = await current_resp.json()

                async with session.get(forecast_url, params=params) as forecast_resp:
                    forecast_data = await forecast_resp.json() if forecast_resp.status == 200 else None

            return self._parse_free_api_response(current_data, forecast_data)

        except Exception as e:
            logger.error(f"Error fetching weather from free API: {e}")
            return None

    def _parse_onecall_response(self, data: Dict) -> WeatherData:
        """Parse One Call API 3.0 response."""
        current = data.get("current", {})
        daily = data.get("daily", [])

        # Parse current conditions
        weather_desc = current.get("weather", [{}])[0]
        current_weather = WeatherCondition(
            temperature=round(current.get("temp", 0)),
            feels_like=round(current.get("feels_like", 0)),
            humidity=current.get("humidity", 0),
            description=weather_desc.get("description", "").title(),
            icon=weather_desc.get("icon", "01d"),
            wind_speed=round(current.get("wind_speed", 0)),
            wind_direction=current.get("wind_deg", 0),
            clouds=current.get("clouds", 0),
            visibility=current.get("visibility", 10000),
            pressure=current.get("pressure", 1013)
        )

        # Parse daily forecast
        forecasts = []
        for day in daily[:7]:  # 7 days
            weather = day.get("weather", [{}])[0]
            temp = day.get("temp", {})

            # Convert Unix timestamps to readable times
            sunrise_dt = datetime.fromtimestamp(day.get("sunrise", 0))
            sunset_dt = datetime.fromtimestamp(day.get("sunset", 0))
            date_dt = datetime.fromtimestamp(day.get("dt", 0))

            forecasts.append(DailyForecast(
                date=date_dt.strftime("%Y-%m-%d"),
                temp_high=round(temp.get("max", 0)),
                temp_low=round(temp.get("min", 0)),
                description=weather.get("description", "").title(),
                icon=weather.get("icon", "01d"),
                pop=day.get("pop", 0),
                humidity=day.get("humidity", 0),
                wind_speed=round(day.get("wind_speed", 0)),
                sunrise=sunrise_dt.strftime("%H:%M"),
                sunset=sunset_dt.strftime("%H:%M")
            ))

        return WeatherData(
            location=LOCATION_NAME,
            current=current_weather,
            forecast=forecasts,
            fetched_at=local_now().isoformat()
        )

    def _parse_free_api_response(self, current_data: Dict, forecast_data: Optional[Dict]) -> WeatherData:
        """Parse free API (2.5) response."""
        # Parse current conditions
        weather_desc = current_data.get("weather", [{}])[0]
        main = current_data.get("main", {})
        wind = current_data.get("wind", {})
        sys = current_data.get("sys", {})

        current_weather = WeatherCondition(
            temperature=round(main.get("temp", 0)),
            feels_like=round(main.get("feels_like", 0)),
            humidity=main.get("humidity", 0),
            description=weather_desc.get("description", "").title(),
            icon=weather_desc.get("icon", "01d"),
            wind_speed=round(wind.get("speed", 0)),
            wind_direction=wind.get("deg", 0),
            clouds=current_data.get("clouds", {}).get("all", 0),
            visibility=current_data.get("visibility", 10000),
            pressure=main.get("pressure", 1013)
        )

        # Parse forecast (5-day/3-hour intervals, group by day)
        forecasts = []
        if forecast_data and "list" in forecast_data:
            daily_data = {}

            for item in forecast_data["list"]:
                dt = datetime.fromtimestamp(item["dt"])
                date_str = dt.strftime("%Y-%m-%d")

                if date_str not in daily_data:
                    daily_data[date_str] = {
                        "temps": [],
                        "descriptions": [],
                        "icons": [],
                        "pops": [],
                        "humidities": [],
                        "wind_speeds": []
                    }

                main = item.get("main", {})
                weather = item.get("weather", [{}])[0]

                daily_data[date_str]["temps"].append(main.get("temp", 0))
                daily_data[date_str]["descriptions"].append(weather.get("description", ""))
                daily_data[date_str]["icons"].append(weather.get("icon", "01d"))
                daily_data[date_str]["pops"].append(item.get("pop", 0))
                daily_data[date_str]["humidities"].append(main.get("humidity", 0))
                daily_data[date_str]["wind_speeds"].append(item.get("wind", {}).get("speed", 0))

            for date_str, data in sorted(daily_data.items())[:5]:
                # Use most common description/icon at noon-ish time
                mid_idx = len(data["descriptions"]) // 2
                forecasts.append(DailyForecast(
                    date=date_str,
                    temp_high=round(max(data["temps"])),
                    temp_low=round(min(data["temps"])),
                    description=data["descriptions"][mid_idx].title(),
                    icon=data["icons"][mid_idx],
                    pop=max(data["pops"]),
                    humidity=round(sum(data["humidities"]) / len(data["humidities"])),
                    wind_speed=round(sum(data["wind_speeds"]) / len(data["wind_speeds"])),
                    sunrise="",  # Not available in free API forecast
                    sunset=""
                ))

        return WeatherData(
            location=LOCATION_NAME,
            current=current_weather,
            forecast=forecasts,
            fetched_at=local_now().isoformat()
        )

    def format_for_brief(self, weather: WeatherData) -> str:
        """Format weather data for morning brief text."""
        current = weather.current

        lines = [
            f"## Weather for {weather.location}",
            f"**Current**: {current.temperature}°F ({current.description})",
            f"Feels like {current.feels_like}°F • Humidity {current.humidity}% • Wind {current.wind_speed} mph",
            "",
            "**Forecast:**"
        ]

        for day in weather.forecast[:3]:  # Next 3 days
            date_obj = datetime.strptime(day.date, "%Y-%m-%d")
            day_name = date_obj.strftime("%A")

            rain_str = ""
            if day.pop > 0.2:
                rain_str = f" • {int(day.pop * 100)}% rain"

            lines.append(f"- {day_name}: {day.temp_high}°/{day.temp_low}° - {day.description}{rain_str}")

        return "\n".join(lines)

    def format_for_tts(self, weather: WeatherData) -> str:
        """Format weather for text-to-speech (more conversational)."""
        current = weather.current
        today_forecast = weather.forecast[0] if weather.forecast else None

        # Current conditions
        parts = [f"Currently in {weather.location}, it's {current.temperature} degrees and {current.description.lower()}."]

        if abs(current.feels_like - current.temperature) >= 5:
            parts.append(f"It feels like {current.feels_like} degrees.")

        # Today's forecast
        if today_forecast:
            parts.append(f"Today's high will be {today_forecast.temp_high}, low of {today_forecast.temp_low}.")

            if today_forecast.pop > 0.3:
                parts.append(f"There's a {int(today_forecast.pop * 100)} percent chance of rain.")

        # Tomorrow preview
        if len(weather.forecast) > 1:
            tomorrow = weather.forecast[1]
            parts.append(f"Tomorrow: {tomorrow.description.lower()}, {tomorrow.temp_high} high.")

        return " ".join(parts)


# Singleton instance
weather_service = WeatherService()
