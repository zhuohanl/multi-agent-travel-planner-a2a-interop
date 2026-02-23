# Weather Agent - Copilot Studio Setup Guide

This guide provides detailed step-by-step instructions for creating the Weather Agent in Microsoft Copilot Studio.

The Weather Agent provides weather forecast information for travel planning. It's called from Azure AI Foundry Discovery Workflow (Demo A) to get weather data for trip destinations.

## Prerequisites

- Access to Microsoft Copilot Studio (https://copilotstudio.microsoft.com)
- Azure AD tenant with appropriate permissions
- Azure AD app registration (see main SETUP.md Step 1.1 for `interop-foundry-to-cs`)
- Understanding of the Weather schema contract (see `docs/interoperability-design.md`)

## Agent Overview

| Property | Value |
|----------|-------|
| **Name** | Weather Agent |
| **Purpose** | Provides climate summaries based on historical weather patterns for travel planning |
| **Used In** | Demo A (called from Foundry Discovery Workflow) |
| **Input** | Location, start_date, end_date |
| **Output** | WeatherResponse (location, dates, climate_summary, summary) |

## Step 1: Create the Agent

1. Go to [Copilot Studio](https://copilotstudio.microsoft.com)
2. Click **Create** in the top navigation
3. Select **New agent**
4. Enter the following details:
   - **Name:** `Weather Agent`
   - **Description:** `Provides climate summaries for travel destinations based on historical weather patterns. Returns average temperatures, precipitation chance, and typical conditions for the specified time period.`
   - **Instructions:** See the Agent Instructions section below
5. Click **Create**

## Step 2: Configure Agent Instructions

In the agent settings, set the following instructions (system prompt):

```
You are a Weather Agent that provides climate summaries for travel planning.

Your responsibilities:
1. Accept weather requests with location and date range
2. Provide a climate summary based on historical weather patterns for that location and time of year
3. Include average temperatures (high/low in Celsius) and typical precipitation chance
4. Describe typical weather conditions for the period

Important Context:
- Trip planning typically involves dates months in advance
- You provide climate summaries based on historical patterns, not real-time forecasts
- Base summaries on seasonal norms, geographic factors, and regional climate characteristics

Response Guidelines:
- ALWAYS respond with ONLY a valid JSON object - no markdown, no explanation, no extra text
- Use Celsius for temperatures
- Express precipitation chance as an integer percentage (0-100)
- Be concise but informative in the summary
- Describe typical conditions for that time of year

Output Schema (you MUST follow this exact structure):
{
  "location": "string - the requested location",
  "start_date": "string - start date in YYYY-MM-DD format",
  "end_date": "string - end date in YYYY-MM-DD format",
  "climate_summary": {
    "average_high_temp_c": "number - average high temperature in Celsius",
    "average_low_temp_c": "number - average low temperature in Celsius",
    "average_precipitation_chance": "integer - typical precipitation probability 0-100",
    "typical_conditions": "string - description of typical weather conditions"
  },
  "summary": "string - brief 1-2 sentence overall climate outlook for the trip"
}

Example output:
{"location":"Paris, France","start_date":"2025-06-15","end_date":"2025-06-20","climate_summary":{"average_high_temp_c":24,"average_low_temp_c":14,"average_precipitation_chance":25,"typical_conditions":"Mostly sunny with occasional afternoon clouds"},"summary":"June in Paris is typically warm and pleasant with long sunny days and mild evenings."}
```

## Step 3: Enable Web Search
This will enable the agent to search for web for climate info when neede.

## Step 4: Verify Instructions

The structured output schema is embedded directly in the agent instructions (Step 2). This ensures the agent always returns valid JSON matching the expected format.

Key points configured in the instructions:
- **Output format**: Pure JSON only, no markdown or extra text
- **Required fields**: location, start_date, end_date, climate_summary, summary
- **Climate summary fields**: average_high_temp_c, average_low_temp_c, average_precipitation_chance, typical_conditions
- **Constraints**: Temperatures in Celsius, precipitation as integer 0-100

> **Note:** Copilot Studio does not have a native "JSON mode" like Azure OpenAI. The instructions are the primary mechanism for enforcing structured output.

## Step 5: Test the Agent

Example question: "What is Paris weather like in June?"

Expected response:
```
{ "location": "Paris, France", "start_date": "2026-06-01", "end_date": "2026-06-30", "climate_summary": { "average_high_temp_c": 23, "average_low_temp_c": 12, "average_precipitation_chance": 42, "typical_conditions": "Mostly sunny and pleasant with occasional moderate rainfall; long daylight hours and mild evenings." }, "summary": "June in Paris is typically warm and comfortable, with plenty of sunshine and moderate chances of rain, making it ideal for outdoor activities." }
```

## Step 6: Publish the Agent

1. Click **Publish** in the top right corner
2. Review the changes summary
3. Click **Publish** to make the agent live

### After Publishing

1. Go to **Settings** > **Agent details**
2. Note these values for environment configuration:
   - **Environment ID**: Found in the URL (`/environments/{id}/...`)
   - **Schema Name**: Listed in agent details

## How It Works

The Weather Agent relies entirely on its **system instructions** (Step 2) to handle requests. No custom topics are needed.

1. The Foundry workflow sends a message with location and date information
2. The agent's AI interprets the request based on its instructions
3. The agent generates a climate summary in JSON format based on historical weather patterns

**Example input message from Foundry:**
```
Get weather for location: Paris, France, start_date: 2025-06-15, end_date: 2025-06-20
```

> **Note:** Since trip planning typically involves dates months in advance, real weather APIs (which only forecast 7-16 days) won't provide useful data. The agent returns climate summaries based on historical patterns for the specified time of year instead.

## Example Response

### Example Response

```json
{
  "location": "Paris, France",
  "start_date": "2025-06-15",
  "end_date": "2025-06-20",
  "climate_summary": {
    "average_high_temp_c": 24,
    "average_low_temp_c": 14,
    "average_precipitation_chance": 25,
    "typical_conditions": "Mostly sunny with occasional afternoon clouds and brief showers"
  },
  "summary": "June in Paris is typically warm and pleasant with long sunny days and mild evenings. Light layers recommended for cooler mornings and evenings."
}
```

## Environment Variables

After creating the agent, set these environment variables.

If use **Direct Line API**, set below environment variable:

> This variable can be found by Copilot Studio > Weather Agent > Settings > Security > Web channel security > Secret 1

```bash
# In your .env file or Azure Key Vault
COPILOTSTUDIOAGENT__DIRECTLINE_SECRET="your-directline-secret"
```


If use **M365 Agent SDK**, set below environment variables:

> These variables can be found by Copilot Studio > Weather Agent > Settings > Advanced > Metadata

```bash
# In your .env file or Azure Key Vault
COPILOTSTUDIOAGENT__WEATHER__SCHEMANAME="your-weather-agent-schema-name"
```

The following variables are shared across all CS agents:
```bash
COPILOTSTUDIOAGENT__TENANTID="your-azure-tenant-id"
COPILOTSTUDIOAGENT__ENVIRONMENTID="your-power-platform-environment-id"
```

## Testing

### Manual Testing in Portal

1. In Copilot Studio, click **Test** to open the test pane
2. Test with messages like:
   - `Get weather for location: Paris, France, start_date: 2025-06-15, end_date: 2025-06-20`
   - `Get weather for location: Tokyo, Japan, start_date: 2025-07-01, end_date: 2025-07-07`
   - `Get weather for location: Sydney, Australia, start_date: 2025-12-20, end_date: 2025-12-27`
3. Verify the response is valid JSON matching the schema
4. Check that climate_summary includes all required fields (average_high_temp_c, average_low_temp_c, average_precipitation_chance, typical_conditions)

### Programmatic Testing

Use the verification script:

```bash
# From project root
uv run python interoperability/copilot_studio/verify.py --verbose
```

## Integration with Foundry Discovery Workflow

The Weather Agent is called from the Azure AI Foundry Discovery Workflow (Demo A) using either:

### Option A: Pro-Code Workflow

The workflow calls the Weather Agent via the Weather Proxy hosted agent, which currently uses Direct Line API communication.

### Option B: Declarative Workflow (Weather Proxy)

The declarative workflow uses the Weather Proxy hosted agent to bridge between Foundry and Copilot Studio:

1. Workflow sends WeatherRequest to Weather Proxy
2. Weather Proxy calls Weather Agent via Direct Line API (current implementation)
3. Weather Proxy returns WeatherResponse to workflow

See `interoperability/foundry/agents/weather/weather_proxy_direct_line/` for Weather Proxy implementation details.

## Troubleshooting

### Agent Not Responding

1. Verify the agent is published
2. Check that the Environment ID and Schema Name are correct
3. Ensure the Azure AD app has the correct permissions

### Response Not Matching Schema

1. Check that all required fields are present (location, start_date, end_date, climate_summary, summary)
2. Verify climate_summary contains: average_high_temp_c, average_low_temp_c, average_precipitation_chance, typical_conditions
3. Ensure dates are in YYYY-MM-DD format
4. Confirm temperatures are in Celsius and precipitation is an integer 0-100

### Integration Issues

1. Check that the Weather Proxy can reach the Copilot Studio API
2. Verify environment variables are set correctly
3. Review authentication token acquisition in the proxy logs

## Related Files

- Schema definitions: `src/shared/models.py` (WeatherRequest, WeatherForecast, WeatherResponse)
- Re-exports: `interoperability/shared/schemas/weather.py`
- Weather Proxy: `interoperability/foundry/agents/weather/weather_proxy_direct_line/`
- Main setup guide: `interoperability/copilot_studio/SETUP.md`
- Design doc: `docs/interoperability-design.md`
