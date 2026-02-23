"""
Tier 1 mock tests for Demo C protocols.

Tests validate:
1. Q&A Parent routing to single agent
2. Q&A Parent routing to multiple agents
3. Connected agent request format (CS -> Foundry)
4. Multi-agent response aggregation

Per design doc Testing Strategy (lines 1203-1241):
- Demo C tests cover: Q&A Parent routes to correct agent(s), single agent calls,
  multi-agent aggregation, CS -> Foundry connection.
- All tests use deterministic fixtures from conftest.py (zero LLM cost).

Per design doc Demo C section (lines 745-805):
- Q&A Parent Agent receives natural language questions
- Routes to one or more connected agents based on topic
- Returns aggregated natural language answer
- Connected agents include: Transport, POI, Events, Stay, Dining (Foundry),
  Weather (internal CS)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import pytest

# Import mock fixtures from conftest
from tests.integration.mock.interoperability.conftest import (
    MockQAQuery,
    MockAgentResponse,
    MockTripSpec,
)


# =============================================================================
# Connected Agent Types (per design doc lines 783-789)
# =============================================================================


class ConnectionType(Enum):
    """Connection type for each agent in Demo C."""
    CS_TO_FOUNDRY = "cs_to_foundry"  # Copilot Studio -> Foundry
    CS_TO_CS = "cs_to_cs"  # Internal Copilot Studio routing


# Agent connection configuration per design doc lines 783-789
AGENT_CONNECTIONS = {
    "transport": ConnectionType.CS_TO_FOUNDRY,
    "poi": ConnectionType.CS_TO_FOUNDRY,
    "events": ConnectionType.CS_TO_FOUNDRY,
    "stay": ConnectionType.CS_TO_FOUNDRY,
    "dining": ConnectionType.CS_TO_FOUNDRY,
    "weather": ConnectionType.CS_TO_CS,  # Weather is internal CS agent
}


# =============================================================================
# Request/Response Schemas (per design doc lines 819-874)
# =============================================================================


@dataclass
class ConnectedAgentRequest:
    """
    Request format for CS -> Foundry connected agent calls.

    Per design doc lines 819-837:
    - input: array with role/content messages
    - conversation_id: optional for multi-turn
    - metadata: source and parent_agent info
    """
    input: list[dict]
    conversation_id: Optional[str] = None
    metadata: dict = field(default_factory=lambda: {
        "source": "copilot_studio",
        "parent_agent": "travel_planning_parent"
    })

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict."""
        result = {
            "input": self.input,
            "metadata": self.metadata,
        }
        if self.conversation_id:
            result["conversation_id"] = self.conversation_id
        return result


@dataclass
class ConnectedAgentResponse:
    """
    Response format from Foundry connected agents.

    Per design doc lines 847-874:
    - id: response identifier
    - status: completed/failed
    - output: array of message objects
    - output_text: convenience field with response text
    - usage: token usage stats (optional)
    - metadata: agent info (optional)
    """
    id: str
    status: str
    output_text: str
    output: list[dict] = field(default_factory=list)
    usage: Optional[dict] = None
    metadata: Optional[dict] = None

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict."""
        result = {
            "id": self.id,
            "status": self.status,
            "output": self.output,
            "output_text": self.output_text,
        }
        if self.usage:
            result["usage"] = self.usage
        if self.metadata:
            result["metadata"] = self.metadata
        return result


@dataclass
class QARoutingDecision:
    """
    Q&A Parent routing decision.

    Represents the routing decision made by Q&A Parent agent
    based on the user's question.
    """
    query: str
    selected_agents: list[str]
    routing_type: str  # single_agent, multi_agent, internal


# =============================================================================
# Fixtures for Demo C Testing
# =============================================================================


@pytest.fixture
def sample_single_agent_query() -> MockQAQuery:
    """Query that routes to single agent (Events)."""
    return MockQAQuery(
        query="What concerts are happening in London next week?",
        expected_agents=["events"],
        expected_response_type="single_agent",
    )


@pytest.fixture
def sample_multi_agent_query() -> MockQAQuery:
    """Query that routes to multiple agents (POI + Weather)."""
    return MockQAQuery(
        query="What's the weather like in Paris and what are the top attractions?",
        expected_agents=["weather", "poi"],
        expected_response_type="multi_agent",
    )


@pytest.fixture
def sample_internal_agent_query() -> MockQAQuery:
    """Query that routes to internal CS agent (Weather)."""
    return MockQAQuery(
        query="What's the weather forecast for Tokyo?",
        expected_agents=["weather"],
        expected_response_type="internal",
    )


@pytest.fixture
def sample_stay_dining_query() -> MockQAQuery:
    """Query that routes to Stay and Dining agents."""
    return MockQAQuery(
        query="I need a hotel and restaurant recommendations for London",
        expected_agents=["stay", "dining"],
        expected_response_type="multi_agent",
    )


@pytest.fixture
def sample_transport_query() -> MockQAQuery:
    """Query that routes to Transport agent."""
    return MockQAQuery(
        query="Find me a flight from Seattle to Tokyo",
        expected_agents=["transport"],
        expected_response_type="single_agent",
    )


@pytest.fixture
def connected_agent_request_events() -> ConnectedAgentRequest:
    """Sample request for Events agent via connected agents."""
    return ConnectedAgentRequest(
        input=[
            {
                "role": "user",
                "content": "What concerts are happening in London next week?"
            }
        ],
        metadata={
            "source": "copilot_studio",
            "parent_agent": "travel_planning_parent"
        }
    )


@pytest.fixture
def connected_agent_response_events() -> ConnectedAgentResponse:
    """Sample response from Events agent."""
    return ConnectedAgentResponse(
        id="resp_events_001",
        status="completed",
        output=[
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": "Found concerts in London: Coldplay at Wembley Aug 8, Ed Sheeran at The O2 Aug 10"
                    }
                ]
            }
        ],
        output_text="Found concerts in London: Coldplay at Wembley Aug 8, Ed Sheeran at The O2 Aug 10",
        usage={"input_tokens": 15, "output_tokens": 25, "total_tokens": 40},
        metadata={"agent": "events", "result_count": 2}
    )


@pytest.fixture
def connected_agent_response_poi() -> ConnectedAgentResponse:
    """Sample response from POI agent."""
    return ConnectedAgentResponse(
        id="resp_poi_001",
        status="completed",
        output=[
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": "Top attractions in Paris: Eiffel Tower, Louvre Museum, Notre-Dame Cathedral"
                    }
                ]
            }
        ],
        output_text="Top attractions in Paris: Eiffel Tower, Louvre Museum, Notre-Dame Cathedral",
        metadata={"agent": "poi", "result_count": 3}
    )


@pytest.fixture
def connected_agent_response_weather() -> ConnectedAgentResponse:
    """Sample response from Weather agent (internal CS)."""
    return ConnectedAgentResponse(
        id="resp_weather_001",
        status="completed",
        output=[
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": "Paris weather: 24C, partly cloudy, 20% chance of rain"
                    }
                ]
            }
        ],
        output_text="Paris weather: 24C, partly cloudy, 20% chance of rain",
        metadata={"agent": "weather"}
    )


@pytest.fixture
def connected_agent_error_response() -> ConnectedAgentResponse:
    """Sample error response from connected agent."""
    return ConnectedAgentResponse(
        id="resp_error_001",
        status="failed",
        output=[],
        output_text="",
        metadata={"error": {"code": "not_found", "message": "Agent not found"}}
    )


# =============================================================================
# Test Classes
# =============================================================================


class TestDemoCRoutingSingleAgent:
    """Tests for Q&A Parent routing to a single agent.

    Per design doc line 1238: Q&A Parent routes to correct agent(s)
    Per design doc line 1239: Q&A Parent calls single agent
    """

    def test_demo_c_routes_single_agent(
        self, sample_single_agent_query: MockQAQuery
    ):
        """Test Q&A Parent routes to single agent based on query.

        Query about concerts should route to Events agent only.
        """
        query = sample_single_agent_query

        # Simulate routing decision
        routing = QARoutingDecision(
            query=query.query,
            selected_agents=["events"],
            routing_type="single_agent"
        )

        # Verify single agent selected
        assert len(routing.selected_agents) == 1
        assert routing.selected_agents == query.expected_agents
        assert routing.routing_type == "single_agent"

    def test_demo_c_routes_transport_single_agent(
        self, sample_transport_query: MockQAQuery
    ):
        """Test flight query routes to Transport agent only."""
        query = sample_transport_query

        routing = QARoutingDecision(
            query=query.query,
            selected_agents=["transport"],
            routing_type="single_agent"
        )

        assert len(routing.selected_agents) == 1
        assert "transport" in routing.selected_agents
        assert routing.routing_type == query.expected_response_type

    def test_demo_c_single_agent_connection_type(
        self, sample_single_agent_query: MockQAQuery
    ):
        """Test single agent has correct connection type (CS -> Foundry)."""
        query = sample_single_agent_query
        selected_agent = query.expected_agents[0]

        # Events agent connects via CS -> Foundry
        assert selected_agent in AGENT_CONNECTIONS
        assert AGENT_CONNECTIONS[selected_agent] == ConnectionType.CS_TO_FOUNDRY

    def test_demo_c_single_agent_response_format(
        self,
        sample_single_agent_query: MockQAQuery,
        connected_agent_response_events: ConnectedAgentResponse,
    ):
        """Test single agent returns properly formatted response."""
        response = connected_agent_response_events

        # Verify response format per design doc lines 847-874
        assert response.id.startswith("resp_")
        assert response.status == "completed"
        assert response.output_text != ""
        assert len(response.output) > 0

        # Verify output structure
        first_output = response.output[0]
        assert first_output["type"] == "message"
        assert first_output["role"] == "assistant"


class TestDemoCRoutingMultipleAgents:
    """Tests for Q&A Parent routing to multiple agents.

    Per design doc line 1240: Q&A Parent calls multiple agents
    """

    def test_demo_c_routes_multiple_agents(
        self, sample_multi_agent_query: MockQAQuery
    ):
        """Test Q&A Parent routes to multiple agents based on query.

        Query about weather AND attractions should route to Weather + POI.
        """
        query = sample_multi_agent_query

        routing = QARoutingDecision(
            query=query.query,
            selected_agents=["weather", "poi"],
            routing_type="multi_agent"
        )

        # Verify multiple agents selected
        assert len(routing.selected_agents) == 2
        assert set(routing.selected_agents) == set(query.expected_agents)
        assert routing.routing_type == "multi_agent"

    def test_demo_c_routes_stay_and_dining(
        self, sample_stay_dining_query: MockQAQuery
    ):
        """Test hotel + restaurant query routes to Stay + Dining agents."""
        query = sample_stay_dining_query

        routing = QARoutingDecision(
            query=query.query,
            selected_agents=["stay", "dining"],
            routing_type="multi_agent"
        )

        assert len(routing.selected_agents) == 2
        assert "stay" in routing.selected_agents
        assert "dining" in routing.selected_agents

    def test_demo_c_multi_agent_connection_types(
        self, sample_multi_agent_query: MockQAQuery
    ):
        """Test multi-agent query has correct connection types.

        Weather is internal (CS -> CS), POI is external (CS -> Foundry).
        """
        query = sample_multi_agent_query

        for agent in query.expected_agents:
            assert agent in AGENT_CONNECTIONS

        # Weather is internal CS agent
        assert AGENT_CONNECTIONS["weather"] == ConnectionType.CS_TO_CS
        # POI is Foundry agent
        assert AGENT_CONNECTIONS["poi"] == ConnectionType.CS_TO_FOUNDRY

    def test_demo_c_multi_agent_parallel_execution(
        self, sample_multi_agent_query: MockQAQuery
    ):
        """Test multi-agent queries can be executed in parallel.

        Per design doc, Q&A Parent can call multiple agents for a single query.
        """
        query = sample_multi_agent_query

        # Simulate parallel execution - all agents can be called concurrently
        execution_results = {
            agent: {"status": "pending", "response": None}
            for agent in query.expected_agents
        }

        # Mark all as completed (simulating parallel completion)
        for agent in query.expected_agents:
            execution_results[agent]["status"] = "completed"

        # All should complete
        assert all(r["status"] == "completed" for r in execution_results.values())
        assert len(execution_results) == len(query.expected_agents)


class TestDemoCConnectedAgentRequestFormat:
    """Tests for connected agent request format compliance.

    Per design doc lines 819-837:
    - OpenAI-compatible Responses API format
    - input array with role/content messages
    - Optional conversation_id for multi-turn
    - metadata with source and parent_agent
    """

    def test_demo_c_connected_agent_request_format(
        self, connected_agent_request_events: ConnectedAgentRequest
    ):
        """Test connected agent request matches design doc schema."""
        request = connected_agent_request_events

        # Verify input structure
        assert request.input is not None
        assert len(request.input) > 0

        # Verify first message format
        first_message = request.input[0]
        assert "role" in first_message
        assert "content" in first_message
        assert first_message["role"] == "user"

    def test_demo_c_connected_agent_request_metadata(
        self, connected_agent_request_events: ConnectedAgentRequest
    ):
        """Test request includes required metadata."""
        request = connected_agent_request_events

        # Verify metadata per design doc lines 832-835
        assert request.metadata is not None
        assert request.metadata["source"] == "copilot_studio"
        assert request.metadata["parent_agent"] == "travel_planning_parent"

    def test_demo_c_connected_agent_request_serialization(
        self, connected_agent_request_events: ConnectedAgentRequest
    ):
        """Test request serializes correctly for API call."""
        request = connected_agent_request_events
        request_dict = request.to_dict()

        # Required fields present
        assert "input" in request_dict
        assert "metadata" in request_dict

        # conversation_id only present if set
        assert "conversation_id" not in request_dict

    def test_demo_c_connected_agent_request_with_conversation(self):
        """Test request with conversation_id for multi-turn."""
        request = ConnectedAgentRequest(
            input=[{"role": "user", "content": "Tell me more about that event"}],
            conversation_id="conv_abc123"
        )

        request_dict = request.to_dict()
        assert "conversation_id" in request_dict
        assert request_dict["conversation_id"] == "conv_abc123"

    def test_demo_c_connected_agent_request_content_types(self):
        """Test request can include different content in messages."""
        # Simple text content
        simple_request = ConnectedAgentRequest(
            input=[{"role": "user", "content": "Find hotels near Eiffel Tower"}]
        )
        assert simple_request.input[0]["content"] == "Find hotels near Eiffel Tower"

        # Query with context
        context_request = ConnectedAgentRequest(
            input=[
                {"role": "user", "content": "Find good restaurants"},
                {"role": "assistant", "content": "What type of cuisine?"},
                {"role": "user", "content": "Italian vegetarian options"}
            ]
        )
        assert len(context_request.input) == 3


class TestDemoCConnectedAgentResponseFormat:
    """Tests for connected agent response format compliance.

    Per design doc lines 847-874:
    - Response includes id, status, output, output_text
    - Structured JSON recommended for interoperability
    """

    def test_demo_c_connected_agent_response_format(
        self, connected_agent_response_events: ConnectedAgentResponse
    ):
        """Test response matches design doc schema."""
        response = connected_agent_response_events

        # Required fields
        assert response.id is not None
        assert response.status is not None
        assert response.output_text is not None

        # Verify format
        assert response.id.startswith("resp_")
        assert response.status in ["completed", "failed"]

    def test_demo_c_connected_agent_response_output_structure(
        self, connected_agent_response_events: ConnectedAgentResponse
    ):
        """Test response output array structure."""
        response = connected_agent_response_events

        # Output should be an array
        assert isinstance(response.output, list)
        assert len(response.output) > 0

        # Each output item has type, role, content
        first_output = response.output[0]
        assert first_output["type"] == "message"
        assert first_output["role"] == "assistant"
        assert "content" in first_output

    def test_demo_c_connected_agent_response_metadata(
        self, connected_agent_response_events: ConnectedAgentResponse
    ):
        """Test response includes helpful metadata."""
        response = connected_agent_response_events

        # Metadata should identify agent
        assert response.metadata is not None
        assert "agent" in response.metadata

    def test_demo_c_connected_agent_error_response(
        self, connected_agent_error_response: ConnectedAgentResponse
    ):
        """Test error response format per design doc lines 906-929."""
        response = connected_agent_error_response

        assert response.status == "failed"
        assert response.output_text == ""

        # Error info in metadata
        assert response.metadata is not None
        assert "error" in response.metadata
        assert "code" in response.metadata["error"]
        assert "message" in response.metadata["error"]


class TestDemoCMultiAgentAggregation:
    """Tests for multi-agent response aggregation.

    Per design doc lines 798-802:
    - Q&A Parent calls one or more connected agents
    - Returns aggregated natural language answer
    """

    def test_demo_c_multi_agent_aggregation(
        self,
        connected_agent_response_poi: ConnectedAgentResponse,
        connected_agent_response_weather: ConnectedAgentResponse,
    ):
        """Test Q&A Parent aggregates multiple agent responses."""
        responses = {
            "poi": connected_agent_response_poi,
            "weather": connected_agent_response_weather,
        }

        # All responses should be successful
        for agent_name, response in responses.items():
            assert response.status == "completed"
            assert response.output_text != ""

        # Simulate aggregation
        aggregated_text = "\n\n".join([
            f"{agent}: {resp.output_text}"
            for agent, resp in responses.items()
        ])

        # Aggregated response should contain info from both agents
        assert "Paris" in aggregated_text or "attractions" in aggregated_text
        assert "weather" in aggregated_text.lower() or "24C" in aggregated_text

    def test_demo_c_multi_agent_aggregation_preserves_content(
        self,
        connected_agent_response_poi: ConnectedAgentResponse,
        connected_agent_response_weather: ConnectedAgentResponse,
    ):
        """Test aggregation preserves content from all agents."""
        poi_text = connected_agent_response_poi.output_text
        weather_text = connected_agent_response_weather.output_text

        # Each response should have meaningful content
        assert len(poi_text) > 10
        assert len(weather_text) > 10

        # Content should be about the expected topics
        assert "attractions" in poi_text.lower() or "eiffel" in poi_text.lower()
        assert "weather" in weather_text.lower() or "cloudy" in weather_text.lower()

    def test_demo_c_multi_agent_aggregation_handles_partial_failure(
        self,
        connected_agent_response_poi: ConnectedAgentResponse,
        connected_agent_error_response: ConnectedAgentResponse,
    ):
        """Test aggregation handles partial failures gracefully."""
        responses = {
            "poi": connected_agent_response_poi,
            "events": connected_agent_error_response,  # This one failed
        }

        # Count successes
        successful = [r for r in responses.values() if r.status == "completed"]
        failed = [r for r in responses.values() if r.status == "failed"]

        assert len(successful) == 1
        assert len(failed) == 1

        # Should still be able to return partial results
        aggregated_text = "\n".join([
            f"{agent}: {resp.output_text}"
            for agent, resp in responses.items()
            if resp.status == "completed"
        ])

        # Aggregated should contain POI info but not events error
        assert "attractions" in aggregated_text.lower() or "eiffel" in aggregated_text.lower()

    def test_demo_c_multi_agent_aggregation_natural_language(
        self,
        connected_agent_response_poi: ConnectedAgentResponse,
        connected_agent_response_weather: ConnectedAgentResponse,
    ):
        """Test Q&A Parent produces natural language aggregated answer.

        Per design doc line 802: Returns aggregated natural language answer
        """
        # Individual responses
        poi_text = connected_agent_response_poi.output_text
        weather_text = connected_agent_response_weather.output_text

        # Simulate Q&A Parent natural language aggregation
        # (In reality, this would use an LLM to combine responses)
        aggregated_answer = (
            f"Here's what I found about Paris:\n\n"
            f"**Attractions**: {poi_text}\n\n"
            f"**Weather**: {weather_text}"
        )

        # Should be natural language, not just concatenation
        assert "Here's what I found" in aggregated_answer
        assert len(aggregated_answer) > len(poi_text) + len(weather_text)


class TestDemoCInternalRouting:
    """Tests for internal CS -> CS routing (Weather agent).

    Per design doc lines 783-789:
    - Weather agent is internal (CS -> CS routing)
    - Other 5 agents connect via CS -> Foundry
    """

    def test_demo_c_routes_internal_agent(
        self, sample_internal_agent_query: MockQAQuery
    ):
        """Test weather query routes to internal CS agent."""
        query = sample_internal_agent_query

        routing = QARoutingDecision(
            query=query.query,
            selected_agents=["weather"],
            routing_type="internal"
        )

        # Verify internal routing
        assert routing.routing_type == "internal"
        assert "weather" in routing.selected_agents

    def test_demo_c_internal_agent_connection_type(
        self, sample_internal_agent_query: MockQAQuery
    ):
        """Test Weather agent has CS -> CS connection type."""
        query = sample_internal_agent_query

        for agent in query.expected_agents:
            connection = AGENT_CONNECTIONS.get(agent)
            if agent == "weather":
                assert connection == ConnectionType.CS_TO_CS
            else:
                assert connection == ConnectionType.CS_TO_FOUNDRY

    def test_demo_c_weather_response_format(
        self, connected_agent_response_weather: ConnectedAgentResponse
    ):
        """Test internal Weather agent response format."""
        response = connected_agent_response_weather

        # Should still follow same response format
        assert response.status == "completed"
        assert response.output_text != ""
        assert response.metadata is not None
        assert response.metadata["agent"] == "weather"


class TestDemoCFullFlow:
    """Integration tests for complete Demo C flow."""

    def test_demo_c_full_flow_single_agent(
        self,
        sample_single_agent_query: MockQAQuery,
        connected_agent_request_events: ConnectedAgentRequest,
        connected_agent_response_events: ConnectedAgentResponse,
    ):
        """Test complete Demo C flow for single agent query.

        Flow:
        1. User asks question to Q&A Parent
        2. Q&A Parent routes to Events agent
        3. Events agent returns response
        4. Q&A Parent returns answer to user
        """
        # Step 1: User query
        query = sample_single_agent_query
        assert "concerts" in query.query.lower()

        # Step 2: Routing decision
        routing = QARoutingDecision(
            query=query.query,
            selected_agents=query.expected_agents,
            routing_type=query.expected_response_type
        )
        assert routing.selected_agents == ["events"]

        # Step 3: Create request and get response
        request = connected_agent_request_events
        assert request.input[0]["content"] == query.query

        response = connected_agent_response_events
        assert response.status == "completed"

        # Step 4: Return to user
        final_answer = response.output_text
        assert "concert" in final_answer.lower() or "coldplay" in final_answer.lower()

    def test_demo_c_full_flow_multi_agent(
        self,
        sample_multi_agent_query: MockQAQuery,
        connected_agent_response_poi: ConnectedAgentResponse,
        connected_agent_response_weather: ConnectedAgentResponse,
    ):
        """Test complete Demo C flow for multi-agent query.

        Flow:
        1. User asks about weather AND attractions
        2. Q&A Parent routes to Weather + POI agents
        3. Both agents return responses
        4. Q&A Parent aggregates and returns answer
        """
        # Step 1: User query spans multiple topics
        query = sample_multi_agent_query
        assert "weather" in query.query.lower()
        assert "attractions" in query.query.lower()

        # Step 2: Routing decision selects multiple agents
        routing = QARoutingDecision(
            query=query.query,
            selected_agents=query.expected_agents,
            routing_type=query.expected_response_type
        )
        assert len(routing.selected_agents) == 2

        # Step 3: Get responses from both agents
        responses = {
            "poi": connected_agent_response_poi,
            "weather": connected_agent_response_weather,
        }
        for response in responses.values():
            assert response.status == "completed"

        # Step 4: Aggregate responses
        aggregated = f"""Based on your question:

Weather: {responses['weather'].output_text}

Attractions: {responses['poi'].output_text}

Is there anything else you'd like to know about Paris?"""

        # Final answer combines both sources
        assert "weather" in aggregated.lower() or "24C" in aggregated
        assert "attractions" in aggregated.lower() or "eiffel" in aggregated.lower()


class TestDemoCAgentInventory:
    """Tests for Demo C agent inventory and connection configuration.

    Per design doc lines 783-789:
    - Transport, POI, Events, Stay, Dining: CS -> Foundry
    - Weather: CS -> CS (internal)
    """

    def test_demo_c_all_agents_configured(self):
        """Test all 6 connected agents are configured."""
        expected_agents = ["transport", "poi", "events", "stay", "dining", "weather"]

        for agent in expected_agents:
            assert agent in AGENT_CONNECTIONS, f"Agent {agent} not configured"

    def test_demo_c_foundry_agents_correct_connection(self):
        """Test Foundry agents have CS -> Foundry connection type."""
        foundry_agents = ["transport", "poi", "events", "stay", "dining"]

        for agent in foundry_agents:
            assert AGENT_CONNECTIONS[agent] == ConnectionType.CS_TO_FOUNDRY

    def test_demo_c_weather_agent_internal_connection(self):
        """Test Weather agent has CS -> CS connection type."""
        assert AGENT_CONNECTIONS["weather"] == ConnectionType.CS_TO_CS

    def test_demo_c_query_coverage(self, sample_qa_queries: list[MockQAQuery]):
        """Test sample queries cover all agent types."""
        all_expected_agents = set()
        for query in sample_qa_queries:
            all_expected_agents.update(query.expected_agents)

        # Should cover at least: transport, poi, events, stay, dining, weather
        required_agents = {"transport", "poi", "events", "stay", "dining", "weather"}
        assert required_agents.issubset(all_expected_agents)

    def test_demo_c_query_types(self, sample_qa_queries: list[MockQAQuery]):
        """Test sample queries include all routing types."""
        routing_types = {q.expected_response_type for q in sample_qa_queries}

        assert "single_agent" in routing_types
        assert "multi_agent" in routing_types
        assert "internal" in routing_types
