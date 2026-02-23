"""
Foundry Hosted Agent Image Builder

Builds, tags, and pushes Docker images for hosted agents to ACR,
then updates .env with the new image references.

Usage (bash):
    uv run python interoperability/foundry/build_images.py --dry-run
    uv run python interoperability/foundry/build_images.py --agent stay --tag v7

Usage (PowerShell):
    uv run python -m interoperability.foundry.build_images --dry-run
    uv run python -m interoperability.foundry.build_images --agent stay --tag v7

Prerequisites:
    - Docker installed and running
    - ACR_REGISTRY env var set (e.g. myregistry.azurecr.io)
    - Logged in to ACR (az acr login --name <registry>)
    - config.yaml exists with hosted agents defined
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from dotenv import load_dotenv

load_dotenv()


ENV_VAR_PATTERN = re.compile(r"\$\{(\w+?)(?::-.+?)?\}")


@dataclass
class HostedAgent:
    """A hosted agent discovered from config.yaml + agent.yaml."""

    name: str  # config.yaml key (e.g. "stay")
    image_name: str  # from agent.yaml name field (e.g. "stay-agent")
    env_var: str  # extracted from container.image (e.g. "STAY_AGENT_IMAGE")
    source: str  # source directory path
    dockerfile: Path  # path to Dockerfile
    deploy_env_vars: list[str]  # env vars from agent.yaml environment section


def get_git_sha() -> str:
    """Get the first 12 chars of the current git commit SHA."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()[:12]


def get_default_tag() -> str:
    """Generate default tag: YYYY-MM-DD-<12-char-git-sha>."""
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sha = get_git_sha()
    return f"{date_str}-{sha}"


def discover_hosted_agents(config_path: Path) -> list[HostedAgent]:
    """Read config.yaml and discover all hosted agents.

    For each agent with type=="hosted", reads {source}/agent.yaml to extract:
    - image_name: from the agent.yaml 'name' field
    - env_var: from the container.image field (e.g. ${STAY_AGENT_IMAGE} -> STAY_AGENT_IMAGE)
    - dockerfile: {source}/Dockerfile
    """
    with open(config_path) as f:
        config = yaml.safe_load(f)

    agents: list[HostedAgent] = []
    for name, agent_config in config.get("agents", {}).items():
        if agent_config.get("type") != "hosted":
            continue

        source = agent_config["source"]
        agent_yaml_path = Path(source) / "agent.yaml"
        if not agent_yaml_path.exists():
            print(f"[WARN] agent.yaml not found at {agent_yaml_path}, skipping {name}")
            continue

        with open(agent_yaml_path) as f:
            agent_yaml = yaml.safe_load(f)

        image_name = agent_yaml.get("name", name)

        # Extract env var from container.image (e.g. ${STAY_AGENT_IMAGE} -> STAY_AGENT_IMAGE)
        container = agent_yaml.get("container", {})
        image_ref = container.get("image", "")
        match = re.match(r"\$\{(\w+)\}", image_ref)
        if not match:
            print(
                f"[WARN] Cannot extract env var from container.image "
                f"'{image_ref}' for {name}, skipping"
            )
            continue
        env_var = match.group(1)

        dockerfile = Path(source) / "Dockerfile"
        if not dockerfile.exists():
            print(f"[WARN] Dockerfile not found at {dockerfile}, skipping {name}")
            continue

        # Extract env var names referenced in agent.yaml environment section
        deploy_env_vars: list[str] = []
        environment = agent_yaml.get("environment", {})
        if isinstance(environment, dict):
            for value in environment.values():
                if isinstance(value, str):
                    for m in ENV_VAR_PATTERN.finditer(value):
                        deploy_env_vars.append(m.group(1))

        agents.append(
            HostedAgent(
                name=name,
                image_name=image_name,
                env_var=env_var,
                source=source,
                dockerfile=dockerfile,
                deploy_env_vars=deploy_env_vars,
            )
        )

    return agents


def update_env_file(env_path: Path, var_name: str, value: str) -> None:
    """Update a variable in .env file. Replace existing line or append."""
    if env_path.exists():
        lines = env_path.read_text().splitlines()
    else:
        lines = []

    prefix = f"{var_name}="
    found = False
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = f"{var_name}={value}"
            found = True
            break

    if not found:
        lines.append(f"{var_name}={value}")

    env_path.write_text("\n".join(lines) + "\n")


def run_command(
    cmd: list[str], dry_run: bool = False, **kwargs: object
) -> subprocess.CompletedProcess[str]:
    """Run a shell command, printing it first."""
    cmd_str = " ".join(cmd)
    if dry_run:
        print(f"  [DRY RUN] {cmd_str}")
        return subprocess.CompletedProcess(cmd, 0)

    print(f"  $ {cmd_str}")
    return subprocess.run(cmd, check=True, **kwargs)


def build_agent(
    agent: HostedAgent,
    registry: str,
    tag: str,
    repo_root: Path,
    env_path: Path,
    dry_run: bool,
) -> None:
    """Build, tag, push one agent image and update .env.

    Steps:
    1. docker build -t {image_name}:latest -f {source}/Dockerfile .
    2. docker tag {image_name}:latest {registry}/{image_name}:{tag}
    3. docker push {registry}/{image_name}:{tag}
    4. Update .env: {env_var}={registry}/{image_name}:{tag}
    """
    full_image = f"{registry}/{agent.image_name}:{tag}"

    print(f"\n{'=' * 60}")
    print(f"Building {agent.name} ({agent.image_name})")
    print(f"  Image:      {full_image}")
    print(f"  Dockerfile: {agent.dockerfile}")
    print(f"  Env var:    {agent.env_var}")
    print(f"{'=' * 60}")

    # 1. Build (use forward slashes for Docker path compatibility on Windows)
    run_command(
        [
            "docker", "build",
            "-t", f"{agent.image_name}:latest",
            "-f", agent.dockerfile.as_posix(),
            ".",
        ],
        dry_run=dry_run,
        cwd=str(repo_root),
    )

    # 2. Tag
    run_command(
        [
            "docker", "tag",
            f"{agent.image_name}:latest",
            full_image,
        ],
        dry_run=dry_run,
    )

    # 3. Push
    run_command(
        ["docker", "push", full_image],
        dry_run=dry_run,
    )

    # 4. Update .env
    if dry_run:
        print(f"  [DRY RUN] Would set {agent.env_var}={full_image} in {env_path}")
    else:
        update_env_file(env_path, agent.env_var, full_image)
        print(f"  Updated {env_path}: {agent.env_var}={full_image}")


def check_deploy_env_vars(agents: list[HostedAgent]) -> None:
    """Check that env vars needed at deploy time are set. Prints warnings."""
    for agent in agents:
        missing = [v for v in agent.deploy_env_vars if not os.environ.get(v)]
        if missing:
            print(
                f"[WARN] {agent.name}: missing env vars needed at deploy time: "
                f"{', '.join(missing)}"
            )


def preflight_checks(registry: str | None, dry_run: bool) -> str:
    """Run pre-flight checks and return the validated registry string."""
    # Check docker is available
    if not shutil.which("docker"):
        print("Error: 'docker' not found in PATH", file=sys.stderr)
        sys.exit(1)

    # Check ACR_REGISTRY
    if not registry:
        print("Error: ACR_REGISTRY environment variable is not set", file=sys.stderr)
        print("  Set it to your Azure Container Registry, e.g.:", file=sys.stderr)
        print("  Bash:       export ACR_REGISTRY=myregistry.azurecr.io", file=sys.stderr)
        print('  PowerShell: $env:ACR_REGISTRY = "myregistry.azurecr.io"', file=sys.stderr)
        print("  Or add ACR_REGISTRY=myregistry.azurecr.io to your .env file", file=sys.stderr)
        sys.exit(1)

    if not dry_run:
        # Check docker daemon is running
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print("Error: Docker daemon is not running", file=sys.stderr)
            sys.exit(1)

    return registry


def main() -> int:
    """Run the image build process."""
    parser = argparse.ArgumentParser(
        description="Build, tag, and push Docker images for hosted Foundry agents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples (bash):
  uv run python interoperability/foundry/build_images.py                          # build all
  uv run python interoperability/foundry/build_images.py --agent stay             # one agent
  uv run python interoperability/foundry/build_images.py --agent stay --tag v7    # custom tag
  uv run python interoperability/foundry/build_images.py --dry-run                # preview

Examples (PowerShell):
  uv run python -m interoperability.foundry.build_images                          # build all
  uv run python -m interoperability.foundry.build_images --agent stay             # one agent
  uv run python -m interoperability.foundry.build_images --agent stay --tag v7    # custom tag
  uv run python -m interoperability.foundry.build_images --dry-run                # preview

Environment Variables:
  ACR_REGISTRY    Azure Container Registry hostname (e.g. myregistry.azurecr.io)
        """,
    )
    parser.add_argument(
        "--agent", type=str, help="Build a specific agent by config name"
    )
    parser.add_argument(
        "--tag", type=str, help="Custom image tag (requires --agent)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without executing",
    )

    args = parser.parse_args()

    if args.tag and not args.agent:
        parser.error("--tag requires --agent (custom tag applies to a single agent only)")

    # Paths
    script_dir = Path(__file__).parent
    config_path = script_dir / "config.yaml"
    repo_root = script_dir.parent.parent
    env_path = repo_root / ".env"

    if not config_path.exists():
        print(f"Error: config.yaml not found at {config_path}", file=sys.stderr)
        return 1

    # Pre-flight checks
    registry = os.environ.get("ACR_REGISTRY", "")
    registry = preflight_checks(registry or None, args.dry_run)

    # Discover hosted agents
    agents = discover_hosted_agents(config_path)
    if not agents:
        print("No hosted agents found in config.yaml")
        return 0

    # Filter to specific agent if requested
    if args.agent:
        filtered = [a for a in agents if a.name == args.agent]
        if not filtered:
            print(
                f"Error: Agent '{args.agent}' not found or not a hosted agent",
                file=sys.stderr,
            )
            print(
                f"Available hosted agents: {', '.join(a.name for a in agents)}",
                file=sys.stderr,
            )
            return 1
        agents = filtered

    # Check deploy-time env vars
    check_deploy_env_vars(agents)

    # Determine tag
    tag = args.tag or get_default_tag()

    print(f"Registry: {registry}")
    print(f"Tag: {tag}")
    print(f"Agents: {', '.join(a.name for a in agents)}")
    if args.dry_run:
        print("[DRY RUN MODE]")

    # Build each agent
    success_count = 0
    fail_count = 0
    for agent in agents:
        try:
            build_agent(agent, registry, tag, repo_root, env_path, args.dry_run)
            success_count += 1
        except subprocess.CalledProcessError as e:
            print(f"\nError building {agent.name}: {e}", file=sys.stderr)
            fail_count += 1
        except Exception as e:
            print(f"\nError building {agent.name}: {e}", file=sys.stderr)
            fail_count += 1

    # Summary
    print(f"\n{'=' * 60}")
    print(f"Summary: {success_count} succeeded, {fail_count} failed")
    if not args.dry_run and success_count > 0:
        print(f"\n.env updated at {env_path}")
        print("Next step: uv run python interoperability/foundry/deploy.py --deploy")

    return 1 if fail_count > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
