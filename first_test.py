from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain.agents import create_agent
from langchain.tools import tool
from langchain.messages import HumanMessage
import os
from pydantic import BaseModel
load_dotenv()

# 定义结构化输出实体
class WeatherResponse(BaseModel):
    location: str
    weather: str


# 加载环境变量
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# 定义工具
@tool
def get_weather (location: str) -> str:
    """
    Get the weather for a given location.
    Args:
        location: The location to get the weather for.
    Returns:
        The weather for the given location.
    """
    return f"The weather in {location} is sunny."



# 初始化模型，根据模型名称指定即可
model = init_chat_model(model="deepseek-chat")

# 创建AGENT
agent = create_agent(
    model=model,
    tools=[get_weather],
)

# 创建AGENT，返回结构化输出
agent_with_structured_output = create_agent(
    model=model,
    tools=[get_weather],
    response_format=WeatherResponse,
)


# def main():
#     print("Hello from learn-langchain!")
#     print(DEEPSEEK_API_KEY)

if __name__ == "__main__":
    inputs = {
        "messages": [
            HumanMessage(content="北京天气怎么样?"),
        ]
    }

    # invoke 返回最终状态字典；stream 返回生成器，不能直接 response["messages"]
    # result = agent.invoke(inputs)
    # for message in result["messages"]:
    #     message.pretty_print()

    # 流式输出
    # stream = agent.stream(inputs, stream_mode="messages")

    # for token, metadata in stream:
    #     print(token.content, end="", flush=True)

    result = agent_with_structured_output.invoke(inputs)
    print(result['structured_response'])