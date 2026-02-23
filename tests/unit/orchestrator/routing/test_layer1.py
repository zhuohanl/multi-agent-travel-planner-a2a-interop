"""
Unit tests for the Layer 1 routing implementation.

Tests cover:
- Layer 1a: Session check routing to workflow_turn
- Layer 1b: Utility pattern matching
- Layer 1c: LLM routing fallback
- Pattern case-insensitivity
- Edge cases and error handling
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.orchestrator.routing.layer1 import (
    UTILITY_PATTERNS,
    RouteResult,
    RouteTarget,
    UtilityMatch,
    _build_utility_args,
    _parse_llm_routing_decision,
    match_utility_pattern,
    route,
)


# =============================================================================
# LAYER 1B: UTILITY PATTERN MATCHING TESTS
# =============================================================================


class TestMatchUtilityPattern:
    """Tests for match_utility_pattern() (Layer 1b)."""

    def test_match_currency_pattern_basic(self) -> None:
        """Test basic currency conversion pattern."""
        result = match_utility_pattern("convert 100 USD to EUR")
        assert result is not None
        assert result.target == RouteTarget.CURRENCY_CONVERT
        assert result.args == ("100", "USD", "EUR")
        assert result.pattern_name == "currency"

    def test_match_currency_pattern_with_decimal(self) -> None:
        """Test currency conversion with decimal amount."""
        result = match_utility_pattern("convert 99.99 GBP to JPY")
        assert result is not None
        assert result.target == RouteTarget.CURRENCY_CONVERT
        assert result.args == ("99.99", "GBP", "JPY")

    def test_match_currency_pattern_case_insensitive(self) -> None:
        """Test currency pattern is case-insensitive."""
        result = match_utility_pattern("CONVERT 50 usd TO eur")
        assert result is not None
        assert result.target == RouteTarget.CURRENCY_CONVERT
        assert result.args == ("50", "usd", "eur")

    def test_match_weather_in_pattern(self) -> None:
        """Test weather lookup with 'in' preposition."""
        result = match_utility_pattern("weather in Tokyo")
        assert result is not None
        assert result.target == RouteTarget.WEATHER_LOOKUP
        assert result.args == ("Tokyo",)
        assert result.pattern_name == "weather"

    def test_match_weather_for_pattern(self) -> None:
        """Test weather lookup with 'for' preposition."""
        result = match_utility_pattern("weather for Paris, France")
        assert result is not None
        assert result.target == RouteTarget.WEATHER_LOOKUP
        assert result.args == ("Paris, France",)

    def test_match_weather_pattern_case_insensitive(self) -> None:
        """Test weather pattern is case-insensitive."""
        result = match_utility_pattern("WEATHER IN london")
        assert result is not None
        assert result.target == RouteTarget.WEATHER_LOOKUP
        assert result.args == ("london",)

    def test_match_timezone_what_time_in(self) -> None:
        """Test timezone lookup with 'what time in' pattern."""
        result = match_utility_pattern("what time in Sydney")
        assert result is not None
        assert result.target == RouteTarget.TIMEZONE_INFO
        assert result.args == ("Sydney",)
        assert result.pattern_name == "timezone"

    def test_match_timezone_what_time_is_it_in(self) -> None:
        """Test timezone lookup with 'what time is it in' pattern."""
        result = match_utility_pattern("what time is it in New York")
        assert result is not None
        assert result.target == RouteTarget.TIMEZONE_INFO
        assert result.args == ("New York",)

    def test_match_timezone_pattern_case_insensitive(self) -> None:
        """Test timezone pattern is case-insensitive."""
        result = match_utility_pattern("What Time Is It In TOKYO")
        assert result is not None
        assert result.target == RouteTarget.TIMEZONE_INFO

    def test_match_booking_lookup(self) -> None:
        """Test booking lookup pattern."""
        result = match_utility_pattern("show booking book_abc123")
        assert result is not None
        assert result.target == RouteTarget.GET_BOOKING
        assert result.args == ("book_abc123",)
        assert result.pattern_name == "booking_lookup"

    def test_match_booking_lookup_case_insensitive(self) -> None:
        """Test booking lookup is case-insensitive."""
        result = match_utility_pattern("SHOW BOOKING book_xyz789")
        assert result is not None
        assert result.target == RouteTarget.GET_BOOKING

    def test_match_consultation_lookup(self) -> None:
        """Test consultation lookup pattern."""
        result = match_utility_pattern("show consultation cons_def456")
        assert result is not None
        assert result.target == RouteTarget.GET_CONSULTATION
        assert result.args == ("cons_def456",)
        assert result.pattern_name == "consultation_lookup"

    def test_match_consultation_lookup_case_insensitive(self) -> None:
        """Test consultation lookup is case-insensitive."""
        result = match_utility_pattern("Show Consultation cons_test123")
        assert result is not None
        assert result.target == RouteTarget.GET_CONSULTATION

    def test_no_match_natural_language_currency(self) -> None:
        """Test natural language currency doesn't match (falls to Layer 1c)."""
        result = match_utility_pattern("how much is 100 dollars in euros?")
        assert result is None

    def test_no_match_natural_language_weather(self) -> None:
        """Test natural language weather doesn't match (falls to Layer 1c)."""
        result = match_utility_pattern("what's the weather like in Paris?")
        assert result is None

    def test_no_match_trip_planning(self) -> None:
        """Test trip planning doesn't match utility patterns."""
        result = match_utility_pattern("Plan a trip to Tokyo")
        assert result is None

    def test_no_match_general_question(self) -> None:
        """Test general question doesn't match utility patterns."""
        result = match_utility_pattern("What's Tokyo like in spring?")
        assert result is None

    def test_no_match_empty_string(self) -> None:
        """Test empty string doesn't match."""
        result = match_utility_pattern("")
        assert result is None


class TestBuildUtilityArgs:
    """Tests for _build_utility_args()."""

    def test_build_currency_args(self) -> None:
        """Test building currency conversion args."""
        match = UtilityMatch(
            target=RouteTarget.CURRENCY_CONVERT,
            args=("100.50", "usd", "eur"),
            pattern_name="currency",
        )
        args = _build_utility_args(match)
        assert args == {
            "amount": 100.50,
            "from_currency": "USD",
            "to_currency": "EUR",
        }

    def test_build_weather_args(self) -> None:
        """Test building weather lookup args."""
        match = UtilityMatch(
            target=RouteTarget.WEATHER_LOOKUP,
            args=("  Tokyo  ",),
            pattern_name="weather",
        )
        args = _build_utility_args(match)
        assert args == {"location": "Tokyo"}  # Trimmed

    def test_build_timezone_args(self) -> None:
        """Test building timezone info args."""
        match = UtilityMatch(
            target=RouteTarget.TIMEZONE_INFO,
            args=("New York",),
            pattern_name="timezone",
        )
        args = _build_utility_args(match)
        assert args == {"location": "New York"}

    def test_build_booking_args(self) -> None:
        """Test building booking lookup args."""
        match = UtilityMatch(
            target=RouteTarget.GET_BOOKING,
            args=("book_abc123",),
            pattern_name="booking_lookup",
        )
        args = _build_utility_args(match)
        assert args == {"booking_id": "book_abc123"}

    def test_build_consultation_args(self) -> None:
        """Test building consultation lookup args."""
        match = UtilityMatch(
            target=RouteTarget.GET_CONSULTATION,
            args=("cons_def456",),
            pattern_name="consultation_lookup",
        )
        args = _build_utility_args(match)
        assert args == {"consultation_id": "cons_def456"}


# =============================================================================
# LAYER 1A: SESSION CHECK TESTS
# =============================================================================


class TestRouteWithSession:
    """Tests for Layer 1a: routing when session exists."""

    @pytest.mark.asyncio
    async def test_session_ref_routes_to_workflow(self) -> None:
        """Test that active session routes to workflow_turn (Layer 1a)."""
        # Create a mock state
        state = MagicMock()
        state.session_id = "sess_test123"

        result = await route(
            message="what about flights?",
            session_id="sess_test123",
            state=state,
        )

        assert result.target == RouteTarget.WORKFLOW_TURN
        assert result.layer == "1a"
        assert result.state is state
        assert result.tool_args is not None
        assert result.tool_args["session_ref"]["session_id"] == "sess_test123"
        assert result.tool_args["message"] == "what about flights?"

    @pytest.mark.asyncio
    async def test_session_routes_utility_to_workflow(self) -> None:
        """Test that utility message with active session goes to workflow_turn.

        Per design doc: With active session, utilities go through workflow_turn
        for context-aware handling at Layer 2.
        """
        state = MagicMock()
        state.session_id = "sess_active"

        # This message would match Layer 1b pattern if no session
        result = await route(
            message="convert 100 USD to EUR",
            session_id="sess_active",
            state=state,
        )

        # Should route to workflow_turn, not currency_convert
        assert result.target == RouteTarget.WORKFLOW_TURN
        assert result.layer == "1a"

    @pytest.mark.asyncio
    async def test_session_routes_weather_to_workflow(self) -> None:
        """Test that weather query with session goes to workflow_turn."""
        state = MagicMock()
        state.session_id = "sess_planning"

        result = await route(
            message="weather in Tokyo",
            session_id="sess_planning",
            state=state,
        )

        assert result.target == RouteTarget.WORKFLOW_TURN
        assert result.layer == "1a"


# =============================================================================
# LAYER 1B: NO SESSION UTILITY PATTERN TESTS
# =============================================================================


class TestRouteNoSessionUtility:
    """Tests for Layer 1b: routing utility patterns when no session."""

    @pytest.mark.asyncio
    async def test_no_session_currency_routes_to_utility(self) -> None:
        """Test currency pattern routes to currency_convert (no session)."""
        result = await route(
            message="convert 100 USD to EUR",
            session_id="new_session",
            state=None,  # No active session
        )

        assert result.target == RouteTarget.CURRENCY_CONVERT
        assert result.layer == "1b"
        assert result.utility_match is not None
        assert result.tool_args == {
            "amount": 100.0,
            "from_currency": "USD",
            "to_currency": "EUR",
        }

    @pytest.mark.asyncio
    async def test_no_session_weather_routes_to_utility(self) -> None:
        """Test weather pattern routes to weather_lookup (no session)."""
        result = await route(
            message="weather in Paris",
            session_id="new_session",
            state=None,
        )

        assert result.target == RouteTarget.WEATHER_LOOKUP
        assert result.layer == "1b"
        assert result.tool_args == {"location": "Paris"}

    @pytest.mark.asyncio
    async def test_no_session_timezone_routes_to_utility(self) -> None:
        """Test timezone pattern routes to timezone_info (no session)."""
        result = await route(
            message="what time in Tokyo",
            session_id="new_session",
            state=None,
        )

        assert result.target == RouteTarget.TIMEZONE_INFO
        assert result.layer == "1b"
        assert result.tool_args == {"location": "Tokyo"}

    @pytest.mark.asyncio
    async def test_no_session_booking_lookup_routes_to_utility(self) -> None:
        """Test booking lookup routes to get_booking (no session)."""
        result = await route(
            message="show booking book_abc123",
            session_id="new_session",
            state=None,
        )

        assert result.target == RouteTarget.GET_BOOKING
        assert result.layer == "1b"
        assert result.tool_args == {"booking_id": "book_abc123"}

    @pytest.mark.asyncio
    async def test_no_session_consultation_lookup_routes_to_utility(self) -> None:
        """Test consultation lookup routes to get_consultation (no session)."""
        result = await route(
            message="show consultation cons_def456",
            session_id="new_session",
            state=None,
        )

        assert result.target == RouteTarget.GET_CONSULTATION
        assert result.layer == "1b"
        assert result.tool_args == {"consultation_id": "cons_def456"}


# =============================================================================
# LAYER 1C: LLM ROUTING TESTS
# =============================================================================


class TestRouteNoSessionLLM:
    """Tests for Layer 1c: LLM routing when no session and no pattern match."""

    @pytest.mark.asyncio
    async def test_no_session_uses_llm(self) -> None:
        """Test that non-utility message without session uses LLM (Layer 1c)."""
        # Create mock LLM with tool call response
        mock_llm = MagicMock()
        mock_llm.ensure_thread_exists = MagicMock(return_value="thread_123")

        # Create mock tool call with explicit attributes
        mock_tool_call = MagicMock()
        mock_tool_call.name = "workflow_turn"
        mock_tool_call.arguments = {"message": "Plan a trip to Tokyo", "session_ref": None}

        mock_run = MagicMock()
        mock_run.status = "requires_action"
        mock_run.has_failed = False
        mock_run.is_completed = False
        mock_run.tool_calls = [mock_tool_call]

        mock_llm.create_run = AsyncMock(return_value=mock_run)

        result = await route(
            message="Plan a trip to Tokyo",
            session_id="new_session",
            state=None,
            llm=mock_llm,
        )

        assert result.target == RouteTarget.WORKFLOW_TURN
        assert result.layer == "1c"
        mock_llm.ensure_thread_exists.assert_called_once()
        mock_llm.create_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_llm_defaults_to_workflow_turn(self) -> None:
        """Test that without LLM, default to workflow_turn (Layer 1c)."""
        result = await route(
            message="Plan a trip to Tokyo",
            session_id="new_session",
            state=None,
            llm=None,  # No LLM configured
        )

        assert result.target == RouteTarget.WORKFLOW_TURN
        assert result.layer == "1c"
        assert result.tool_args is not None
        assert result.tool_args["message"] == "Plan a trip to Tokyo"

    @pytest.mark.asyncio
    async def test_llm_answer_question_routing(self) -> None:
        """Test LLM routing to answer_question."""
        mock_llm = MagicMock()
        mock_llm.ensure_thread_exists = MagicMock(return_value="thread_123")

        # Create mock tool call with explicit attributes
        mock_tool_call = MagicMock()
        mock_tool_call.name = "answer_question"
        mock_tool_call.arguments = {"question": "What's Tokyo like?", "domain": "general"}

        mock_run = MagicMock()
        mock_run.status = "requires_action"
        mock_run.has_failed = False
        mock_run.is_completed = False
        mock_run.tool_calls = [mock_tool_call]

        mock_llm.create_run = AsyncMock(return_value=mock_run)

        result = await route(
            message="What's Tokyo like in spring?",
            session_id="new_session",
            state=None,
            llm=mock_llm,
        )

        assert result.target == RouteTarget.ANSWER_QUESTION
        assert result.layer == "1c"

    @pytest.mark.asyncio
    async def test_llm_exception_falls_back_to_workflow_turn(self) -> None:
        """LLM/auth failures should not crash routing and should fall back safely."""
        mock_llm = MagicMock()
        mock_llm.ensure_thread_exists = MagicMock(side_effect=RuntimeError("credential error"))
        mock_llm.create_run = AsyncMock()

        result = await route(
            message="Plan a trip to Fiji",
            session_id="new_session",
            state=None,
            llm=mock_llm,
        )

        assert result.target == RouteTarget.WORKFLOW_TURN
        assert result.layer == "1c"
        assert result.tool_args is not None
        assert result.tool_args["session_ref"]["session_id"] == "new_session"
        assert result.tool_args["message"] == "Plan a trip to Fiji"


# =============================================================================
# LLM ROUTING DECISION PARSING TESTS
# =============================================================================


class TestParseLLMRoutingDecision:
    """Tests for _parse_llm_routing_decision()."""

    def test_parse_workflow_turn_decision(self) -> None:
        """Test parsing workflow_turn tool call."""
        mock_tool_call = MagicMock()
        mock_tool_call.name = "workflow_turn"
        mock_tool_call.arguments = {"message": "Plan trip", "session_ref": {"session_id": "test"}}

        mock_run = MagicMock()
        mock_run.has_failed = False
        mock_run.is_completed = False
        mock_run.tool_calls = [mock_tool_call]

        target, args = _parse_llm_routing_decision(mock_run, "sess_123", "Plan trip")

        assert target == RouteTarget.WORKFLOW_TURN
        assert args["message"] == "Plan trip"

    def test_parse_answer_question_decision(self) -> None:
        """Test parsing answer_question tool call."""
        mock_tool_call = MagicMock()
        mock_tool_call.name = "answer_question"
        mock_tool_call.arguments = {"question": "What is Tokyo?", "domain": "poi"}

        mock_run = MagicMock()
        mock_run.has_failed = False
        mock_run.is_completed = False
        mock_run.tool_calls = [mock_tool_call]

        target, args = _parse_llm_routing_decision(mock_run, "sess_123", "What is Tokyo?")

        assert target == RouteTarget.ANSWER_QUESTION
        assert args["question"] == "What is Tokyo?"
        assert args["domain"] == "poi"

    def test_parse_utility_fallback_decision(self) -> None:
        """Test parsing utility tool call (LLM fallback for regex miss)."""
        mock_tool_call = MagicMock()
        mock_tool_call.name = "currency_convert"
        mock_tool_call.arguments = {"amount": 100, "from_currency": "USD", "to_currency": "EUR"}

        mock_run = MagicMock()
        mock_run.has_failed = False
        mock_run.is_completed = False
        mock_run.tool_calls = [mock_tool_call]

        target, args = _parse_llm_routing_decision(mock_run, "sess_123", "message")

        assert target == RouteTarget.CURRENCY_CONVERT
        assert args["amount"] == 100

    def test_parse_failed_run_defaults_to_workflow_turn(self) -> None:
        """Test failed LLM run defaults to workflow_turn."""
        mock_run = MagicMock()
        mock_run.has_failed = True
        mock_run.error_message = "Azure error"

        target, args = _parse_llm_routing_decision(mock_run, "sess_123", "Plan trip")

        assert target == RouteTarget.WORKFLOW_TURN
        assert args["message"] == "Plan trip"
        assert args["session_ref"]["session_id"] == "sess_123"

    def test_parse_completed_no_tools_defaults_to_answer_question(self) -> None:
        """Test completed run without tool calls defaults to answer_question."""
        mock_run = MagicMock()
        mock_run.has_failed = False
        mock_run.is_completed = True
        mock_run.tool_calls = []

        target, args = _parse_llm_routing_decision(mock_run, "sess_123", "question")

        assert target == RouteTarget.ANSWER_QUESTION
        assert args["question"] == "question"

    def test_parse_workflow_turn_fills_missing_session_ref(self) -> None:
        """Test that missing session_ref is filled in for workflow_turn."""
        mock_tool_call = MagicMock()
        mock_tool_call.name = "workflow_turn"
        mock_tool_call.arguments = {"message": "test"}  # No session_ref

        mock_run = MagicMock()
        mock_run.has_failed = False
        mock_run.is_completed = False
        mock_run.tool_calls = [mock_tool_call]

        target, args = _parse_llm_routing_decision(mock_run, "sess_456", "test")

        assert target == RouteTarget.WORKFLOW_TURN
        assert args["session_ref"]["session_id"] == "sess_456"

    def test_parse_workflow_turn_fills_missing_message(self) -> None:
        """Test that missing message is filled in for workflow_turn."""
        mock_tool_call = MagicMock()
        mock_tool_call.name = "workflow_turn"
        mock_tool_call.arguments = {"session_ref": {"session_id": "x"}}  # No message

        mock_run = MagicMock()
        mock_run.has_failed = False
        mock_run.is_completed = False
        mock_run.tool_calls = [mock_tool_call]

        target, args = _parse_llm_routing_decision(
            mock_run, "sess_456", "original message"
        )

        assert target == RouteTarget.WORKFLOW_TURN
        assert args["message"] == "original message"


# =============================================================================
# ROUTE RESULT TESTS
# =============================================================================


class TestRouteResult:
    """Tests for RouteResult dataclass."""

    def test_route_result_layer_1a(self) -> None:
        """Test RouteResult for Layer 1a."""
        state = MagicMock()
        result = RouteResult(
            target=RouteTarget.WORKFLOW_TURN,
            layer="1a",
            state=state,
            tool_args={"session_ref": {"session_id": "test"}},
        )

        assert result.target == RouteTarget.WORKFLOW_TURN
        assert result.layer == "1a"
        assert result.state is state
        assert result.utility_match is None
        assert result.llm_run is None

    def test_route_result_layer_1b(self) -> None:
        """Test RouteResult for Layer 1b."""
        match = UtilityMatch(
            target=RouteTarget.CURRENCY_CONVERT,
            args=("100", "USD", "EUR"),
            pattern_name="currency",
        )
        result = RouteResult(
            target=RouteTarget.CURRENCY_CONVERT,
            layer="1b",
            utility_match=match,
            tool_args={"amount": 100, "from_currency": "USD", "to_currency": "EUR"},
        )

        assert result.target == RouteTarget.CURRENCY_CONVERT
        assert result.layer == "1b"
        assert result.utility_match is match
        assert result.state is None

    def test_route_result_layer_1c(self) -> None:
        """Test RouteResult for Layer 1c."""
        mock_run = MagicMock()
        result = RouteResult(
            target=RouteTarget.ANSWER_QUESTION,
            layer="1c",
            llm_run=mock_run,
            tool_args={"question": "test"},
        )

        assert result.target == RouteTarget.ANSWER_QUESTION
        assert result.layer == "1c"
        assert result.llm_run is mock_run


# =============================================================================
# UTILITY PATTERNS TESTS
# =============================================================================


class TestUtilityPatterns:
    """Tests for UTILITY_PATTERNS constant."""

    def test_all_patterns_have_target(self) -> None:
        """Test all utility patterns have a valid target."""
        for name, (pattern, target) in UTILITY_PATTERNS.items():
            assert isinstance(pattern, str)
            assert isinstance(target, RouteTarget)

    def test_patterns_count(self) -> None:
        """Test we have expected number of patterns."""
        assert len(UTILITY_PATTERNS) == 5  # currency, weather, timezone, booking, consultation


# =============================================================================
# ROUTE TARGET TESTS
# =============================================================================


class TestRouteTarget:
    """Tests for RouteTarget enum."""

    def test_route_target_values(self) -> None:
        """Test RouteTarget enum values."""
        assert RouteTarget.WORKFLOW_TURN.value == "workflow_turn"
        assert RouteTarget.ANSWER_QUESTION.value == "answer_question"
        assert RouteTarget.CURRENCY_CONVERT.value == "currency_convert"
        assert RouteTarget.WEATHER_LOOKUP.value == "weather_lookup"
        assert RouteTarget.TIMEZONE_INFO.value == "timezone_info"
        assert RouteTarget.GET_BOOKING.value == "get_booking"
        assert RouteTarget.GET_CONSULTATION.value == "get_consultation"

    def test_route_target_is_string(self) -> None:
        """Test RouteTarget.value returns string value."""
        assert RouteTarget.WORKFLOW_TURN.value == "workflow_turn"
