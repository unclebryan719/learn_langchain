from fastapi import APIRouter
from app.models.schemas import ChatRequest
from app.agents.personal_recipe import get_messages,search_recipes,clear_messages
from fastapi.responses import StreamingResponse

router = APIRouter()

@router.post("/chat/stream")
async def chat_endpoint(request: ChatRequest):
    """流式对话"""
    return StreamingResponse(
        search_recipes(request.message, request.image_url, request.thread_id),
        media_type="text/plain; charset=utf-8",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

@router.get("/chat/messages")
async def get_chat_messages (thread_id: str):
    """获取历史消息"""
    messages = get_messages(thread_id)
    return {"messages": messages}

@router.delete("/chat/messages")
async def clear_chat_messages (thread_id: str):
    """清空历消息"""
    clear_messages(thread_id)
    return {"success": True} 
