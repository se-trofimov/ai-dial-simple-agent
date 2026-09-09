# DIAL AI Simple Agent Task
Python implementation for building AI-powered chat applications using the DIAL API with advanced tool integration.

## 🎯 Task Overview

This project implements a terminal-based agent that manages users through a User Service and can search the web for public profile information. It sends conversation history and tool schemas directly to DIAL using `requests`, executes the tools selected by the model, and returns their results to the model until a final answer is available.

## 🏗️ Architecture

### <img src="flow.png">
```
task/
|-- models/                Conversation, Message, and Role
|-- tools/
|   |-- base.py            Shared function-tool schema interface
|   |-- web_search.py      Gemini with Google Search grounding
|   `-- users/
|       |-- base.py                 Shared service client and ID validation
|       |-- create_user_tool.py     Create a validated user
|       |-- update_user_tool.py     Update selected fields
|       |-- delete_user_tool.py     Delete one user by ID
|       |-- get_user_by_id_tool.py  Retrieve a user by ID
|       |-- search_users_tool.py    Search with optional filters
|       |-- user_client.py         User Service HTTP operations
|       `-- models/user_info.py     Pydantic request models
|-- client.py              DIAL requests and tool-execution loop
|-- prompts.py             User-management behavior and safety guidance
`-- app.py                 Interactive terminal application

tests/test_agent.py        Offline unit and workflow tests
```

## 📋 Requirements

- **Python**: 3.11 or higher
- **Dependencies**: Listed in `requirements.txt`
- **API Access**: DIAL API key with appropriate permissions
- **Network**: EPAM VPN connection for internal API access
- **Docker**

## 🔧 Setup Instructions

### 1. Environment Setup

```bash
python -m venv .venv
```

Activate the environment in PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

### 2. Install Dependencies

```bash
python -m pip install -r requirements.txt
```

### 3. API Configuration

1. **Connect to EPAM VPN** (required for internal API access)
2. **Obtain DIAL API Key**:
    - Visit: https://support.epam.com/ess?id=sc_cat_item&table=sc_cat_item&sys_id=910603f1c3789e907509583bb001310c
3. **Set `DIAL_API_KEY` in the environment of the terminal that will run the app.** Do not put it in source control. The app reads process environment variables; it does not automatically load an `.env` file.
4. **Start the User Service** with Docker Desktop running:

```powershell
docker compose up -d
```

The service is exposed at `http://localhost:8041`. Its generated database is persisted in the ignored `data/` directory.

### 4. Run the Agent

```powershell
python -m task.app
```

Enter a request, such as `Find users named Andrej Karpathy`. The agent keeps the conversation in memory until you exit. Blank input is ignored; `exit`, `quit`, Ctrl+C, and end-of-input stop the session.

Configuration:

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `DIAL_API_KEY` | Required | DIAL authentication; missing or blank values stop startup |
| `DIAL_MODEL` | `gpt-4o` | Main agent deployment; must support function calling and be available to your key |
| `DIAL_ENDPOINT` | `https://ai-proxy.lab.epam.com` | DIAL base URL |

To try another authorized deployment, set `DIAL_MODEL` before starting the app. For example:

```powershell
$env:DIAL_MODEL = "gemini-2.5-pro"
python -m task.app
```

Web search uses the task's specified `gemini-2.5-pro` deployment independently of the main model. That deployment must support DIAL's `google_search` static function.

## Implementation Details

### Conversation and Tool Execution

1. The app creates one shared `UserClient`, registers all six tools, and starts a `Conversation` with `SYSTEM_PROMPT`.
2. Each terminal request becomes a user message. `DialClient` serializes the full history and tool schemas and posts them to `/openai/deployments/{model}/chat/completions` using the `api-key` header.
3. If DIAL returns tool calls, the client first records the assistant message containing those calls. It parses each call's JSON arguments and dispatches it by tool name.
4. Each execution produces a tool message containing the original `tool_call_id`, tool name, and result. Matching IDs are required by the chat-completion protocol; without them, the next request has an incomplete tool exchange.
5. The client sends the expanded history to DIAL again. It handles multiple calls in one response and successive tool rounds. The app appends and prints the final assistant response exactly once.

The loop is iterative rather than recursive, keeping stack usage constant. It allows up to ten tool rounds per completion, then raises an error instead of executing tools indefinitely. DIAL and web-search requests have 60-second timeouts; User Service requests have 30-second timeouts.

Unknown tool names, invalid JSON arguments, validation failures, and tool exceptions become tool results, allowing the model to explain or correct the problem. One failed call does not skip the other calls in that response. DIAL HTTP errors and unusable responses surface to the CLI, which reports the error and remains available for another request. Writes are not automatically retried because a timeout does not prove that a mutation failed.

Request-body printing remains available through `get_completion(..., print_request=True)`, but the CLI disables it to avoid routinely logging full conversation and profile data. API-key headers are not printed.

### Tools and Schemas

| Tool name | Arguments | Implementation and reason |
| --- | --- | --- |
| `web_search_tool` | Required non-empty `request` string | Calls Gemini with DIAL's `google_search` static function for grounded public information; returns the model's search response or HTTP error |
| `get_user_by_id` | Required integer `id` | Retrieves one record through `UserClient.get_user` |
| `search_users` | Optional `name`, `surname`, `email`, `gender` | Forwards supplied filters to the service; no filters means an unfiltered search |
| `add_user` | `UserCreate` fields | Validates arguments before calling the service; `name`, `surname`, `email`, and `about_me` are required |
| `update_user` | Required integer `id` and `new_info` object | Validates `new_info` using `UserUpdate` and sends only explicitly supplied fields |
| `delete_users` | Required integer `id` | Deletes one record; the plural function name preserves the original task contract |

Create and update schemas come from Pydantic, so their advertised fields match the request models. The update schema moves nested `$defs` to the outer schema root so address and credit-card `$ref` paths resolve correctly. ID-based tools reject strings, booleans, and fractional IDs rather than silently converting them to a different record ID.

Two existing update defects were corrected: `UserUpdate.credit_card` now uses `CreditCard`, not `UserCreate`, and serialization uses `model_dump(exclude_unset=True)`. For example, changing only `company` sends only `company`; it does not send `null` for every other field. An explicitly supplied `null` is still sent to support intentional clearing. Updates accept successful HTTP 200, 201, or 204 responses.

### System Prompt

The prompt directs the model to check for duplicates, ask for missing required details, disambiguate matching records, obtain authorization for changes and a separate confirmation for deletion, and report success only after a tool confirms it. For a request such as `Add Andrej Karpathy as a new user`, it should gather relevant public information but ask for any missing required details, such as an email address, rather than inventing them.

It also limits web search to public context supplied by the user, treats retrieved content as untrusted data, and discourages disclosure of secrets and unnecessary personal data.

These are model instructions, not application-enforced access controls. The tool layer does not enforce confirmation, redact service responses, or provide authentication and authorization for the User Service. This is a learning agent for mock data, not a production system for sensitive records or payment data. Existing Pydantic models validate declared types and required fields, not business rules such as email validity or duplicate uniqueness. Conversation storage is in-memory only and does not implement context-window trimming.

### Verification

Run the offline suite without credentials, Docker, or network access:

```powershell
python -B -m unittest discover -s tests -v
```

The tests cover request headers and payloads, all six tool schemas and dispatch paths, multiple tool calls and rounds, correlated history, malformed arguments, service failures, loop limits, partial updates, CLI configuration and exits, and a complete mocked search-then-create workflow through the real application components. Tests use the standard-library `unittest` framework and add no runtime dependencies.

Live DIAL behavior, model adherence to the prompt, deployment availability, and compatibility with the running Docker service require a separate check with the configured service, VPN, and authorized API access. The offline tests do not establish those properties.

## 🔍 API Reference

### DIAL Endpoint
```
POST https://ai-proxy.lab.epam.com/openai/deployments/{model}/chat/completions
```

### Request Format
```json
{
  "messages": [
    {
      "role": "system",
      "content": "You are a helpful assistant."
    },
    {
      "role": "user",
      "content": "Who is Andrej Karpathy?"
    }
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "web_search_tool",
        "description": "Tool for WEB searching.",
        "parameters": {
          "type": "object",
          "properties": {
            "request": {
              "type": "string",
              "description": "The search query or question to search for on the web"
            }
          },
          "required": [
            "request"
          ]
        }
      }
    },
    {
      "type": "function",
      "function": {
        "name": "get_user_by_id",
        "description": "Provides full user information",
        "parameters": {
          "type": "object",
          "properties": {
            "id": {
              "type": "integer",
              "description": "User ID"
            }
          },
          "required": [
            "id"
          ]
        }
      }
    },
    ...
  ]
}
```

### Response Format
With tool calls
```json
{
  "choices": [
    {
      "message": {
        "role": "assistant",
        "content": "",
        "tool_calls": [
          {
            "id": "call_6JriK7u5DL2heJ1lkw08WUFd",
            "function": {
              "arguments": "{\"request\":\"Andrej Karpathy profile\"}",
              "name": "web_search_tool"
            },
            "type": "function"
          }
        ]
      },
      "finish_reason": "tool_calls" 
    }
  ]
}
```

Final response:
```json
{
  "choices": [
    {
      "message": {
        "role": "assistant",
        "content": "Andrej Karpathy is..."
      },
      "finish_reason": "stop" 
    }
  ]
}
```
---
# <img src="dialx-banner.png">