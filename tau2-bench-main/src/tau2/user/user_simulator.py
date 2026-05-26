from typing import Optional, Tuple

import json
from loguru import logger

from tau2.data_model.message import (
    Message,
    MultiToolMessage,
    SystemMessage,
    ToolCall,
    UserMessage,
)
from tau2.data_model.tasks import UserInstructions
from tau2.environment.tool import Tool
from tau2.user.base import (
    OUT_OF_SCOPE,
    STOP,
    TRANSFER,
    BaseUser,
    UserState,
    ValidUserInputMessage,
    is_valid_user_history_message,
)
from tau2.utils import DATA_DIR
from tau2.utils.llm_utils import generate

GLOBAL_USER_SIM_GUIDELINES_DIR = DATA_DIR / "tau2" / "user_simulator"


GLOBAL_USER_SIM_GUIDELINES_PATH = (
    GLOBAL_USER_SIM_GUIDELINES_DIR / "simulation_guidelines.md"
)

GLOBAL_USER_SIM_GUIDELINES_PATH_TOOLS = (
    GLOBAL_USER_SIM_GUIDELINES_DIR / "simulation_guidelines_tools.md"
)
GLOBAL_USER_SIM_GUIDELINES_PATH_TOOLS_EDU = (
    GLOBAL_USER_SIM_GUIDELINES_DIR / "simulation_guidelines_tools_edu.md"
)


def get_global_user_sim_guidelines(use_tools: bool = False, domain: Optional[str] = None) -> str:
    """
    Get the global user simulator guidelines.
    """
    import os
    if domain == "edu":
        env_var = (
            "TAU2_USER_SIM_GUIDELINES_TOOLS_EDU_PATH" if use_tools else "TAU2_USER_SIM_GUIDELINES_EDU_PATH"
        )
        custom_path = os.getenv(env_var)
        try:
            if custom_path:
                with open(custom_path, "r", encoding="utf-8") as fp:
                    return fp.read()
        except Exception as e:
            logger.warning(
                f"Failed to load custom user sim guidelines from {custom_path}: {e}"
            )
        with open(GLOBAL_USER_SIM_GUIDELINES_PATH_TOOLS_EDU, "r", encoding="utf-8") as fp:
            return fp.read()
    env_var = (
        "TAU2_USER_SIM_GUIDELINES_TOOLS_PATH" if use_tools else "TAU2_USER_SIM_GUIDELINES_PATH"
    )
    custom_path = os.getenv(env_var)
    try:
        if custom_path:
            with open(custom_path, "r", encoding="utf-8") as fp:
                return fp.read()
    except Exception as e:
        logger.warning(
            f"Failed to load custom user sim guidelines from {custom_path}: {e}"
        )
    if use_tools:
        with open(GLOBAL_USER_SIM_GUIDELINES_PATH_TOOLS, "r", encoding="utf-8") as fp:
            return fp.read()
    with open(GLOBAL_USER_SIM_GUIDELINES_PATH, "r", encoding="utf-8") as fp:
        return fp.read()


SYSTEM_PROMPT = """
{global_user_sim_guidelines}

<rules>
- 你是学生，老师主导课堂。你绝不能主动引导教学方向或暴露自己的缺陷。
- 不能主动提问来暴露自己的知识盲区。你的不理解只应在老师提问或讲解时自然显现。
- 不能在老师讲完一个知识点后，主动把话题引向下一个缺陷相关的内容（比如"老师接下来我们是不是要学XX呀？"）。
- 老师没问你、没讲到的内容，你就安静等着，不要主动提起。
- 只有在老师给出明确相关提示后，才可调用对应的解决函数（如 mark_defect_solved('D2-1')）；否则不得调用。
- 当老师讲完某个部分等你回应时，你只需要简短表达"听懂了/没听懂"，然后等老师继续，不要主动追问其他话题。
</rules>

<scenario>
{instructions}
</scenario>
""".strip()


class UserSimulator(BaseUser):
    """Stateless implementation of a user simulator."""

    def __init__(
        self,
        tools: Optional[list[Tool]] = None,
        instructions: Optional[UserInstructions] = None,
        llm: Optional[str] = None,
        llm_args: Optional[dict] = None,
    ):
        super().__init__(instructions=instructions, llm=llm, llm_args=llm_args)
        self.tools = tools

    @property
    def global_simulation_guidelines(self) -> str:
        """
        The simulation guidelines for the user simulator.
        """
        use_tools = self.tools is not None
        try:
            domain = getattr(self.instructions, "domain", None)
        except Exception:
            domain = None
        return get_global_user_sim_guidelines(use_tools=use_tools, domain=domain)

    @property
    def system_prompt(self) -> str:
        if self.instructions is None:
            logger.warning("No instructions provided for user simulator")
        base = SYSTEM_PROMPT.format(
            global_user_sim_guidelines=self.global_simulation_guidelines,
            instructions=self.instructions,
        )
        defects_text = self._build_defects_text()
        if defects_text:
            return base + "\n<defects>\n" + defects_text + "\n</defects>"
        return base

    def _build_defects_text(self) -> str:
        if not self.tools:
            return ""
        t = None
        for tool in self.tools:
            if getattr(tool, "name", "") == "get_defects":
                t = tool
                break
        if t is None:
            return ""
        try:
            import json
            all_defects = []
            seen = set()
            for stage in ["D1", "D2", "D3"]:
                try:
                    res = t(task_id=stage)
                except Exception:
                    res = None
                if not res:
                    continue
                try:
                    data = res if isinstance(res, dict) else json.loads(res)
                except Exception:
                    data = {}
                defects = data.get("defects", [])
                for d in defects:
                    did = d.get("id", "")
                    if did and did not in seen:
                        all_defects.append(d)
                        seen.add(did)
            if not all_defects:
                try:
                    res = t()
                    data = res if isinstance(res, dict) else json.loads(res)
                    all_defects = data.get("defects", [])
                except Exception:
                    all_defects = []
            if not all_defects:
                return ""
            lines = ["以下是你当前的认知盲区（仅供你在回应老师提问时参考，绝对不要主动提起或暴露这些内容）："]
            for d in all_defects:
                did = d.get("id", "")
                desc = d.get("defect", "")
                fn = d.get("solve_function", "")
                lines.append(f"- {did}：{desc}")
                if fn:
                    lines.append(f"  解决函数：{fn}")
            lines.append("")
            lines.append("【重要提醒】")
            lines.append("- 这些盲区只用于：当老师主动讲解或提问到相关知识点时，帮助你判断自己应该表现出怎样的认知水平（比如答错、困惑、不理解）。")
            lines.append("- 绝对不要按照上面的列表去依次提问、暗示或引导老师。你不知道自己有这些盲区——你只是一个普通学生。")
            lines.append("- 不要在没有老师讲解的情况下，把课堂引向某个盲区相关的话题。")
            lines.append("- 只有当老师的讲解确实解决了某个盲区时，才可调用对应的解决函数（如 mark_defect_solved('D2-1')）。")
            return "\n".join(lines)
        except Exception:
            return ""

    def get_init_state(
        self, message_history: Optional[list[Message]] = None
    ) -> UserState:
        """
        Get the initial state of the user simulator.
        """
        if message_history is None:
            message_history = []
        assert all(is_valid_user_history_message(m) for m in message_history), (
            "Invalid user message history. User messages must be of type UserMessage, AssistantMessage, or ToolMessage to User."
        )

        user_state = UserState(
            system_messages=[SystemMessage(role="system", content=self.system_prompt)],
            messages=message_history,
        )
        return user_state

    @classmethod
    def is_stop(cls, message: UserMessage) -> bool:
        """
        Check if the message is a stop message.
        """
        if message.is_tool_call():
            return False
        assert message.content is not None
        return (
            STOP in message.content
            or TRANSFER in message.content
            or OUT_OF_SCOPE in message.content
        )

    def generate_next_message(
        self, message: ValidUserInputMessage, state: UserState
    ) -> Tuple[UserMessage, UserState]:
        return self._generate_next_message(message, state)

    def _generate_next_message(
        self, message: ValidUserInputMessage, state: UserState
    ) -> Tuple[UserMessage, UserState]:
        """Get the response from the user simulator.

        Args:
            message: The assistant or tool message.
            state: The user simulator's state.

        Returns:
            A tuple containing the user message and the updated user state.
        """
        # Updating state with new message
        if isinstance(message, MultiToolMessage):
            state.messages.extend(message.tool_messages)
        else:
            state.messages.append(message)

        # Refresh system prompt to reflect current defects
        state.system_messages = [SystemMessage(role="system", content=self.system_prompt)]

        messages = state.system_messages + state.flip_roles()

        # Generate response
        assistant_message = generate(
            model=self.llm,
            messages=messages,
            tools=self.tools,
            role="user",
            **self.llm_args,
        )

        user_response = assistant_message.content
        # 过滤 <think>...</think> 思考块，避免教师模型看到用户模拟器的内部推理
        if user_response:
            import re
            # 情况1：完整的 <think>...</think> 块
            user_response = re.sub(r"<think>.*?</think>", "", user_response, flags=re.DOTALL)
            # 情况2：API 裁掉了 <think> 开头，只剩内容 + </think>（即以 </think> 为分隔符取后半部分）
            if "</think>" in user_response:
                user_response = user_response.split("</think>", 1)[-1]
            user_response = user_response.strip()
        # 如果过滤 think 块后内容变空且没有工具调用，打印原始返回便于排查
        if (not user_response or user_response.strip() == "") and assistant_message.tool_calls is None:
            print(f"[WARNING] 学生模拟器返回空内容，原始返回: content={assistant_message.content!r}, tool_calls={assistant_message.tool_calls}, raw_data={assistant_message.raw_data}")
        logger.debug(f"Response: {user_response}")

        user_message = UserMessage(
            role="user",
            content=user_response,
            cost=assistant_message.cost,
            usage=assistant_message.usage,
            raw_data=assistant_message.raw_data,
        )

        # flip the requestor of the tool calls
        if assistant_message.tool_calls is not None:
            user_message.tool_calls = []
            for tool_call in assistant_message.tool_calls:
                user_message.tool_calls.append(
                    ToolCall(
                        id=tool_call.id,
                        name=tool_call.name,
                        arguments=tool_call.arguments,
                        requestor="user",
                    )
                )

        # Updating state with response
        state.messages.append(user_message)
        return user_message, state


class DummyUser(UserSimulator):
    """A dummy user to run a agent solo simulation."""

    def get_init_state(
        self, message_history: Optional[list[Message]] = None
    ) -> UserState:
        return UserState(messages=[], system_messages=[])

    def is_stop(cls, message: UserMessage) -> bool:
        raise NotImplementedError("DummyUser does not support stop messages")

    def set_seed(self, seed: int):
        pass

    def generate_next_message(
        self, message: ValidUserInputMessage, state: UserState
    ) -> tuple[UserMessage, UserState]:
        raise NotImplementedError("DummyUser does not support generate_next_message")
