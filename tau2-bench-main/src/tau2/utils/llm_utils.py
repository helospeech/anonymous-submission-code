import json
import re
import os
from typing import Any, Optional

import requests
import litellm
from litellm import completion, completion_cost
from litellm.caching.caching import Cache
from litellm.main import ModelResponse, Usage
from loguru import logger

from tau2.config import (
    DEFAULT_LLM_CACHE_TYPE,
    DEFAULT_MAX_RETRIES,
    DEFAULT_LLM_TIMEOUT,
    LLM_CACHE_ENABLED,
    REDIS_CACHE_TTL,
    REDIS_CACHE_VERSION,
    REDIS_HOST,
    REDIS_PASSWORD,
    REDIS_PORT,
    REDIS_PREFIX,
    USE_LANGFUSE,
)
from tau2.data_model.message import (
    AssistantMessage,
    Message,
    SystemMessage,
    ToolCall,
    ToolMessage,
    UserMessage,
)
from tau2.environment.tool import Tool

# litellm._turn_on_debug()

if USE_LANGFUSE:
    # set callbacks
    litellm.success_callback = ["langfuse"]
    litellm.failure_callback = ["langfuse"]

litellm.drop_params = True

if LLM_CACHE_ENABLED:
    if DEFAULT_LLM_CACHE_TYPE == "redis":
        logger.info(f"LiteLLM: Using Redis cache at {REDIS_HOST}:{REDIS_PORT}")
        litellm.cache = Cache(
            type=DEFAULT_LLM_CACHE_TYPE,
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=REDIS_PASSWORD,
            namespace=f"{REDIS_PREFIX}:{REDIS_CACHE_VERSION}:litellm",
            ttl=REDIS_CACHE_TTL,
        )
    elif DEFAULT_LLM_CACHE_TYPE == "local":
        logger.info("LiteLLM: Using local cache")
        litellm.cache = Cache(
            type="local",
            ttl=REDIS_CACHE_TTL,
        )
    else:
        raise ValueError(
            f"Invalid cache type: {DEFAULT_LLM_CACHE_TYPE}. Should be 'redis' or 'local'"
        )
    litellm.enable_cache()
else:
    logger.info("LiteLLM: Cache is disabled")
    litellm.disable_cache()


ALLOW_SONNET_THINKING = False

if not ALLOW_SONNET_THINKING:
    logger.warning("Sonnet thinking is disabled")


def _parse_ft_model_name(model: str) -> str:
    """
    Parse the ft model name from the litellm model name.
    e.g: "ft:gpt-4.1-mini-2025-04-14:sierra::BSQA2TFg" -> "gpt-4.1-mini-2025-04-14"
    """
    pattern = r"ft:(?P<model>[^:]+):(?P<provider>\w+)::(?P<id>\w+)"
    match = re.match(pattern, model)
    if match:
        return match.group("model")
    else:
        return model


def get_response_cost(response: ModelResponse) -> float:
    """
    Get the cost of the response from the litellm completion.
    """
    response.model = _parse_ft_model_name(
        response.model
    )  # FIXME: Check Litellm, passing the model to completion_cost doesn't work.
    try:
        cost = completion_cost(completion_response=response)
    except Exception as e:
        logger.error(e)
        return 0.0
    return cost


def get_response_usage(response: ModelResponse) -> Optional[dict]:
    usage: Optional[Usage] = response.get("usage")
    if usage is None:
        return None
    return {
        "completion_tokens": usage.completion_tokens,
        "prompt_tokens": usage.prompt_tokens,
    }


def to_tau2_messages(
    messages: list[dict], ignore_roles: set[str] = set()
) -> list[Message]:
    """
    Convert a list of messages from a dictionary to a list of Tau2 messages.
    """
    tau2_messages = []
    for message in messages:
        role = message["role"]
        if role in ignore_roles:
            continue
        if role == "user":
            tau2_messages.append(UserMessage(**message))
        elif role == "assistant":
            tau2_messages.append(AssistantMessage(**message))
        elif role == "tool":
            tau2_messages.append(ToolMessage(**message))
        elif role == "system":
            tau2_messages.append(SystemMessage(**message))
        else:
            raise ValueError(f"Unknown message type: {role}")
    return tau2_messages


def to_litellm_messages(messages: list[Message]) -> list[dict]:
    """
    Convert a list of Tau2 messages to a list of litellm messages.
    """
    litellm_messages = []
    for message in messages:
        if isinstance(message, UserMessage):
            litellm_messages.append({"role": "user", "content": message.content})
        elif isinstance(message, AssistantMessage):
            tool_calls = None
            if message.is_tool_call():
                tool_calls = [
                    {
                        "id": tc.id,
                        "name": tc.name,
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                        "type": "function",
                    }
                    for tc in message.tool_calls
                ]
            litellm_messages.append(
                {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": tool_calls,
                }
            )
        elif isinstance(message, ToolMessage):
            litellm_messages.append(
                {
                    "role": "tool",
                    "content": message.content,
                    "tool_call_id": message.id,
                }
            )
        elif isinstance(message, SystemMessage):
            litellm_messages.append({"role": "system", "content": message.content})
    return litellm_messages


def _to_anthropic_messages(litellm_messages: list[dict]) -> tuple[Optional[str], list[dict]]:
    """
    将 litellm 格式的消息列表转换为 Anthropic Messages API 格式。
    返回 (system_prompt, messages)。
    Anthropic 要求 system 单独传，不在 messages 列表中。
    """
    system_prompt = None
    anthropic_messages = []
    for msg in litellm_messages:
        role = msg.get("role")
        if role == "system":
            # Anthropic 的 system 是单独字段
            if system_prompt is None:
                system_prompt = msg["content"]
            else:
                system_prompt += "\n\n" + msg["content"]
        elif role == "user":
            anthropic_messages.append({"role": "user", "content": msg["content"]})
        elif role == "assistant":
            content_blocks = []
            if msg.get("content"):
                content_blocks.append({"type": "text", "text": msg["content"]})
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", {})
                    args_str = fn.get("arguments", "{}")
                    try:
                        input_obj = json.loads(args_str) if isinstance(args_str, str) else args_str
                    except Exception:
                        input_obj = {}
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id"),
                        "name": fn.get("name"),
                        "input": input_obj,
                    })
            if not content_blocks:
                content_blocks.append({"type": "text", "text": ""})
            anthropic_messages.append({"role": "assistant", "content": content_blocks})
        elif role == "tool":
            # Anthropic 用 tool_result 类型的 user message
            anthropic_messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": msg.get("tool_call_id"),
                    "content": msg.get("content", ""),
                }]
            })
    return system_prompt, anthropic_messages


def _to_anthropic_tools(tools_schema: list[dict]) -> list[dict]:
    """
    将 OpenAI 格式的 tools schema 转换为 Anthropic 格式。
    OpenAI: {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}
    Anthropic: {"name": ..., "description": ..., "input_schema": ...}
    """
    anthropic_tools = []
    for tool in tools_schema:
        fn = tool.get("function", {})
        anthropic_tools.append({
            "name": fn.get("name"),
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
        })
    return anthropic_tools


def _to_gemini_contents(litellm_messages: list[dict]) -> tuple[Optional[str], list[dict]]:
    """
    将 litellm 格式的消息列表转换为 Gemini API 的 contents 格式。
    Gemini 使用 role: "user"/"model", parts: [{text: ...}] 格式。
    system 消息作为 system_instruction 单独传递。
    """
    system_prompt = None
    contents = []
    for msg in litellm_messages:
        role = msg.get("role")
        if role == "system":
            if system_prompt is None:
                system_prompt = msg["content"]
            else:
                system_prompt += "\n\n" + msg["content"]
        elif role == "user":
            contents.append({
                "role": "user",
                "parts": [{"text": msg["content"]}]
            })
        elif role == "assistant":
            parts = []
            if msg.get("content"):
                parts.append({"text": msg["content"]})
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", {})
                    args_str = fn.get("arguments", "{}")
                    try:
                        args_obj = json.loads(args_str) if isinstance(args_str, str) else args_str
                    except Exception:
                        args_obj = {}
                    parts.append({
                        "functionCall": {
                            "name": fn.get("name"),
                            "args": args_obj,
                        }
                    })
            if not parts:
                parts.append({"text": ""})
            contents.append({"role": "model", "parts": parts})
        elif role == "tool":
            # Gemini 用 functionResponse
            tool_content = msg.get("content", "")
            try:
                response_obj = json.loads(tool_content) if isinstance(tool_content, str) else tool_content
            except Exception:
                response_obj = {"result": tool_content}
            contents.append({
                "role": "user",
                "parts": [{
                    "functionResponse": {
                        "name": msg.get("tool_call_id", "unknown"),
                        "response": response_obj if isinstance(response_obj, dict) else {"result": str(response_obj)},
                    }
                }]
            })
    return system_prompt, contents


def _to_gemini_tools(tools_schema: list[dict]) -> list[dict]:
    """
    将 OpenAI 格式的 tools schema 转换为 Gemini 格式。
    Gemini: {"functionDeclarations": [{"name": ..., "description": ..., "parameters": ...}]}
    """
    function_declarations = []
    for tool in tools_schema:
        fn = tool.get("function", {})
        decl = {
            "name": fn.get("name"),
            "description": fn.get("description", ""),
        }
        params = fn.get("parameters")
        if params:
            decl["parameters"] = params
        function_declarations.append(decl)
    return [{"functionDeclarations": function_declarations}]


def _generate_gemini(
    model: str,
    litellm_messages: list[dict],
    tools_schema: Optional[list[dict]],
    tool_choice: Optional[str],
    max_retries: int,
    role: Optional[str] = None,
    **kwargs: Any,
) -> AssistantMessage:
    """
    使用 Gemini API 格式调用模型。
    URL: configured via GEMINI_API_URL environment variable
    请求格式使用 contents (role + parts)，响应格式使用 candidates。
    """
    import time
    url = os.getenv("GEMINI_API_URL", "https://openrouter.ai/api/v1/chat/completions")
    api_key = os.getenv("GEMINI_API_KEY", os.getenv("OPENROUTER_API_KEY", ""))

    system_prompt, contents = _to_gemini_contents(litellm_messages)

    headers = {
        "Content-Type": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "contents": contents,
    }
    if system_prompt:
        payload["system_instruction"] = {
            "parts": [{"text": system_prompt}]
        }
    if tools_schema:
        payload["tools"] = _to_gemini_tools(tools_schema)
    if tool_choice is not None:
        if tool_choice == "auto":
            payload["tool_config"] = {"function_calling_config": {"mode": "AUTO"}}
        elif tool_choice == "required":
            payload["tool_config"] = {"function_calling_config": {"mode": "ANY"}}
        elif tool_choice == "none":
            payload["tool_config"] = {"function_calling_config": {"mode": "NONE"}}

    # 传递额外参数（temperature 等）
    generation_config = {}
    for k, v in kwargs.items():
        if v is not None and k not in ("thinking",):
            generation_config[k] = v
    if generation_config:
        payload["generationConfig"] = generation_config

    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=DEFAULT_LLM_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            break
        except Exception as e:
            if attempt < max_retries:
                logger.warning(f"Gemini API call failed with {e}. Retrying {attempt + 1}/{max_retries} in 3 seconds...")
                time.sleep(3)
            else:
                logger.error(f"Gemini API call failed after {max_retries} retries: {e}")
                raise e

    # 解析 Gemini 响应 (candidates 格式)
    candidates = data.get("candidates", [])
    text_parts = []
    tool_calls = []
    if candidates:
        candidate = candidates[0]
        content_obj = candidate.get("content", {})
        parts = content_obj.get("parts", [])
        for part in parts:
            if "text" in part:
                text_parts.append(part["text"])
            elif "functionCall" in part:
                fc = part["functionCall"]
                tool_calls.append(
                    ToolCall(
                        id=fc.get("name", ""),  # Gemini 没有独立 id，用 name 代替
                        name=fc.get("name"),
                        arguments=fc.get("args", {}),
                    )
                )

    content = "\n".join(text_parts) if text_parts else None
    tool_calls = tool_calls or None

    # 解析 usage
    raw_usage = data.get("usageMetadata", {})
    usage = {
        "prompt_tokens": raw_usage.get("promptTokenCount", 0),
        "completion_tokens": raw_usage.get("candidatesTokenCount", 0),
    }

    message = AssistantMessage(
        role="assistant",
        content=content,
        tool_calls=tool_calls,
        cost=0.0,
        usage=usage,
        raw_data=data,
    )
    return message


def _generate_anthropic(
    model: str,
    litellm_messages: list[dict],
    tools_schema: Optional[list[dict]],
    tool_choice: Optional[str],
    max_retries: int,
    **kwargs: Any,
) -> AssistantMessage:
    """
    使用 Anthropic Messages API 格式调用教师模型。
    """
    import time
    url = os.getenv("TEACHER_API_URL", "https://openrouter.ai/api/v1/chat/completions")
    api_key = os.getenv("TEACHER_API_KEY", os.getenv("OPENROUTER_API_KEY", ""))

    system_prompt, anthropic_messages = _to_anthropic_messages(litellm_messages)

    headers = {
        "Content-Type": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "max_tokens": kwargs.pop("max_tokens", 4096),
        "messages": anthropic_messages,
    }
    if system_prompt:
        payload["system"] = system_prompt
    if tools_schema:
        payload["tools"] = _to_anthropic_tools(tools_schema)
    if tool_choice is not None:
        # Anthropic tool_choice 格式: {"type": "auto"} / {"type": "any"} / {"type": "tool", "name": "..."}
        if tool_choice == "required":
            payload["tool_choice"] = {"type": "any"}
        elif tool_choice == "auto":
            payload["tool_choice"] = {"type": "auto"}
        elif tool_choice == "none":
            pass  # 不传 tool_choice
        else:
            payload["tool_choice"] = {"type": "tool", "name": tool_choice}

    # 传递额外参数（temperature 等）
    for k, v in kwargs.items():
        if v is not None and k not in ("thinking",):
            payload[k] = v

    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=DEFAULT_LLM_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            break
        except Exception as e:
            if attempt < max_retries:
                wait = 3 * (2 ** attempt) if "429" in str(e) else 3
                logger.warning(f"Anthropic API call failed with {e}. Retrying {attempt + 1}/{max_retries} in {wait}s...")
                time.sleep(wait)
            else:
                logger.error(f"Anthropic API call failed after {max_retries} retries: {e}")
                raise e

    # 解析 Anthropic 响应
    content_blocks = data.get("content", [])
    text_parts = []
    tool_calls = []
    for block in content_blocks:
        if block.get("type") == "text":
            text_parts.append(block.get("text", ""))
        elif block.get("type") == "tool_use":
            tool_calls.append(
                ToolCall(
                    id=block.get("id"),
                    name=block.get("name"),
                    arguments=block.get("input", {}),
                )
            )

    content = "\n".join(text_parts) if text_parts else None
    tool_calls = tool_calls or None

    # 解析 usage
    raw_usage = data.get("usage", {})
    usage = {
        "prompt_tokens": raw_usage.get("input_tokens", 0),
        "completion_tokens": raw_usage.get("output_tokens", 0),
    }

    message = AssistantMessage(
        role="assistant",
        content=content,
        tool_calls=tool_calls,
        cost=0.0,
        usage=usage,
        raw_data=data,
    )
    return message


def _generate_openai(
    model: str,
    litellm_messages: list[dict],
    tools_schema: Optional[list[dict]],
    tool_choice: Optional[str],
    max_retries: int,
    role: Optional[str] = None,
    **kwargs: Any,
) -> AssistantMessage:
    """
    使用 OpenAI Chat Completions API 格式调用模型（学生模型或默认）。
    """
    import time
    if role == "user":
        url = os.getenv("STUDENT_API_URL", os.getenv("DMX_API_URL", "https://openrouter.ai/api/v1/chat/completions"))
        api_key = os.getenv("STUDENT_API_KEY", os.getenv("OPENROUTER_API_KEY", ""))
    else:
        url = os.getenv("TEACHER_API_URL", os.getenv("DMX_API_URL", "https://openrouter.ai/api/v1/chat/completions"))
        api_key = os.getenv("TEACHER_API_KEY", os.getenv("OPENROUTER_API_KEY", ""))

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": model,
        "messages": litellm_messages,
    }
    if tools_schema:
        payload["tools"] = tools_schema
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice
    for k, v in kwargs.items():
        if v is not None:
            payload[k] = v

    logger.info(f"🚀 Preparing to call model: '{model}' via URL: '{url}' (role: {role})")

    for attempt in range(max_retries + 1):
        try:
            resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=DEFAULT_LLM_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            break
        except Exception as e:
            if attempt < max_retries:
                wait = 3 * (2 ** attempt) if "429" in str(e) else 3
                logger.warning(f"API call failed with {e}. Retrying {attempt + 1}/{max_retries} in {wait}s...")
                time.sleep(wait)
            else:
                logger.error(f"API call failed after {max_retries} retries: {e}")
                raise e

    usage = data.get("usage")
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message", {})
    content = msg.get("content")
    raw_tool_calls = msg.get("tool_calls") or []
    tool_calls = []
    for tc in raw_tool_calls:
        fn = tc.get("function", {}) or {}
        args = fn.get("arguments") or "{}"
        try:
            parsed_args = json.loads(args)
        except Exception:
            parsed_args = {}
        tool_calls.append(
            ToolCall(
                id=tc.get("id"),
                name=fn.get("name"),
                arguments=parsed_args,
            )
        )
    tool_calls = tool_calls or None

    message = AssistantMessage(
        role="assistant",
        content=content,
        tool_calls=tool_calls,
        cost=0.0,
        usage=usage,
        raw_data=data,
    )
    return message


def generate(
    model: str,
    messages: list[Message],
    tools: Optional[list[Tool]] = None,
    tool_choice: Optional[str] = None,
    **kwargs: Any,
) -> UserMessage | AssistantMessage:
    """
    Generate a response from the model.

    Args:
        model: The model to use.
        messages: The messages to send to the model.
        tools: The tools to use.
        tool_choice: The tool choice to use.
        role: "agent" for teacher model (Anthropic API), "user" for student model (OpenAI API).
        **kwargs: Additional arguments to pass to the model.

    Returns: The assistant message.
    """
    max_retries = kwargs.pop("num_retries", DEFAULT_MAX_RETRIES)
    role = kwargs.pop("role", None)

    if model.startswith("claude") and not ALLOW_SONNET_THINKING:
        kwargs["thinking"] = {"type": "disabled"}

    litellm_messages = to_litellm_messages(messages)
    tools_schema = [tool.openai_schema for tool in tools] if tools else None
    if tools_schema and tool_choice is None:
        tool_choice = "auto"

    if "gemini" in model.lower():
        # Gemini 系列模型：使用 Gemini API (contents 格式)
        return _generate_gemini(
            model=model,
            litellm_messages=litellm_messages,
            tools_schema=tools_schema,
            tool_choice=tool_choice,
            max_retries=max_retries,
            role=role,
            **kwargs,
        )
    elif role == "agent" and "claude" in model.lower():
        # 教师模型且为 Claude 系列：使用 Anthropic Messages API
        return _generate_anthropic(
            model=model,
            litellm_messages=litellm_messages,
            tools_schema=tools_schema,
            tool_choice=tool_choice,
            max_retries=max_retries,
            **kwargs,
        )
    else:
        # 学生模型或默认：使用 OpenAI Chat Completions API
        return _generate_openai(
            model=model,
            litellm_messages=litellm_messages,
            tools_schema=tools_schema,
            tool_choice=tool_choice,
            max_retries=max_retries,
            role=role,
            **kwargs,
        )


def get_cost(messages: list[Message]) -> tuple[float, float] | None:
    """
    Get the cost of the interaction between the agent and the user.
    Returns None if any message has no cost.
    """
    agent_cost = 0
    user_cost = 0
    for message in messages:
        if isinstance(message, ToolMessage):
            continue
        if message.cost is not None:
            if isinstance(message, AssistantMessage):
                agent_cost += message.cost
            elif isinstance(message, UserMessage):
                user_cost += message.cost
        else:
            logger.warning(f"Message {message.role}: {message.content} has no cost")
            return None
    return agent_cost, user_cost


def get_token_usage(messages: list[Message]) -> dict:
    """
    Get the token usage of the interaction between the agent and the user.
    """
    usage = {"completion_tokens": 0, "prompt_tokens": 0}
    for message in messages:
        if isinstance(message, ToolMessage):
            continue
        if message.usage is None:
            logger.warning(f"Message {message.role}: {message.content} has no usage")
            continue
        usage["completion_tokens"] += message.usage["completion_tokens"]
        usage["prompt_tokens"] += message.usage["prompt_tokens"]
    return usage
