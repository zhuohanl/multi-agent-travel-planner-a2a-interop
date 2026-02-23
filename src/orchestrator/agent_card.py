"""
AgentCard definition for the Travel Planner Orchestrator.

The AgentCard declares the orchestrator's capabilities per the A2A protocol.
This enables automatic discovery and capability negotiation by clients.

Skills map to the 7 tools available to the orchestrator (per design doc):
- workflow_turn (implicitly via plan_trip skill)
- answer_question (answer_travel_question skill)
- currency_convert (convert_currency skill)
- weather_lookup (lookup_weather skill)
- timezone_info (lookup_timezone skill)
- get_booking (get_booking skill)
- get_consultation (get_consultation skill)
"""

from a2a.types import AgentCapabilities, AgentCard, AgentSkill

AGENT_NAME = "Travel Planner Orchestrator"
AGENT_VERSION = "1.0.0"
AGENT_DESCRIPTION = (
    "Central orchestrator for multi-agent travel planning. "
    "Routes user requests to appropriate tools and workflows, "
    "manages trip planning conversations, and coordinates "
    "with specialized agents for discovery, planning, and booking."
)


def build_orchestrator_skills() -> list[AgentSkill]:
    """Build the list of skills for the orchestrator AgentCard.

    Returns:
        List of AgentSkill objects describing orchestrator capabilities.
    """
    return [
        AgentSkill(
            id="plan_trip",
            name="Plan Trip",
            description="Start or continue a trip planning workflow",
            tags=["orchestrator", "trip-planning", "workflow"],
            examples=[
                "I want to plan a trip to Tokyo",
                "Help me plan a vacation to Paris for 2 people",
                "I need to travel from Melbourne to Fiji next month",
            ],
        ),
        AgentSkill(
            id="answer_travel_question",
            name="Answer Travel Question",
            description="Answer travel-related questions with or without context",
            tags=["orchestrator", "qa", "travel-info"],
            examples=[
                "What's Tokyo like in spring?",
                "What are the best neighborhoods to stay in Paris?",
                "Is March a good time to visit Japan?",
            ],
        ),
        AgentSkill(
            id="convert_currency",
            name="Convert Currency",
            description="Convert amounts between currencies",
            tags=["orchestrator", "utility", "currency"],
            examples=[
                "Convert 100 USD to EUR",
                "How much is 5000 JPY in dollars?",
            ],
        ),
        AgentSkill(
            id="lookup_weather",
            name="Lookup Weather",
            description="Get weather forecast for a location",
            tags=["orchestrator", "utility", "weather"],
            examples=[
                "What's the weather in Tokyo?",
                "Weather forecast for Paris next week",
            ],
        ),
        AgentSkill(
            id="lookup_timezone",
            name="Lookup Timezone",
            description="Get timezone information for a location",
            tags=["orchestrator", "utility", "timezone"],
            examples=[
                "What timezone is Tokyo in?",
                "Time difference between New York and London",
            ],
        ),
        AgentSkill(
            id="get_booking",
            name="Get Booking",
            description="Retrieve booking details by booking_id",
            tags=["orchestrator", "booking", "query"],
            examples=[
                "Show me booking book_abc123",
                "What's the status of my hotel booking?",
            ],
        ),
        AgentSkill(
            id="get_consultation",
            name="Get Consultation",
            description="Retrieve consultation details by consultation_id",
            tags=["orchestrator", "consultation", "query"],
            examples=[
                "Show me consultation cons_xyz789",
                "What's in my travel plan?",
            ],
        ),
    ]


def build_orchestrator_agent_card(host: str, port: int) -> AgentCard:
    """Build the AgentCard for the Travel Planner Orchestrator.

    The AgentCard is served at /.well-known/agent.json and declares the
    orchestrator's capabilities to clients following the A2A protocol.

    Args:
        host: The hostname where the orchestrator is running.
        port: The port number where the orchestrator is running.

    Returns:
        AgentCard with orchestrator metadata and skills.
    """
    capabilities = AgentCapabilities(streaming=True)
    skills = build_orchestrator_skills()

    return AgentCard(
        name=AGENT_NAME,
        description=AGENT_DESCRIPTION,
        url=f"http://{host}:{port}/",
        version=AGENT_VERSION,
        defaultInputModes=["text"],
        defaultOutputModes=["text"],
        capabilities=capabilities,
        skills=skills,
    )


# Skill IDs for reference
ORCHESTRATOR_SKILL_IDS = [
    "plan_trip",
    "answer_travel_question",
    "convert_currency",
    "lookup_weather",
    "lookup_timezone",
    "get_booking",
    "get_consultation",
]
