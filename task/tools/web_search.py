from typing import Any

import requests

from task.tools.base import BaseTool


class WebSearchTool(BaseTool):

    def __init__(self, api_key: str, endpoint: str):
        self.__api_key = api_key
        self.__endpoint = f"{endpoint.rstrip('/')}/openai/deployments/gemini-2.5-pro/chat/completions"

    # https://dialx.ai/dial_api#operation/sendChatCompletionRequest (-> tools -> function)
    # Sample of tool config:
    # {
    #     "type": "function",
    #     "function": {
    #         "name": "web_search_tool",
    #         "description": "Tool for WEB searching.",
    #         "parameters": {
    #             "type": "object",
    #             "properties": {
    #                 "request": {
    #                     "type": "string",
    #                     "description": "The search query or question to search for on the web"
    #                 }
    #             },
    #             "required": [
    #                 "request"
    #             ]
    #         }
    #     }
    # }

    @property
    def name(self) -> str:
        return "web_search_tool"

    @property
    def description(self) -> str:
        return "Search the web for current, public information using Google Search grounding."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "request": {
                    "type": "string",
                    "minLength": 1,
                    "description": "The search query or question to search for on the web"
                }
            },
            "required": ["request"],
            "additionalProperties": False
        }

    def execute(self, arguments: dict[str, Any]) -> str:
        query = arguments["request"]
        if not isinstance(query, str) or not query.strip():
            raise ValueError("The search request must be a non-empty string.")
        response = requests.post(
            url=self.__endpoint,
            headers={"api-key": self.__api_key, "Content-Type": "application/json"},
            json={
                "messages": [{"role": "user", "content": query}],
                "tools": [{
                    "type": "static_function",
                    "static_function": {
                        "name": "google_search",
                        "description": "Grounding with Google Search",
                        "configuration": {}
                    }
                }]
            },
            timeout=60
        )
        if response.status_code != 200:
            return f"Error: {response.status_code} {response.text}"
        choices = response.json().get("choices")
        if not choices:
            raise ValueError("Web search returned no completion choices.")
        return choices[0]["message"].get("content") or ""
