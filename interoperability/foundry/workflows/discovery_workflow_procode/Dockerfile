# Discovery Workflow (Pro-Code) Dockerfile - Hosted Workflow Agent
#
# Build: docker build -t discovery-workflow:latest -f interoperability/foundry/workflows/discovery_workflow_procode/Dockerfile .
# Run locally: docker run -p 8088:8088 --env-file .env discovery-workflow:latest
# Test: curl -X POST http://localhost:8088/responses -H "Content-Type: application/json" \
#       -d '{"input": {"messages": [{"role": "user", "content": "{\"destination\": \"Paris\"}"}]}}'
#
# Design doc references:
# - Development Workflow (Portal-First Approach) lines 509-552
# - CI/CD Reference Pattern lines 1255-1354
#
# Prerequisites:
# - Azure CLI logged in or managed identity configured
# - COPILOTSTUDIOAGENT__* env vars set for Weather Proxy integration
# - PROJECT_ENDPOINT env var set for Foundry agent invocation

FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY interoperability/foundry/workflows/discovery_workflow_procode/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the interoperability module
COPY interoperability/ interoperability/

# Copy the source agent logic (wrap, don't rewrite)
COPY src/ src/

# Set Python path to include the project root
ENV PYTHONPATH=/app

# Expose the agent server port
EXPOSE 8088

# Run the workflow agent server
CMD ["python", "-m", "interoperability.foundry.workflows.discovery_workflow_procode.main"]
