"""
Unit tests for agent wrapper classes.

Tests the base wrapper abstract class and platform-specific wrappers
(Foundry, MAF Hosted, LangGraph Hosted).
"""

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from interoperability.shared.agent_wrappers import (
    AgentConfig,
    BaseAgentWrapper,
    FoundryAgentWrapper,
    MAFHostedWrapper,
    LangGraphHostedWrapper,
)


class TestBaseWrapperIsAbstract:
    """Tests verifying BaseAgentWrapper is properly abstract."""

    def test_base_wrapper_cannot_be_instantiated_directly(self) -> None:
        """Verify BaseAgentWrapper cannot be instantiated."""
        config = AgentConfig(name="test", source_path=Path("test/path"))

        with pytest.raises(TypeError) as exc_info:
            BaseAgentWrapper(config)  # type: ignore[abstract]

        assert "abstract" in str(exc_info.value).lower()

    def test_base_wrapper_has_required_abstract_methods(self) -> None:
        """Verify BaseAgentWrapper defines required abstract methods."""
        assert hasattr(BaseAgentWrapper, "wrap")
        assert hasattr(BaseAgentWrapper, "get_config")
        assert hasattr(BaseAgentWrapper, "deploy")


class ConcreteWrapper(BaseAgentWrapper):
    """Concrete implementation for testing base class functionality."""

    def wrap(self) -> None:
        self._wrapped = True
        self._instructions = "Test instructions"
        self._tools = [{"kind": "test"}]

    def get_config(self) -> dict[str, Any]:
        self._ensure_wrapped()
        return {"name": self.name}

    def deploy(self, dry_run: bool = False) -> dict[str, Any]:
        self._ensure_wrapped()
        return {"success": True}


class TestBaseWrapperFunctionality:
    """Tests for BaseAgentWrapper base functionality."""

    def test_config_property(self) -> None:
        """Verify config property returns the configuration."""
        config = AgentConfig(name="test", source_path=Path("test/path"))
        wrapper = ConcreteWrapper(config)

        assert wrapper.config == config

    def test_name_property(self) -> None:
        """Verify name property returns agent name."""
        config = AgentConfig(name="test_agent", source_path=Path("test/path"))
        wrapper = ConcreteWrapper(config)

        assert wrapper.name == "test_agent"

    def test_source_path_property(self) -> None:
        """Verify source_path property returns the path."""
        config = AgentConfig(name="test", source_path=Path("test/path"))
        wrapper = ConcreteWrapper(config)

        assert wrapper.source_path == Path("test/path")

    def test_is_wrapped_false_before_wrap(self) -> None:
        """Verify is_wrapped is False before wrap() is called."""
        config = AgentConfig(name="test", source_path=Path("test/path"))
        wrapper = ConcreteWrapper(config)

        assert wrapper.is_wrapped is False

    def test_is_wrapped_true_after_wrap(self) -> None:
        """Verify is_wrapped is True after wrap() is called."""
        config = AgentConfig(name="test", source_path=Path("test/path"))
        wrapper = ConcreteWrapper(config)
        wrapper.wrap()

        assert wrapper.is_wrapped is True

    def test_ensure_wrapped_raises_before_wrap(self) -> None:
        """Verify _ensure_wrapped raises if wrap() not called."""
        config = AgentConfig(name="test", source_path=Path("test/path"))
        wrapper = ConcreteWrapper(config)

        with pytest.raises(RuntimeError) as exc_info:
            wrapper.get_config()

        assert "has not been wrapped" in str(exc_info.value)

    def test_ensure_wrapped_succeeds_after_wrap(self) -> None:
        """Verify _ensure_wrapped succeeds after wrap() called."""
        config = AgentConfig(name="test", source_path=Path("test/path"))
        wrapper = ConcreteWrapper(config)
        wrapper.wrap()

        # Should not raise
        result = wrapper.get_config()
        assert result == {"name": "test"}


class TestFoundryWrapperInitialization:
    """Tests for FoundryAgentWrapper initialization."""

    def test_foundry_wrapper_initialization(self) -> None:
        """Verify FoundryAgentWrapper can be initialized."""
        config = AgentConfig(
            name="transport",
            source_path=Path("src/agents/transport_agent"),
            agent_type="native",
            model="gpt-4.1-mini",
        )

        wrapper = FoundryAgentWrapper(config)

        assert wrapper.name == "transport"
        assert wrapper.config.agent_type == "native"
        assert wrapper.is_wrapped is False

    def test_foundry_wrapper_tool_mapping_defined(self) -> None:
        """Verify FoundryAgentWrapper has tool mapping."""
        assert "HostedWebSearchTool" in FoundryAgentWrapper.TOOL_MAPPING
        assert FoundryAgentWrapper.TOOL_MAPPING["HostedWebSearchTool"] == {"kind": "bing_grounding"}


class TestMAFHostedWrapperInitialization:
    """Tests for MAFHostedWrapper initialization."""

    def test_maf_hosted_wrapper_initialization(self) -> None:
        """Verify MAFHostedWrapper can be initialized."""
        config = AgentConfig(
            name="stay",
            source_path=Path("src/agents/stay_agent"),
            agent_type="hosted",
            framework="agent_framework",
        )

        wrapper = MAFHostedWrapper(config)

        assert wrapper.name == "stay"
        assert wrapper.config.framework == "agent_framework"
        assert wrapper.is_wrapped is False

    def test_maf_hosted_wrapper_default_requirements(self) -> None:
        """Verify MAFHostedWrapper has default requirements."""
        assert "azure-ai-agentserver-agentframework" in MAFHostedWrapper.DEFAULT_REQUIREMENTS


class TestLangGraphHostedWrapperInitialization:
    """Tests for LangGraphHostedWrapper initialization."""

    def test_langgraph_hosted_wrapper_initialization(self) -> None:
        """Verify LangGraphHostedWrapper can be initialized."""
        config = AgentConfig(
            name="dining",
            source_path=Path("src/agents/dining_agent"),
            agent_type="hosted",
            framework="langgraph",
        )

        wrapper = LangGraphHostedWrapper(config)

        assert wrapper.name == "dining"
        assert wrapper.config.framework == "langgraph"
        assert wrapper.is_wrapped is False

    def test_langgraph_hosted_wrapper_default_requirements(self) -> None:
        """Verify LangGraphHostedWrapper has LangGraph requirements."""
        assert "azure-ai-agentserver-langgraph" in LangGraphHostedWrapper.DEFAULT_REQUIREMENTS
        assert "langgraph>=0.2" in LangGraphHostedWrapper.DEFAULT_REQUIREMENTS


class TestWrappersCanImportSharedModels:
    """Tests verifying wrappers can work with shared models."""

    def test_wrappers_can_import_shared_models(self) -> None:
        """Verify shared models can be imported."""
        # This test verifies the import path works
        from src.shared.models import TripSpec, TransportResponse

        # Verify the models exist
        assert TripSpec is not None
        assert TransportResponse is not None

    def test_agent_config_dataclass_fields(self) -> None:
        """Verify AgentConfig has all required fields."""
        config = AgentConfig(
            name="test",
            source_path=Path("test/path"),
            agent_type="native",
            framework="agent_framework",
            model="gpt-4.1-mini",
            tools=["tool1"],
            env_vars=["VAR1"],
        )

        assert config.name == "test"
        assert config.source_path == Path("test/path")
        assert config.agent_type == "native"
        assert config.framework == "agent_framework"
        assert config.model == "gpt-4.1-mini"
        assert config.tools == ["tool1"]
        assert config.env_vars == ["VAR1"]


class TestFoundryWrapperWithRealAgent:
    """Tests for FoundryAgentWrapper with real agent code."""

    def test_foundry_wrapper_wrap_with_real_agent(self) -> None:
        """Test wrapping a real agent from src/agents/."""
        config = AgentConfig(
            name="transport",
            source_path=Path("src/agents/transport_agent"),
            agent_type="native",
            model="gpt-4.1-mini",
        )

        wrapper = FoundryAgentWrapper(config)
        wrapper.wrap()

        # Should have extracted instructions and tools
        assert wrapper.is_wrapped is True
        assert wrapper.instructions is not None
        assert len(wrapper.instructions) > 0

    def test_foundry_wrapper_maps_hosted_web_search_tool(self) -> None:
        """Verify HostedWebSearchTool is mapped to bing_grounding."""
        config = AgentConfig(
            name="transport",
            source_path=Path("src/agents/transport_agent"),
            agent_type="native",
        )

        wrapper = FoundryAgentWrapper(config)
        wrapper.wrap()

        # Transport agent uses HostedWebSearchTool
        assert {"kind": "bing_grounding"} in wrapper.tools

    def test_foundry_wrapper_get_config_includes_tools(self) -> None:
        """Verify get_config includes tools section."""
        config = AgentConfig(
            name="transport",
            source_path=Path("src/agents/transport_agent"),
            agent_type="native",
        )

        wrapper = FoundryAgentWrapper(config)
        wrapper.wrap()
        agent_config = wrapper.get_config()

        assert "tools" in agent_config
        assert {"kind": "bing_grounding"} in agent_config["tools"]


class TestMAFHostedWrapperWithRealAgent:
    """Tests for MAFHostedWrapper with real agent code."""

    def test_maf_wrapper_wrap_with_real_agent(self) -> None:
        """Test wrapping a real agent from src/agents/."""
        config = AgentConfig(
            name="stay",
            source_path=Path("src/agents/stay_agent"),
            agent_type="hosted",
            framework="agent_framework",
        )

        wrapper = MAFHostedWrapper(config)
        wrapper.wrap()

        assert wrapper.is_wrapped is True

    def test_maf_wrapper_get_config_generates_artifacts(self) -> None:
        """Verify get_config generates all required artifacts."""
        config = AgentConfig(
            name="stay",
            source_path=Path("src/agents/stay_agent"),
            agent_type="hosted",
            framework="agent_framework",
        )

        wrapper = MAFHostedWrapper(config)
        wrapper.wrap()
        artifacts = wrapper.get_config()

        assert "agent_yaml" in artifacts
        assert "main_py" in artifacts
        assert "dockerfile" in artifacts
        assert "requirements_txt" in artifacts

    def test_maf_wrapper_dockerfile_contains_agent_server(self) -> None:
        """Verify Dockerfile contains agent server setup."""
        config = AgentConfig(
            name="stay",
            source_path=Path("src/agents/stay_agent"),
            agent_type="hosted",
        )

        wrapper = MAFHostedWrapper(config)
        wrapper.wrap()
        artifacts = wrapper.get_config()

        assert "main.py" in artifacts["dockerfile"]
        assert "EXPOSE 8080" in artifacts["dockerfile"]


class TestLangGraphHostedWrapperWithRealAgent:
    """Tests for LangGraphHostedWrapper with real agent code."""

    def test_langgraph_wrapper_wrap_with_real_agent(self) -> None:
        """Test wrapping a real agent from src/agents/."""
        config = AgentConfig(
            name="dining",
            source_path=Path("src/agents/dining_agent"),
            agent_type="hosted",
            framework="langgraph",
        )

        wrapper = LangGraphHostedWrapper(config)
        wrapper.wrap()

        assert wrapper.is_wrapped is True

    def test_langgraph_wrapper_get_config_generates_artifacts(self) -> None:
        """Verify get_config generates all required artifacts."""
        config = AgentConfig(
            name="dining",
            source_path=Path("src/agents/dining_agent"),
            agent_type="hosted",
            framework="langgraph",
        )

        wrapper = LangGraphHostedWrapper(config)
        wrapper.wrap()
        artifacts = wrapper.get_config()

        assert "agent_yaml" in artifacts
        assert "main_py" in artifacts
        assert "dockerfile" in artifacts
        assert "requirements_txt" in artifacts

    def test_langgraph_wrapper_main_py_contains_graph(self) -> None:
        """Verify main.py contains LangGraph patterns."""
        config = AgentConfig(
            name="dining",
            source_path=Path("src/agents/dining_agent"),
            agent_type="hosted",
        )

        wrapper = LangGraphHostedWrapper(config)
        wrapper.wrap()
        artifacts = wrapper.get_config()

        assert "StateGraph" in artifacts["main_py"]
        assert "workflow.compile()" in artifacts["main_py"]
