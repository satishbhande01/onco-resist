from pathlib import Path
from fastapi import APIRouter, Request, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from app.database import get_all_drugs, get_drug_by_id, get_drug_classes

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parent.parent

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@router.get("/drugs", response_class=HTMLResponse)
def drug_archive(
    request: Request,
    drug_class: str = None,
    search: str = None,
):
    drug_list = get_all_drugs(drug_class=drug_class, search=search)
    drug_classes = get_drug_classes()
    return templates.TemplateResponse(
        request=request,
        name="drugs/archive.html",
        context={
            "drugs": drug_list,
            "drug_classes": drug_classes,
            "selected_class": drug_class,
            "search_query": search or "",
            "total": len(drug_list),
        },
    )


@router.get("/drugs/{drugbank_id}", response_class=HTMLResponse)
def drug_detail(request: Request, drugbank_id: str):
    drug = get_drug_by_id(drugbank_id)
    if not drug:
        raise HTTPException(status_code=404, detail="Drug not found")

    # Pick the best PDB ID for the viewer
    # Prefer confirmed targets (known_action == "yes") first
    viewer_pdb_id = None
    viewer_target = None
    for target in drug.get("targets", []):
        if target.get("pdb_ids"):
            viewer_pdb_id = target["pdb_ids"][0]
            viewer_target = target
            if target.get("known_action") == "yes":
                break

    return templates.TemplateResponse(
        request=request,
        name="drugs/detail.html",
        context={
            "drug": drug,
            "viewer_pdb_id": viewer_pdb_id,
            "viewer_target": viewer_target,
        },
    )


@router.get("/api/drugs", response_model=None)
def api_drugs(drug_class: str = None, search: str = None):
    return get_all_drugs(drug_class=drug_class, search=search)


@router.get("/api/drugs/{drugbank_id}", response_model=None)
def api_drug_detail(drugbank_id: str):
    drug = get_drug_by_id(drugbank_id)
    if not drug:
        raise HTTPException(status_code=404, detail="Drug not found")
    return drug
