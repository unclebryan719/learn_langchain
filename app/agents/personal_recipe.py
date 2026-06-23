# 基于 langgraph 部署智能体，适用于本地调试
import asyncio
import os
import sqlite3

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.messages.content import create_image_block, create_text_block
from langchain_tavily import TavilySearch
from langgraph.checkpoint.sqlite import SqliteSaver

from app.common.logger import logger

load_dotenv()

model = init_chat_model(
    model="qwen3.6-plus",
    model_provider="openai",
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url=os.getenv("DASHSCOPE_API_BASE_URL"),
    streaming=True,
    extra_body={"enable_thinking": False},
)

web_search = TavilySearch(max_results=3, topic="general")

current_dir = os.path.dirname(os.path.abspath(__file__))
db_dir = os.path.join(current_dir, "..", "..", "db")
os.makedirs(db_dir, exist_ok=True)
db_path = os.path.join(db_dir, "recipe.db")

conn = sqlite3.connect(db_path, check_same_thread=False)
checkpointer = SqliteSaver(conn)
checkpointer.setup()

system_prompt = """
你是一名私人厨师。收到用户提供的食材照片或清单后，请按以下流程操作：
1. 识别和评估食材：若用户提供照片，首先辨识所有可见食材，整理出“当前可用食材清单”。
2. 结合下方提供的网络检索结果，筛选可行菜谱。
3. 从营养价值和制作难度两个维度对候选食谱进行量化打分并排序。
4. 输出结构清晰的建议报告，包含食谱信息、得分、推荐理由。
不要调用任何工具，直接基于已有信息回答。
"""

# 仅用于 checkpoint 读写，不在流式阶段调用 graph 推理
agent = create_agent(
    model=model,
    tools=[],
    checkpointer=checkpointer,
    system_prompt=system_prompt,
)


def _extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text" and "text" in block:
                    parts.append(block["text"])
                elif "text" in block:
                    parts.append(block["text"])
        return "".join(parts)
    return str(content)


def _build_user_text(prompt: str, search_result: str) -> str:
    user_question = prompt.strip() if prompt and prompt.strip() else "请根据图片中的食材推荐菜谱。"
    return (
        f"用户问题：{user_question}\n\n"
        f"网络检索参考信息：\n{search_result}\n\n"
        "请基于以上信息，输出完整的食谱推荐报告。"
    )


def _build_human_message(prompt: str, image: str | None, search_result: str) -> HumanMessage:
    text = _build_user_text(prompt, search_result)
    if not image or not image.strip():
        return HumanMessage(content=text)

    return HumanMessage(
        content=[
            create_image_block(url=image.strip()),
            create_text_block(text=text),
        ]
    )


def _get_history_messages(thread_id: str) -> list:
    checkpoint_tuple = checkpointer.get_tuple({"configurable": {"thread_id": thread_id}})
    if not checkpoint_tuple:
        return []

    messages = checkpoint_tuple.checkpoint.get("channel_values", {}).get("messages", [])
    return list(messages)


def _persist_turn(thread_id: str, user_message: HumanMessage, assistant_message: AIMessage) -> None:
    config = {"configurable": {"thread_id": thread_id}}
    agent.update_state(config, {"messages": [user_message, assistant_message]})


async def _run_web_search(prompt: str) -> str:
    query = prompt.strip() if prompt and prompt.strip() else "常见家常菜谱"
    result = await asyncio.to_thread(web_search.invoke, {"query": query})
    return str(result)


async def search_recipes(prompt: str, image: str | None, thread_id: str):
    """Tavily 搜索 + 单次大模型流式输出（只调用 1 次 LLM）。"""
    logger.info(f"[用户]: {prompt}, image: {image}, thread_id: {thread_id}")
    try:
        yield "🔍 正在搜索食谱，请稍候...\n\n"

        search_result = await _run_web_search(prompt)
        logger.info(f"[搜索完成] thread_id={thread_id}")

        user_message = _build_human_message(prompt, image, search_result)
        history = await asyncio.to_thread(_get_history_messages, thread_id)
        llm_messages = [SystemMessage(content=system_prompt), *history, user_message]

        full_parts: list[str] = []
        async for chunk in model.astream(llm_messages):
            text = _extract_text(chunk.content)
            if not text:
                continue
            full_parts.append(text)
            yield text

        if not full_parts:
            raise RuntimeError("模型未返回有效内容")

        assistant_message = AIMessage(content="".join(full_parts))
        await asyncio.to_thread(_persist_turn, thread_id, user_message, assistant_message)
    except Exception as e:
        logger.error(f"[错误]: {e}")
        yield "信息检索失败，试试看手动输入食物列表？"


def clear_messages(thread_id: str):
    logger.info(f"清空历史消息，thread_id: {thread_id}")
    checkpointer.delete_thread(thread_id)


def _display_user_content(content: str) -> str:
    if content.startswith("用户问题："):
        return content.split("\n", 1)[0].removeprefix("用户问题：").strip()
    return content


def get_messages(thread_id: str) -> list[dict[str, str | None]]:
    logger.info(f"获取历史消息，thread_id：{thread_id}")
    checkpoint_tuple = checkpointer.get_tuple({"configurable": {"thread_id": thread_id}})
    if not checkpoint_tuple:
        return []

    messages = checkpoint_tuple.checkpoint.get("channel_values", {}).get("messages", [])
    if not messages:
        return []

    result = []
    for msg in messages:
        if not msg.content:
            continue

        content = msg.content
        image_url = None

        if isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, dict):
                    item_type = item.get("type")
                    if item_type == "text" and "text" in item:
                        text_parts.append(item["text"])
                    elif item_type == "image" and "url" in item:
                        image_url = item["url"]
                    elif item_type == "image_url":
                        image_data = item.get("image_url", {})
                        if isinstance(image_data, dict):
                            image_url = image_data.get("url")
            content = _display_user_content("".join(text_parts))
        else:
            content = _extract_text(content)
            if isinstance(msg, HumanMessage):
                content = _display_user_content(content)

        if isinstance(msg, HumanMessage):
            result.append({"role": "user", "content": content, "image_url": image_url})
        elif isinstance(msg, AIMessage):
            result.append({"role": "assistant", "content": content, "image_url": image_url})
    return result
