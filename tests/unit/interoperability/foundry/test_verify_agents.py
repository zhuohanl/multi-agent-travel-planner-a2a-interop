"""Unit tests for verify_agents.py."""

import pytest
from unittest.mock import MagicMock, patch

from interoperability.foundry.verify_agents import (
    AgentVerifier,
    VerificationStatus,
    VerificationResult,
    TestQuery,
    TEST_QUERIES,
    print_results,
)


class TestVerificationStatus:
    """Tests for VerificationStatus enum."""

    def test_status_values(self):
        """Verify all status values are correct."""
        assert VerificationStatus.PASS.value == "pass"
        assert VerificationStatus.FAIL.value == "fail"
        assert VerificationStatus.SKIP.value == "skip"


class TestTestQuery:
    """Tests for TestQuery dataclass."""

    def test_test_query_creation(self):
        """Test creating a TestQuery."""
        query = TestQuery(
            agent_name="test_agent",
            query="Test query",
            expected_keywords=["keyword1", "keyword2"],
        )
        assert query.agent_name == "test_agent"
        assert query.query == "Test query"
        assert query.expected_keywords == ["keyword1", "keyword2"]

    def test_test_query_default_keywords(self):
        """Test TestQuery with default empty keywords."""
        query = TestQuery(agent_name="test", query="query")
        assert query.expected_keywords == []


class TestVerificationResult:
    """Tests for VerificationResult dataclass."""

    def test_verification_result_creation(self):
        """Test creating a VerificationResult."""
        result = VerificationResult(
            agent_name="transport",
            status=VerificationStatus.PASS,
            query="Find flights",
            response="Here are some flights...",
            message="Success",
            details=["Detail 1"],
        )
        assert result.agent_name == "transport"
        assert result.status == VerificationStatus.PASS
        assert result.query == "Find flights"
        assert result.response == "Here are some flights..."
        assert result.message == "Success"
        assert result.details == ["Detail 1"]

    def test_verification_result_defaults(self):
        """Test VerificationResult default values."""
        result = VerificationResult(
            agent_name="test",
            status=VerificationStatus.SKIP,
            query="query",
        )
        assert result.response == ""
        assert result.message == ""
        assert result.details == []


class TestTEST_QUERIES:
    """Tests for predefined test queries."""

    def test_transport_query_defined(self):
        """Verify transport agent test query exists."""
        assert "transport" in TEST_QUERIES
        query = TEST_QUERIES["transport"]
        assert query.agent_name == "transport"
        assert "Seattle" in query.query
        assert "Tokyo" in query.query
        assert len(query.expected_keywords) > 0

    def test_poi_query_defined(self):
        """Verify POI agent test query exists."""
        assert "poi" in TEST_QUERIES
        query = TEST_QUERIES["poi"]
        assert query.agent_name == "poi"
        assert "Paris" in query.query
        assert len(query.expected_keywords) > 0

    def test_events_query_defined(self):
        """Verify events agent test query exists."""
        assert "events" in TEST_QUERIES
        query = TEST_QUERIES["events"]
        assert query.agent_name == "events"
        assert "London" in query.query
        assert len(query.expected_keywords) > 0

    def test_all_agents_have_expected_keywords(self):
        """Verify all test queries have expected keywords."""
        for agent_name, query in TEST_QUERIES.items():
            assert len(query.expected_keywords) > 0, f"{agent_name} should have expected keywords"


class TestAgentVerifier:
    """Tests for AgentVerifier class."""

    def test_init_with_endpoint(self):
        """Test initialization with explicit endpoint."""
        verifier = AgentVerifier(project_endpoint="https://test.endpoint.com")
        assert verifier.project_endpoint == "https://test.endpoint.com"
        assert verifier.verbose is False

    def test_init_with_verbose(self):
        """Test initialization with verbose mode."""
        verifier = AgentVerifier(project_endpoint="https://test.endpoint.com", verbose=True)
        assert verifier.verbose is True

    @patch.dict("os.environ", {"PROJECT_ENDPOINT": "https://env.endpoint.com"})
    def test_init_from_env(self):
        """Test initialization from environment variable."""
        verifier = AgentVerifier()
        assert verifier.project_endpoint == "https://env.endpoint.com"

    @patch.dict("os.environ", {"AZURE_AI_PROJECT_ENDPOINT": "https://azure.endpoint.com"})
    def test_init_prefers_azure_env(self):
        """Test initialization prefers AZURE_AI_PROJECT_ENDPOINT."""
        verifier = AgentVerifier()
        assert verifier.project_endpoint == "https://azure.endpoint.com"

    def test_verify_agent_dry_run(self):
        """Test dry run mode for verify_agent."""
        verifier = AgentVerifier(project_endpoint="https://test.endpoint.com")
        result = verifier.verify_agent("transport", dry_run=True)

        assert result.status == VerificationStatus.SKIP
        assert "[DRY RUN]" in result.message
        assert "transport" in result.message

    def test_verify_agent_unknown_agent(self):
        """Test verify_agent with unknown agent name."""
        verifier = AgentVerifier(project_endpoint="https://test.endpoint.com")
        result = verifier.verify_agent("unknown_agent", dry_run=True)

        assert result.status == VerificationStatus.SKIP
        assert "No test query defined" in result.message

    def test_verify_agent_custom_query_dry_run(self):
        """Test verify_agent with custom test query."""
        verifier = AgentVerifier(project_endpoint="https://test.endpoint.com")
        custom_query = TestQuery(
            agent_name="custom",
            query="Custom query",
            expected_keywords=["custom", "keyword"],
        )
        result = verifier.verify_agent("custom", test_query=custom_query, dry_run=True)

        assert result.status == VerificationStatus.SKIP
        assert "Custom query" in result.query

    def test_verify_all_dry_run(self):
        """Test verify_all in dry run mode."""
        verifier = AgentVerifier(project_endpoint="https://test.endpoint.com")
        results = verifier.verify_all(dry_run=True)

        # Should have results for all predefined agents
        assert len(results) == len(TEST_QUERIES)
        for result in results:
            assert result.status == VerificationStatus.SKIP
            assert "[DRY RUN]" in result.message

    def test_verify_all_specific_agents(self):
        """Test verify_all with specific agent list."""
        verifier = AgentVerifier(project_endpoint="https://test.endpoint.com")
        results = verifier.verify_all(agent_names=["transport"], dry_run=True)

        assert len(results) == 1
        assert results[0].agent_name == "transport"

    @patch.dict("os.environ", {"PROJECT_ENDPOINT": "", "AZURE_AI_PROJECT_ENDPOINT": ""}, clear=False)
    def test_get_project_client_no_endpoint(self):
        """Test _get_project_client raises error without endpoint."""
        # Clear environment vars that might be set
        import os
        old_values = {}
        for key in ["PROJECT_ENDPOINT", "AZURE_AI_PROJECT_ENDPOINT"]:
            if key in os.environ:
                old_values[key] = os.environ.pop(key)

        try:
            verifier = AgentVerifier(project_endpoint=None)
            with pytest.raises(RuntimeError, match="Project endpoint not configured"):
                verifier._get_project_client()
        finally:
            # Restore environment
            os.environ.update(old_values)


class TestAgentVerifierLiveSimulation:
    """Tests for AgentVerifier with mocked API calls."""

    def test_verify_agent_success(self):
        """Test successful agent verification with mocked response."""
        verifier = AgentVerifier(project_endpoint="https://test.endpoint.com")

        # Mock the OpenAI client
        mock_openai_client = MagicMock()
        mock_conversation = MagicMock()
        mock_conversation.id = "conv-123"
        mock_openai_client.conversations.create.return_value = mock_conversation

        mock_response = MagicMock()
        mock_response.output_text = "Here are flights from Seattle to Tokyo. Airlines include JAL, ANA, and United for your travel."
        mock_openai_client.responses.create.return_value = mock_response

        verifier._openai_client = mock_openai_client

        result = verifier.verify_agent("transport")

        assert result.status == VerificationStatus.PASS
        assert result.agent_name == "transport"
        assert len(result.response) > 0

    def test_verify_agent_empty_response(self):
        """Test agent verification with empty response."""
        verifier = AgentVerifier(project_endpoint="https://test.endpoint.com")

        mock_openai_client = MagicMock()
        mock_conversation = MagicMock()
        mock_conversation.id = "conv-123"
        mock_openai_client.conversations.create.return_value = mock_conversation

        mock_response = MagicMock()
        mock_response.output_text = ""
        mock_openai_client.responses.create.return_value = mock_response

        verifier._openai_client = mock_openai_client

        result = verifier.verify_agent("transport")

        assert result.status == VerificationStatus.FAIL
        assert "empty response" in result.message

    def test_verify_agent_api_error(self):
        """Test agent verification handles API errors."""
        verifier = AgentVerifier(project_endpoint="https://test.endpoint.com")

        mock_openai_client = MagicMock()
        mock_openai_client.conversations.create.side_effect = Exception("API Error")

        verifier._openai_client = mock_openai_client

        result = verifier.verify_agent("transport")

        assert result.status == VerificationStatus.FAIL
        assert "Error testing agent" in result.message

    def test_verify_agent_low_keyword_match(self):
        """Test agent verification with low keyword match but long response."""
        verifier = AgentVerifier(project_endpoint="https://test.endpoint.com")

        mock_openai_client = MagicMock()
        mock_conversation = MagicMock()
        mock_conversation.id = "conv-123"
        mock_openai_client.conversations.create.return_value = mock_conversation

        # Response is long but has few keywords
        mock_response = MagicMock()
        mock_response.output_text = "Here is some information about traveling. " * 10
        mock_openai_client.responses.create.return_value = mock_response

        verifier._openai_client = mock_openai_client

        result = verifier.verify_agent("transport")

        # Should pass due to content length threshold
        assert result.status == VerificationStatus.PASS


class TestPrintResults:
    """Tests for print_results function."""

    def test_print_results_pass(self, capsys):
        """Test printing results with passing status."""
        results = [
            VerificationResult(
                agent_name="transport",
                status=VerificationStatus.PASS,
                query="Test query",
                message="Test passed",
            )
        ]
        print_results(results)
        captured = capsys.readouterr()

        assert "transport" in captured.out
        assert "PASS" in captured.out
        assert "1 passed" in captured.out

    def test_print_results_fail(self, capsys):
        """Test printing results with failing status."""
        results = [
            VerificationResult(
                agent_name="transport",
                status=VerificationStatus.FAIL,
                query="Test query",
                message="Test failed",
            )
        ]
        print_results(results)
        captured = capsys.readouterr()

        assert "FAIL" in captured.out
        assert "1 failed" in captured.out
        assert "[!]" in captured.out

    def test_print_results_verbose(self, capsys):
        """Test printing results with verbose mode."""
        results = [
            VerificationResult(
                agent_name="transport",
                status=VerificationStatus.PASS,
                query="Test query",
                response="Response text here",
                message="Test passed",
            )
        ]
        print_results(results, verbose=True)
        captured = capsys.readouterr()

        assert "Response preview" in captured.out
        assert "Response text" in captured.out

    def test_print_results_all_pass(self, capsys):
        """Test printing results when all pass."""
        results = [
            VerificationResult(
                agent_name="transport",
                status=VerificationStatus.PASS,
                query="q1",
                message="passed",
            ),
            VerificationResult(
                agent_name="poi",
                status=VerificationStatus.PASS,
                query="q2",
                message="passed",
            ),
        ]
        print_results(results)
        captured = capsys.readouterr()

        assert "2 passed" in captured.out
        assert "[OK]" in captured.out
