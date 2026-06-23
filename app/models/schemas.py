from pydantic import BaseModel
from typing import Optional

#---2. 数据模型 ---
class ChatRequest(BaseModel):
    message: str
    image_url: Optional[str] = None
    thread_id: str