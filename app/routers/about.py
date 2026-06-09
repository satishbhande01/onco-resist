from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

router = APIRouter()

BASE_DIR   = Path(__file__).resolve().parent.parent
templates  = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.get("/about", response_class=HTMLResponse)
def about_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="about.html"
    )