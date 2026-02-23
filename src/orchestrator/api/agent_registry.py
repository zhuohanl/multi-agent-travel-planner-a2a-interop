"""Agent registry management for the orchestrator API."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from src.shared.a2a.registry import AgentRegistry

logger = logging.getLogger(__name__)

DEFAULT_CUSTOM_AGENTS_FILE = Path(__file__).resolve().parents[3] / "custom_agents.json"

DISCOVERY_AGENT_IDS = {"clarifier", "transport", "stay", "poi", "events", "dining"}
PLANNING_AGENT_IDS = {"aggregator", "budget", "route", "validator"}


@dataclass(frozen=True)
class _AgentRecord:
    """Internal record used to combine built-in and custom agents."""

    agent_id: str
    name: str
    url: str
    agent_type: str
    is_custom: bool
    card: dict[str, Any] | None = None


class AgentRegistryApi:
    """Provides agent registry CRUD and health status APIs."""

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        orchestrator_url: str,
        custom_agents_file: Path | None = None,
        builtin_registry: AgentRegistry | None = None,
    ) -> None:
        self._http_client = http_client
        self._orchestrator_url = self._normalize_url(orchestrator_url)
        self._custom_agents_file = custom_agents_file or DEFAULT_CUSTOM_AGENTS_FILE
        self._builtin_registry = builtin_registry or AgentRegistry.load()

        self._custom_agents: dict[str, dict[str, Any]] = {}
        self._status_by_agent: dict[str, str] = {}
        self._last_activity_by_agent: dict[str, str] = {}

        self._health_task: asyncio.Task[None] | None = None
        self._health_loop_running = False

        self._load_custom_agents()

    async def start_health_checks(self, interval_seconds: int = 10) -> None:
        """Start periodic health checks for all known agents."""
        if self._health_task is not None and not self._health_task.done():
            return

        self._health_loop_running = True
        await self.refresh_health_statuses()
        self._health_task = asyncio.create_task(self._health_loop(interval_seconds))

    async def stop_health_checks(self) -> None:
        """Stop periodic health checks."""
        self._health_loop_running = False
        if self._health_task is None:
            return

        self._health_task.cancel()
        try:
            await self._health_task
        except asyncio.CancelledError:
            pass
        finally:
            self._health_task = None

    async def list_agents(self) -> list[dict[str, Any]]:
        """Return all known agents (built-in + custom)."""
        agents = self._all_agents()
        payload = [self._record_to_response(record) for record in agents]
        payload.sort(key=lambda item: (item["type"], item["agentId"]))
        return payload

    async def get_agent_card(self, agent_id: str) -> dict[str, Any]:
        """Fetch and return an agent card by agent id."""
        record = self._find_agent(agent_id)
        if record is None:
            raise KeyError(f"Unknown agent: {agent_id}")

        try:
            card = await self._fetch_agent_card(record.url)
        except ValueError:
            cached = record.card or {}
            if cached:
                return self._normalize_agent_card(cached, record.url, record.name)
            raise

        if record.is_custom:
            self._custom_agents[record.agent_id]["card"] = card
            self._save_custom_agents()

        return self._normalize_agent_card(card, record.url, record.name)

    async def add_custom_agent(self, name: str, url: str) -> dict[str, Any]:
        """Validate and add a custom agent."""
        normalized_url = self._normalize_url(url)
        card = await self._fetch_agent_card(normalized_url)
        card_name = card.get("name")
        effective_name = card_name if isinstance(card_name, str) and card_name else name

        agent_id = self._generate_custom_agent_id(effective_name)
        if self._find_agent(agent_id) is not None:
            raise ValueError(f"Agent id already exists: {agent_id}")

        self._custom_agents[agent_id] = {
            "agent_id": agent_id,
            "name": effective_name,
            "url": normalized_url,
            "card": card,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save_custom_agents()

        self._status_by_agent[agent_id] = await self._probe_health(normalized_url)
        if self._status_by_agent[agent_id] == "online":
            self._last_activity_by_agent[agent_id] = datetime.now(timezone.utc).isoformat()

        record = self._find_agent(agent_id)
        if record is None:
            raise RuntimeError("Custom agent added but not retrievable")
        return self._record_to_response(record)

    async def remove_custom_agent(self, agent_id: str) -> bool:
        """Remove a custom agent by id."""
        if agent_id not in self._custom_agents:
            raise KeyError(f"Custom agent not found: {agent_id}")

        del self._custom_agents[agent_id]
        self._save_custom_agents()
        self._status_by_agent.pop(agent_id, None)
        self._last_activity_by_agent.pop(agent_id, None)
        return True

    async def refresh_health_statuses(self) -> None:
        """Refresh health status for all known agents."""
        records = self._all_agents()
        probes = [self._probe_health(record.url) for record in records]
        statuses = await asyncio.gather(*probes, return_exceptions=True)

        now_iso = datetime.now(timezone.utc).isoformat()
        for record, status in zip(records, statuses, strict=False):
            if isinstance(status, Exception):
                logger.debug("Health probe failed for %s: %s", record.agent_id, status)
                self._status_by_agent[record.agent_id] = "offline"
                continue

            self._status_by_agent[record.agent_id] = status
            if status == "online":
                self._last_activity_by_agent[record.agent_id] = now_iso

    async def _health_loop(self, interval_seconds: int) -> None:
        while self._health_loop_running:
            try:
                await asyncio.sleep(interval_seconds)
                if not self._health_loop_running:
                    break
                await self.refresh_health_statuses()
            except asyncio.CancelledError:
                break
            except Exception:  # pragma: no cover - defensive guard
                logger.exception("Health check loop failed")

    async def _probe_health(self, agent_url: str) -> str:
        health_url = f"{self._normalize_url(agent_url)}/health"
        try:
            response = await self._http_client.get(health_url, timeout=5.0)
            return "online" if response.status_code == 200 else "offline"
        except Exception:
            return "offline"

    async def _fetch_agent_card(self, agent_url: str) -> dict[str, Any]:
        card_url = f"{self._normalize_url(agent_url)}/.well-known/agent.json"
        try:
            response = await self._http_client.get(card_url, timeout=8.0)
        except Exception as exc:
            raise ValueError(f"Failed to fetch agent card: {exc}") from exc

        if response.status_code != 200:
            raise ValueError(
                f"Agent card request failed for {card_url} with status {response.status_code}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError(f"Agent card is not valid JSON: {exc}") from exc

        if not isinstance(payload, dict):
            raise ValueError("Agent card payload must be a JSON object")
        return payload

    def _all_agents(self) -> list[_AgentRecord]:
        records: list[_AgentRecord] = []
        records.append(
            _AgentRecord(
                agent_id="orchestrator",
                name="Orchestrator",
                url=self._orchestrator_url,
                agent_type="orchestrator",
                is_custom=False,
                card=None,
            )
        )

        for agent_id in self._builtin_registry.list_agents():
            config = self._builtin_registry.get(agent_id)
            records.append(
                _AgentRecord(
                    agent_id=agent_id,
                    name=self._humanize_name(agent_id),
                    url=self._normalize_url(config.url),
                    agent_type=self._classify_agent_type(agent_id, is_custom=False),
                    is_custom=False,
                    card=None,
                )
            )

        for agent_id, custom in self._custom_agents.items():
            records.append(
                _AgentRecord(
                    agent_id=agent_id,
                    name=str(custom.get("name") or self._humanize_name(agent_id)),
                    url=self._normalize_url(str(custom.get("url", ""))),
                    agent_type="custom",
                    is_custom=True,
                    card=custom.get("card") if isinstance(custom.get("card"), dict) else None,
                )
            )
        return records

    def _find_agent(self, agent_id: str) -> _AgentRecord | None:
        for record in self._all_agents():
            if record.agent_id == agent_id:
                return record
        return None

    def _record_to_response(self, record: _AgentRecord) -> dict[str, Any]:
        capabilities = self._extract_capabilities(record.card, record.agent_id)
        status = self._status_by_agent.get(record.agent_id, "unknown")
        payload: dict[str, Any] = {
            "agentId": record.agent_id,
            "name": record.name,
            "type": record.agent_type,
            "status": status,
            "url": record.url,
            "capabilities": capabilities,
        }
        last_activity = self._last_activity_by_agent.get(record.agent_id)
        if last_activity:
            payload["lastActivity"] = last_activity
        return payload

    def _normalize_agent_card(
        self,
        card: dict[str, Any],
        url: str,
        fallback_name: str,
    ) -> dict[str, Any]:
        skills_raw = card.get("skills")
        skills: list[dict[str, Any]] = []
        if isinstance(skills_raw, list):
            for skill in skills_raw:
                if not isinstance(skill, dict):
                    continue
                skill_id = skill.get("id")
                skill_name = skill.get("name")
                skill_desc = skill.get("description")
                skill_tags = skill.get("tags")
                skills.append(
                    {
                        "id": str(skill_id) if skill_id is not None else "",
                        "name": str(skill_name) if skill_name is not None else "",
                        "description": str(skill_desc) if skill_desc is not None else "",
                        "tags": skill_tags if isinstance(skill_tags, list) else [],
                    }
                )

        capabilities_raw = card.get("capabilities")
        capabilities: dict[str, bool] = {}
        if isinstance(capabilities_raw, dict):
            capabilities = {str(key): bool(value) for key, value in capabilities_raw.items()}

        return {
            "name": str(card.get("name") or fallback_name),
            "description": str(card.get("description") or ""),
            "version": str(card.get("version") or "unknown"),
            "url": str(card.get("url") or url),
            "protocolVersion": str(
                card.get("protocolVersion") or card.get("protocol_version") or "unknown"
            ),
            "skills": skills,
            "capabilities": capabilities,
            "defaultInputModes": self._ensure_str_list(
                card.get("defaultInputModes") or card.get("default_input_modes")
            ),
            "defaultOutputModes": self._ensure_str_list(
                card.get("defaultOutputModes") or card.get("default_output_modes")
            ),
        }

    def _generate_custom_agent_id(self, name: str) -> str:
        base = self._slugify(name) or "custom-agent"
        candidate = base
        suffix = 2
        while self._find_agent(candidate) is not None:
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate

    def _extract_capabilities(self, card: dict[str, Any] | None, fallback: str) -> list[str]:
        if card and isinstance(card.get("skills"), list):
            names: list[str] = []
            for skill in card["skills"]:
                if not isinstance(skill, dict):
                    continue
                name = skill.get("name") or skill.get("id")
                if isinstance(name, str) and name:
                    names.append(name)
            if names:
                return names
        return [fallback]

    def _load_custom_agents(self) -> None:
        if not self._custom_agents_file.exists():
            self._custom_agents = {}
            return

        try:
            payload = json.loads(self._custom_agents_file.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.warning("Failed to load custom agents file: %s", exc)
            self._custom_agents = {}
            return

        if isinstance(payload, dict):
            self._custom_agents = {
                str(key): value
                for key, value in payload.items()
                if isinstance(value, dict)
            }
        else:
            self._custom_agents = {}

    def _save_custom_agents(self) -> None:
        self._custom_agents_file.parent.mkdir(parents=True, exist_ok=True)
        self._custom_agents_file.write_text(
            json.dumps(self._custom_agents, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _normalize_url(url: str) -> str:
        return url.rstrip("/")

    @staticmethod
    def _slugify(value: str) -> str:
        lowered = value.strip().lower()
        lowered = re.sub(r"[^a-z0-9]+", "-", lowered)
        return lowered.strip("-")

    @staticmethod
    def _ensure_str_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if isinstance(item, (str, int, float))]

    @staticmethod
    def _humanize_name(agent_id: str) -> str:
        return agent_id.replace("_", " ").title()

    @staticmethod
    def _classify_agent_type(agent_id: str, *, is_custom: bool) -> str:
        if is_custom:
            return "custom"
        if agent_id == "orchestrator":
            return "orchestrator"
        if agent_id in DISCOVERY_AGENT_IDS:
            return "discovery"
        if agent_id in PLANNING_AGENT_IDS:
            return "planning"
        if agent_id == "booking":
            return "booking"
        return "custom"
