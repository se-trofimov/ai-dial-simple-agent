from typing import Any

from task.tools.users.base import BaseUserServiceTool
from task.tools.users.models.user_info import UserUpdate


class UpdateUserTool(BaseUserServiceTool):

    @property
    def name(self) -> str:
        return "update_user"

    @property
    def description(self) -> str:
        return "Update an existing user by ID, providing only the fields that should change in new_info."

    @property
    def input_schema(self) -> dict[str, Any]:
        new_info_schema = UserUpdate.model_json_schema()
        definitions = new_info_schema.pop("$defs", {})
        schema = {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "User ID that should be updated"},
                "new_info": new_info_schema
            },
            "required": ["id", "new_info"],
            "additionalProperties": False
        }
        if definitions:
            schema["$defs"] = definitions
        return schema

    def execute(self, arguments: dict[str, Any]) -> str:
        user_id = self._get_user_id(arguments)
        new_info = UserUpdate.model_validate(arguments["new_info"])
        return self._user_client.update_user(user_id, new_info)
