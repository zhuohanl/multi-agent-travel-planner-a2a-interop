"""
Unit tests for interoperability directory structure.

These tests verify that the interoperability directory structure is set up
correctly according to the design document specifications.
"""

from pathlib import Path

import pytest

# Base path for interoperability directory
INTEROP_ROOT = Path(__file__).parent.parent.parent.parent / "interoperability"


class TestInteroperabilityRootExists:
    """Tests for the interoperability root directory."""

    def test_interoperability_root_exists(self) -> None:
        """Verify interoperability/ directory exists."""
        assert INTEROP_ROOT.exists(), "interoperability/ directory should exist"
        assert INTEROP_ROOT.is_dir(), "interoperability/ should be a directory"

    def test_readme_exists(self) -> None:
        """Verify README.md exists in interoperability root."""
        readme = INTEROP_ROOT / "README.md"
        assert readme.exists(), "interoperability/README.md should exist"

    def test_verify_auth_exists(self) -> None:
        """Verify verify_auth.py exists in interoperability root."""
        verify_auth = INTEROP_ROOT / "verify_auth.py"
        assert verify_auth.exists(), "interoperability/verify_auth.py should exist"


class TestFoundryAgentsSubdirsExist:
    """Tests for Foundry agent subdirectories."""

    @pytest.fixture
    def foundry_agents_dir(self) -> Path:
        """Return the foundry agents directory path."""
        return INTEROP_ROOT / "foundry" / "agents"

    def test_foundry_agents_dir_exists(self, foundry_agents_dir: Path) -> None:
        """Verify foundry/agents/ directory exists."""
        assert foundry_agents_dir.exists(), "foundry/agents/ directory should exist"
        assert foundry_agents_dir.is_dir(), "foundry/agents/ should be a directory"

    @pytest.mark.parametrize(
        "agent_name",
        ["transport", "poi", "events", "stay", "dining", "aggregator", "route", "weather"],
    )
    def test_agent_subdir_exists(self, foundry_agents_dir: Path, agent_name: str) -> None:
        """Verify each agent subdirectory exists."""
        agent_dir = foundry_agents_dir / agent_name
        assert agent_dir.exists(), f"foundry/agents/{agent_name}/ should exist"
        assert agent_dir.is_dir(), f"foundry/agents/{agent_name}/ should be a directory"

    def test_foundry_workflows_dir_exists(self) -> None:
        """Verify foundry/workflows/ directory exists."""
        workflows_dir = INTEROP_ROOT / "foundry" / "workflows"
        assert workflows_dir.exists(), "foundry/workflows/ directory should exist"

    @pytest.mark.parametrize(
        "workflow_name",
        ["discovery_workflow_procode", "discovery_workflow_declarative"],
    )
    def test_workflow_subdir_exists(self, workflow_name: str) -> None:
        """Verify each workflow subdirectory exists."""
        workflow_dir = INTEROP_ROOT / "foundry" / "workflows" / workflow_name
        assert workflow_dir.exists(), f"foundry/workflows/{workflow_name}/ should exist"
        assert workflow_dir.is_dir(), f"foundry/workflows/{workflow_name}/ should be a directory"

    def test_foundry_config_yaml_exists(self) -> None:
        """Verify foundry/config.yaml exists."""
        config = INTEROP_ROOT / "foundry" / "config.yaml"
        assert config.exists(), "foundry/config.yaml should exist"

    def test_foundry_deploy_py_exists(self) -> None:
        """Verify foundry/deploy.py exists."""
        deploy = INTEROP_ROOT / "foundry" / "deploy.py"
        assert deploy.exists(), "foundry/deploy.py should exist"

    def test_foundry_intake_form_exists(self) -> None:
        """Verify legacy foundry/intake_form/ directory if present."""
        intake_form = INTEROP_ROOT / "foundry" / "intake_form"
        if not intake_form.exists():
            pytest.skip("foundry/intake_form/ is not part of the current structure")
        assert intake_form.is_dir(), "foundry/intake_form/ should be a directory"


class TestCopilotStudioAgentsSubdirsExist:
    """Tests for Copilot Studio agent subdirectories."""

    @pytest.fixture
    def cs_agents_dir(self) -> Path:
        """Return the Copilot Studio agents directory path."""
        return INTEROP_ROOT / "copilot_studio" / "agents"

    def test_copilot_studio_agents_dir_exists(self, cs_agents_dir: Path) -> None:
        """Verify copilot_studio/agents/ directory exists."""
        assert cs_agents_dir.exists(), "copilot_studio/agents/ directory should exist"
        assert cs_agents_dir.is_dir(), "copilot_studio/agents/ should be a directory"

    @pytest.mark.parametrize(
        "agent_name",
        ["weather", "approval", "travel_planning_parent"],
    )
    def test_cs_agent_subdir_exists(self, cs_agents_dir: Path, agent_name: str) -> None:
        """Verify each CS agent subdirectory exists."""
        agent_dir = cs_agents_dir / agent_name
        assert agent_dir.exists(), f"copilot_studio/agents/{agent_name}/ should exist"
        assert agent_dir.is_dir(), f"copilot_studio/agents/{agent_name}/ should be a directory"

    def test_copilot_studio_config_yaml_exists(self) -> None:
        """Verify copilot_studio/config.yaml exists."""
        config = INTEROP_ROOT / "copilot_studio" / "config.yaml"
        assert config.exists(), "copilot_studio/config.yaml should exist"

    def test_copilot_studio_setup_md_exists(self) -> None:
        """Verify copilot_studio/SETUP.md exists."""
        setup = INTEROP_ROOT / "copilot_studio" / "SETUP.md"
        assert setup.exists(), "copilot_studio/SETUP.md should exist"

    def test_copilot_studio_verify_py_exists(self) -> None:
        """Verify copilot_studio/verify.py exists."""
        verify = INTEROP_ROOT / "copilot_studio" / "verify.py"
        assert verify.exists(), "copilot_studio/verify.py should exist"


class TestSharedSchemasExists:
    """Tests for shared schemas directory."""

    def test_shared_dir_exists(self) -> None:
        """Verify shared/ directory exists."""
        shared_dir = INTEROP_ROOT / "shared"
        assert shared_dir.exists(), "shared/ directory should exist"
        assert shared_dir.is_dir(), "shared/ should be a directory"

    def test_shared_schemas_exists(self) -> None:
        """Verify shared/schemas/ directory exists."""
        schemas_dir = INTEROP_ROOT / "shared" / "schemas"
        assert schemas_dir.exists(), "shared/schemas/ directory should exist"

    def test_shared_agent_wrappers_exists(self) -> None:
        """Verify shared/agent_wrappers/ directory exists."""
        wrappers_dir = INTEROP_ROOT / "shared" / "agent_wrappers"
        assert wrappers_dir.exists(), "shared/agent_wrappers/ directory should exist"

    def test_shared_agent_wrappers_init_exists(self) -> None:
        """Verify shared/agent_wrappers/__init__.py exists."""
        init_file = INTEROP_ROOT / "shared" / "agent_wrappers" / "__init__.py"
        assert init_file.exists(), "shared/agent_wrappers/__init__.py should exist"


class TestProCodeExists:
    """Tests for pro_code directory."""

    def test_pro_code_dir_exists(self) -> None:
        """Verify pro_code/ directory exists."""
        pro_code_dir = INTEROP_ROOT / "pro_code"
        assert pro_code_dir.exists(), "pro_code/ directory should exist"
        assert pro_code_dir.is_dir(), "pro_code/ should be a directory"

    def test_pro_code_config_yaml_exists(self) -> None:
        """Verify pro_code/config.yaml exists."""
        config = INTEROP_ROOT / "pro_code" / "config.yaml"
        assert config.exists(), "pro_code/config.yaml should exist"
