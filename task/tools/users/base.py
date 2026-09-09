from abc import ABC
from typing import Any

from task.tools.base import BaseTool
from task.tools.users.user_client import UserClient


class BaseUserServiceTool(BaseTool, ABC):

    def __init__(self, user_client: UserClient):
        super().__init__()
        self._user_client = user_client

    @staticmethod
    def _get_user_id(arguments: dict[str, Any]) -> int:
        user_id = arguments["id"]
        if not isinstance(user_id, int) or isinstance(user_id, bool):
            raise ValueError("User ID must be an integer.")
        return user_id
