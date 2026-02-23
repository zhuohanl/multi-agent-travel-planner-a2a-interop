"""
Mock fixtures for A2A protocol testing.

These tests verify format correctness without LLM costs.
The mock infrastructure simulates A2A streaming responses.
"""

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


@dataclass
class MockA2AChunk:
    """
    Simulates an A2A streaming response chunk.

    This dataclass represents a single chunk from an A2A streaming response,
    matching the actual A2A protocol format used by agents in this repo.
    """

    context_id: str | None = None
    task_id: str | None = None
    status_state: str = "completed"
    text: str = ""
    is_task: bool = False
    # History injection fields (per design doc Agent Communication section)
    last_seen_seq: int | None = None  # Echoed back for divergence detection

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """
        Convert to A2A response format.

        Returns a dict matching the A2A protocol response structure:
        - result.contextId: Session context identifier
        - result.id + result.kind="task": Task identifier (when is_task=True)
        - result.taskId: Task identifier (when is_task=False)
        - result.status.state: Current task state
        - result.status.message.parts: Message content
        - result.metadata.lastSeenSeq: Echoed sequence number for divergence detection
        """
        result: dict[str, Any] = {}

        if self.context_id:
            result["contextId"] = self.context_id
        if self.task_id:
            if self.is_task:
                result["id"] = self.task_id
                result["kind"] = "task"
            else:
                result["taskId"] = self.task_id

        result["status"] = {
            "state": self.status_state,
            "message": {"parts": [{"kind": "text", "text": self.text}]},
        }

        # History injection response metadata (per design doc)
        if self.last_seen_seq is not None:
            result["metadata"] = {"lastSeenSeq": self.last_seen_seq}

        return {"result": result}


class MockA2AResponseFactory:
    """
    Factory for creating mock A2A responses.

    Provides pre-configured responses for common test scenarios:
    - Clarifier asking questions (input_required)
    - Clarifier completing with TripSpec (completed)
    - Discovery agent results (completed)
    - Agent errors (failed)
    """

    @staticmethod
    def clarifier_asking_destination() -> list[MockA2AChunk]:
        """Clarifier response asking for destination."""
        return [
            MockA2AChunk(
                context_id="ctx_clarifier_001",
                task_id="task_clarifier_001",
                status_state="input_required",
                text="Where would you like to travel to?",
                is_task=True,
            )
        ]

    @staticmethod
    def clarifier_asking_dates() -> list[MockA2AChunk]:
        """Clarifier response asking for travel dates."""
        return [
            MockA2AChunk(
                context_id="ctx_clarifier_001",
                task_id="task_clarifier_001",
                status_state="input_required",
                text="When would you like to travel? Please provide your preferred dates.",
                is_task=True,
            )
        ]

    @staticmethod
    def clarifier_asking_travelers() -> list[MockA2AChunk]:
        """Clarifier response asking for number of travelers."""
        return [
            MockA2AChunk(
                context_id="ctx_clarifier_001",
                task_id="task_clarifier_001",
                status_state="input_required",
                text="How many people will be traveling?",
                is_task=True,
            )
        ]

    @staticmethod
    def clarifier_complete_tripspec() -> list[MockA2AChunk]:
        """Clarifier response with complete TripSpec."""
        return [
            MockA2AChunk(
                context_id="ctx_clarifier_001",
                task_id="task_clarifier_001",
                status_state="completed",
                text='{"destination": "Tokyo", "dates": {"start": "2026-03-10", "end": "2026-03-17"}, "travelers": 2}',
                is_task=True,
            )
        ]

    @staticmethod
    def discovery_agent_results(agent_name: str) -> list[MockA2AChunk]:
        """Discovery agent response with search results."""
        return [
            MockA2AChunk(
                context_id=f"ctx_{agent_name}_001",
                task_id=f"task_{agent_name}_001",
                status_state="completed",
                text=f'{{"agent": "{agent_name}", "results": ["option1", "option2"]}}',
                is_task=True,
            )
        ]

    @staticmethod
    def stay_agent_results() -> list[MockA2AChunk]:
        """Stay agent response with hotel options."""
        return [
            MockA2AChunk(
                context_id="ctx_stay_001",
                task_id="task_stay_001",
                status_state="completed",
                text='{"hotels": [{"name": "Park Hyatt Tokyo", "price": 500}, {"name": "Keio Plaza", "price": 300}]}',
                is_task=True,
            )
        ]

    @staticmethod
    def transport_agent_results() -> list[MockA2AChunk]:
        """Transport agent response with flight options."""
        return [
            MockA2AChunk(
                context_id="ctx_transport_001",
                task_id="task_transport_001",
                status_state="completed",
                text='{"flights": [{"airline": "JAL", "price": 1200}, {"airline": "ANA", "price": 1100}]}',
                is_task=True,
            )
        ]

    @staticmethod
    def booking_agent_confirmation() -> list[MockA2AChunk]:
        """Booking agent confirmation response."""
        return [
            MockA2AChunk(
                context_id="ctx_booking_001",
                task_id="task_booking_001",
                status_state="completed",
                text='{"booking_id": "BK-12345", "status": "confirmed", "confirmation_number": "ABC123"}',
                is_task=True,
            )
        ]

    @staticmethod
    def booking_agent_pending() -> list[MockA2AChunk]:
        """Booking agent pending response (awaiting confirmation)."""
        return [
            MockA2AChunk(
                context_id="ctx_booking_001",
                task_id="task_booking_001",
                status_state="input_required",
                text='{"quote_id": "Q-67890", "quoted_price": 500, "expires_at": "2026-01-22T10:00:00Z"}',
                is_task=True,
            )
        ]

    @staticmethod
    def agent_error(error_message: str) -> list[MockA2AChunk]:
        """Agent error response."""
        return [
            MockA2AChunk(
                status_state="failed",
                text=error_message,
            )
        ]

    @staticmethod
    def agent_timeout() -> list[MockA2AChunk]:
        """Agent timeout response."""
        return [
            MockA2AChunk(
                status_state="failed",
                text="Request timed out after 30 seconds",
            )
        ]

    # ============================================================
    # Utility Tool Responses (per design doc Tool Definitions)
    # ============================================================

    @staticmethod
    def currency_convert_result(
        from_amount: float = 100.0,
        from_currency: str = "USD",
        to_currency: str = "EUR",
        result_amount: float = 92.50,
    ) -> list[MockA2AChunk]:
        """Currency conversion utility response."""
        return [
            MockA2AChunk(
                status_state="completed",
                text=f'{{"from": {{"amount": {from_amount}, "currency": "{from_currency}"}}, "to": {{"amount": {result_amount}, "currency": "{to_currency}"}}}}',
            )
        ]

    @staticmethod
    def weather_lookup_result(
        location: str = "Tokyo",
        temperature_high: int = 18,
        temperature_low: int = 12,
        conditions: str = "partly cloudy",
    ) -> list[MockA2AChunk]:
        """Weather lookup utility response."""
        return [
            MockA2AChunk(
                status_state="completed",
                text=f'{{"location": "{location}", "temperature": {{"high": {temperature_high}, "low": {temperature_low}}}, "conditions": "{conditions}"}}',
            )
        ]

    @staticmethod
    def timezone_info_result(
        location: str = "Tokyo",
        timezone: str = "Asia/Tokyo",
        utc_offset: str = "+09:00",
        current_time: str = "2026-03-10T14:30:00",
    ) -> list[MockA2AChunk]:
        """Timezone info utility response."""
        return [
            MockA2AChunk(
                status_state="completed",
                text=f'{{"location": "{location}", "timezone": "{timezone}", "utcOffset": "{utc_offset}", "currentTime": "{current_time}"}}',
            )
        ]

    @staticmethod
    def get_booking_result(
        booking_id: str = "BK-12345",
        status: str = "confirmed",
        item_type: str = "hotel",
    ) -> list[MockA2AChunk]:
        """Get booking lookup response."""
        return [
            MockA2AChunk(
                status_state="completed",
                text=f'{{"bookingId": "{booking_id}", "status": "{status}", "itemType": "{item_type}", "details": {{"name": "Park Hyatt Tokyo"}}}}',
            )
        ]

    @staticmethod
    def get_consultation_result(
        consultation_id: str = "CONS-67890",
        trip_spec_summary: str = "Tokyo, March 10-17, 2 travelers",
    ) -> list[MockA2AChunk]:
        """Get consultation lookup response."""
        return [
            MockA2AChunk(
                status_state="completed",
                text=f'{{"consultationId": "{consultation_id}", "tripSpecSummary": "{trip_spec_summary}", "itineraryIds": ["IT-001"], "bookingIds": ["BK-12345"]}}',
            )
        ]

    # ============================================================
    # Q&A Mode Responses (per design doc answer_question tool)
    # ============================================================

    @staticmethod
    def qa_mode_response(
        agent_name: str = "stay",
        question: str = "Does the Park Hyatt have a pool?",
        answer: str = "Yes, the Park Hyatt Tokyo has an indoor swimming pool on the 47th floor.",
    ) -> list[MockA2AChunk]:
        """Domain agent Q&A mode response (mode='qa' in request)."""
        return [
            MockA2AChunk(
                context_id=f"ctx_{agent_name}_qa_001",
                task_id=f"task_{agent_name}_qa_001",
                status_state="completed",
                text=f'{{"mode": "qa", "question": "{question}", "answer": "{answer}"}}',
                is_task=True,
            )
        ]

    # ============================================================
    # History Injection Responses (per design doc Agent Communication)
    # ============================================================

    @staticmethod
    def response_with_history_ack(
        context_id: str = "ctx_clarifier_001",
        last_seen_seq: int = 3,
    ) -> list[MockA2AChunk]:
        """Response acknowledging history injection with sequence number."""
        return [
            MockA2AChunk(
                context_id=context_id,
                task_id="task_clarifier_001",
                status_state="input_required",
                text="What dates would you like to travel?",
                is_task=True,
                last_seen_seq=last_seen_seq,
            )
        ]

    @staticmethod
    def divergence_detected_response(
        context_id: str = "ctx_clarifier_001",
        expected_seq: int = 5,
        received_seq: int = 3,
    ) -> list[MockA2AChunk]:
        """Response indicating divergence was detected and history was rebuilt."""
        return [
            MockA2AChunk(
                context_id=context_id,
                task_id="task_clarifier_001",
                status_state="input_required",
                text=f'{{"divergenceDetected": true, "expectedSeq": {expected_seq}, "receivedSeq": {received_seq}, "action": "rebuilt_from_history"}}',
                is_task=True,
                last_seen_seq=received_seq,
            )
        ]


@pytest.fixture
def mock_response_factory() -> MockA2AResponseFactory:
    """Provide mock response factory to tests."""
    return MockA2AResponseFactory()


@pytest.fixture
def mock_a2a_client(mock_response_factory: MockA2AResponseFactory) -> MagicMock:
    """
    Create a mock A2A client that returns predefined responses.

    Tests can configure responses per-agent using:
        mock_a2a_client.configure_response(agent_url, chunks)

    The mock client simulates the A2AClientWrapper interface:
    - send_message() returns A2AResponse
    - Supports context manager protocol
    - Extracts context_id, task_id, status from chunks
    """
    from src.shared.a2a.client_wrapper import A2AResponse

    client = MagicMock()
    client._responses: dict[str, list[MockA2AChunk]] = {}

    def configure_response(agent_url: str, chunks: list[MockA2AChunk]) -> None:
        """Configure mock response for an agent URL."""
        client._responses[agent_url] = chunks

    async def mock_send_message(
        agent_url: str,
        message: str,
        context_id: str | None = None,
        task_id: str | None = None,
        history: list[dict[str, Any]] | None = None,
        history_seq: int | None = None,
        **kwargs: Any,
    ) -> A2AResponse:
        """Mock implementation of send_message.

        Args:
            agent_url: URL of the target agent
            message: Message to send
            context_id: Existing context_id for multi-turn
            task_id: Existing task_id to continue in-progress task
            history: Full conversation history (per design doc Agent Communication)
            history_seq: Sequence number for divergence detection (per design doc)
        """
        chunks = client._responses.get(
            agent_url, [MockA2AChunk(text="Default mock response")]
        )

        # Parse chunks into A2AResponse
        text_parts: list[str] = []
        result_context_id = context_id
        result_task_id = task_id
        is_complete = False
        requires_input = False
        last_seen_seq: int | None = None

        for chunk in chunks:
            data = chunk.model_dump()
            result = data.get("result", {})

            if "contextId" in result:
                result_context_id = result["contextId"]
            if result.get("kind") == "task" and "id" in result:
                result_task_id = result["id"]
            elif "taskId" in result:
                result_task_id = result["taskId"]

            status = result.get("status", {})
            if status.get("state") == "completed":
                is_complete = True
            elif status.get("state") == "input_required":
                requires_input = True

            if "message" in status and "parts" in status["message"]:
                for part in status["message"]["parts"]:
                    if part.get("kind") == "text":
                        text_parts.append(part.get("text", ""))

            # Extract history acknowledgment (per design doc)
            metadata = result.get("metadata", {})
            if "lastSeenSeq" in metadata:
                last_seen_seq = metadata["lastSeenSeq"]

        return A2AResponse(
            text=" ".join(text_parts),
            context_id=result_context_id,
            task_id=result_task_id,
            is_complete=is_complete,
            requires_input=requires_input,
            raw_chunks=[],
        )

    client.send_message = AsyncMock(side_effect=mock_send_message)
    client.configure_response = configure_response
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)

    return client


# ============================================================
# Mock Cosmos DB Fixtures (for Phase 2+ orchestrator tests)
# ============================================================


class MockCosmosContainer:
    """
    Mock Cosmos DB container for testing.

    Simulates basic CRUD operations with in-memory storage.
    Used for testing WorkflowStore and other Cosmos-backed stores.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self._items: dict[str, dict[str, Any]] = {}

    async def create_item(self, body: dict[str, Any]) -> dict[str, Any]:
        """Create an item in the container."""
        item_id = body.get("id", str(len(self._items)))
        body["id"] = item_id
        body["_etag"] = f"etag_{item_id}_{len(self._items)}"
        self._items[item_id] = body
        return body

    async def read_item(
        self, item: str, partition_key: str
    ) -> dict[str, Any]:
        """Read an item from the container."""
        if item not in self._items:
            raise Exception(f"Item {item} not found")
        return self._items[item]

    async def upsert_item(self, body: dict[str, Any]) -> dict[str, Any]:
        """Upsert an item in the container."""
        item_id = body.get("id")
        if item_id:
            body["_etag"] = f"etag_{item_id}_{len(self._items)}"
            self._items[item_id] = body
        return body

    async def delete_item(self, item: str, partition_key: str) -> None:
        """Delete an item from the container."""
        if item in self._items:
            del self._items[item]

    def query_items(
        self,
        query: str,
        parameters: list[dict[str, Any]] | None = None,
        partition_key: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query items (simplified - returns all items)."""
        return list(self._items.values())


class MockCosmosClient:
    """
    Mock Cosmos DB client for testing.

    Provides in-memory container storage for testing without
    requiring actual Azure Cosmos DB connection.
    """

    def __init__(self) -> None:
        self._databases: dict[str, dict[str, MockCosmosContainer]] = {}

    def get_database_client(self, database: str) -> "MockCosmosDatabase":
        """Get a mock database client."""
        if database not in self._databases:
            self._databases[database] = {}
        return MockCosmosDatabase(database, self._databases[database])


class MockCosmosDatabase:
    """Mock Cosmos DB database."""

    def __init__(
        self, name: str, containers: dict[str, MockCosmosContainer]
    ) -> None:
        self.name = name
        self._containers = containers

    def get_container_client(self, container: str) -> MockCosmosContainer:
        """Get a mock container client."""
        if container not in self._containers:
            self._containers[container] = MockCosmosContainer(container)
        return self._containers[container]


@pytest.fixture
def mock_cosmos_client() -> MockCosmosClient:
    """
    Create a mock Cosmos DB client for testing.

    Provides in-memory storage simulating Cosmos DB containers.
    Used for testing WorkflowStore, ConsultationStore, BookingStore.

    Example:
        def test_workflow_persistence(mock_cosmos_client):
            db = mock_cosmos_client.get_database_client("travel_planner")
            container = db.get_container_client("workflow_states")
            await container.create_item({"id": "sess_123", "phase": "INTAKE"})
    """
    return MockCosmosClient()


# ============================================================
# Mock Azure AI Agent Service Fixtures (for Phase 2+ tests)
# ============================================================


class MockAzureAgent:
    """
    Mock Azure AI Agent for testing.

    Simulates Azure AI Agent Service agent behavior without
    requiring actual Azure connection.
    """

    def __init__(
        self,
        agent_id: str,
        name: str = "mock_agent",
        model: str = "gpt-4o",
    ) -> None:
        self.id = agent_id
        self.name = name
        self.model = model
        self._threads: dict[str, list[dict[str, Any]]] = {}
        self._configured_responses: list[str] = []

    def configure_responses(self, responses: list[str]) -> None:
        """Configure responses to return in sequence."""
        self._configured_responses = list(responses)

    async def create_thread(self) -> str:
        """Create a new thread."""
        thread_id = f"thread_{len(self._threads)}"
        self._threads[thread_id] = []
        return thread_id

    async def add_message(
        self, thread_id: str, content: str, role: str = "user"
    ) -> dict[str, Any]:
        """Add a message to a thread."""
        if thread_id not in self._threads:
            self._threads[thread_id] = []
        message = {
            "id": f"msg_{len(self._threads[thread_id])}",
            "role": role,
            "content": content,
        }
        self._threads[thread_id].append(message)
        return message

    async def run(self, thread_id: str) -> dict[str, Any]:
        """Run the agent on a thread."""
        response_text = "Mock agent response"
        if self._configured_responses:
            response_text = self._configured_responses.pop(0)

        response = {
            "id": f"run_{thread_id}",
            "status": "completed",
            "response": response_text,
        }

        # Add assistant message to thread
        await self.add_message(thread_id, response_text, role="assistant")

        return response


class MockAzureAgentRegistry:
    """
    Mock registry for Azure AI agents.

    Simulates the agent registry pattern used by the orchestrator.
    """

    def __init__(self) -> None:
        self._agents: dict[str, MockAzureAgent] = {}

    def register(self, agent_type: str, agent: MockAzureAgent) -> None:
        """Register an agent."""
        self._agents[agent_type] = agent

    def get(self, agent_type: str) -> MockAzureAgent | None:
        """Get an agent by type."""
        return self._agents.get(agent_type)


@pytest.fixture
def mock_azure_agent() -> MockAzureAgent:
    """
    Create a mock Azure AI agent for testing.

    Simulates agent behavior without Azure connection.
    Used for testing orchestrator LLM decision points.

    Example:
        def test_routing_decision(mock_azure_agent):
            mock_azure_agent.configure_responses(["workflow_turn"])
            thread_id = await mock_azure_agent.create_thread()
            result = await mock_azure_agent.run(thread_id)
            assert result["response"] == "workflow_turn"
    """
    return MockAzureAgent(
        agent_id="mock_agent_001",
        name="test_agent",
        model="gpt-4o",
    )


@pytest.fixture
def mock_azure_agent_registry() -> MockAzureAgentRegistry:
    """
    Create a mock Azure AI agent registry for testing.

    Provides pre-configured agents for orchestrator testing:
    - routing: For Layer 1c routing decisions
    - classifier: For action classification
    - planner: For modification planning
    - qa: For Q&A mode responses

    Example:
        def test_orchestrator_routing(mock_azure_agent_registry):
            router = mock_azure_agent_registry.get("routing")
            router.configure_responses(["answer_question"])
    """
    registry = MockAzureAgentRegistry()

    # Pre-configure the 4 orchestrator agents per design doc
    registry.register(
        "routing",
        MockAzureAgent("routing_001", "routing_agent"),
    )
    registry.register(
        "classifier",
        MockAzureAgent("classifier_001", "classifier_agent"),
    )
    registry.register(
        "planner",
        MockAzureAgent("planner_001", "planner_agent"),
    )
    registry.register(
        "qa",
        MockAzureAgent("qa_001", "qa_agent"),
    )

    return registry
