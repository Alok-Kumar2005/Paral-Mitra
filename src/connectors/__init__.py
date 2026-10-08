"""External service connectors (NASA FIRMS, Open-Meteo, Nominatim Geocoding)."""

from src.connectors.firms import (
    FirmsApiError,
    FirmsAuthError,
    FirmsClient,
    FirmsError,
    parse_firms_csv,
)
from src.connectors.geocode import (
    GeocodeResult,
    Geocoder,
    GeocodingError,
    NominatimApiError,
    parse_nominatim_results,
)
from src.connectors.ingest_fires import ingest_active_fires
from src.connectors.weather import (
    WeatherApiError,
    WeatherClient,
    WeatherError,
    parse_open_meteo_response,
)

__all__ = [
    "FirmsClient",
    "FirmsError",
    "FirmsAuthError",
    "FirmsApiError",
    "parse_firms_csv",
    "WeatherClient",
    "WeatherError",
    "WeatherApiError",
    "parse_open_meteo_response",
    "Geocoder",
    "GeocodeResult",
    "GeocodingError",
    "NominatimApiError",
    "parse_nominatim_results",
    "ingest_active_fires",
]
