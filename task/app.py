import os

import requests

from task.client import DialClient
from task.models.conversation import Conversation
from task.models.message import Message
from task.models.role import Role
from task.prompts import SYSTEM_PROMPT
from task.tools.users.create_user_tool import CreateUserTool
from task.tools.users.delete_user_tool import DeleteUserTool
from task.tools.users.get_user_by_id_tool import GetUserByIdTool
from task.tools.users.search_users_tool import SearchUsersTool
from task.tools.users.update_user_tool import UpdateUserTool
from task.tools.users.user_client import UserClient
from task.tools.web_search import WebSearchTool

DIAL_ENDPOINT = os.getenv("DIAL_ENDPOINT", "https://ai-proxy.lab.epam.com")
API_KEY = os.getenv("DIAL_API_KEY")
DIAL_MODEL = os.getenv("DIAL_MODEL", "gpt-4o")

def main():
    if not API_KEY or not API_KEY.strip():
        raise SystemExit("Set DIAL_API_KEY before starting the agent.")

    user_client = UserClient()
    client = DialClient(
        endpoint=DIAL_ENDPOINT,
        deployment_name=DIAL_MODEL,
        api_key=API_KEY,
        tools=[
            WebSearchTool(API_KEY, DIAL_ENDPOINT),
            GetUserByIdTool(user_client),
            SearchUsersTool(user_client),
            CreateUserTool(user_client),
            UpdateUserTool(user_client),
            DeleteUserTool(user_client)
        ]
    )
    conversation = Conversation()
    conversation.add_message(Message(role=Role.SYSTEM, content=SYSTEM_PROMPT))
    print(f"User management agent ({DIAL_MODEL}). Type 'exit' or 'quit' to stop.")

    while True:
        try:
            user_input = input("> ").strip()
            if not user_input:
                continue
            if user_input.lower() in {"exit", "quit"}:
                break

            conversation.add_message(Message(role=Role.USER, content=user_input))
            try:
                assistant_message = client.get_completion(conversation.get_messages(), print_request=False)
            except (requests.RequestException, ValueError, RuntimeError, KeyError, TypeError) as error:
                print(f"Request failed: {error}")
                print("No automatic retry was made. Check any previous changes before retrying.")
                continue
            conversation.add_message(assistant_message)
            print(assistant_message.content)
        except (EOFError, KeyboardInterrupt):
            print()
            break


if __name__ == "__main__":
    main()