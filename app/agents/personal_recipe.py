# 基于 langgraph 部署智能体，适用于本地调试
import asyncio
import json
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

web_search = TavilySearch(
    max_results=5,
    topic="general",
    include_images=True,
    include_image_descriptions=True,
)

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
5. 每个推荐食谱必须附带参考图片：优先使用「网络检索参考信息」中「相关图片」里的 URL，
   用 Markdown 格式单独一行输出，例如：![番茄炒蛋](https://example.com/image.jpg)
   若检索结果中没有与菜名匹配的图片，可省略该菜的图片，但不得编造 URL。
不要调用任何工具，直接基于已有信息回答。
"""

search_plan_prompt = """
你是搜索查询规划助手。根据对话历史和用户最新问题，决定是否调用 Tavily 联网搜索，并生成具体搜索词。

规则：
1. 用户说「第N道菜 / 第一个推荐 / 上面那道」等指代时，必须先从历史中解析出具体菜名，
   再用「菜名 + 做法/步骤/详细教程」作为 query，禁止直接搜索「第二道菜」等指代词。
2. 首次问「能做什么菜」、上传食材、列出食材清单时，need_search=true，query 基于食材或用户描述。
3. 用户只是确认、闲聊、或问题已能仅凭对话历史完整回答时，need_search=false。
4. query 必须是可直接用于搜索引擎的具体中文关键词，可含菜名、做法、步骤、成品图等。
5. 只输出一个 JSON 对象，不要 markdown 代码块，格式：
{"need_search": true, "query": "番茄炒蛋 详细做法 步骤"}
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


def _build_search_query(prompt: str) -> str:
    base = prompt.strip() if prompt and prompt.strip() else "家常菜谱推荐"
    return f"{base} 做法 步骤 成品图"


def _parse_json_object(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("响应中未找到 JSON 对象")
    return json.loads(text[start : end + 1])


async def _plan_web_search(prompt: str, history: list) -> tuple[bool, str | None]:
    user_question = prompt.strip() if prompt and prompt.strip() else "请根据图片中的食材推荐菜谱。"

    if not history:
        return True, _build_search_query(user_question)

    planner_messages = [
        SystemMessage(content=search_plan_prompt),
        *history[-8:],
        HumanMessage(content=f"用户最新问题：{user_question}"),
    ]
    response = await model.ainvoke(planner_messages)
    try:
        plan = _parse_json_object(_extract_text(response.content))
    except (ValueError, json.JSONDecodeError) as e:
        logger.warning("[搜索规划] 解析失败: %s，跳过联网搜索", e)
        return False, None

    need_search = bool(plan.get("need_search"))
    query = (plan.get("query") or "").strip() or None
    if need_search and not query:
        need_search = False
    logger.info("[搜索规划] need_search=%s query=%r", need_search, query)
    return need_search, query


def _format_image_entry(image) -> str | None:
    if isinstance(image, str) and image.strip():
        return image.strip()
    if isinstance(image, dict):
        url = (image.get("url") or image.get("src") or "").strip()
        if not url:
            return None
        description = (
            image.get("description") or image.get("alt") or image.get("title") or "参考图"
        ).strip()
        return f"{description}: {url}"
    return None


def _format_search_result(result) -> str:
    if isinstance(result, str):
        return result
    if not isinstance(result, dict):
        return str(result)

    if result.get("error"):
        return f"搜索出错: {result['error']}"

    lines: list[str] = []
    answer = result.get("answer")
    if answer:
        lines.append(f"摘要: {answer}")

    lines.append("搜索结果:")
    for index, item in enumerate(result.get("results", []), start=1):
        title = item.get("title", "未知标题")
        url = item.get("url", "")
        content = item.get("content", "")
        lines.append(f"{index}. {title}")
        if url:
            lines.append(f"   链接: {url}")
        if content:
            lines.append(f"   内容: {content}")

    image_lines = [
        formatted
        for image in result.get("images") or []
        if (formatted := _format_image_entry(image))
    ]
    if image_lines:
        lines.append("相关图片（请为对应食谱选用以下 URL，并用 Markdown 图片语法展示）:")
        lines.extend(f"- {line}" for line in image_lines)
    else:
        lines.append("相关图片: 本次检索未返回可用图片。")

    return "\n".join(lines)


def _build_user_text(prompt: str, search_result: str, searched: bool) -> str:
    user_question = prompt.strip() if prompt and prompt.strip() else "请根据图片中的食材推荐菜谱。"
    if searched:
        reference = f"网络检索参考信息：\n{search_result}\n\n"
        tail = (
            "请基于以上信息，输出完整的食谱推荐报告；"
            "每个食谱需包含 Markdown 格式的参考图片（若检索结果中有匹配图片）。"
        )
    else:
        reference = f"{search_result}\n\n"
        tail = "请结合对话历史直接回答用户问题，无需重复完整推荐列表。"
    return f"用户问题：{user_question}\n\n{reference}{tail}"


def _build_human_message(
    prompt: str, image: str | None, search_result: str, searched: bool
) -> HumanMessage:
    text = _build_user_text(prompt, search_result, searched)
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


async def _run_web_search(query: str) -> str:
    result = await asyncio.to_thread(web_search.invoke, {"query": query})
    formatted = _format_search_result(result)
    logger.info(
        "[Tavily] query=%r image_count=%s",
        query,
        len(result.get("images", [])) if isinstance(result, dict) else 0,
    )
    if logger.isEnabledFor(10):
        logger.debug("[Tavily raw] %s", json.dumps(result, ensure_ascii=False)[:2000])
    return formatted


NO_SEARCH_HINT = "（本次无需额外网络检索，请结合上文对话历史回答用户问题。）"


async def search_recipes(prompt: str, image: str | None, thread_id: str):
    """搜索规划 + Tavily（按需）+ 单次大模型流式输出。"""
    logger.info(f"[用户]: {prompt}, image: {image}, thread_id: {thread_id}")
    try:
        history = await asyncio.to_thread(_get_history_messages, thread_id)
        need_search, query = await _plan_web_search(prompt, history)

        if need_search and query:
            yield "🔍 正在搜索食谱，请稍候...\n\n"
            search_result = await _run_web_search(query)
            logger.info(f"[搜索完成] thread_id={thread_id}")
            searched = True
        else:
            search_result = NO_SEARCH_HINT
            searched = False
            logger.info(f"[跳过搜索] thread_id={thread_id}")

        user_message = _build_human_message(prompt, image, search_result, searched)
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
