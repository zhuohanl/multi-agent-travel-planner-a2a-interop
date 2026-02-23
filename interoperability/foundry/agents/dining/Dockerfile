# Dining Agent Dockerfile - LangGraph Hosted Agent
#
# Build: docker build -t dining-agent:latest .
# Run locally: docker run -p 8088:8088 dining-agent:latest
# Test: curl -X POST http://localhost:8088/responses -H "Content-Type: application/json" \
#       -d '{"input": {"messages": [{"role": "user", "content": "Find restaurants in Tokyo"}]}}'
#
# Design doc references:
# - Appendix A.2 lines 1527-1646: Hosted Agents patterns
# - Security notes: Don't put secrets in images, use managed identities

FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY interoperability/foundry/agents/dining/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the interoperability module
COPY interoperability/ interoperability/

# Copy the source agent logic (wrap, don't rewrite)
COPY src/ src/

# Copy the main entry point
COPY interoperability/foundry/agents/dining/main.py main.py

# Set Python path to include the project root
ENV PYTHONPATH=/app

# Expose the agent server port
EXPOSE 8088

# Run the agent server
CMD ["python", "main.py"]
