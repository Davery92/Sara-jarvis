"""
FatSecret API Service
OAuth 2.0 Client Credentials flow for food database access
"""
import httpx
import base64
import time
import logging
import re
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class FatSecretServing:
    """Represents a serving size option from FatSecret"""
    serving_id: str
    serving_description: str
    metric_serving_amount: Optional[float]
    metric_serving_unit: Optional[str]
    number_of_units: Optional[float]
    measurement_description: Optional[str]
    calories: float
    protein: float
    carbohydrate: float
    fat: float
    fiber: Optional[float] = None
    sugar: Optional[float] = None
    sodium: Optional[float] = None
    saturated_fat: Optional[float] = None


@dataclass
class FatSecretFood:
    """Represents a food item from FatSecret"""
    food_id: str
    food_name: str
    food_type: str  # "Brand" or "Generic"
    brand_name: Optional[str]
    food_description: Optional[str]  # Summary like "Per 1 serving - Calories: 300kcal | Fat: 13g..."
    servings: List[FatSecretServing]

    def get_default_serving(self) -> Optional[FatSecretServing]:
        """Get the first/default serving option"""
        return self.servings[0] if self.servings else None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "food_id": self.food_id,
            "food_name": self.food_name,
            "food_type": self.food_type,
            "brand_name": self.brand_name,
            "food_description": self.food_description,
            "servings": [
                {
                    "serving_id": s.serving_id,
                    "serving_description": s.serving_description,
                    "metric_serving_amount": s.metric_serving_amount,
                    "metric_serving_unit": s.metric_serving_unit,
                    "number_of_units": s.number_of_units,
                    "measurement_description": s.measurement_description,
                    "calories": s.calories,
                    "protein": s.protein,
                    "carbohydrate": s.carbohydrate,
                    "fat": s.fat,
                    "fiber": s.fiber,
                    "sugar": s.sugar,
                    "sodium": s.sodium,
                    "saturated_fat": s.saturated_fat
                }
                for s in self.servings
            ]
        }


class FatSecretService:
    """
    FatSecret API client using OAuth 2.0 Client Credentials flow.
    Handles token management and API requests.
    """

    TOKEN_URL = "https://oauth.fatsecret.com/connect/token"
    API_BASE_URL = "https://platform.fatsecret.com/rest"

    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0

    async def _get_access_token(self) -> str:
        """Get a valid access token, refreshing if necessary"""
        # Check if we have a valid token with 5 minute buffer
        if self._access_token and time.time() < (self._token_expires_at - 300):
            return self._access_token

        # Request new token
        credentials = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.TOKEN_URL,
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Content-Type": "application/x-www-form-urlencoded"
                },
                data={
                    "grant_type": "client_credentials",
                    "scope": "basic barcode premier"
                }
            )

            if response.status_code != 200:
                logger.error(f"FatSecret token request failed: {response.status_code} {response.text}")
                raise Exception(f"Failed to get FatSecret access token: {response.status_code}")

            data = response.json()
            self._access_token = data["access_token"]
            self._token_expires_at = time.time() + data.get("expires_in", 86400)

            logger.info("FatSecret access token refreshed")
            return self._access_token

    async def _api_request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Make an authenticated API request"""
        token = await self._get_access_token()

        # Add common params
        params["format"] = "json"
        params["method"] = method

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{self.API_BASE_URL}/server.api",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/x-www-form-urlencoded"
                },
                data=params
            )

            if response.status_code != 200:
                logger.error(f"FatSecret API error: {response.status_code} {response.text}")
                raise Exception(f"FatSecret API error: {response.status_code}")

            return response.json()

    async def search_foods(
        self,
        query: str,
        page: int = 0,
        max_results: int = 20
    ) -> tuple[List[Dict[str, Any]], int]:
        """
        Search for foods by name.

        Args:
            query: Search term
            page: Page number (0-indexed)
            max_results: Max results per page (max 50)

        Returns:
            Tuple of (list of food dicts with basic info, total_results)
        """
        if max_results > 50:
            max_results = 50

        try:
            data = await self._api_request("foods.search", {
                "search_expression": query,
                "page_number": page,
                "max_results": max_results
            })

            foods_data = data.get("foods", {})
            total_results = int(foods_data.get("total_results", 0))

            if total_results == 0:
                return [], 0

            # Handle single result vs array
            food_list = foods_data.get("food", [])
            if isinstance(food_list, dict):
                food_list = [food_list]

            foods = []
            for f in food_list:
                # Parse the description to extract basic macros
                desc = f.get("food_description", "")
                parsed = self._parse_food_description(desc)

                foods.append({
                    "food_id": f.get("food_id"),
                    "food_name": f.get("food_name"),
                    "brand_name": f.get("brand_name"),
                    "food_type": f.get("food_type"),
                    "food_description": desc,
                    "calories": parsed.get("calories"),
                    "protein": parsed.get("protein"),
                    "carbs": parsed.get("carbs"),
                    "fat": parsed.get("fat"),
                    "serving_description": parsed.get("serving_description")
                })

            return foods, total_results

        except Exception as e:
            logger.error(f"FatSecret search error: {e}")
            return [], 0

    def _parse_food_description(self, description: str) -> Dict[str, Any]:
        """
        Parse the food_description string to extract nutrition info.
        Example: "Per 1 serving - Calories: 300kcal | Fat: 13.00g | Carbs: 32.00g | Protein: 15.00g"
        """
        result = {
            "serving_description": None,
            "calories": None,
            "protein": None,
            "carbs": None,
            "fat": None
        }

        if not description:
            return result

        # Extract serving description
        serving_match = re.match(r"Per (.+?) -", description)
        if serving_match:
            result["serving_description"] = serving_match.group(1)

        # Extract calories
        cal_match = re.search(r"Calories:\s*([\d.]+)", description)
        if cal_match:
            result["calories"] = float(cal_match.group(1))

        # Extract protein
        protein_match = re.search(r"Protein:\s*([\d.]+)", description)
        if protein_match:
            result["protein"] = float(protein_match.group(1))

        # Extract carbs
        carbs_match = re.search(r"Carbs:\s*([\d.]+)", description)
        if carbs_match:
            result["carbs"] = float(carbs_match.group(1))

        # Extract fat
        fat_match = re.search(r"Fat:\s*([\d.]+)", description)
        if fat_match:
            result["fat"] = float(fat_match.group(1))

        return result

    async def find_food_by_barcode(self, barcode: str, region: str = "US") -> Optional[str]:
        """
        Find a food_id by barcode.

        Args:
            barcode: The barcode to search for (UPC-A, EAN-13, EAN-8)
            region: Region code (defaults to "US")

        Returns:
            food_id if found, None otherwise
        """
        try:
            # Zero-pad barcode to 13 digits (GTIN-13 format)
            padded_barcode = barcode.zfill(13)
            logger.info(f"Looking up barcode: {barcode} -> padded: {padded_barcode}, region: {region}")

            data = await self._api_request("food.find_id_for_barcode", {
                "barcode": padded_barcode,
                "region": region
            })

            logger.info(f"FatSecret barcode response: {data}")

            food_id_data = data.get("food_id")
            if food_id_data:
                # Handle both formats: {"value": "123"} or just "123"
                if isinstance(food_id_data, dict):
                    food_id = food_id_data.get("value")
                else:
                    food_id = str(food_id_data)
                logger.info(f"Found food_id: {food_id} for barcode: {barcode}")
                return food_id

            # Check for error in response
            error = data.get("error")
            if error:
                logger.warning(f"FatSecret barcode error: {error}")

            logger.info(f"No food found for barcode: {barcode}")
            return None

        except Exception as e:
            logger.error(f"FatSecret barcode lookup error: {e}", exc_info=True)
            return None

    async def get_food_by_barcode(self, barcode: str, region: str = "US") -> Optional[FatSecretFood]:
        """
        Get detailed food information by barcode.
        Combines find_food_by_barcode and get_food into a single call.

        Args:
            barcode: The barcode to search for
            region: Region code (defaults to "US")

        Returns:
            FatSecretFood object if found, None otherwise
        """
        food_id = await self.find_food_by_barcode(barcode, region)
        if not food_id:
            return None
        return await self.get_food(food_id)

    async def get_food(self, food_id: str) -> Optional[FatSecretFood]:
        """
        Get detailed food information including all serving sizes.

        Args:
            food_id: FatSecret food ID

        Returns:
            FatSecretFood object with full details
        """
        try:
            data = await self._api_request("food.get.v4", {
                "food_id": food_id
            })

            food_data = data.get("food", {})
            if not food_data:
                return None

            # Parse servings
            servings_data = food_data.get("servings", {}).get("serving", [])
            if isinstance(servings_data, dict):
                servings_data = [servings_data]

            servings = []
            for s in servings_data:
                servings.append(FatSecretServing(
                    serving_id=s.get("serving_id", ""),
                    serving_description=s.get("serving_description", ""),
                    metric_serving_amount=self._safe_float(s.get("metric_serving_amount")),
                    metric_serving_unit=s.get("metric_serving_unit"),
                    number_of_units=self._safe_float(s.get("number_of_units")),
                    measurement_description=s.get("measurement_description"),
                    calories=self._safe_float(s.get("calories"), 0),
                    protein=self._safe_float(s.get("protein"), 0),
                    carbohydrate=self._safe_float(s.get("carbohydrate"), 0),
                    fat=self._safe_float(s.get("fat"), 0),
                    fiber=self._safe_float(s.get("fiber")),
                    sugar=self._safe_float(s.get("sugar")),
                    sodium=self._safe_float(s.get("sodium")),
                    saturated_fat=self._safe_float(s.get("saturated_fat"))
                ))

            return FatSecretFood(
                food_id=food_data.get("food_id", ""),
                food_name=food_data.get("food_name", ""),
                food_type=food_data.get("food_type", ""),
                brand_name=food_data.get("brand_name"),
                food_description=None,
                servings=servings
            )

        except Exception as e:
            logger.error(f"FatSecret get_food error: {e}")
            return None

    @staticmethod
    def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
        """Safely convert value to float"""
        if value is None:
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default


# Singleton instance - initialized lazily
_fatsecret_service: Optional[FatSecretService] = None


def get_fatsecret_service() -> FatSecretService:
    """Get or create the FatSecret service singleton"""
    global _fatsecret_service

    if _fatsecret_service is None:
        import os
        client_id = os.getenv("FATSECRET_CLIENT_ID")
        client_secret = os.getenv("FATSECRET_CLIENT_SECRET")

        if not client_id or not client_secret:
            raise ValueError(
                "FatSecret credentials not configured. "
                "Set FATSECRET_CLIENT_ID and FATSECRET_CLIENT_SECRET environment variables."
            )

        _fatsecret_service = FatSecretService(client_id, client_secret)

    return _fatsecret_service
