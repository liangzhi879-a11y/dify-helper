from collections.abc import Generator
from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage
import httpx
import json


class SubmitTaskTool(Tool):
    def _invoke(self, user_id: str, tool_parameters: dict) -> Generator[ToolInvokeMessage, None, None]:
        bridge_url = self.runtime.credentials.get("bridge_url", "").rstrip("/")
        task_description = tool_parameters.get("task_description", "").strip()
        if not task_description:
            yield self.create_text_message("Error: task_description is required")
            return
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.post(f"{bridge_url}/tasks", json={"task_description": task_description})
                resp.raise_for_status()
                data = resp.json()
            yield self.create_text_message(json.dumps(data, ensure_ascii=False))
            yield self.create_json_message(data)
        except httpx.HTTPError as e:
            yield self.create_text_message(f"Error calling bridge service: {e}")
