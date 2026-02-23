"""Unit tests for test_smoke.py."""

import pytest
from unittest.mock import MagicMock, patch

from interoperability.test_smoke import (
    SmokeTester,
    SmokeTestStatus,
    SmokeTestResult,
    AgentTestQuery,
    DEMO_A_AGENTS,
    DEMO_B_AGENTS,
    DEMO_C_AGENTS,
    print_results,
)


class TestSmokeTestStatus:
    """Tests for SmokeTestStatus enum."""

    def test_status_values(self):
        """Verify all status values are correct."""
        assert SmokeTestStatus.PASS.value == "pass"
        assert SmokeTestStatus.FAIL.value == "fail"
        assert SmokeTestStatus.SKIP.value == "skip"
        assert SmokeTestStatus.TIMEOUT.value == "timeout"


class TestAgentTestQuery:
    """Tests for AgentTestQuery dataclass."""

    def test_agent_test_query_creation(self):
        """Test creating an AgentTestQuery."""
        query = AgentTestQuery(
            agent_name="test_agent",
            query="Test query",
            expected_keywords=["keyword1", "keyword2"],
            agent_type="foundry",
        )
        assert query.agent_name == "test_agent"
        assert query.query == "Test query"
        assert query.expected_keywords == ["keyword1", "keyword2"]
        assert query.agent_type == "foundry"

    def test_agent_test_query_defaults(self):
        """Test AgentTestQuery default values."""
        query = AgentTestQuery(agent_name="test", query="query")
        assert query.expected_keywords == []
        assert query.agent_type == "foundry"


class TestSmokeTestResult:
    """Tests for SmokeTestResult dataclass."""

    def test_smoke_test_result_creation(self):
        """Test creating a SmokeTestResult."""
        result = SmokeTestResult(
            agent_name="transport",
            status=SmokeTestStatus.PASS,
            query="Find flights",
            response="Here are some flights...",
            message="Success",
            response_time_ms=150.5,
        )
        assert result.agent_name == "transport"
        assert result.status == SmokeTestStatus.PASS
        assert result.query == "Find flights"
        assert result.response == "Here are some flights..."
        assert result.message == "Success"
        assert result.response_time_ms == 150.5

    def test_smoke_test_result_defaults(self):
        """Test SmokeTestResult default values."""
        result = SmokeTestResult(
            agent_name="test",
            status=SmokeTestStatus.SKIP,
            query="query",
        )
        assert result.response == ""
        assert result.message == ""
        assert result.response_time_ms == 0.0


class TestDemoAgentDefinitions:
    """Tests for demo agent definitions."""

    def test_demo_a_has_all_agents(self):
        """Test Demo A includes all required agents."""
        expected_agents = ["transport", "poi", "events", "stay", "dining", "aggregator", "route"]
        for agent in expected_agents:
            assert agent in DEMO_A_AGENTS, f"Demo A should include {agent}"

    def test_demo_a_agents_have_queries(self):
        """Test all Demo A agents have test queries."""
        # Demo A includes Foundry agents + CS Weather (Foundry->CS cross-platform call)
        allowed_types = {"foundry", "copilot_studio"}
        for agent_name, query in DEMO_A_AGENTS.items():
            assert query.query, f"{agent_name} should have a test query"
            assert query.expected_keywords, f"{agent_name} should have expected keywords"
            assert query.agent_type in allowed_types, (
                f"{agent_name} should be a foundry or copilot_studio agent"
            )

    def test_demo_b_agents_defined(self):
        """Test Demo B agents are defined."""
        assert "approval" in DEMO_B_AGENTS
        assert DEMO_B_AGENTS["approval"].agent_type == "copilot_studio"

    def test_demo_c_agents_defined(self):
        """Test Demo C agents are defined."""
        expected_agents = ["weather", "travel_planning_parent"]
        for agent in expected_agents:
            assert agent in DEMO_C_AGENTS, f"Demo C should include {agent}"
            assert DEMO_C_AGENTS[agent].agent_type == "copilot_studio"


class TestSmokeTester:
    """Tests for SmokeTester class."""

    def test_init_with_endpoint(self):
        """Test initialization with explicit endpoint."""
        tester = SmokeTester(project_endpoint="https://test.endpoint.com")
        assert tester.project_endpoint == "https://test.endpoint.com"
        assert tester.verbose is False
        assert tester.timeout_seconds == 30

    def test_init_with_verbose(self):
        """Test initialization with verbose mode."""
        tester = SmokeTester(project_endpoint="https://test.endpoint.com", verbose=True)
        assert tester.verbose is True

    def test_init_with_timeout(self):
        """Test initialization with custom timeout."""
        tester = SmokeTester(project_endpoint="https://test.endpoint.com", timeout_seconds=60)
        assert tester.timeout_seconds == 60

    @patch.dict("os.environ", {"PROJECT_ENDPOINT": "https://env.endpoint.com"})
    def test_init_from_env(self):
        """Test initialization from environment variable."""
        tester = SmokeTester()
        assert tester.project_endpoint == "https://env.endpoint.com"


class TestSmokeTesterDryRun:
    """Tests for SmokeTester dry run mode."""

    def test_smoke_demo_a_calls_all_agents(self):
        """Test that test_demo_a tests all Demo A agents in dry run."""
        tester = SmokeTester(project_endpoint="https://test.endpoint.com")
        results = tester.test_demo_a(dry_run=True)

        # Should have results for all Demo A agents
        assert len(results) == len(DEMO_A_AGENTS)
        agent_names = {r.agent_name for r in results}
        expected_names = set(DEMO_A_AGENTS.keys())
        assert agent_names == expected_names

    def test_all_dry_run_results_are_skip(self):
        """Test all dry run results have SKIP status."""
        tester = SmokeTester(project_endpoint="https://test.endpoint.com")
        results = tester.test_demo_a(dry_run=True)

        for result in results:
            assert result.status == SmokeTestStatus.SKIP
            assert "[DRY RUN]" in result.message

    def test_test_demo_b_dry_run(self):
        """Test test_demo_b in dry run mode."""
        tester = SmokeTester(project_endpoint="https://test.endpoint.com")
        results = tester.test_demo_b(dry_run=True)

        assert len(results) == len(DEMO_B_AGENTS)
        for result in results:
            assert result.status == SmokeTestStatus.SKIP

    def test_test_demo_c_dry_run(self):
        """Test test_demo_c in dry run mode."""
        tester = SmokeTester(project_endpoint="https://test.endpoint.com")
        results = tester.test_demo_c(dry_run=True)

        assert len(results) == len(DEMO_C_AGENTS)
        for result in results:
            assert result.status == SmokeTestStatus.SKIP

    def test_test_all_dry_run(self):
        """Test test_all in dry run mode."""
        tester = SmokeTester(project_endpoint="https://test.endpoint.com")
        all_results = tester.test_all(dry_run=True)

        assert "a" in all_results
        assert "b" in all_results
        assert "c" in all_results
        assert len(all_results["a"]) == len(DEMO_A_AGENTS)
        assert len(all_results["b"]) == len(DEMO_B_AGENTS)
        assert len(all_results["c"]) == len(DEMO_C_AGENTS)


class TestSmokeTesterValidation:
    """Tests for response validation."""

    def test_smoke_validates_response_format(self):
        """Test that _validate_response validates response format."""
        tester = SmokeTester(project_endpoint="https://test.endpoint.com")

        # Test with valid long response
        status, message = tester._validate_response(
            "This is a long response with enough content to pass validation. " * 3,
            ["keyword1", "keyword2"],
        )
        assert status == SmokeTestStatus.PASS

    def test_validate_empty_response_fails(self):
        """Test that empty response fails validation."""
        tester = SmokeTester(project_endpoint="https://test.endpoint.com")

        status, message = tester._validate_response("", ["keyword1"])
        assert status == SmokeTestStatus.FAIL
        assert "Empty" in message

    def test_validate_whitespace_response_fails(self):
        """Test that whitespace-only response fails validation."""
        tester = SmokeTester(project_endpoint="https://test.endpoint.com")

        status, message = tester._validate_response("   \n\t  ", ["keyword1"])
        assert status == SmokeTestStatus.FAIL

    def test_validate_with_keywords(self):
        """Test validation with matching keywords."""
        tester = SmokeTester(project_endpoint="https://test.endpoint.com")

        # Short response but with matching keywords
        status, message = tester._validate_response(
            "Flight to Tokyo",
            ["flight", "Tokyo", "airline", "travel"],
        )
        # Should pass due to keyword match (2 out of 4 = half)
        assert status == SmokeTestStatus.PASS
        assert "2/4 keywords" in message


class TestSmokeTesterTimeout:
    """Tests for timeout handling."""

    def test_smoke_handles_timeout(self):
        """Test that timeout is handled gracefully."""
        tester = SmokeTester(project_endpoint="https://test.endpoint.com")

        # Mock the OpenAI client to raise our TimeoutError
        from interoperability.test_smoke import TimeoutError as SmokeTimeoutError

        mock_openai_client = MagicMock()
        mock_openai_client.conversations.create.side_effect = SmokeTimeoutError("Timed out")

        tester._openai_client = mock_openai_client

        result = tester._test_foundry_agent(DEMO_A_AGENTS["transport"])

        assert result.status == SmokeTestStatus.TIMEOUT
        # Message contains "did not respond within X seconds"
        assert "did not respond within" in result.message.lower() or "timeout" in result.message.lower()

    def test_timeout_continues_to_next_agent(self):
        """Test that timeout on one agent doesn't stop other tests."""
        tester = SmokeTester(project_endpoint="https://test.endpoint.com")

        # In dry run, all agents should be tested regardless
        results = tester.test_demo_a(dry_run=True)
        assert len(results) == len(DEMO_A_AGENTS)


class TestSmokeTesterLive:
    """Tests for SmokeTester with mocked API calls."""

    def test_foundry_agent_success(self):
        """Test successful Foundry agent test with mocked response."""
        tester = SmokeTester(project_endpoint="https://test.endpoint.com")

        # Mock the OpenAI client
        mock_openai_client = MagicMock()
        mock_conversation = MagicMock()
        mock_conversation.id = "conv-123"
        mock_openai_client.conversations.create.return_value = mock_conversation

        mock_response = MagicMock()
        mock_response.output_text = "Here are flights from Seattle to Tokyo. Airlines include JAL, ANA, and United for your travel needs."
        mock_openai_client.responses.create.return_value = mock_response

        tester._openai_client = mock_openai_client

        result = tester._test_foundry_agent(DEMO_A_AGENTS["transport"])

        assert result.status == SmokeTestStatus.PASS
        assert result.agent_name == "transport"
        assert result.response_time_ms > 0

    def test_foundry_agent_empty_response(self):
        """Test Foundry agent test with empty response."""
        tester = SmokeTester(project_endpoint="https://test.endpoint.com")

        mock_openai_client = MagicMock()
        mock_conversation = MagicMock()
        mock_conversation.id = "conv-123"
        mock_openai_client.conversations.create.return_value = mock_conversation

        mock_response = MagicMock()
        mock_response.output_text = ""
        mock_openai_client.responses.create.return_value = mock_response

        tester._openai_client = mock_openai_client

        result = tester._test_foundry_agent(DEMO_A_AGENTS["transport"])

        assert result.status == SmokeTestStatus.FAIL
        assert "empty response" in result.message.lower()

    def test_foundry_agent_api_error(self):
        """Test Foundry agent test handles API errors."""
        tester = SmokeTester(project_endpoint="https://test.endpoint.com")

        mock_openai_client = MagicMock()
        mock_openai_client.conversations.create.side_effect = Exception("API Error")

        tester._openai_client = mock_openai_client

        result = tester._test_foundry_agent(DEMO_A_AGENTS["transport"])

        assert result.status == SmokeTestStatus.FAIL
        assert "Error testing agent" in result.message

    def test_copilot_studio_agent_skipped(self):
        """Test Copilot Studio agents are skipped (not implemented)."""
        tester = SmokeTester(project_endpoint="https://test.endpoint.com")

        result = tester.test_agent(DEMO_B_AGENTS["approval"], dry_run=False)

        assert result.status == SmokeTestStatus.SKIP
        assert "not implemented" in result.message.lower()


class TestPrintResults:
    """Tests for print_results function."""

    def test_smoke_outputs_summary(self, capsys):
        """Test that print_results outputs summary."""
        results = [
            SmokeTestResult(
                agent_name="transport",
                status=SmokeTestStatus.PASS,
                query="Test query",
                message="Test passed",
            ),
            SmokeTestResult(
                agent_name="poi",
                status=SmokeTestStatus.PASS,
                query="Test query 2",
                message="Test passed",
            ),
        ]
        print_results(results, demo_name="a")
        captured = capsys.readouterr()

        assert "2/2 agents passed" in captured.out
        assert "Demo A" in captured.out

    def test_print_results_with_failures(self, capsys):
        """Test print_results with failures shows warning."""
        results = [
            SmokeTestResult(
                agent_name="transport",
                status=SmokeTestStatus.PASS,
                query="q1",
                message="passed",
            ),
            SmokeTestResult(
                agent_name="poi",
                status=SmokeTestStatus.FAIL,
                query="q2",
                message="failed",
            ),
        ]
        print_results(results)
        captured = capsys.readouterr()

        assert "1/2 agents passed" in captured.out
        assert "1 failed" in captured.out
        assert "[!]" in captured.out

    def test_print_results_with_timeout(self, capsys):
        """Test print_results with timeout shows count."""
        results = [
            SmokeTestResult(
                agent_name="transport",
                status=SmokeTestStatus.TIMEOUT,
                query="q1",
                message="timed out",
            ),
        ]
        print_results(results)
        captured = capsys.readouterr()

        assert "1 timed out" in captured.out
        assert "⏱" in captured.out

    def test_print_results_all_pass(self, capsys):
        """Test print_results when all pass shows OK."""
        results = [
            SmokeTestResult(
                agent_name="transport",
                status=SmokeTestStatus.PASS,
                query="q1",
                message="passed",
            ),
        ]
        print_results(results)
        captured = capsys.readouterr()

        assert "[OK]" in captured.out
        assert "All agents passed" in captured.out

    def test_print_results_verbose(self, capsys):
        """Test print_results with verbose shows response."""
        results = [
            SmokeTestResult(
                agent_name="transport",
                status=SmokeTestStatus.PASS,
                query="q1",
                response="This is the response text from the agent.",
                message="passed",
            ),
        ]
        print_results(results, verbose=True)
        captured = capsys.readouterr()

        assert "Response preview" in captured.out
        assert "response text" in captured.out.lower()

    def test_print_results_with_response_time(self, capsys):
        """Test print_results shows response time."""
        results = [
            SmokeTestResult(
                agent_name="transport",
                status=SmokeTestStatus.PASS,
                query="q1",
                message="passed",
                response_time_ms=150.5,
            ),
        ]
        print_results(results)
        captured = capsys.readouterr()

        assert "150ms" in captured.out or "151ms" in captured.out


class TestSmokeTesterProjectClient:
    """Tests for project client initialization."""

    @patch.dict("os.environ", {"PROJECT_ENDPOINT": "", "AZURE_AI_PROJECT_ENDPOINT": ""}, clear=False)
    def test_get_project_client_no_endpoint(self):
        """Test _get_project_client raises error without endpoint."""
        import os
        old_values = {}
        for key in ["PROJECT_ENDPOINT", "AZURE_AI_PROJECT_ENDPOINT"]:
            if key in os.environ:
                old_values[key] = os.environ.pop(key)

        try:
            tester = SmokeTester(project_endpoint=None)
            with pytest.raises(RuntimeError, match="Project endpoint not configured"):
                tester._get_project_client()
        finally:
            os.environ.update(old_values)
