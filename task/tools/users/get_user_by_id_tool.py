from typing import Any

from task.tools.users.base import BaseUserServiceTool


class GetUserByIdTool(BaseUserServiceTool):

    @property
    def name(self) -> str:
        return "get_user_by_id"

    @property
    def description(self) -> str:
        return "Retrieve a stored user's full profile by their integer ID."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "User ID to retrieve"}
            },
            "required": ["id"],
            "additionalProperties": False
        }

    def execute(self, arguments: dict[str, Any]) -> str:
        user_id = self._get_user_id(arguments)
        return self._user_client.get_user(user_id)