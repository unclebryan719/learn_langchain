from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain.agents import create_agent
from langchain.tools import tool
from langchain.messages import HumanMessage
from pydantic import BaseModel, Field
from langchain_tavily import TavilySearch

# 加载环境变量
load_dotenv()

# 定义结构化输出实体
# AI引用信息实体
class Reference(BaseModel):
    title: str = Field(description="The title of the search result")
    url: str = Field(description="The URL of the search result")

# 查询结果实体
class WebSearchResponse(BaseModel):
    answer: str = Field(description="The answer to the question")
    references: list[Reference] = Field(description="The search results referenced in the answer")


# 定义工具
search_tool = TavilySearch(max_results=1)
# 封装工具，减少Token消耗
@tool
def web_search(query: str) -> str:
    """Search the web for information. Call at most once per question."""
    result = search_tool.invoke({"query": query})
    return str(result)


# 初始化模型
model = init_chat_model(model="deepseek-chat")

# 创建 AGENT
# 同时使用 tools 和 response_format 时，模型可能反复调用搜索而不返回结构化结果。
# 用 system_prompt 约束：最多搜索一次，然后输出 WebSearchResponse。
agent = create_agent(
    model=model,
    tools=[web_search],
    response_format=WebSearchResponse,
    system_prompt=(
        "You are a web research assistant. "
        "Call web_search at most once to gather information. "
        "After you receive search results, immediately return the final structured response. "
        "Do not call web_search again."
    ),
)

if __name__ == "__main__":
    # 调用AGENT
    result = agent.invoke(
        {
            "messages": [
                HumanMessage(content="Who is Messi?"),
            ]
        },
        config={"recursion_limit": 10},
    )

    print("=== structured_response ===")
    print(result["structured_response"])

    # print("\n=== messages ===")
    # for message in result["messages"]:
    #     message.pretty_print()