from dotenv import load_dotenv
import os

from langchain.chat_models import init_chat_model
from langchain.messages import HumanMessage
from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.runnables import RunnableConfig
from langchain_ollama.chat_models import ChatOllama

# 加载环境变量
load_dotenv()

# 初始化模型
model = init_chat_model(
    model="qwen3.6-plus",
    model_provider="openai",
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url=os.getenv("DASHSCOPE_API_BASE_URL"),
)

# 定义搜索工具
from langchain_tavily import TavilySearch
web_search = TavilySearch(max_results=5, topic="general")


# 记忆管理
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver
## 建立数据库连接
conn = sqlite3.connect("resources/recipe.db", check_same_thread=False)
# 初始化检查点
checkpointer = SqliteSaver(conn)
# 自动建表
checkpointer.setup()

from langchain.agents import create_agent
system_prompt = """
你是一名私人厨师。收到用户提供的食材照片或清单后，请按以下流程操作：
1.识别和评估食材：若用户提供照片，首先辨识所有可见食材。基于食材的外观状态，评估其新鲜度与可用量，整理出一份“当前可用食材清单”。
2.智能食谱检索：优先调用 web_search 工具，以“可用食材清单”为核心关键词，查找可行菜谱。
3.多维度评估与排序：从营养价值和制作难度两个维度对检索到的候选食谱进行量化打分，并根据得分排序，制作简单且营养丰富的排名靠前。
4.结构化方案输出：把排序局的食谱整理为一份结构清晰的建议报告，要包含食谱信息、得分、推荐理由、食谱的参考图片，帮助用户快速做出决策。
请严格按照流程，优先调用 web_search 工具搜索食谱，搜索不到的情况下才能自己发挥。
"""

# 初始化中间件
middleware = SummarizationMiddleware(
    model=model,
    trigger=("messages", 3),
    keep=("messages", 1)
)



# 创建 AGENT
agent = create_agent(
    model=model,
    tools=[web_search],
    middleware=[middleware],
    system_prompt=system_prompt,
    checkpointer=checkpointer
)

# 设置thread_id
config: RunnableConfig = {
    "configurable":
        {
            "thread_id": "recipe_1"
        }
}

if __name__ == "__main__":
    # 调用AGENT——图片识别出食材
    # 调用tavily，根据食材查询食谱
    # 调用AGENT——将食谱制作难度和营养价值进行排序
    # 调用AGENT——当找不到食谱时，提供创意搭配建议，温度调高
    image_url = "https://aisearch.cdn.bcebos.com/pic_create/2026-04-10/10/74d52055e4947f8c.jpg"
    multimodel_messages = HumanMessage(
        [
            {"type": "text","text": "看看能做什么菜"},
            {"type": "image","url": image_url},
        ]
    )
    # multimodel_messages = HumanMessage(
    #     [
    #         {"type": "text","text": "我想吃第二道菜，帮我生成详细的操作步骤"},
    #     ]
    # )
    final_result = agent.invoke( { "messages": [multimodel_messages]}, config)

    for message in final_result["messages"]:
        message.pretty_print()