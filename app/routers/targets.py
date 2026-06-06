from pathlib import Path
from fastapi import APIRouter, Request, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from app.database import get_all_targets, get_target_by_uniprot

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.get("/targets", response_class=HTMLResponse)
def target_archive(request: Request):
    targets = get_all_targets()
    return templates.TemplateResponse(
        request=request,
        name="targets/archive.html",
        context={
            "targets": targets,
            "total": len(targets),
        },
    )


@router.get("/targets/{uniprot_accession}", response_class=HTMLResponse)
def target_detail(request: Request, uniprot_accession: str):
    target = get_target_by_uniprot(uniprot_accession)
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")
    return templates.TemplateResponse(
        request=request, name="targets/detail.html", context={"target": target}
    )


@router.get("/api/targets/{uniprot_accession}", response_model=None)
def api_target_detail(uniprot_accession: str):
    target = get_target_by_uniprot(uniprot_accession)
    if not target:
        raise HTTPException(status_code=404, detail="Target not found")
    return target
