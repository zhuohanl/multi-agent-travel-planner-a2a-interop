import logging

import httpx
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import (
    BasePushNotificationSender,
    InMemoryPushNotificationConfigStore,
    InMemoryTaskStore,
)
from a2a.types import AgentCard

logger = logging.getLogger(__name__)


class BaseA2AServer:
    """Base A2A server wiring shared across agent implementations."""

    _task_store = None
    _config_store = None
    _agent_executor = None

    def __init__(
        self, httpx_client: httpx.AsyncClient, host: str = "localhost", port: int = 8000
    ):
        self.httpx_client = httpx_client
        self.host = host
        self.port = port

        self._ensure_shared_state()
        self._setup_server()

    def _ensure_shared_state(self) -> None:
        cls = self.__class__
        if cls._task_store is None:
            cls._task_store = InMemoryTaskStore()
            cls._config_store = InMemoryPushNotificationConfigStore()
            cls._agent_executor = self.build_agent_executor()
            logger.info("Initialized shared task store and agent executor")

    def build_agent_executor(self):
        raise NotImplementedError("Subclasses must provide an agent executor.")

    def build_agent_card(self) -> AgentCard:
        raise NotImplementedError("Subclasses must provide an agent card.")

    def _setup_server(self) -> None:
        """Setup the A2A server."""
        cls = self.__class__
        push_sender = BasePushNotificationSender(
            self.httpx_client, cls._config_store
        )

        request_handler = DefaultRequestHandler(
            agent_executor=cls._agent_executor,
            task_store=cls._task_store,
            push_config_store=cls._config_store,
            push_sender=push_sender,
        )

        self.a2a_app = A2AStarletteApplication(
            agent_card=self.build_agent_card(),
            http_handler=request_handler,
        )

        logger.info("A2A server configured for %s:%s", self.host, self.port)
