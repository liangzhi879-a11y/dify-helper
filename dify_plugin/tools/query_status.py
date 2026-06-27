from collections.abc import Generator
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
import httpx
import json


class QueryStatusTool(Tool):
    def _invoke(self, user_id: str, tool_parameters: dict) -> Generator[ToolInvokeMessage, None, None]:
        bridge_url = self.runtime.credentials.get("bridge_url", "").rstrip("/")
        task_id = tool_parameters.get("task_id", "").strip()
        if not task_id:
            yield self.create_text_message("Error: task_id is required")
            return
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.get(f"{bridge_url}/tasks/{task_id}/status")
                if resp.status_code == 404:
                    yield self.create_text_message(f"Error: task {task_id} not found")
                    return
                resp.raise_for_status()
                data = resp.json()
            yield self.create_text_message(json.dumps(data, ensure_ascii=False))
            yield self.create_json_message(data)
        except httpx.HTTPError as e:
            yield self.create_text_message(f"Error: {e}")
