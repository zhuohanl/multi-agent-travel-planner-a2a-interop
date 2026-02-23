"""
Unit tests for Agent Framework hosted agents (Stay agent).

Tests verify:
- agent.yaml is valid and defines correct hosted agent configuration
- main.py imports existing agent logic correctly
- Dockerfile builds configuration is correct
- requirements.txt includes required Agent Framework packages
- deploy.py handles hosted agent type correctly

Design doc references:
- Appendix A.2 lines 1527-1646: Hosted Agents patterns
- Agent Distribution lines 64-97: Stay agent as Hosted Agent (AF)
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

# Root paths
INTEROP_ROOT = Path(__file__).parent.parent.parent.parent.parent / "interoperability"
FOUNDRY_ROOT = INTEROP_ROOT / "foundry"
STAY_AGENT_DIR = FOUNDRY_ROOT / "agents" / "stay"


class TestStayAgentYaml:
    """Tests for Stay agent.yaml configuration."""

    @pytest.fixture
    def agent_yaml(self) -> dict:
        """Load the Stay agent.yaml file."""
        agent_yaml_path = STAY_AGENT_DIR / "agent.yaml"
        assert agent_yaml_path.exists(), f"agent.yaml not found at {agent_yaml_path}"
        with open(agent_yaml_path) as f:
            return yaml.safe_load(f)

    def test_stay_agent_yaml_valid(self, agent_yaml: dict) -> None:
        """Test that Stay agent.yaml is valid YAML with required fields."""
        assert "name" in agent_yaml
        assert "type" in agent_yaml
        assert agent_yaml["type"] == "hosted"

    def test_stay_agent_yaml_has_framework(self, agent_yaml: dict) -> None:
        """Test that Stay agent.yaml specifies agent_framework."""
        assert "framework" in agent_yaml
        assert agent_yaml["framework"] == "agent_framework"

    def test_stay_agent_yaml_has_container_config(self, agent_yaml: dict) -> None:
        """Test that Stay agent.yaml has container configuration."""
        assert "container" in agent_yaml
        container = agent_yaml["container"]
        assert "image" in container
        assert "cpu" in container
        assert "memory" in container

    def test_stay_agent_yaml_has_protocol(self, agent_yaml: dict) -> None:
        """Test that Stay agent.yaml defines the responses protocol."""
        assert "protocol" in agent_yaml
        protocols = agent_yaml["protocol"]
        assert len(protocols) > 0
        # Should support responses protocol
        protocol_names = [p.get("protocol") for p in protocols]
        assert "responses" in protocol_names


class TestStayMainPy:
    """Tests for Stay main.py entry point."""

    def test_stay_main_exists(self) -> None:
        """Test that main.py exists."""
        main_path = STAY_AGENT_DIR / "main.py"
        assert main_path.exists(), f"main.py not found at {main_path}"

    def test_stay_main_imports_existing_logic(self) -> None:
        """Test that main.py references the existing Stay agent logic."""
        main_path = STAY_AGENT_DIR / "main.py"
        content = main_path.read_text()

        # Should import from existing agent
        assert "src.agents.stay_agent" in content or "stay_agent" in content
        # Should reference AgentFrameworkStayAgent
        assert "AgentFrameworkStayAgent" in content

    def test_stay_uses_agent_server_handler(self) -> None:
        """Test that main.py uses the AgentServer handler pattern."""
        main_path = STAY_AGENT_DIR / "main.py"
        content = main_path.read_text()

        # Should import AgentServer
        assert "AgentServer" in content
        # Should use @server.handler decorator pattern
        assert "@server.handler" in content or "server.handler" in content

    def test_stay_main_has_entry_point(self) -> None:
        """Test that main.py has a main entry point."""
        main_path = STAY_AGENT_DIR / "main.py"
        content = main_path.read_text()

        # Should have a main function
        assert "def main(" in content
        # Should be runnable as script
        assert "__name__" in content and "__main__" in content


class TestStayDockerfile:
    """Tests for Stay Dockerfile."""

    def test_stay_dockerfile_exists(self) -> None:
        """Test that Dockerfile exists."""
        dockerfile_path = STAY_AGENT_DIR / "Dockerfile"
        assert dockerfile_path.exists(), f"Dockerfile not found at {dockerfile_path}"

    def test_stay_dockerfile_has_python_base(self) -> None:
        """Test that Dockerfile uses Python base image."""
        dockerfile_path = STAY_AGENT_DIR / "Dockerfile"
        content = dockerfile_path.read_text()

        # Should use Python base image
        assert "FROM python:" in content

    def test_stay_dockerfile_exposes_port(self) -> None:
        """Test that Dockerfile exposes the agent server port."""
        dockerfile_path = STAY_AGENT_DIR / "Dockerfile"
        content = dockerfile_path.read_text()

        # Should expose port 8088 (agent server default)
        assert "EXPOSE" in content
        assert "8088" in content

    def test_stay_dockerfile_copies_source(self) -> None:
        """Test that Dockerfile copies source agent logic."""
        dockerfile_path = STAY_AGENT_DIR / "Dockerfile"
        content = dockerfile_path.read_text()

        # Should copy src/ for "wrap, don't rewrite"
        assert "COPY src/" in content or "src" in content


class TestStayRequirements:
    """Tests for Stay requirements.txt."""

    @pytest.fixture
    def requirements(self) -> list[str]:
        """Load requirements.txt lines."""
        req_path = STAY_AGENT_DIR / "requirements.txt"
        assert req_path.exists(), f"requirements.txt not found at {req_path}"
        with open(req_path) as f:
            # Filter out comments and empty lines
            return [
                line.strip()
                for line in f.readlines()
                if line.strip() and not line.strip().startswith("#")
            ]

    def test_stay_requirements_exists(self) -> None:
        """Test that requirements.txt exists."""
        req_path = STAY_AGENT_DIR / "requirements.txt"
        assert req_path.exists()

    def test_stay_requirements_includes_agentframework(self, requirements: list[str]) -> None:
        """Test that requirements.txt includes azure-ai-agentserver-agentframework."""
        # Look for the agentframework package
        agentframework_found = any(
            "azure-ai-agentserver-agentframework" in req for req in requirements
        )
        assert agentframework_found, (
            "requirements.txt should include azure-ai-agentserver-agentframework"
        )

    def test_stay_requirements_includes_core_packages(self, requirements: list[str]) -> None:
        """Test that requirements.txt includes core hosting packages."""
        # Should include azure-ai-projects
        azure_projects_found = any("azure-ai-projects" in req for req in requirements)
        assert azure_projects_found, "requirements.txt should include azure-ai-projects"

        # Should include azure-identity
        azure_identity_found = any("azure-identity" in req for req in requirements)
        assert azure_identity_found, "requirements.txt should include azure-identity"


class TestDeployPyHostedAgents:
    """Tests for deploy.py hosted agent handling."""

    def test_deploy_config_parses_stay_agent(self) -> None:
        """Test that deploy.py correctly parses the Stay agent as hosted."""
        from interoperability.foundry.deploy import FoundryDeployer

        deployer = FoundryDeployer()
        config = deployer.config

        assert "stay" in config.agents
        stay_agent = config.agents["stay"]
        assert stay_agent.agent_type == "hosted"
        assert stay_agent.framework == "agent_framework"
        assert stay_agent.source == "src/agents/stay_agent"

    def test_deploy_validates_hosted_framework(self) -> None:
        """Test that deploy.py validates framework for hosted agents."""
        from interoperability.foundry.deploy import ConfigParseError, FoundryDeployer

        # The current config is valid, so this should not raise
        deployer = FoundryDeployer()
        _ = deployer.config  # Should not raise

    def test_deploy_dry_run_shows_hosted_agent(self) -> None:
        """Test that deploy.py --dry-run shows hosted agent info."""
        from interoperability.foundry.deploy import FoundryDeployer

        deployer = FoundryDeployer()
        result = deployer.deploy_agent("stay", dry_run=True)

        assert result["success"] is True
        assert "DRY RUN" in result["message"]
        assert "framework: agent_framework" in result["message"]

        # Check deployment info
        assert "deployment_info" in result
        info = result["deployment_info"]
        assert info["type"] == "hosted"
        assert info["framework"] == "agent_framework"

    def test_deploy_dry_run_shows_hosted_info(self) -> None:
        """Test that deploy.py includes hosted_info in deployment_info."""
        from interoperability.foundry.deploy import FoundryDeployer

        deployer = FoundryDeployer()
        result = deployer.deploy_agent("stay", dry_run=True)

        info = result["deployment_info"]
        assert "hosted_info" in info

        hosted_info = info["hosted_info"]
        assert hosted_info["framework"] == "agent_framework"
        assert "deployment_steps" in hosted_info
        assert "container_spec" in hosted_info

    def test_deploy_all_includes_stay_agent(self) -> None:
        """Test that deploy_all includes the Stay agent."""
        from interoperability.foundry.deploy import FoundryDeployer

        deployer = FoundryDeployer()
        results = deployer.deploy_all(dry_run=True)

        assert "stay" in results["agents"]
        stay_result = results["agents"]["stay"]
        assert stay_result["success"] is True
