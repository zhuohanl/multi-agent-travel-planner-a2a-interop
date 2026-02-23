"""
Foundry Agent Deployment Script

Deploys all agents and workflows defined in config.yaml to Azure AI Foundry.

Usage:
    python deploy.py --dry-run              # Preview what would be deployed
    python deploy.py --deploy               # Execute deployment
    python deploy.py --deploy --agent NAME  # Deploy specific agent
    python deploy.py --validate             # Validate config only

Prerequisites:
    - Azure CLI logged in (`az login`)
    - Resource group exists
    - Foundry project created
    - For hosted agents: ACR configured with pull permissions

Design doc references:
    - Directory Structure section lines 964-966: deploy.py deploys all Foundry agents + workflow
    - Example config.yaml lines 1120-1200: Agent definitions schema
    - Appendix A.1 lines 1441-1525: AIProjectClient, agents.create_version, PromptAgentDefinition
    - Cross-Platform Authentication lines 975-1000: COPILOTSTUDIOAGENT__* env vars, Key Vault references
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from dotenv import load_dotenv

load_dotenv()

from interoperability.foundry.extract_agent import (
    ExtractionError,
    extract_agent_for_foundry,
)

if TYPE_CHECKING:
    from azure.ai.projects import AIProjectClient
    from azure.ai.projects.models import Agent


# Default model deployment name from environment
DEFAULT_MODEL = os.environ.get(
    "AZURE_AI_MODEL_DEPLOYMENT_NAME",
    os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4.1"),
)


@dataclass
class AgentDefinition:
    """Parsed agent definition from config.yaml."""

    name: str
    agent_type: str  # "native" or "hosted"
    source: str
    model: str = field(default_factory=lambda: DEFAULT_MODEL)
    framework: str | None = None  # For hosted: "agent_framework" or "langgraph"
    description: str = ""
    env_vars: list[str] = field(default_factory=list)


@dataclass
class WorkflowDefinition:
    """Parsed workflow definition from config.yaml."""

    name: str
    workflow_type: str  # "hosted_workflow" or "declarative"
    source: str
    description: str = ""
    agents: list[str] = field(default_factory=list)
    env_vars: list[str] = field(default_factory=list)


@dataclass
class FoundryConfig:
    """Parsed Foundry configuration."""

    platform: str
    resource_group: str
    project: str
    agents: dict[str, AgentDefinition]
    workflows: dict[str, WorkflowDefinition]


class ConfigParseError(Exception):
    """Error parsing configuration file."""

    pass


class DeploymentError(Exception):
    """Error during deployment."""

    pass


class FoundryDeployer:
    """Deploys agents and workflows to Azure AI Foundry.

    This class provides the main deployment interface:
    - deploy_agent(): Deploy a single agent
    - deploy_workflow(): Deploy a workflow
    - deploy_all(): Deploy all agents and workflows
    - validate(): Validate configuration without deploying

    Environment variables can reference Key Vault secrets using the syntax:
        @Microsoft.KeyVault(SecretUri=https://your-vault.vault.azure.net/secrets/secret-name)

    Prerequisites documented in DEPLOY.md.
    """

    # Key Vault reference pattern
    KEYVAULT_PATTERN = re.compile(
        r"@Microsoft\.KeyVault\(SecretUri=([^)]+)\)"
    )

    def __init__(self, config_path: Path | None = None):
        """Initialize the deployer.

        Args:
            config_path: Path to config.yaml. Defaults to foundry/config.yaml.
        """
        if config_path is None:
            config_path = Path(__file__).parent / "config.yaml"

        self.config_path = config_path
        self._config: FoundryConfig | None = None

    @property
    def config(self) -> FoundryConfig:
        """Get the parsed configuration, loading if necessary."""
        if self._config is None:
            self._config = self._parse_config()
        return self._config

    def _parse_config(self) -> FoundryConfig:
        """Parse and validate config.yaml.

        Returns:
            Parsed configuration.

        Raises:
            ConfigParseError: If configuration is invalid.
        """
        if not self.config_path.exists():
            raise ConfigParseError(f"Config file not found: {self.config_path}")

        try:
            with open(self.config_path) as f:
                raw_config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ConfigParseError(f"Invalid YAML in config file: {e}")

        # Validate required top-level fields
        required_fields = ["platform", "resource_group", "project"]
        for field_name in required_fields:
            if field_name not in raw_config:
                raise ConfigParseError(f"Missing required field: {field_name}")

        # Expand environment variables in string values
        platform = self._expand_env_vars(raw_config["platform"])
        resource_group = self._expand_env_vars(raw_config["resource_group"])
        project = self._expand_env_vars(raw_config["project"])

        # Parse agents
        agents: dict[str, AgentDefinition] = {}
        raw_agents = raw_config.get("agents", {})
        for name, agent_config in raw_agents.items():
            agents[name] = self._parse_agent(name, agent_config)

        # Parse workflows
        workflows: dict[str, WorkflowDefinition] = {}
        raw_workflows = raw_config.get("workflows", {})
        for name, workflow_config in raw_workflows.items():
            workflows[name] = self._parse_workflow(name, workflow_config)

        return FoundryConfig(
            platform=platform,
            resource_group=resource_group,
            project=project,
            agents=agents,
            workflows=workflows,
        )

    def _parse_agent(self, name: str, config: dict[str, Any]) -> AgentDefinition:
        """Parse a single agent definition.

        Args:
            name: Agent name.
            config: Raw agent configuration.

        Returns:
            Parsed agent definition.

        Raises:
            ConfigParseError: If agent configuration is invalid.
        """
        if "type" not in config:
            raise ConfigParseError(f"Agent '{name}' missing required field: type")
        if "source" not in config:
            raise ConfigParseError(f"Agent '{name}' missing required field: source")

        agent_type = config["type"]
        if agent_type not in ("native", "hosted"):
            raise ConfigParseError(
                f"Agent '{name}' has invalid type: {agent_type}. "
                "Must be 'native' or 'hosted'."
            )

        framework = config.get("framework")
        if agent_type == "hosted" and framework not in ("agent_framework", "langgraph", "custom"):
            raise ConfigParseError(
                f"Hosted agent '{name}' missing or invalid framework. "
                "Must be 'agent_framework', 'langgraph', or 'custom'."
            )

        return AgentDefinition(
            name=name,
            agent_type=agent_type,
            source=self._expand_env_vars(config["source"]),
            model=self._expand_env_vars(config.get("model", DEFAULT_MODEL)),
            framework=framework,
            description=self._expand_env_vars(config.get("description", "")),
            env_vars=config.get("env_vars", []),
        )

    def _parse_workflow(
        self, name: str, config: dict[str, Any]
    ) -> WorkflowDefinition:
        """Parse a single workflow definition.

        Args:
            name: Workflow name.
            config: Raw workflow configuration.

        Returns:
            Parsed workflow definition.

        Raises:
            ConfigParseError: If workflow configuration is invalid.
        """
        if "type" not in config:
            raise ConfigParseError(f"Workflow '{name}' missing required field: type")
        if "source" not in config:
            raise ConfigParseError(f"Workflow '{name}' missing required field: source")

        workflow_type = config["type"]
        if workflow_type not in ("hosted_workflow", "declarative"):
            raise ConfigParseError(
                f"Workflow '{name}' has invalid type: {workflow_type}. "
                "Must be 'hosted_workflow' or 'declarative'."
            )

        return WorkflowDefinition(
            name=name,
            workflow_type=workflow_type,
            source=self._expand_env_vars(config["source"]),
            description=self._expand_env_vars(config.get("description", "")),
            agents=config.get("agents", []),
            env_vars=config.get("env_vars", []),
        )

    def _get_env(self, *names: str) -> str | None:
        """Get the first non-empty environment variable value from a list."""
        for name in names:
            value = os.environ.get(name)
            if value:
                return value
        return None

    def _expand_env_vars(self, value: str) -> str:
        """Expand environment variables in a string.

        Supports ${VAR_NAME} and ${VAR_NAME:-default} syntax.

        Args:
            value: String potentially containing environment variable references.

        Returns:
            String with environment variables expanded.
        """
        if not isinstance(value, str):
            return value

        # Find ${VAR_NAME} or ${VAR_NAME:-default} patterns and expand them
        pattern = re.compile(r"\$\{([^}:]+)(?::-(.+?))?\}")

        def replace(match: re.Match[str]) -> str:
            var_name = match.group(1)
            default_value = match.group(2)
            value = os.environ.get(var_name)
            if value is not None:
                return value
            if default_value is not None:
                return default_value
            return match.group(0)

        return pattern.sub(replace, value)

    def _extract_unresolved_env_vars(self, value: str) -> list[str]:
        """Extract unresolved env var placeholders from a string."""
        pattern = re.compile(r"\$\{([^}:]+)(?::-[^}]+)?\}")
        return [match.group(1) for match in pattern.finditer(value)]

    def _resolve_hosted_env_vars(self, env_vars: dict[str, Any]) -> dict[str, Any]:
        """Resolve env var values for hosted agent definitions."""
        resolved: dict[str, Any] = {}
        missing: set[str] = set()

        for name, value in env_vars.items():
            if value is None:
                missing.add(name)
                continue
            if isinstance(value, str):
                if self._is_keyvault_reference(value):
                    resolved[name] = value
                    continue
                expanded = self._expand_env_vars(value)
                unresolved = self._extract_unresolved_env_vars(expanded)
                if unresolved:
                    missing.update(unresolved)
                resolved[name] = expanded
            else:
                resolved[name] = value

        if missing:
            missing_list = ", ".join(sorted(missing))
            raise DeploymentError(
                "Hosted agent environment variables reference missing values: "
                f"{missing_list}"
            )

        return resolved

    def _find_hosted_agent_dir(self, agent: AgentDefinition) -> Path:
        """Find the directory containing hosted agent deployment files."""
        source_path = Path(agent.source)
        candidates = [
            source_path,
            Path(__file__).parent / "agents" / agent.name,
        ]
        for candidate in candidates:
            if (candidate / "agent.yaml").exists():
                return candidate
        return source_path

    def _load_hosted_agent_yaml(self, agent: AgentDefinition) -> dict[str, Any]:
        """Load hosted agent.yaml for deployment details."""
        agent_dir = self._find_hosted_agent_dir(agent)
        agent_yaml_path = agent_dir / "agent.yaml"
        if not agent_yaml_path.exists():
            raise DeploymentError(
                f"Hosted agent.yaml not found at {agent_yaml_path}"
            )
        with open(agent_yaml_path) as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise DeploymentError(
                f"Invalid agent.yaml format in {agent_yaml_path}"
            )
        return data

    def _parse_hosted_protocols(self, raw: dict[str, Any]) -> list[Any]:
        """Parse protocol versions for hosted agent deployment."""
        from azure.ai.projects.models import ProtocolVersionRecord, AgentProtocol

        protocols = (
            raw.get("protocol")
            or raw.get("protocols")
            or raw.get("template", {}).get("protocols")
        )
        if not protocols:
            return [
                ProtocolVersionRecord(
                    protocol=AgentProtocol.RESPONSES,
                    version="v1",
                )
            ]

        parsed: list[Any] = []
        for entry in protocols:
            if not isinstance(entry, dict):
                continue
            protocol_name = str(entry.get("protocol", "")).lower()
            version = str(entry.get("version", "v1"))
            if protocol_name == "responses":
                parsed.append(
                    ProtocolVersionRecord(
                        protocol=AgentProtocol.RESPONSES,
                        version=version,
                    )
                )

        if not parsed:
            parsed.append(
                ProtocolVersionRecord(
                    protocol=AgentProtocol.RESPONSES,
                    version="v1",
                )
            )

        return parsed

    def _parse_project_endpoint(self) -> tuple[str, str]:
        """Extract account name and project name from the project endpoint.

        Endpoint format: https://<account>.services.ai.azure.com/api/projects/<project>

        Returns:
            Tuple of (account_name, project_name).

        Raises:
            DeploymentError: If endpoint is not set or cannot be parsed.
        """
        endpoint = self._get_env("AZURE_AI_PROJECT_ENDPOINT", "PROJECT_ENDPOINT")
        if not endpoint:
            raise DeploymentError("AZURE_AI_PROJECT_ENDPOINT not set")

        match = re.match(
            r"https://([^.]+)\.services\.ai\.azure\.com/api/projects/([^/]+)",
            endpoint,
        )
        if not match:
            raise DeploymentError(
                f"Cannot parse account/project from endpoint: {endpoint}"
            )
        return match.group(1), match.group(2)

    def _start_hosted_agent(self, agent_name: str, agent_version: str) -> bool:
        """Start a hosted agent deployment using az CLI.

        Args:
            agent_name: Name of the hosted agent.
            agent_version: Version of the hosted agent.

        Returns:
            True if the agent was started successfully, False otherwise.
        """
        import subprocess

        account_name, project_name = self._parse_project_endpoint()

        cmd = [
            "az", "cognitiveservices", "agent", "start",
            "--account-name", account_name,
            "--project-name", project_name,
            "--name", agent_name,
            "--agent-version", str(agent_version),
        ]

        print(f"[INFO] Starting hosted agent '{agent_name}' (version {agent_version})...")
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                shell=True,  # az may be a .cmd (Windows) or shell wrapper (macOS/Linux)
            )
            if result.returncode == 0:
                print(f"[INFO] Successfully started hosted agent '{agent_name}'")
                return True
            else:
                print(
                    f"[WARN] Failed to start hosted agent '{agent_name}': "
                    f"{result.stderr.strip() or result.stdout.strip()}"
                )
                return False
        except subprocess.TimeoutExpired:
            print(f"[WARN] Timed out starting hosted agent '{agent_name}'")
            return False
        except FileNotFoundError:
            print("[WARN] 'az' CLI not found. Start the hosted agent manually via: "
                  f"az cognitiveservices agent start --account-name {account_name} "
                  f"--project-name {project_name} --name {agent_name} "
                  f"--agent-version {agent_version}")
            return False

    def _deploy_hosted_agent(self, agent: AgentDefinition) -> dict[str, Any]:
        """Deploy a hosted agent to Foundry using ImageBasedHostedAgentDefinition."""
        from azure.ai.projects.models import ImageBasedHostedAgentDefinition

        client = self._create_project_client()
        hosted_yaml = self._load_hosted_agent_yaml(agent)

        container = hosted_yaml.get("container") or hosted_yaml.get("template", {}).get("container") or {}
        image = container.get("image")
        if not image:
            raise DeploymentError("Hosted agent container.image is required in agent.yaml")
        image = self._expand_env_vars(str(image))
        unresolved_image_vars = self._extract_unresolved_env_vars(image)
        if unresolved_image_vars:
            missing_vars = ", ".join(sorted(set(unresolved_image_vars)))
            raise DeploymentError(
                "Hosted agent container.image references missing env vars: "
                f"{missing_vars}"
            )

        cpu = str(container.get("cpu", "1"))
        memory = str(container.get("memory", "2Gi"))

        env_vars = hosted_yaml.get("environment", {})
        if not isinstance(env_vars, dict):
            env_vars = {}

        # Support sample-style environment_variables list.
        # Note: entries here overwrite any same-named keys from the "environment" section above.
        env_list = hosted_yaml.get("environment_variables") or hosted_yaml.get("template", {}).get("environment_variables")
        if isinstance(env_list, list):
            for item in env_list:
                if isinstance(item, dict) and "name" in item:
                    env_vars[item["name"]] = item.get("value", "")

        resolved_env = self._resolve_hosted_env_vars(env_vars)
        protocol_versions = self._parse_hosted_protocols(hosted_yaml)

        print(f"[INFO] Deploying hosted agent '{agent.name}' with image: {image}")
        if resolved_env:
            print(f"[INFO] Hosted agent env vars: {', '.join(sorted(resolved_env.keys()))}")

        definition = ImageBasedHostedAgentDefinition(
            container_protocol_versions=protocol_versions,
            cpu=cpu,
            memory=memory,
            image=image,
            environment_variables=resolved_env,
        )

        created_agent: Agent = client.agents.create_version(
            agent_name=agent.name,
            definition=definition,
            description=agent.description or hosted_yaml.get("description") or None,
        )

        return {
            "agent_id": created_agent.id,
            "agent_name": created_agent.name,
            "agent_version": created_agent.version,
        }

    def _validate_env_vars(self, agent: AgentDefinition) -> list[str]:
        """Validate that required environment variables exist.

        Args:
            agent: Agent definition with env_vars list.

        Returns:
            List of missing environment variable names.
        """
        missing = []
        for var_name in agent.env_vars:
            if var_name not in os.environ:
                missing.append(var_name)
        return missing

    def _is_keyvault_reference(self, value: str) -> bool:
        """Check if a value is a Key Vault reference.

        Args:
            value: Value to check.

        Returns:
            True if the value is a Key Vault reference.
        """
        return bool(self.KEYVAULT_PATTERN.match(value))

    def _resolve_keyvault_reference(self, value: str) -> str:
        """Resolve a Key Vault reference to its secret value.

        Note: In production, this would use Azure SDK to fetch the secret.
        For now, this returns the reference unchanged (Foundry handles resolution).

        Args:
            value: Key Vault reference string.

        Returns:
            The resolved secret value or the original reference.
        """
        # Foundry handles Key Vault references at runtime
        # We just pass them through
        return value

    def _create_project_client(self) -> AIProjectClient:
        """Create an AIProjectClient for deploying to Foundry.

        Uses AZURE_AI_PROJECT_ENDPOINT (or PROJECT_ENDPOINT) and DefaultAzureCredential.

        Returns:
            Configured AIProjectClient instance.

        Raises:
            DeploymentError: If PROJECT_ENDPOINT is not set or client creation fails.
        """
        from azure.ai.projects import AIProjectClient
        from azure.identity import DefaultAzureCredential

        project_endpoint = self._get_env(
            "AZURE_AI_PROJECT_ENDPOINT", "PROJECT_ENDPOINT"
        )
        if not project_endpoint:
            raise DeploymentError(
                "AZURE_AI_PROJECT_ENDPOINT (or PROJECT_ENDPOINT) environment "
                "variable not set. Set it to your Foundry project endpoint, e.g., "
                "https://<resource-name>.services.ai.azure.com/api/projects/<project-name>"
            )

        try:
            client = AIProjectClient(
                endpoint=project_endpoint,
                credential=DefaultAzureCredential(),
            )
            return client
        except Exception as e:
            raise DeploymentError(
                f"Failed to create AIProjectClient: {e}. "
                "Ensure you are logged in with 'az login' and have access to the project."
            )

    def _build_bing_grounding_tool(self) -> Any:
        """Build a Bing grounding tool definition using SDK models."""
        from azure.ai.projects.models import (
            BingGroundingAgentTool,
            BingGroundingSearchConfiguration,
            BingGroundingSearchToolParameters,
        )

        connection_id = self._get_env("BING_PROJECT_CONNECTION_ID")
        if not connection_id:
            raise DeploymentError(
                "BING_PROJECT_CONNECTION_ID environment variable is required "
                "for bing_grounding tools."
            )

        search_config = BingGroundingSearchConfiguration(
            project_connection_id=connection_id
        )
        params = BingGroundingSearchToolParameters(
            search_configurations=[search_config]
        )
        return BingGroundingAgentTool(bing_grounding=params)

    def _deploy_native_agent(
        self,
        agent: AgentDefinition,
        instructions: str,
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Deploy a native MFA agent to Foundry using AIProjectClient.

        Uses agents.create_version() with PromptAgentDefinition per design doc
        Appendix A.1 lines 1487-1494.

        Args:
            agent: Agent definition from config.
            instructions: Extracted system prompt/instructions.
            tools: List of tool configurations (e.g., [{"kind": "bing_grounding"}]).

        Returns:
            Dictionary with agent id, name, and version on success.

        Raises:
            DeploymentError: If deployment fails.
        """
        from azure.ai.projects.models import PromptAgentDefinition

        client = self._create_project_client()

        try:
            tools_payload: list[Any] = []
            for tool in tools:
                tool_payload: Any = tool
                if isinstance(tool, dict):
                    if "type" not in tool and "kind" in tool:
                        tool_payload = dict(tool)
                        tool_payload["type"] = tool_payload.pop("kind")
                    if tool_payload.get("type") == "bing_grounding":
                        tool_payload = self._build_bing_grounding_tool()
                tools_payload.append(tool_payload)

            # Build the agent definition using SDK models
            definition = PromptAgentDefinition(
                model=agent.model,
                instructions=instructions,
                tools=tools_payload,
            )

            # Debug: print what we're sending
            print(f"[DEBUG] Creating agent '{agent.name}' with model '{agent.model}'")
            print(f"[DEBUG] Instructions length: {len(instructions)} chars")

            # Create the agent version
            created_agent: Agent = client.agents.create_version(
                agent_name=agent.name,
                definition=definition,
                description=agent.description or None,
            )

            # Debug: print the full response object
            print(f"[DEBUG] Response object type: {type(created_agent)}")
            print(f"[DEBUG] Response attributes: {vars(created_agent) if hasattr(created_agent, '__dict__') else 'N/A'}")
            print(f"[DEBUG] Agent ID: {created_agent.id}")
            print(f"[DEBUG] Agent name: {created_agent.name}")
            print(f"[DEBUG] Agent version: {created_agent.version}")

            return {
                "agent_id": created_agent.id,
                "agent_name": created_agent.name,
                "agent_version": created_agent.version,
            }
        except Exception as e:
            raise DeploymentError(
                f"Failed to deploy agent '{agent.name}': {e}. "
                "Check your Azure credentials and project permissions."
            )

    def _validate_workflow_env_vars(self, workflow: WorkflowDefinition) -> list[str]:
        """Validate that required environment variables for a workflow exist.

        Args:
            workflow: Workflow definition with env_vars list.

        Returns:
            List of missing environment variable names.
        """
        missing = []
        for var_name in workflow.env_vars:
            if var_name not in os.environ:
                missing.append(var_name)
        return missing

    def validate(self) -> dict[str, Any]:
        """Validate the configuration without deploying.

        Returns:
            Validation result with any issues found.
        """
        issues: list[str] = []
        warnings: list[str] = []

        try:
            config = self.config
        except ConfigParseError as e:
            return {
                "valid": False,
                "issues": [str(e)],
                "warnings": [],
            }

        # Check for missing env vars in agents that require them
        for name, agent in config.agents.items():
            missing = self._validate_env_vars(agent)
            if missing:
                warnings.append(
                    f"Agent '{name}' requires env vars not currently set: {missing}"
                )

        # Check hosted agent.yaml environment vars (needed at deploy time)
        for name, agent in config.agents.items():
            if agent.agent_type != "hosted":
                continue
            try:
                hosted_yaml = self._load_hosted_agent_yaml(agent)
            except DeploymentError:
                continue

            # Check container.image env var
            container = (
                hosted_yaml.get("container")
                or hosted_yaml.get("template", {}).get("container")
                or {}
            )
            image_ref = str(container.get("image", ""))
            image_vars = self._extract_unresolved_env_vars(image_ref)
            missing_image = [v for v in image_vars if not os.environ.get(v)]
            if missing_image:
                warnings.append(
                    f"Hosted agent '{name}' container.image references "
                    f"missing env vars: {missing_image}"
                )

            # Check environment section env vars
            env_section = hosted_yaml.get("environment", {})
            if isinstance(env_section, dict):
                missing_env: list[str] = []
                for value in env_section.values():
                    if not isinstance(value, str):
                        continue
                    for var in self._extract_unresolved_env_vars(value):
                        if not os.environ.get(var):
                            missing_env.append(var)
                if missing_env:
                    warnings.append(
                        f"Hosted agent '{name}' environment references "
                        f"missing env vars: {missing_env}"
                    )

        # Check for missing env vars in workflows that require them
        for name, workflow in config.workflows.items():
            missing = self._validate_workflow_env_vars(workflow)
            if missing:
                warnings.append(
                    f"Workflow '{name}' requires env vars not currently set: {missing}"
                )

        # Check workflow references valid agents
        for name, workflow in config.workflows.items():
            for agent_name in workflow.agents:
                if agent_name not in config.agents:
                    issues.append(
                        f"Workflow '{name}' references unknown agent: {agent_name}"
                    )

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "warnings": warnings,
            "agents": list(config.agents.keys()),
            "workflows": list(config.workflows.keys()),
        }

    def _get_hosted_agent_info(self, agent: AgentDefinition) -> dict[str, Any]:
        """Get deployment information for a hosted agent.

        Hosted agents require:
        - Container image built and pushed to ACR
        - Dockerfile, main.py, requirements.txt in source directory
        - ACR pull permissions for project's managed identity

        Args:
            agent: Agent definition with type='hosted'.

        Returns:
            Dictionary with hosted agent deployment details.
        """
        source_path = Path(agent.source)

        # Check for required files in the source directory
        required_files = ["main.py", "Dockerfile", "requirements.txt", "agent.yaml"]
        existing_files = []
        missing_files = []

        for filename in required_files:
            file_path = source_path / filename
            if file_path.exists():
                existing_files.append(filename)
            else:
                missing_files.append(filename)

        return {
            "framework": agent.framework,
            "source_path": str(source_path),
            "existing_files": existing_files,
            "missing_files": missing_files,
            "deployment_steps": [
                f"1. Build container: docker build -t {agent.name}:latest {source_path}",
                f"2. Tag for ACR: docker tag {agent.name}:latest ${{ACR_REGISTRY}}/{agent.name}:latest",
                f"3. Push to ACR: docker push ${{ACR_REGISTRY}}/{agent.name}:latest",
                f"4. Deploy to Foundry using ImageBasedHostedAgentDefinition",
            ],
            "container_spec": {
                "image": f"${{ACR_REGISTRY}}/{agent.name}:latest",
                "cpu": "1",
                "memory": "2Gi",
                "protocol": "responses/v1",
            },
        }

    def deploy_agent(
        self, agent_name: str, dry_run: bool = False
    ) -> dict[str, Any]:
        """Deploy a single agent.

        For native agents, extracts instructions and tools from source code:
        - src/agents/: Extract SYSTEM_PROMPT from prompt files, map tools
        - interoperability/: Load from prompts.py or agent.yaml

        Args:
            agent_name: Name of the agent to deploy.
            dry_run: If True, only print what would be deployed.

        Returns:
            Deployment result dictionary.

        Raises:
            DeploymentError: If agent not found or deployment fails.
        """
        config = self.config

        if agent_name not in config.agents:
            raise DeploymentError(f"Agent '{agent_name}' not found in config")

        agent = config.agents[agent_name]

        # Validate env vars
        missing_vars = self._validate_env_vars(agent)
        if missing_vars and not dry_run:
            raise DeploymentError(
                f"Agent '{agent_name}' requires missing env vars: {missing_vars}"
            )

        # Build deployment info
        deployment_info: dict[str, Any] = {
            "agent_name": agent_name,
            "type": agent.agent_type,
            "source": agent.source,
            "model": agent.model,
            "framework": agent.framework,
            "env_vars": agent.env_vars,
        }

        # For native agents, extract instructions and tools
        extraction_result: dict[str, Any] | None = None
        if agent.agent_type == "native":
            try:
                extraction_result = extract_agent_for_foundry(
                    agent_name=agent_name,
                    source_path=agent.source,
                    model=agent.model,
                    description=agent.description,
                )
                deployment_info["extracted_instructions"] = extraction_result["instructions"]
                deployment_info["extracted_tools"] = extraction_result["tools"]
                deployment_info["tool_names"] = extraction_result.get("tool_names", [])
                deployment_info["source_type"] = extraction_result["source_type"]
                deployment_info["generated_yaml"] = extraction_result["yaml"]
            except ExtractionError as e:
                if not dry_run:
                    raise DeploymentError(
                        f"Failed to extract agent '{agent_name}': {e}"
                    )
                # In dry-run, report the extraction error but continue
                deployment_info["extraction_error"] = str(e)

        # For hosted agents, gather container deployment information
        if agent.agent_type == "hosted":
            hosted_info = self._get_hosted_agent_info(agent)
            deployment_info["hosted_info"] = hosted_info

        if dry_run:
            message = f"[DRY RUN] Would deploy agent '{agent_name}'"
            if extraction_result:
                tools_desc = extraction_result["tools"]
                message += f" (tools: {tools_desc})"
            if agent.agent_type == "hosted":
                message += f" (framework: {agent.framework})"
            return {
                "success": True,
                "agent_id": None,
                "message": message,
                "deployment_info": deployment_info,
            }

        # Actual deployment using AIProjectClient
        if agent.agent_type == "native":
            if not extraction_result:
                raise DeploymentError(
                    f"Cannot deploy native agent '{agent_name}' without extracted instructions."
                )

            # Deploy using AIProjectClient
            deploy_result = self._deploy_native_agent(
                agent=agent,
                instructions=extraction_result["instructions"],
                tools=extraction_result["tools"],
            )

            return {
                "success": True,
                "agent_id": deploy_result["agent_id"],
                "agent_name": deploy_result["agent_name"],
                "agent_version": deploy_result["agent_version"],
                "message": (
                    f"Successfully deployed agent '{agent_name}' "
                    f"(id={deploy_result['agent_id']}, version={deploy_result['agent_version']})"
                ),
                "deployment_info": deployment_info,
            }
        elif agent.agent_type == "hosted":
            # Hosted agents require container build/push before deployment
            deploy_result = self._deploy_hosted_agent(agent)

            # Start the hosted agent deployment
            started = self._start_hosted_agent(
                agent_name, str(deploy_result["agent_version"])
            )

            message = (
                f"Successfully deployed hosted agent '{agent_name}' "
                f"(id={deploy_result['agent_id']}, version={deploy_result['agent_version']})"
            )
            if started:
                message += " — agent started"
            else:
                message += " — deploy succeeded but agent start failed (start manually)"

            return {
                "success": True,
                "agent_id": deploy_result["agent_id"],
                "agent_name": deploy_result["agent_name"],
                "agent_version": deploy_result["agent_version"],
                "message": message,
                "deployment_info": deployment_info,
            }
        else:
            return {
                "success": False,
                "agent_id": None,
                "message": f"Unknown agent type '{agent.agent_type}' for agent '{agent_name}'.",
                "deployment_info": deployment_info,
            }

    def _get_workflow_deployment_info(
        self, workflow: WorkflowDefinition
    ) -> dict[str, Any]:
        """Get deployment information for a hosted workflow.

        Args:
            workflow: Workflow definition with type='hosted_workflow'.

        Returns:
            Dictionary with workflow deployment details.
        """
        source_path = Path(workflow.source)

        required_files = ["Dockerfile", "requirements.txt"]
        existing_files = []
        missing_files = []

        for filename in required_files:
            file_path = source_path / filename
            if file_path.exists():
                existing_files.append(filename)
            else:
                missing_files.append(filename)

        return {
            "source_path": str(source_path),
            "existing_files": existing_files,
            "missing_files": missing_files,
            "env_vars": workflow.env_vars,
            "deployment_steps": [
                f"1. Build container: docker build -t {workflow.name}:latest -f {source_path}/Dockerfile .",
                f"2. Tag for ACR: docker tag {workflow.name}:latest ${{ACR_REGISTRY}}/{workflow.name}:latest",
                f"3. Push to ACR: docker push ${{ACR_REGISTRY}}/{workflow.name}:latest",
                f"4. Deploy to Foundry using ImageBasedHostedAgentDefinition",
            ],
        }

    def deploy_workflow(
        self, workflow_name: str, dry_run: bool = False
    ) -> dict[str, Any]:
        """Deploy a workflow.

        For hosted_workflow type: validates env vars, checks deployment files,
        and deploys as a hosted agent using ImageBasedHostedAgentDefinition.

        For declarative type: validates YAML exists in source directory.

        Args:
            workflow_name: Name of the workflow to deploy.
            dry_run: If True, only print what would be deployed.

        Returns:
            Deployment result dictionary.

        Raises:
            DeploymentError: If workflow not found or deployment fails.
        """
        config = self.config

        if workflow_name not in config.workflows:
            raise DeploymentError(f"Workflow '{workflow_name}' not found in config")

        workflow = config.workflows[workflow_name]

        # Validate env vars for hosted workflows
        missing_vars = self._validate_workflow_env_vars(workflow)
        if missing_vars and not dry_run:
            raise DeploymentError(
                f"Workflow '{workflow_name}' requires missing env vars: {missing_vars}"
            )

        deployment_info: dict[str, Any] = {
            "workflow_name": workflow_name,
            "type": workflow.workflow_type,
            "source": workflow.source,
            "agents": workflow.agents,
            "env_vars": workflow.env_vars,
        }

        # For hosted workflows, gather deployment info
        if workflow.workflow_type == "hosted_workflow":
            wf_info = self._get_workflow_deployment_info(workflow)
            deployment_info["workflow_info"] = wf_info

        if dry_run:
            message = f"[DRY RUN] Would deploy workflow '{workflow_name}'"
            if missing_vars:
                message += f" (missing env vars: {missing_vars})"
            if workflow.workflow_type == "hosted_workflow":
                wf_info = deployment_info.get("workflow_info", {})
                if wf_info.get("missing_files"):
                    message += f" (missing files: {wf_info['missing_files']})"
            return {
                "success": True,
                "workflow_id": None,
                "message": message,
                "deployment_info": deployment_info,
            }

        # Actual deployment
        if workflow.workflow_type == "hosted_workflow":
            source_path = Path(workflow.source)
            dockerfile_path = source_path / "Dockerfile"
            if not dockerfile_path.exists():
                raise DeploymentError(
                    f"Workflow '{workflow_name}' Dockerfile not found at {dockerfile_path}. "
                    "Build the container before deploying."
                )

            # Hosted workflows are deployed as hosted agents
            # Create a temporary AgentDefinition to reuse hosted agent deployment
            agent_def = AgentDefinition(
                name=workflow_name,
                agent_type="hosted",
                source=workflow.source,
                framework="agent_framework",
                description=workflow.description,
                env_vars=workflow.env_vars,
            )

            try:
                deploy_result = self._deploy_hosted_agent(agent_def)

                # Start the hosted workflow deployment
                started = self._start_hosted_agent(
                    workflow_name, str(deploy_result["agent_version"])
                )

                message = (
                    f"Successfully deployed workflow '{workflow_name}' "
                    f"(id={deploy_result['agent_id']}, version={deploy_result['agent_version']})"
                )
                if started:
                    message += " — workflow started"
                else:
                    message += " — deploy succeeded but start failed (start manually)"

                return {
                    "success": True,
                    "workflow_id": deploy_result["agent_id"],
                    "message": message,
                    "deployment_info": deployment_info,
                }
            except DeploymentError:
                raise
            except Exception as e:
                raise DeploymentError(
                    f"Failed to deploy workflow '{workflow_name}': {e}"
                )

        elif workflow.workflow_type == "declarative":
            source_path = Path(workflow.source)
            workflow_yaml = source_path / "workflow.yaml"
            if not workflow_yaml.exists():
                raise DeploymentError(
                    f"Workflow '{workflow_name}' YAML not found at {workflow_yaml}"
                )
            return {
                "success": False,
                "workflow_id": None,
                "message": (
                    f"Declarative workflow '{workflow_name}' deployment requires "
                    "portal import. Use Foundry portal to import workflow.yaml from "
                    f"{workflow.source}."
                ),
                "deployment_info": deployment_info,
            }

        return {
            "success": False,
            "workflow_id": None,
            "message": (
                f"Unknown workflow type '{workflow.workflow_type}' for '{workflow_name}'."
            ),
            "deployment_info": deployment_info,
        }

    def deploy_all(self, dry_run: bool = False) -> dict[str, Any]:
        """Deploy all agents and workflows.

        Args:
            dry_run: If True, only print what would be deployed.

        Returns:
            Combined deployment results.
        """
        results: dict[str, Any] = {
            "agents": {},
            "workflows": {},
            "summary": {
                "agents_deployed": 0,
                "agents_failed": 0,
                "workflows_deployed": 0,
                "workflows_failed": 0,
            },
        }

        config = self.config

        # Deploy all agents
        for agent_name in config.agents:
            try:
                result = self.deploy_agent(agent_name, dry_run=dry_run)
                results["agents"][agent_name] = result
                if result.get("success"):
                    results["summary"]["agents_deployed"] += 1
                else:
                    results["summary"]["agents_failed"] += 1
            except DeploymentError as e:
                results["agents"][agent_name] = {
                    "success": False,
                    "message": str(e),
                }
                results["summary"]["agents_failed"] += 1

        # Deploy all workflows
        for workflow_name in config.workflows:
            try:
                result = self.deploy_workflow(workflow_name, dry_run=dry_run)
                results["workflows"][workflow_name] = result
                if result.get("success"):
                    results["summary"]["workflows_deployed"] += 1
                else:
                    results["summary"]["workflows_failed"] += 1
            except DeploymentError as e:
                results["workflows"][workflow_name] = {
                    "success": False,
                    "message": str(e),
                }
                results["summary"]["workflows_failed"] += 1

        return results


def main() -> int:
    """Run the deployment process.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    parser = argparse.ArgumentParser(
        description="Deploy agents and workflows to Azure AI Foundry",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python deploy.py --dry-run                   # Preview all deployments
  python deploy.py --deploy                    # Deploy everything
  python deploy.py --deploy --agent transport  # Deploy specific agent
  python deploy.py --deploy --workflow discovery_procode  # Deploy workflow
  python deploy.py --validate                  # Validate config only

Environment Variables:
  AZURE_RESOURCE_GROUP         Azure resource group name
  AZURE_AI_PROJECT_ENDPOINT    Foundry project endpoint (preferred)
  PROJECT_ENDPOINT             Foundry project endpoint (legacy)
  AZURE_OPENAI_DEPLOYMENT_NAME Model deployment name
  COPILOTSTUDIOAGENT__*        Copilot Studio agent env vars (for weather proxy)

Environment Promotion (dev -> test -> prod):
  1. Set AZURE_AI_PROJECT_ENDPOINT to target environment endpoint
  2. Set AZURE_RESOURCE_GROUP to target environment resource group
  3. Run: python deploy.py --deploy
  4. Verify: python ../test_smoke.py --demo a

For more information, see DEPLOY.md.
        """,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be deployed without deploying",
    )
    parser.add_argument(
        "--deploy",
        action="store_true",
        help="Execute deployment (requires Azure credentials)",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate configuration only",
    )
    parser.add_argument(
        "--agent",
        type=str,
        help="Deploy specific agent by name",
    )
    parser.add_argument(
        "--workflow",
        type=str,
        help="Deploy specific workflow by name",
    )
    parser.add_argument(
        "--config",
        type=str,
        help="Path to config.yaml (default: foundry/config.yaml)",
    )

    args = parser.parse_args()

    # Determine config path
    config_path = Path(args.config) if args.config else None

    try:
        deployer = FoundryDeployer(config_path=config_path)
    except ConfigParseError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Validate mode
    if args.validate:
        result = deployer.validate()
        print("Configuration Validation")
        print("=" * 40)
        print(f"Valid: {result['valid']}")

        if result["issues"]:
            print("\nIssues:")
            for issue in result["issues"]:
                print(f"  - {issue}")

        if result["warnings"]:
            print("\nWarnings:")
            for warning in result["warnings"]:
                print(f"  - {warning}")

        print(f"\nAgents defined: {len(result['agents'])}")
        for agent in result["agents"]:
            print(f"  - {agent}")

        print(f"\nWorkflows defined: {len(result['workflows'])}")
        for workflow in result["workflows"]:
            print(f"  - {workflow}")

        return 0 if result["valid"] else 1

    # Deployment mode
    if not args.dry_run and not args.deploy:
        parser.print_help()
        return 1

    dry_run = args.dry_run or not args.deploy

    # Deploy specific agent
    if args.agent:
        try:
            result = deployer.deploy_agent(args.agent, dry_run=dry_run)
            print(result["message"])
            if "deployment_info" in result:
                info = result["deployment_info"]
                print(f"  Type: {info['type']}")
                print(f"  Source: {info['source']}")
                # Show extraction details for native agents
                if info["type"] == "native":
                    if "extracted_tools" in info:
                        print(f"  Tools: {info['extracted_tools']}")
                    if "source_type" in info:
                        print(f"  Source type: {info['source_type']}")
                    if "extraction_error" in info:
                        print(f"  Extraction error: {info['extraction_error']}")
                # Show hosted agent details
                if info["type"] == "hosted" and "hosted_info" in info:
                    hosted = info["hosted_info"]
                    print(f"  Framework: {hosted['framework']}")
                    if hosted["existing_files"]:
                        print(f"  Files found: {', '.join(hosted['existing_files'])}")
                    if hosted["missing_files"]:
                        print(f"  Missing files: {', '.join(hosted['missing_files'])}")
            return 0 if result.get("success") else 1
        except DeploymentError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    # Deploy specific workflow
    if args.workflow:
        try:
            result = deployer.deploy_workflow(args.workflow, dry_run=dry_run)
            print(result["message"])
            if "deployment_info" in result:
                info = result["deployment_info"]
                print(f"  Type: {info['type']}")
                print(f"  Source: {info['source']}")
                if info.get("env_vars"):
                    print(f"  Env vars: {info['env_vars']}")
                if "workflow_info" in info:
                    wf_info = info["workflow_info"]
                    if wf_info.get("existing_files"):
                        print(f"  Files found: {', '.join(wf_info['existing_files'])}")
                    if wf_info.get("missing_files"):
                        print(f"  Missing files: {', '.join(wf_info['missing_files'])}")
            return 0 if result.get("success") else 1
        except DeploymentError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    # Deploy all
    results = deployer.deploy_all(dry_run=dry_run)

    print("Deployment Results")
    print("=" * 40)

    print("\nAgents:")
    for name, result in results["agents"].items():
        status = "✓" if result.get("success") else "✗"
        print(f"  {status} {name}: {result.get('message', 'Unknown')}")
        # Show details in verbose mode
        if "deployment_info" in result:
            info = result["deployment_info"]
            if info.get("type") == "native" and "extracted_tools" in info:
                print(f"      Tools: {info['extracted_tools']}")
            if info.get("type") == "hosted" and "hosted_info" in info:
                print(f"      Framework: {info['hosted_info']['framework']}")

    print("\nWorkflows:")
    for name, result in results["workflows"].items():
        status = "✓" if result.get("success") else "✗"
        print(f"  {status} {name}: {result.get('message', 'Unknown')}")

    summary = results["summary"]
    print("\nSummary:")
    print(f"  Agents: {summary['agents_deployed']} deployed, {summary['agents_failed']} failed")
    print(f"  Workflows: {summary['workflows_deployed']} deployed, {summary['workflows_failed']} failed")

    total_failed = summary["agents_failed"] + summary["workflows_failed"]
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
