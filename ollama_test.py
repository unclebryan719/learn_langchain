from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.messages import HumanMessage
from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.runnables import RunnableConfig
from langchain_ollama.chat_models import ChatOllama
# 导入依赖
import sqlite3
from langgraph.checkpoint.sqlite import SqliteSaver
# 加载环境变量
load_dotenv()

# 初始化模型
model = ChatOllama(model="qwen3.5:9b")
# 建立数据库连接
conn = sqlite3.connect("resources/short_memory.db", check_same_thread=False)
# 初始化检查点
checkpointer = SqliteSaver(conn)
# 自动建表
checkpointer.setup()

# 初始化中间件
middleware = SummarizationMiddleware(
    model=model,
    trigger=("messages", 3),
    keep=("messages", 1)
)



# 创建 AGENT
agent = create_agent(
    model=model,
    middleware=[middleware],
    checkpointer=checkpointer
)

# 设置thread_id
config: RunnableConfig = {
    "configurable":
        {
            "thread_id": "5"
        }
}

if __name__ == "__main__":
    # 调用AGENT
    agent.invoke( { "messages": [ HumanMessage(content="我是小马哥")]}, config)
    agent.invoke( { "messages": [ HumanMessage(content="我不喜欢动物")]}, config)
    agent.invoke( { "messages": [ HumanMessage(content="我喜欢打篮球")]}, config)
    final_result = agent.invoke( { "messages": [ HumanMessage(content="你还记得我吗？")]}, config)

    for message in final_result["messages"]:
        message.pretty_print()