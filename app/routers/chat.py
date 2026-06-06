from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent.parent
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
    return templates.TemplateResponse(request=request, name="chat.html")


@router.post("/api/chat")
def chat_endpoint(payload: ChatRequest):
    # Placeholder — returns a stub response until the RAG agent is built
    # Replace the body of this function when the agent is ready
    return {
        "answer": "The AI assistant is not connected yet.",
        "reformulated_query": payload.message,
        "sources": [],
        "source_details": [],
        "history": [
            {"role": "user", "content": payload.message},
            {"role": "assistant", "content": "The AI assistant is not connected yet."},
        ],
    }
