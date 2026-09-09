from typing import Any

from task.tools.users.base import BaseUserServiceTool


class DeleteUserTool(BaseUserServiceTool):

    @property
    def name(self) -> str:
        return "delete_users"

    @property
    def description(self) -> str:
        return "Delete one user by their integer ID, only after the user explicitly confirms the deletion."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "User ID to delete"}
            },
            "required": ["id"],
            "additionalProperties": False
        }

    def execute(self, arguments: dict[str, Any]) -> str:
        user_id = self._get_user_id(arguments)
        return self._user_client.delete_user(user_id)