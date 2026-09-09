from typing import Any, Optional

import requests

from task.tools.users.models.user_info import UserCreate, UserUpdate

USER_SERVICE_ENDPOINT = "http://localhost:8041"

class UserClient:

    def __user_to_string(self, user: dict[str, Any]):
        user_str = "```\n"
        for key, value in user.items():
            user_str += f"  {key}: {value}\n"
        user_str += "```\n"

        return user_str

    def __users_to_string(self, users: list[dict[str, Any]], limit: int = 20):
        users_str = ""
        displayed_users = users[:limit]
        for value in displayed_users:
            users_str += self.__user_to_string(value)
        if len(users) > limit:
            users_str += f"\nNote: Showing first {limit} of {len(users)} users. Refine your search criteria (e.g. name, surname, email) to narrow results.\n"
        else:
            users_str += "\n"

        return users_str

    def get_user(self, user_id: int) -> str:
        headers = {"Content-Type": "application/json"}

        response = requests.get(url=f"{USER_SERVICE_ENDPOINT}/v1/users/{user_id}", headers=headers, timeout=30)

        if response.status_code == 200:
            data = response.json()
            return self.__user_to_string(data)

        raise Exception(f"HTTP {response.status_code}: {response.text}")

    def search_users(
            self,
            name: Optional[str] = None,
            surname: Optional[str] = None,
            email: Optional[str] = None,
            gender: Optional[str] = None,
    ) -> str:
        headers = {"Content-Type": "application/json"}

        params = {}
        if name:
            params["name"] = name
        if surname:
            params["surname"] = surname
        if email:
            params["email"] = email
        if gender:
            params["gender"] = gender

        response = requests.get(
            url=USER_SERVICE_ENDPOINT + "/v1/users/search", headers=headers, params=params, timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            print(f"Get {len(data)} users successfully")
            return self.__users_to_string(data)

        raise Exception(f"HTTP {response.status_code}: {response.text}")

    def add_user(self, user_create_model: UserCreate) -> str:
        headers = {"Content-Type": "application/json"}

        response = requests.post(
            url=f"{USER_SERVICE_ENDPOINT}/v1/users",
            headers=headers,
            json=user_create_model.model_dump(),
            timeout=30
        )

        if response.status_code == 201:
            return f"User successfully added: {response.text}"

        raise Exception(f"HTTP {response.status_code}: {response.text}")

    def update_user(self, user_id: int, user_update_model: UserUpdate) -> str:
        headers = {"Content-Type": "application/json"}

        response = requests.put(
            url=f"{USER_SERVICE_ENDPOINT}/v1/users/{user_id}",
            headers=headers,
            json=user_update_model.model_dump(exclude_unset=True),
            timeout=30
        )

        if response.status_code in (200, 201, 204):
            return f"User successfully updated: {response.text}"

        raise Exception(f"HTTP {response.status_code}: {response.text}")

    def delete_user(self, user_id: int) -> str:
        headers = {"Content-Type": "application/json"}

        response = requests.delete(url=f"{USER_SERVICE_ENDPOINT}/v1/users/{user_id}", headers=headers, timeout=30)

        if response.status_code == 204:
            return "User successfully deleted"

        raise Exception(f"HTTP {response.status_code}: {response.text}")
