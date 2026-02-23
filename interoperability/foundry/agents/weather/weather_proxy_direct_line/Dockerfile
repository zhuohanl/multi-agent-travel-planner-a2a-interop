# Weather Proxy Dockerfile - Hosted Agent for Copilot Studio integration
#
# Build: docker build -t weather-proxy:latest .
# Run locally: docker run -p 8088:8088 --env-file .env weather-proxy:latest
# Test: curl -X POST http://localhost:8088/responses -H "Content-Type: application/json" \
#       -d '{"input": {"messages": [{"role": "user", "content": "Get weather for location: Paris, France, start_date: 2025-06-15, end_date: 2025-06-20"}]}}'
#
# Design doc references:
# - INTEROP-011B Implementation Details (lines 2425-2453)
# - Security notes: Don't put secrets in images, use managed identities

FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY interoperability/foundry/agents/weather/weather_proxy_direct_line/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the interoperability module
COPY interoperability/ interoperability/

# Copy the source shared models (for WeatherResponse schema)
COPY src/ src/

# Copy the main entry point
COPY interoperability/foundry/agents/weather/weather_proxy_direct_line/main.py main.py

# Set Python path to include the project root
ENV PYTHONPATH=/app

# Expose the agent server port
EXPOSE 8088

# Run the agent server
CMD ["python", "main.py"]
