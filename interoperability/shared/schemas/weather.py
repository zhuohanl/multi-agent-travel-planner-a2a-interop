"""Weather schemas for cross-platform interoperability.

Re-exports WeatherRequest, ClimateSummary, WeatherResponse from src/shared/models.py
for use by interoperability modules (Weather Proxy, mock tests, etc.).

These schemas define the contract between:
- Foundry Discovery Workflow (consumer)
- Copilot Studio Weather Agent (provider)

See interoperability/copilot_studio/agents/weather/README.md for schema details.
"""

from src.shared.models import WeatherRequest, ClimateSummary, WeatherResponse

__all__ = ["WeatherRequest", "ClimateSummary", "WeatherResponse"]
