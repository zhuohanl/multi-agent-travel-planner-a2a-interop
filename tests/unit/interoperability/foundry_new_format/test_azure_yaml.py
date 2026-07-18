from pathlib import Path

import yaml


AZURE_YAML = Path("interoperability/foundry_new_format/azure.yaml")


def test_declares_exact_hosted_agent_services() -> None:
    document = yaml.safe_load(AZURE_YAML.read_text(encoding="utf-8"))
    services = document["services"]
    agents = {
        name: value
        for name, value in services.items()
        if value.get("host") == "azure.ai.agent"
    }

    assert set(agents) == {
        "travel-planner-stay",
        "travel-planner-dining",
        "travel-planner-weather-proxy",
    }
    expected_entry_points = {
        "travel-planner-stay": "run_stay.py",
        "travel-planner-dining": "run_dining.py",
        "travel-planner-weather-proxy": "run_weather_proxy.py",
    }
    expected_startup_commands = {
        "travel-planner-stay": "python run_stay.py",
        "travel-planner-dining": "python run_dining.py",
        "travel-planner-weather-proxy": "python run_weather_proxy.py",
    }
    for name, service in agents.items():
        assert service["name"] == name
        assert service["kind"] == "hosted"
        assert service["project"] == "."
        assert service["language"] == "python"
        assert service["codeConfiguration"]["runtime"] == "python_3_13"
        assert service["codeConfiguration"]["entryPoint"] == expected_entry_points[name]
        assert service["startupCommand"] == expected_startup_commands[name]
        assert service["protocols"] == [
            {"protocol": "responses", "version": "2.0.0"}
        ]
        assert "toolboxes" not in service
        assert "image" not in service

    assert agents["travel-planner-stay"]["uses"] == ["ai-project", "travel-search"]
    assert agents["travel-planner-dining"]["uses"] == [
        "ai-project",
        "travel-search",
    ]


def test_runtime_variables_use_current_manifest_shape() -> None:
    document = yaml.safe_load(AZURE_YAML.read_text(encoding="utf-8"))
    agents = [
        value
        for value in document["services"].values()
        if value.get("host") == "azure.ai.agent"
    ]

    for service in agents:
        assert "env" not in service
        assert isinstance(service.get("environmentVariables", []), list)


def test_dining_binds_toolbox_endpoint_to_azd_published_variable() -> None:
    document = yaml.safe_load(AZURE_YAML.read_text(encoding="utf-8"))
    dining = document["services"]["travel-planner-dining"]
    environment_variables = {
        variable["name"]: variable["value"]
        for variable in dining["environmentVariables"]
    }

    assert environment_variables["TOOLBOX_ENDPOINT"] == (
        "${TOOLBOX_TRAVEL_SEARCH_MCP_ENDPOINT}"
    )


def test_manifest_never_references_legacy_foundry_folder() -> None:
    text = AZURE_YAML.read_text(encoding="utf-8")

    assert "interoperability/foundry/" not in text
    assert "STAY_AGENT_IMAGE" not in text
    assert "DINING_AGENT_IMAGE" not in text
    assert "WEATHER_PROXY_IMAGE" not in text
