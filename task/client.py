import json
from typing import Any

import requests

from task.models.message import Message
from task.models.role import Role
from task.tools.base import BaseTool


class DialClient:

    MAX_TOOL_ROUNDS = 10

    def __init__(
            self,
            endpoint: str,
            deployment_name: str,
            api_key: str,
            tools: list[BaseTool] | None = None
    ):
        if not api_key or not api_key.strip():
            raise ValueError("DIAL_API_KEY must be set.")
        self.__endpoint = f"{endpoint.rstrip('/')}/openai/deployments/{deployment_name}/chat/completions"
        self.__api_key = api_key
        self.__tools_dict = {tool.name: tool for tool in tools or []}
        self.__tools = [tool.schema for tool in self.__tools_dict.values()]


    def get_completion(self, messages: list[Message], print_request: bool = True) -> Message:
        headers = {
            "api-key": self.__api_key,
            "Content-Type": "application/json"
        }
        for tool_round in range(self.MAX_TOOL_ROUNDS + 1):
            request_data = {"messages": [message.to_dict() for message in messages]}
            if self.__tools:
                request_data["tools"] = self.__tools
            if print_request:
                print(json.dumps(request_data, indent=2))

            response = requests.post(
                self.__endpoint,
                headers=headers,
                json=request_data,
                timeout=60
            )
            try:
                response.raise_for_status()
            except requests.HTTPError as error:
                detail = response.text.strip()
                if detail:
                    raise requests.HTTPError(f"{error} - Details: {detail}", response=response) from error
                raise
            choices = response.json().get("choices")
            if not choices:
                raise ValueError("DIAL returned no completion choices.")
            choice = choices[0]
            message_data = choice["message"]
            tool_calls = message_data.get("tool_calls")
            ai_response = Message(
                role=Role.AI,
                content=message_data.get("content") or "",
                tool_calls=tool_calls
            )
            if not tool_calls:
                if choice.get("finish_reason") == "tool_calls":
                    raise ValueError("DIAL requested tool execution without any tool calls.")
                return ai_response
            if tool_round == self.MAX_TOOL_ROUNDS:
                raise RuntimeError("DIAL exceeded the maximum number of tool rounds.")

            messages.append(ai_response)
            messages.extend(self._process_tool_calls(tool_calls))


    def _process_tool_calls(self, tool_calls: list[dict[str, Any]]) -> list[Message]:
        """Process tool calls and add results to messages."""
        tool_messages = []
        for tool_call in tool_calls:
            tool_call_id = tool_call["id"]
            function = tool_call["function"]
            function_name = function["name"]
            try:
                arguments = json.loads(function["arguments"])
                if not isinstance(arguments, dict):
                    raise ValueError("Tool arguments must be a JSON object.")
                tool_execution_result = self._call_tool(function_name, arguments)
            except Exception as error:
                tool_execution_result = json.dumps({"error": str(error)})
            tool_messages.append(Message(
                role=Role.TOOL,
                name=function_name,
                tool_call_id=tool_call_id,
                content=tool_execution_result
            ))

        return tool_messages

    def _call_tool(self, function_name: str, arguments: dict[str, Any]) -> str:
        tool = self.__tools_dict.get(function_name)
        if tool is None:
            return f"Unknown function: {function_name}"
        return tool.execute(arguments)
