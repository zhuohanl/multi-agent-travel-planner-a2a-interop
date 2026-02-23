"""
Unit tests for LangGraph hosted agents (Dining agent).

Tests verify:
- agent.yaml is valid and defines correct hosted agent configuration
- main.py imports existing agent logic correctly and uses LangGraph patterns
- Dockerfile builds configuration is correct
- requirements.txt includes required LangGraph packages
- deploy.py handles hosted agent type with langgraph framework correctly

Design doc references:
- Appendix A.2 lines 1527-1646: Hosted Agents patterns
- Agent Distribution lines 64-97: Dining agent as Hosted Agent (LC)
"""

from pathlib import Path

import pytest
import yaml

# Root paths
INTEROP_ROOT = Path(__file__).parent.parent.parent.parent.parent / "interoperability"
FOUNDRY_ROOT = INTEROP_ROOT / "foundry"
DINING_AGENT_DIR = FOUNDRY_ROOT / "agents" / "dining"


class TestDiningAgentYaml:
    """Tests for Dining agent.yaml configuration."""

    @pytest.fixture
    def agent_yaml(self) -> dict:
        """Load the Dining agent.yaml file."""
        agent_yaml_path = DINING_AGENT_DIR / "agent.yaml"
        assert agent_yaml_path.exists(), f"agent.yaml not found at {agent_yaml_path}"
        with open(agent_yaml_path) as f:
            return yaml.safe_load(f)

    def test_dining_agent_yaml_valid(self, agent_yaml: dict) -> None:
        """Test that Dining agent.yaml is valid YAML with required fields."""
        assert "name" in agent_yaml
        assert "type" in agent_yaml
        assert agent_yaml["type"] == "hosted"

    def test_dining_agent_yaml_has_framework(self, agent_yaml: dict) -> None:
        """Test that Dining agent.yaml specifies langgraph framework."""
        assert "framework" in agent_yaml
        assert agent_yaml["framework"] == "langgraph"

    def test_dining_agent_yaml_has_container_config(self, agent_yaml: dict) -> None:
        """Test that Dining agent.yaml has container configuration."""
        assert "container" in agent_yaml
        container = agent_yaml["container"]
        assert "image" in container
        assert "cpu" in container
        assert "memory" in container

    def test_dining_agent_yaml_has_protocol(self, agent_yaml: dict) -> None:
        """Test that Dining agent.yaml defines the responses protocol."""
        assert "protocol" in agent_yaml
        protocols = agent_yaml["protocol"]
        assert len(protocols) > 0
        # Should support responses protocol
        protocol_names = [p.get("protocol") for p in protocols]
        assert "responses" in protocol_names


class TestDiningMainPy:
    """Tests for Dining main.py entry point."""

    def test_dining_main_exists(self) -> None:
        """Test that main.py exists."""
        main_path = DINING_AGENT_DIR / "main.py"
        assert main_path.exists(), f"main.py not found at {main_path}"

    def test_dining_main_imports_existing_logic(self) -> None:
        """Test that main.py references shared Dining prompt + models."""
        main_path = DINING_AGENT_DIR / "main.py"
        content = main_path.read_text()

        # Should load the shared dining prompt
        assert "load_prompt" in content
        assert "dining" in content
        # Should reference DiningResponse for structured output
        assert "DiningResponse" in content

    def test_dining_uses_langgraph_patterns(self) -> None:
        """Test that main.py uses LangGraph patterns."""
        main_path = DINING_AGENT_DIR / "main.py"
        content = main_path.read_text()

        # Should import LangGraph components
        assert "langgraph" in content
        assert "StateGraph" in content

        # Should define a state type with MessagesState
        assert "MessagesState" in content

    def test_dining_uses_langgraph_adapter(self) -> None:
        """Test that main.py uses the LangGraph hosted adapter."""
        main_path = DINING_AGENT_DIR / "main.py"
        content = main_path.read_text()

        # Should use the hosted adapter
        assert "LangGraphAdapter" in content

    def test_dining_main_has_entry_point(self) -> None:
        """Test that main.py has a main entry point."""
        main_path = DINING_AGENT_DIR / "main.py"
        content = main_path.read_text()

        # Should have a main function
        assert "def main(" in content
        # Should be runnable as script
        assert "__name__" in content and "__main__" in content


class TestDiningDockerfile:
    """Tests for Dining Dockerfile."""

    def test_dining_dockerfile_exists(self) -> None:
        """Test that Dockerfile exists."""
        dockerfile_path = DINING_AGENT_DIR / "Dockerfile"
        assert dockerfile_path.exists(), f"Dockerfile not found at {dockerfile_path}"

    def test_dining_dockerfile_has_python_base(self) -> None:
        """Test that Dockerfile uses Python base image."""
        dockerfile_path = DINING_AGENT_DIR / "Dockerfile"
        content = dockerfile_path.read_text()

        # Should use Python base image
        assert "FROM python:" in content

    def test_dining_dockerfile_exposes_port(self) -> None:
        """Test that Dockerfile exposes the agent server port."""
        dockerfile_path = DINING_AGENT_DIR / "Dockerfile"
        content = dockerfile_path.read_text()

        # Should expose port 8088 (agent server default)
        assert "EXPOSE" in content
        assert "8088" in content

    def test_dining_dockerfile_copies_source(self) -> None:
        """Test that Dockerfile copies source agent logic."""
        dockerfile_path = DINING_AGENT_DIR / "Dockerfile"
        content = dockerfile_path.read_text()

        # Should copy src/ for "wrap, don't rewrite"
        assert "COPY src/" in content or "src" in content


class TestDiningRequirements:
    """Tests for Dining requirements.txt."""

    @pytest.fixture
    def requirements(self) -> list[str]:
        """Load requirements.txt lines."""
        req_path = DINING_AGENT_DIR / "requirements.txt"
        assert req_path.exists(), f"requirements.txt not found at {req_path}"
        with open(req_path) as f:
            # Filter out comments and empty lines
            return [
                line.strip()
                for line in f.readlines()
                if line.strip() and not line.strip().startswith("#")
            ]

    def test_dining_requirements_exists(self) -> None:
        """Test that requirements.txt exists."""
        req_path = DINING_AGENT_DIR / "requirements.txt"
        assert req_path.exists()

    def test_dining_requirements_includes_langgraph(self, requirements: list[str]) -> None:
        """Test that requirements.txt includes azure-ai-agentserver-langgraph."""
        # Look for the langgraph agent server package
        langgraph_server_found = any(
            "azure-ai-agentserver-langgraph" in req for req in requirements
        )
        assert langgraph_server_found, (
            "requirements.txt should include azure-ai-agentserver-langgraph"
        )

        # Also check for langgraph itself
        langgraph_found = any(
            req.startswith("langgraph") for req in requirements
        )
        assert langgraph_found, "requirements.txt should include langgraph"

    def test_dining_requirements_includes_core_packages(self, requirements: list[str]) -> None:
        """Test that requirements.txt includes core hosting packages."""
        # Should include azure-ai-projects
        azure_projects_found = any("azure-ai-projects" in req for req in requirements)
        assert azure_projects_found, "requirements.txt should include azure-ai-projects"

        # Should include azure-identity
        azure_identity_found = any("azure-identity" in req for req in requirements)
        assert azure_identity_found, "requirements.txt should include azure-identity"


class TestDeployPyLangGraphAgents:
    """Tests for deploy.py LangGraph hosted agent handling."""

    def test_deploy_config_parses_dining_agent(self) -> None:
        """Test that deploy.py correctly parses the Dining agent as hosted with langgraph."""
        from interoperability.foundry.deploy import FoundryDeployer

        deployer = FoundryDeployer()
        config = deployer.config

        assert "dining" in config.agents
        dining_agent = config.agents["dining"]
        assert dining_agent.agent_type == "hosted"
        assert dining_agent.framework == "langgraph"
        assert dining_agent.source == "src/agents/dining_agent"

    def test_deploy_validates_langgraph_framework(self) -> None:
        """Test that deploy.py validates framework for hosted agents."""
        from interoperability.foundry.deploy import FoundryDeployer

        # The current config is valid, so this should not raise
        deployer = FoundryDeployer()
        _ = deployer.config  # Should not raise

    def test_deploy_dry_run_shows_dining_agent(self) -> None:
        """Test that deploy.py --dry-run shows dining agent info."""
        from interoperability.foundry.deploy import FoundryDeployer

        deployer = FoundryDeployer()
        result = deployer.deploy_agent("dining", dry_run=True)

        assert result["success"] is True
        assert "DRY RUN" in result["message"]
        assert "framework: langgraph" in result["message"]

        # Check deployment info
        assert "deployment_info" in result
        info = result["deployment_info"]
        assert info["type"] == "hosted"
        assert info["framework"] == "langgraph"

    def test_deploy_dry_run_shows_hosted_info(self) -> None:
        """Test that deploy.py includes hosted_info in deployment_info for dining agent."""
        from interoperability.foundry.deploy import FoundryDeployer

        deployer = FoundryDeployer()
        result = deployer.deploy_agent("dining", dry_run=True)

        info = result["deployment_info"]
        assert "hosted_info" in info

        hosted_info = info["hosted_info"]
        assert hosted_info["framework"] == "langgraph"
        assert "deployment_steps" in hosted_info
        assert "container_spec" in hosted_info

    def test_deploy_all_includes_dining_agent(self) -> None:
        """Test that deploy_all includes the Dining agent."""
        from interoperability.foundry.deploy import FoundryDeployer

        deployer = FoundryDeployer()
        results = deployer.deploy_all(dry_run=True)

        assert "dining" in results["agents"]
        dining_result = results["agents"]["dining"]
        assert dining_result["success"] is True
