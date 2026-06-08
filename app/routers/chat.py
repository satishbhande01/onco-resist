from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.agent.agent import run_agent

router = APIRouter()

BASE_DIR  = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[Message] = []
    context: str = ""


@router.get("/chat", response_class=HTMLResponse)
def chat_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="chat.html"
    )


@router.post("/api/chat")
def chat_endpoint(payload: ChatRequest):
    history = [
        {"role": m.role, "content": m.content}
        for m in payload.history
    ]

    result = run_agent(
        message=payload.message,
        history=history,
        page_context=payload.context,
    )

    return {
        "answer":     result["answer"],
        "history":    result["history"],
        "tools_used": result["tools_used"],
        "sources":    [],
    }