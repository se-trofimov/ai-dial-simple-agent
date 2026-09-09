import json
import unittest
from unittest.mock import Mock, patch

import requests
from pydantic import ValidationError

from task import app
from task.client import DialClient
from task.models.message import Message
from task.models.role import Role
from task.tools.users.create_user_tool import CreateUserTool
from task.tools.users.delete_user_tool import DeleteUserTool
from task.tools.users.get_user_by_id_tool import GetUserByIdTool
from task.tools.users.models.user_info import UserCreate, UserUpdate
from task.tools.users.search_users_tool import SearchUsersTool
from task.tools.users.update_user_tool import UpdateUserTool
from task.tools.users.user_client import UserClient
from task.tools.web_search import WebSearchTool


def completion_response(content=None, tool_calls=None):
    response = Mock()
    response.json.return_value = {
        "choices": [{
            "message": {"content": content, "tool_calls": tool_calls},
            "finish_reason": "tool_calls" if tool_calls else "stop"
        }]
    }
    return response


def tool_call(call_id="call_1", name="example", arguments='{"id": 1}'):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments}
    }


class DialClientTests(unittest.TestCase):
    def setUp(self):
        self.tool = Mock()
        self.tool.name = "example"
        self.tool.schema = {"type": "function", "function": {"name": "example"}}
        self.tool.execute.return_value = '{"id": 1}'
        self.client = DialClient("https://dial.example/", "test-model", "test-key", [self.tool])
        self.messages = [Message(Role.USER, "Find the user")]

    def test_requires_api_key(self):
        for api_key in (None, "", "   "):
            with self.subTest(api_key=api_key), self.assertRaises(ValueError):
                DialClient("https://dial.example", "test-model", api_key)

    @patch("task.client.requests.post")
    def test_final_completion_and_request(self, post):
        post.return_value = completion_response("Hello")

        result = self.client.get_completion(self.messages, print_request=False)

        self.assertEqual(result, Message(Role.AI, "Hello"))
        self.assertEqual(len(self.messages), 1)
        post.assert_called_once_with(
            "https://dial.example/openai/deployments/test-model/chat/completions",
            headers={"api-key": "test-key", "Content-Type": "application/json"},
            json={"messages": [self.messages[0].to_dict()], "tools": [self.tool.schema]},
            timeout=60
        )

    @patch("task.client.requests.post")
    def test_multiple_calls_and_rounds_preserve_history(self, post):
        calls = [tool_call(), tool_call("call_2", arguments='{"id": 2}')]
        post.side_effect = [
            completion_response(tool_calls=calls),
            completion_response(tool_calls=[tool_call("call_3")]),
            completion_response("Found the users")
        ]

        result = self.client.get_completion(self.messages, print_request=False)

        self.assertEqual(result.content, "Found the users")
        self.assertEqual(self.tool.execute.call_count, 3)
        self.assertEqual([message.role for message in self.messages], [
            Role.USER, Role.AI, Role.TOOL, Role.TOOL, Role.AI, Role.TOOL
        ])
        self.assertEqual(self.messages[1].content, "")
        self.assertEqual([message.tool_call_id for message in self.messages if message.role == Role.TOOL],
                         ["call_1", "call_2", "call_3"])
        second_request = post.call_args_list[1].kwargs["json"]["messages"]
        self.assertEqual(second_request[1]["tool_calls"], calls)
        self.assertEqual(second_request[2]["content"], '{"id": 1}')
        self.assertEqual(second_request[3]["tool_call_id"], "call_2")

    def test_unknown_tool(self):
        result = self.client._process_tool_calls([tool_call(name="missing")])[0]
        self.assertEqual(result.content, "Unknown function: missing")
        self.assertEqual(result.tool_call_id, "call_1")

    def test_invalid_arguments_are_tool_results(self):
        for arguments in ("invalid json", "[]", "null"):
            with self.subTest(arguments=arguments):
                result = self.client._process_tool_calls([tool_call(arguments=arguments)])[0]
                self.assertIn("error", json.loads(result.content))
                self.assertEqual(result.tool_call_id, "call_1")
        self.tool.execute.assert_not_called()

    def test_tool_failure_does_not_skip_other_calls(self):
        self.tool.execute.side_effect = [requests.Timeout("Service timed out"), "success"]

        results = self.client._process_tool_calls([tool_call(), tool_call("call_2")])

        self.assertIn("Service timed out", results[0].content)
        self.assertEqual(results[1].content, "success")

    @patch("task.client.requests.post")
    def test_http_errors_propagate_with_response_details(self, post):
        response_mock = Mock()
        response_mock.text = '{"error": {"message": "context_length_exceeded"}}'
        error = requests.HTTPError("400 Client Error", response=response_mock)
        response_mock.raise_for_status.side_effect = error
        post.return_value = response_mock

        with self.assertRaises(requests.HTTPError) as ctx:
            self.client.get_completion(self.messages, print_request=False)
        self.assertIn("context_length_exceeded", str(ctx.exception))

    @patch("task.client.requests.post")
    def test_empty_choices_are_rejected(self, post):
        post.return_value.json.return_value = {"choices": []}
        with self.assertRaisesRegex(ValueError, "no completion choices"):
            self.client.get_completion(self.messages, print_request=False)

    @patch("task.client.requests.post")
    def test_tool_round_limit(self, post):
        self.client.MAX_TOOL_ROUNDS = 1
        post.return_value = completion_response(tool_calls=[tool_call()])
        with self.assertRaisesRegex(RuntimeError, "maximum number"):
            self.client.get_completion(self.messages, print_request=False)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(self.tool.execute.call_count, 1)
        self.assertEqual(self.messages[-1].role, Role.TOOL)

    @patch("task.client.requests.post")
    def test_tools_are_optional(self, post):
        post.return_value = completion_response("Hello")
        client = DialClient("https://dial.example", "test-model", "test-key")
        client.get_completion(self.messages, print_request=False)
        self.assertNotIn("tools", post.call_args.kwargs["json"])


class WebSearchToolTests(unittest.TestCase):
    def setUp(self):
        self.tool = WebSearchTool("test-key", "https://dial.example/")

    def test_schema(self):
        self.assertEqual(self.tool.name, "web_search_tool")
        self.assertEqual(self.tool.schema["function"]["parameters"]["required"], ["request"])
        self.assertEqual(self.tool.input_schema["properties"]["request"]["type"], "string")

    @patch("task.tools.web_search.requests.post")
    def test_grounded_search_request(self, post):
        post.return_value = completion_response("Public profile with sources")
        post.return_value.status_code = 200

        result = self.tool.execute({"request": "Andrej Karpathy profile"})

        self.assertEqual(result, "Public profile with sources")
        request = post.call_args.kwargs
        self.assertEqual(request["url"],
                         "https://dial.example/openai/deployments/gemini-2.5-pro/chat/completions")
        self.assertEqual(request["headers"]["api-key"], "test-key")
        self.assertEqual(request["timeout"], 60)
        self.assertEqual(request["json"]["messages"], [
            {"role": "user", "content": "Andrej Karpathy profile"}
        ])
        self.assertEqual(request["json"]["tools"], [{
            "type": "static_function",
            "static_function": {
                "name": "google_search", "description": "Grounding with Google Search", "configuration": {}
            }
        }])

    @patch("task.tools.web_search.requests.post")
    def test_http_error_is_returned(self, post):
        post.return_value.status_code = 403
        post.return_value.text = "Forbidden"
        self.assertEqual(self.tool.execute({"request": "query"}), "Error: 403 Forbidden")

    @patch("task.tools.web_search.requests.post")
    def test_invalid_query_does_not_send_request(self, post):
        for query in ("", "   ", None, 42):
            with self.subTest(query=query), self.assertRaises(ValueError):
                self.tool.execute({"request": query})
        post.assert_not_called()

    @patch("task.tools.web_search.requests.post")
    def test_empty_choices_are_rejected(self, post):
        post.return_value.status_code = 200
        post.return_value.json.return_value = {"choices": []}
        with self.assertRaisesRegex(ValueError, "no completion choices"):
            self.tool.execute({"request": "query"})


class UserToolTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(spec=UserClient)
        self.user_data = {
            "name": "Test", "surname": "User", "email": "test@example.com", "about_me": "Test profile"
        }

    def test_create_validates_and_calls_service(self):
        tool = CreateUserTool(self.client)
        self.client.add_user.return_value = "created"

        self.assertEqual(tool.execute(self.user_data), "created")
        self.client.add_user.assert_called_once_with(UserCreate.model_validate(self.user_data))
        self.assertEqual(tool.name, "add_user")
        self.assertEqual(set(tool.input_schema["required"]), {"name", "surname", "email", "about_me"})

    def test_create_rejects_missing_fields(self):
        with self.assertRaises(ValidationError):
            CreateUserTool(self.client).execute({"name": "Test"})
        self.client.add_user.assert_not_called()

    def test_update_validates_and_calls_service(self):
        tool = UpdateUserTool(self.client)
        self.client.update_user.return_value = "updated"

        self.assertEqual(tool.execute({"id": 7, "new_info": {"company": "Example"}}), "updated")
        self.client.update_user.assert_called_once_with(7, UserUpdate(company="Example"))
        self.assertEqual(tool.name, "update_user")

    def test_update_credit_card_uses_credit_card_model(self):
        card = {"num": "test-card", "cvv": "000", "exp_date": "12/30"}
        UpdateUserTool(self.client).execute({"id": 7, "new_info": {"credit_card": card}})
        updated = self.client.update_user.call_args.args[1]
        self.assertEqual(updated.credit_card.model_dump(), card)

    def test_update_schema_references_resolve_at_root(self):
        schema = UpdateUserTool(self.client).input_schema
        self.assertEqual(schema["required"], ["id", "new_info"])
        self.assertEqual(schema["properties"]["id"]["type"], "integer")
        self.assertNotIn("$defs", schema["properties"]["new_info"])
        for field_name, definition in (("address", "Address"), ("credit_card", "CreditCard")):
            alternatives = schema["properties"]["new_info"]["properties"][field_name]["anyOf"]
            self.assertIn({"$ref": f"#/$defs/{definition}"}, alternatives)
            self.assertIn(definition, schema["$defs"])

    def test_update_rejects_invalid_fields(self):
        with self.assertRaises(ValidationError):
            UpdateUserTool(self.client).execute({"id": 7, "new_info": {"salary": "invalid"}})
        self.client.update_user.assert_not_called()

    def test_search_passes_optional_filters(self):
        tool = SearchUsersTool(self.client)
        self.client.search_users.return_value = "users"
        for arguments in ({}, {"name": "Test", "email": "test@example.com"}):
            with self.subTest(arguments=arguments):
                self.assertEqual(tool.execute(arguments), "users")
                self.client.search_users.assert_called_with(**arguments)
        self.assertEqual(tool.name, "search_users")
        self.assertEqual(tool.input_schema["required"], [])

    def test_id_tools_delegate_and_require_integer_ids(self):
        for tool_class, method_name, tool_name in (
                (GetUserByIdTool, "get_user", "get_user_by_id"),
                (DeleteUserTool, "delete_user", "delete_users")
        ):
            with self.subTest(tool=tool_name):
                tool = tool_class(self.client)
                method = getattr(self.client, method_name)
                method.return_value = "success"
                self.assertEqual(tool.execute({"id": 7}), "success")
                method.assert_called_once_with(7)
                self.assertEqual(tool.name, tool_name)
                self.assertEqual(tool.input_schema["required"], ["id"])
                self.assertEqual(tool.input_schema["properties"]["id"]["type"], "integer")

    def test_invalid_ids_never_reach_service(self):
        for tool_class in (GetUserByIdTool, DeleteUserTool, UpdateUserTool):
            for user_id in ("7", 7.5, True, None):
                with self.subTest(tool=tool_class.__name__, user_id=user_id), self.assertRaises(ValueError):
                    tool_class(self.client).execute({"id": user_id, "new_info": {"name": "Test"}})
        self.assertEqual(self.client.mock_calls, [])


class UserClientTests(unittest.TestCase):
    @patch("task.tools.users.user_client.requests.put")
    def test_update_sends_only_explicit_fields(self, put):
        for status_code in (200, 201, 204):
            with self.subTest(status_code=status_code):
                put.return_value.status_code = status_code
                put.return_value.text = "updated"
                result = UserClient().update_user(7, UserUpdate(company="Example"))
                self.assertIn("successfully updated", result)
                self.assertEqual(put.call_args.kwargs["url"], "http://localhost:8041/v1/users/7")
                self.assertEqual(put.call_args.kwargs["json"], {"company": "Example"})
                self.assertEqual(put.call_args.kwargs["timeout"], 30)

    @patch("task.tools.users.user_client.requests.put")
    def test_update_preserves_explicit_null(self, put):
        put.return_value.status_code = 201
        UserClient().update_user(7, UserUpdate(phone=None))
        self.assertEqual(put.call_args.kwargs["json"], {"phone": None})

    @patch("task.tools.users.user_client.requests.get")
    def test_get_user_request(self, get):
        get.return_value.status_code = 200
        get.return_value.json.return_value = {"id": 7, "name": "Test"}
        result = UserClient().get_user(7)
        self.assertIn("id: 7", result)
        get.assert_called_once_with(
            url="http://localhost:8041/v1/users/7", headers={"Content-Type": "application/json"}, timeout=30
        )

    @patch("builtins.print")
    @patch("task.tools.users.user_client.requests.get")
    def test_search_request(self, get, print_mock):
        get.return_value.status_code = 200
        get.return_value.json.return_value = [{"id": 7}]
        self.assertIn("id: 7", UserClient().search_users(name="Test", email="test@example.com"))
        self.assertEqual(get.call_args.kwargs["url"], "http://localhost:8041/v1/users/search")
        self.assertEqual(get.call_args.kwargs["params"], {"name": "Test", "email": "test@example.com"})
        self.assertEqual(get.call_args.kwargs["timeout"], 30)

    @patch("task.tools.users.user_client.requests.get")
    def test_search_request_truncates_large_result_list(self, get):
        fake_users = [{"id": i, "name": f"User{i}"} for i in range(25)]
        get.return_value.status_code = 200
        get.return_value.json.return_value = fake_users

        result = UserClient().search_users()
        self.assertIn("Showing first 20 of 25 users", result)
        self.assertIn("id: 19", result)
        self.assertNotIn("id: 20", result)

    @patch("task.tools.users.user_client.requests.post")
    def test_create_request(self, post):
        post.return_value.status_code = 201
        post.return_value.text = "created"
        user = UserCreate(name="Test", surname="User", email="test@example.com", about_me="Test profile")
        self.assertIn("successfully added", UserClient().add_user(user))
        self.assertEqual(post.call_args.kwargs["url"], "http://localhost:8041/v1/users")
        self.assertEqual(post.call_args.kwargs["json"], user.model_dump())
        self.assertEqual(post.call_args.kwargs["timeout"], 30)

    @patch("task.tools.users.user_client.requests.delete")
    def test_delete_request(self, delete):
        delete.return_value.status_code = 204
        self.assertEqual(UserClient().delete_user(7), "User successfully deleted")
        delete.assert_called_once_with(
            url="http://localhost:8041/v1/users/7", headers={"Content-Type": "application/json"}, timeout=30
        )

    @patch("task.tools.users.user_client.requests.get")
    def test_service_error_surfaces(self, get):
        get.return_value.status_code = 404
        get.return_value.text = "Not found"
        with self.assertRaisesRegex(Exception, "HTTP 404: Not found"):
            UserClient().get_user(7)


class AppTests(unittest.TestCase):
    @patch("task.app.API_KEY", "test-key")
    @patch("builtins.print")
    @patch("builtins.input", side_effect=["Create Test User, test@example.com, about me: Test profile", "exit"])
    @patch("requests.get")
    @patch("requests.post")
    def test_complete_search_then_create_workflow(self, post, get, input_mock, print_mock):
        user_data = {
            "name": "Test", "surname": "User", "email": "test@example.com", "about_me": "Test profile"
        }
        get.return_value.status_code = 200
        get.return_value.json.return_value = []
        created_response = Mock(status_code=201, text='{"id": 7}')
        post.side_effect = [
            completion_response(tool_calls=[tool_call("call_search", "search_users", '{"email":"test@example.com"}')]),
            completion_response(tool_calls=[tool_call("call_create", "add_user", json.dumps(user_data))]),
            created_response,
            completion_response("Created user 7")
        ]

        app.main()

        self.assertEqual(post.call_count, 4)
        self.assertEqual(get.call_args.kwargs["params"], {"email": "test@example.com"})
        create_request = post.call_args_list[2].kwargs
        self.assertEqual(create_request["url"], "http://localhost:8041/v1/users")
        self.assertEqual(create_request["json"], UserCreate.model_validate(user_data).model_dump())
        history = post.call_args_list[3].kwargs["json"]["messages"]
        self.assertEqual([message["role"] for message in history],
                         ["system", "user", "assistant", "tool", "assistant", "tool"])
        self.assertEqual(history[3]["tool_call_id"], "call_search")
        self.assertEqual(history[5]["tool_call_id"], "call_create")
        self.assertIn("successfully added", history[5]["content"])
        print_mock.assert_any_call("Created user 7")

    @patch("task.app.API_KEY", "test-key")
    @patch("task.app.DialClient")
    @patch("builtins.print")
    @patch("builtins.input", side_effect=["  ", " Find a user ", "Show their company", "EXIT"])
    def test_cli_wires_tools_and_keeps_history(self, input_mock, print_mock, client_class):
        snapshots = []

        def get_completion(messages, print_request):
            self.assertFalse(print_request)
            snapshots.append([message.to_dict() for message in messages])
            return Message(Role.AI, "Result")

        client_class.return_value.get_completion.side_effect = get_completion

        app.main()

        tools = client_class.call_args.kwargs["tools"]
        self.assertEqual({tool.name for tool in tools}, {
            "web_search_tool", "get_user_by_id", "search_users", "add_user", "update_user", "delete_users"
        })
        self.assertEqual(client_class.call_args.kwargs["deployment_name"], app.DIAL_MODEL)
        self.assertEqual(snapshots[0][0], {"role": "system", "content": app.SYSTEM_PROMPT})
        self.assertEqual(snapshots[0][1], {"role": "user", "content": "Find a user"})
        self.assertEqual([message["role"] for message in snapshots[1]], ["system", "user", "assistant", "user"])
        self.assertEqual(snapshots[1][2]["content"], "Result")
        print_mock.assert_any_call("Result")

    @patch("task.app.API_KEY", None)
    @patch("builtins.input")
    def test_missing_key_fails_before_prompt(self, input_mock):
        with self.assertRaisesRegex(SystemExit, "Set DIAL_API_KEY"):
            app.main()
        input_mock.assert_not_called()

    @patch("task.app.API_KEY", "test-key")
    @patch("task.app.DialClient")
    @patch("builtins.print")
    @patch("builtins.input", side_effect=["Find a user", "Try again", "quit"])
    def test_request_failure_does_not_end_session(self, input_mock, print_mock, client_class):
        client_class.return_value.get_completion.side_effect = [requests.Timeout("Timed out"), Message(Role.AI, "Done")]
        app.main()
        self.assertEqual(client_class.return_value.get_completion.call_count, 2)
        print_mock.assert_any_call("Request failed: Timed out")
        print_mock.assert_any_call("Done")

    @patch("task.app.API_KEY", "test-key")
    @patch("task.app.DialClient")
    @patch("builtins.print")
    def test_eof_and_interrupt_exit_cleanly(self, print_mock, client_class):
        for error in (EOFError, KeyboardInterrupt):
            with self.subTest(error=error), patch("builtins.input", side_effect=error):
                app.main()
        client_class.return_value.get_completion.assert_not_called()


if __name__ == "__main__":
    unittest.main()