FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY interoperability/foundry/agents/weather/weather_proxy_m365_agent_sdk_client_credentials_flow/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the interoperability module
COPY interoperability/ interoperability/

# Copy the source shared models (for WeatherResponse schema)
COPY src/ src/

# Copy the main entry point
COPY interoperability/foundry/agents/weather/weather_proxy_m365_agent_sdk_client_credentials_flow/main.py main.py

# Set Python path to include the project root
ENV PYTHONPATH=/app

# Expose the agent server port
EXPOSE 8088

# Run the agent server
CMD ["python", "main.py"]
