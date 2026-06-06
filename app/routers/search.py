from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from app.database import search_all

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.get("/search", response_class=HTMLResponse)
def search_page(request: Request, q: str = ""):
    results = (
        search_all(q)
        if q.strip()
        else {"query": q, "drugs": [], "targets": [], "mutations": []}
    )
    return templates.TemplateResponse(
        request=request, name="search.html", context={"results": results, "query": q}
    )


@router.get("/api/search", response_model=None)
def api_search(q: str = ""):
    if not q.strip():
        return {"query": q, "drugs": [], "targets": [], "mutations": []}
    return search_all(q)
