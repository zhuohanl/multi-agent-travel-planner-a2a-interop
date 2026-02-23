from unittest.mock import MagicMock, patch

from src.shared.chat_services import _get_azure_openai_chat_completion_service


def _set_required_env(monkeypatch) -> None:
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4.1")
    monkeypatch.setenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")


def test_azure_chat_service_uses_api_key_when_present(monkeypatch):
    _set_required_env(monkeypatch)
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")

    expected_client = MagicMock()

    with patch(
        "src.shared.chat_services.AzureOpenAIChatClient",
        return_value=expected_client,
    ) as chat_client_cls, patch(
        "src.shared.chat_services.DefaultAzureCredential"
    ) as default_credential_cls:
        result = _get_azure_openai_chat_completion_service()

    assert result is expected_client
    chat_client_cls.assert_called_once_with(
        service_id="default",
        deployment_name="gpt-4.1",
        endpoint="https://example.openai.azure.com/",
        api_key="test-key",
        api_version="2025-01-01-preview",
    )
    default_credential_cls.assert_not_called()


def test_azure_chat_service_falls_back_to_managed_identity(monkeypatch):
    _set_required_env(monkeypatch)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)

    credential = MagicMock()
    token_provider = MagicMock()
    async_client = MagicMock()
    expected_client = MagicMock()

    with patch(
        "src.shared.chat_services.DefaultAzureCredential",
        return_value=credential,
    ) as default_credential_cls, patch(
        "src.shared.chat_services.get_bearer_token_provider",
        return_value=token_provider,
    ) as token_provider_fn, patch(
        "src.shared.chat_services.openai.AsyncAzureOpenAI",
        return_value=async_client,
    ) as async_azure_openai_cls, patch(
        "src.shared.chat_services.AzureOpenAIChatClient",
        return_value=expected_client,
    ) as chat_client_cls:
        result = _get_azure_openai_chat_completion_service()

    assert result is expected_client
    default_credential_cls.assert_called_once_with()
    token_provider_fn.assert_called_once_with(
        credential,
        "https://cognitiveservices.azure.com/.default",
    )
    async_azure_openai_cls.assert_called_once_with(
        azure_endpoint="https://example.openai.azure.com/",
        azure_ad_token_provider=token_provider,
        api_version="2025-01-01-preview",
    )
    chat_client_cls.assert_called_once_with(
        service_id="default",
        deployment_name="gpt-4.1",
        async_client=async_client,
    )
