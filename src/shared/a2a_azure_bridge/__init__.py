"""
A2A ↔ Azure AI Agent Service bridge module.

This module handles format conversion between A2A protocol and Azure AI Agent Service.
It keeps A2A protocol code separate from Azure AI Agent code.

The bridge has 4 boundaries:
  1. A2A Request → Azure AI: Extract message/session for runs.create() + poll
  2. Tool handler → A2A Client: Convert tool args to A2A request format
  3. A2A Response → Tool output: Convert downstream AgentResponse to string for Azure AI
  4. Azure AI response → A2A Response: Wrap final response in A2A envelope

Boundaries #1 and #4 are handled by inbound.py.
Boundaries #2 and #3 are handled by outbound.py.
"""

from src.shared.a2a_azure_bridge.inbound import (
    AzureAIInput,
    A2AResponseEnvelope,
    translate_a2a_to_azure,
    translate_azure_to_a2a,
    translate_azure_streaming_chunk,
)
from src.shared.a2a_azure_bridge.outbound import (
    A2AOutboundRequest,
    A2AToolResponse,
    ToolOutput,
    translate_tool_args_to_a2a,
    translate_a2a_to_tool_output,
    translate_a2a_response_to_tool_response,
    create_tool_output,
    create_error_tool_output,
    WORKFLOW_TOOLS,
    UTILITY_TOOLS,
    ALL_TOOLS,
)

__all__ = [
    # Inbound types
    "AzureAIInput",
    "A2AResponseEnvelope",
    # Inbound functions
    "translate_a2a_to_azure",
    "translate_azure_to_a2a",
    "translate_azure_streaming_chunk",
    # Outbound types
    "A2AOutboundRequest",
    "A2AToolResponse",
    "ToolOutput",
    # Outbound functions
    "translate_tool_args_to_a2a",
    "translate_a2a_to_tool_output",
    "translate_a2a_response_to_tool_response",
    "create_tool_output",
    "create_error_tool_output",
    # Outbound constants
    "WORKFLOW_TOOLS",
    "UTILITY_TOOLS",
    "ALL_TOOLS",
]
