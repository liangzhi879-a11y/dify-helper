from dify_plugin import ToolProvider
from dify_plugin.errors.tool import ValidateCredentialsError
import httpx


def _get_credential(credentials, key, default=None):
    """兼容 credentials 为 dict 或对象两种结构。"""
    if isinstance(credentials, dict):
        return credentials.get(key, default)
    inner = getattr(credentials, "credentials", None)
    if isinstance(inner, dict):
        return inner.get(key, default)
    return getattr(credentials, key, default)


class ClaudeCodeBridgeProvider(ToolProvider):
    def _validate_credentials(self, credentials, **kwargs):
        bridge_url = _get_credential(credentials, "bridge_url", "")
        if isinstance(bridge_url, str):
            bridge_url = bridge_url.rstrip("/")
        if not bridge_url:
            raise ValidateCredentialsError("bridge_url credential is required")
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.get(f"{bridge_url}/health")
                if resp.status_code != 200:
                    raise ValidateCredentialsError(
                        f"Bridge health check failed: HTTP {resp.status_code}"
                    )
        except httpx.HTTPError as e:
            raise ValidateCredentialsError(
                f"Cannot reach bridge service at {bridge_url}: {e}"
            )
