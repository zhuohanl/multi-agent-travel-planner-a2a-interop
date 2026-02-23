import logging
from collections.abc import AsyncIterable
from typing import Any

from agent_framework import ChatAgent, TextContent
from agent_framework import BaseChatClient
from agent_framework._types import ChatMessage
from agent_framework._threads import ChatMessageStore

from src.shared.chat_services import ChatServices, get_chat_completion_service
from src.shared.utils.load_prompt import load_prompt

logger = logging.getLogger(__name__)


class BaseAgentFrameworkAgent:
    """Shared Agent Framework wrapper with session/thread management."""

    def __init__(self, service: ChatServices | None = None):
        chat_service = get_chat_completion_service(
            service or ChatServices.AZURE_OPENAI
        )
        self.agent = self.build_chat_agent(chat_service)
        self.session_threads: dict[str, Any] = {}
        # Track last_seen_seq per session for divergence detection (ORCH-009)
        # Key: session_id, Value: last sequence number we successfully processed
        self._session_last_seen_seq: dict[str, int] = {}
        # History parameters for divergence detection (ORCH-008/009)
        # These are set per-request in _ensure_thread_exists
        self._current_history: list[dict] | None = None
        self._current_history_seq: int | None = None

    def build_chat_agent(self, chat_service: BaseChatClient) -> ChatAgent:
        agent_kwargs: dict[str, Any] = {
            "name": self.get_agent_name(),
            "instructions": self.get_instructions(),
            "response_format": self.get_response_format(),
        }
        tools = self.get_tools()
        if tools:
            agent_kwargs["tools"] = tools

        agent_kwargs.update(self.get_chat_agent_kwargs())
        return ChatAgent(chat_client=chat_service, **agent_kwargs)

    def get_agent_name(self) -> str:
        raise NotImplementedError("Subclasses must provide an agent name.")

    def get_prompt_name(self) -> str:
        raise NotImplementedError("Subclasses must provide a prompt name.")

    def get_instructions(self) -> str:
        return load_prompt(self.get_prompt_name())

    def get_response_format(self) -> Any:
        return None

    def get_tools(self) -> list[Any]:
        return []

    def get_chat_agent_kwargs(self) -> dict[str, Any]:
        return {}

    def parse_response(self, message: Any) -> dict[str, Any]:
        raise NotImplementedError("Subclasses must parse agent responses.")

    def build_error_response(self, error: Exception) -> dict[str, Any]:
        """Build a safe fallback payload when the underlying chat service fails."""
        logger.error("Agent execution failed: %s", error, exc_info=True)
        return {
            "is_task_complete": False,
            "require_user_input": True,
            "content": "We are unable to process your request at the moment. Please try again.",
            "data": {"error": str(error)},
        }

    async def invoke(
        self,
        user_input: str,
        session_id: str,
        history: list[dict] | None = None,
        history_seq: int | None = None,
    ) -> dict[str, Any]:
        """Handle synchronous tasks (like tasks/send).

        Args:
            user_input: The user's message to process.
            session_id: Unique identifier for the conversation session.
            history: Optional conversation history from orchestrator for divergence detection.
            history_seq: Optional sequence number for divergence detection.
                         Per design doc: client is authoritative, agents compare with last_seen_seq.
        """
        await self._ensure_thread_exists(session_id, history=history, history_seq=history_seq)

        try:
            response = await self.agent.run(
                messages=user_input,
                thread=self.session_threads[session_id],
            )
            return self.parse_response(response.text)
        except Exception as exc:
            return self.build_error_response(exc)

    async def stream(
        self,
        user_input: str,
        session_id: str,
        history: list[dict] | None = None,
        history_seq: int | None = None,
    ) -> AsyncIterable[dict[str, Any]]:
        """Yield a final structured response after streaming completes.

        Args:
            user_input: The user's message to process.
            session_id: Unique identifier for the conversation session.
            history: Optional conversation history from orchestrator for divergence detection.
            history_seq: Optional sequence number for divergence detection.
                         Per design doc: client is authoritative, agents compare with last_seen_seq.
        """
        await self._ensure_thread_exists(session_id, history=history, history_seq=history_seq)

        chunks: list[TextContent] = []
        try:
            async for chunk in self.agent.run_stream(
                messages=user_input,
                thread=self.session_threads[session_id],
            ):
                if chunk.text:
                    chunks.append(chunk.text)

            if chunks:
                combined_text = "".join(str(chunk) for chunk in chunks)
                yield self.parse_response(combined_text)
        except Exception as exc:
            yield self.build_error_response(exc)

    def _check_divergence(self, session_id: str, history_seq: int | None) -> bool:
        """Check if there's a divergence between client and server state.

        Per design doc (Agent Communication section):
        - Compare history_seq (from client) with last_seen_seq (our tracked value)
        - Divergence means the sequences don't match
        - On divergence, we should invalidate cache and rebuild from client history

        Args:
            session_id: Unique identifier for the conversation session.
            history_seq: Sequence number sent by client (orchestrator).

        Returns:
            True if divergence detected, False otherwise.
        """
        # If no history_seq provided, no divergence detection is possible
        if history_seq is None:
            return False

        # Get our last tracked sequence for this session
        last_seen_seq = self._session_last_seen_seq.get(session_id)

        # If we have no prior record, this is a new session - no divergence
        if last_seen_seq is None:
            return False

        # Check if sequences match
        if last_seen_seq != history_seq:
            logger.warning(
                "Context divergence detected for session_id=%s: "
                "cached last_seen_seq=%d, client sent history_seq=%d. "
                "Client history is authoritative - will rebuild.",
                session_id,
                last_seen_seq,
                history_seq,
            )
            return True

        return False

    async def _rebuild_thread_from_history(
        self,
        session_id: str,
        history: list[dict],
    ) -> None:
        """Rebuild thread state from client-provided history.

        Per design doc (Agent Communication section):
        - This is called when divergence is detected
        - Client (orchestrator) history is authoritative
        - Invalidate existing thread and rebuild from history

        The history is expected to contain messages with 'role' and 'content' fields.
        Valid roles are 'user' and 'assistant'. Messages are added to the thread
        in the order they appear in the history list to preserve conversation flow.

        Args:
            session_id: Unique identifier for the conversation session.
            history: Conversation history from orchestrator (authoritative).
                     Each message should have 'role' ('user' or 'assistant') and 'content'.
        """
        logger.info(
            "Rebuilding thread from history for session_id=%s: %d messages",
            session_id,
            len(history),
        )

        # Create a new thread (invalidates the old one)
        new_thread = self.agent.get_new_thread(thread_id=session_id)

        # If history is empty, just create a fresh thread
        if not history:
            logger.debug(
                "Empty history provided for session_id=%s, creating fresh thread",
                session_id,
            )
            self.session_threads[session_id] = new_thread
            return

        # Create a message store and populate it with history
        message_store = ChatMessageStore()
        chat_messages: list[ChatMessage] = []

        for i, msg in enumerate(history):
            role = msg.get("role")
            content = msg.get("content", "")

            # Validate role - only 'user' and 'assistant' are valid for conversation history
            if role not in ("user", "assistant"):
                logger.warning(
                    "Skipping message %d with invalid role '%s' for session_id=%s",
                    i,
                    role,
                    session_id,
                )
                continue

            # Create ChatMessage with the role and content
            chat_message = ChatMessage(role=role, text=content)
            chat_messages.append(chat_message)

        # Add all messages to the store in order
        if chat_messages:
            await message_store.add_messages(chat_messages)
            logger.debug(
                "Added %d messages to thread for session_id=%s",
                len(chat_messages),
                session_id,
            )

        # Assign the populated message store to the thread
        new_thread.message_store = message_store

        # Store the rebuilt thread
        self.session_threads[session_id] = new_thread

        logger.info(
            "Thread rebuilt successfully for session_id=%s with %d messages",
            session_id,
            len(chat_messages),
        )

    def get_last_seen_seq(self, session_id: str) -> int | None:
        """Get the last_seen_seq for a session.

        This value should be echoed back in response metadata for client tracking.

        Args:
            session_id: Unique identifier for the conversation session.

        Returns:
            The last sequence number we processed for this session, or None.
        """
        return self._session_last_seen_seq.get(session_id)

    def _update_last_seen_seq(self, session_id: str, history_seq: int | None) -> None:
        """Update the last_seen_seq after processing a request.

        Args:
            session_id: Unique identifier for the conversation session.
            history_seq: The sequence number from the client request.
        """
        if history_seq is not None:
            self._session_last_seen_seq[session_id] = history_seq
            logger.debug(
                "Updated last_seen_seq for session_id=%s to %d",
                session_id,
                history_seq,
            )

    async def _ensure_thread_exists(
        self,
        session_id: str,
        history: list[dict] | None = None,
        history_seq: int | None = None,
    ) -> None:
        """Ensure the thread exists for the given session ID.

        This method handles divergence detection and recovery (ORCH-009).
        Per design doc (Agent Communication section):
        - history_seq is compared with last_seen_seq to detect divergence
        - On divergence, thread is rebuilt from client-provided history
        - last_seen_seq is updated after processing for future comparisons

        Args:
            session_id: Unique identifier for the conversation session.
            history: Optional conversation history from orchestrator.
            history_seq: Optional sequence number for divergence detection.
        """
        # Store history parameters for access by other methods
        self._current_history = history
        self._current_history_seq = history_seq

        if history is not None or history_seq is not None:
            logger.debug(
                "Received history for session_id=%s: %d messages, history_seq=%s",
                session_id,
                len(history) if history else 0,
                history_seq,
            )

        # Check for divergence if we have an existing thread
        if session_id in self.session_threads:
            diverged = self._check_divergence(session_id, history_seq)
            if diverged and history is not None:
                # Divergence detected - rebuild from client history
                await self._rebuild_thread_from_history(session_id, history)
                # Update last_seen_seq to the client's sequence
                self._update_last_seen_seq(session_id, history_seq)
                return
            elif diverged and history is None:
                # Divergence but no history provided - log warning but continue
                logger.warning(
                    "Divergence detected for session_id=%s but no history provided. "
                    "Cannot rebuild - continuing with potentially stale thread.",
                    session_id,
                )

        # Create new thread if it doesn't exist
        if session_id not in self.session_threads:
            logger.info("Creating new thread for session_id: %s", session_id)
            self.session_threads[session_id] = self.agent.get_new_thread(
                thread_id=session_id
            )
            # Initialize last_seen_seq for new sessions
            self._update_last_seen_seq(session_id, history_seq)
            return

        # Existing thread, no divergence - update last_seen_seq
        self._update_last_seen_seq(session_id, history_seq)

        logger.info("Reusing existing thread for session_id: %s", session_id)
        thread = self.session_threads[session_id]
        if thread.message_store is None:
            if thread.service_thread_id:
                logger.info(
                    "Thread uses service-managed storage: %s",
                    thread.service_thread_id,
                )
            else:
                logger.info("Thread has no message store yet")
            return
        try:
            messages = await thread.message_store.list_messages()
        except Exception as exc:
            logger.debug("Unable to list thread messages: %s", exc)
            return
        logger.info("Thread has %s messages", len(messages))
