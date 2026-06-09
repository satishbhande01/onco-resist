from pathlib import Path
from fastapi import APIRouter, Request, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from app.database import get_all_drugs, get_drug_by_id, get_drug_classes, get_cancer_types, get_sifts_mapping
from fastapi.responses import JSONResponse
import molviewspec as mvs

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
    cancer_type: str = None,       # ← new
):
    drug_list    = get_all_drugs(drug_class=drug_class, search=search, cancer_type=cancer_type)
    drug_classes = get_drug_classes()
    cancer_types = get_cancer_types()          # ← new

    return templates.TemplateResponse(
        request=request,
        name="drugs/archive.html",
        context={
            "drugs":           drug_list,
            "drug_classes":    drug_classes,
            "cancer_types":    cancer_types,   # ← new
            "selected_class":  drug_class,
            "selected_cancer": cancer_type,    # ← new
            "search_query":    search or "",
            "total":           len(drug_list),
        }
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

@router.post("/api/molview")
def build_molview(payload: dict):
    pdb_id    = payload.get("pdb_id", "").upper()
    mutations = payload.get("mutations", [])
    uniprot   = payload.get("uniprot", "")

    if not pdb_id:
        return JSONResponse({"error": "pdb_id required"}, status_code=400)

    sifts = {}
    if uniprot:
        sifts = get_sifts_mapping(pdb_id, uniprot)

    found     = []
    not_found = []

    for uniprot_pos in mutations:
        if sifts:
            pdb_pos = sifts.get(uniprot_pos)
            if pdb_pos:
                found.append(pdb_pos)
            else:
                not_found.append(uniprot_pos)
        else:
            found.append(uniprot_pos)

    builder   = mvs.create_builder()
    structure = (
        builder
        .download(url=f"https://files.rcsb.org/download/{pdb_id}.cif")
        .parse(format="mmcif")
        .model_structure()
    )

    # Protein — cartoon, dark blue, no solvent
    (
        structure
        .component(selector="polymer")
        .representation(type="cartoon")
        .color(color="#1a3a6b")
    )

    # Ligand — ball and stick, coral orange (complementary to dark blue)
    (
        structure
        .component(selector="ligand")
        .representation(type="ball_and_stick")
        .color(color="#ff6b35")
    )

    # Highlighted mutation residues — red ball and stick
    for pdb_pos in found:
        (
            structure
            .component(
                selector=mvs.ComponentExpression(label_seq_id=pdb_pos)
            )
            .representation(type="ball_and_stick")
            .color(color="#ff4d6a")
        )

    return {
        "mvs":       builder.get_state().to_dict(),
        "not_found": not_found,
        "found":     found,
    }

@router.post("/api/molview/target")
def build_molview_target(payload: dict):
    """
    MolViewSpec scene for target detail page.
    No mutations — just clean protein + ligand.
    """
    pdb_id = payload.get("pdb_id", "").upper()

    if not pdb_id:
        return JSONResponse({"error": "pdb_id required"}, status_code=400)

    builder   = mvs.create_builder()
    structure = (
        builder
        .download(url=f"https://files.rcsb.org/download/{pdb_id}.cif")
        .parse(format="mmcif")
        .model_structure()
    )

    # Protein — cartoon, dark blue, no solvent
    (
        structure
        .component(selector="polymer")
        .representation(type="cartoon")
        .color(color="#1a3a6b")
    )

    # Ligand — ball and stick, coral orange
    (
        structure
        .component(selector="ligand")
        .representation(type="ball_and_stick")
        .color(color="#ff6b35")
    )

    return builder.get_state().to_dict()

def get_pdb_residues(pdb_id: str) -> set:
    """
    Query RCSB GraphQL for residue sequence IDs in a PDB structure.
    Returns a set of integer residue numbers or empty set on failure.
    """
    query = """
    query($id: String!) {
        entry(entry_id: $id) {
            polymer_entities {
                entity_poly {
                    pdbx_seq_one_letter_code_can
                }
                polymer_entity_instances {
                    rcsb_polymer_entity_instance_container_identifiers {
                        auth_seq_id_1
                        auth_seq_id_2
                    }
                }
            }
        }
    }
    """
    try:
        import requests
        resp = requests.post(
            "https://data.rcsb.org/graphql",
            json={"query": query, "variables": {"id": pdb_id}},
            timeout=8
        )
        resp.raise_for_status()
        data = resp.json()

        residues = set()
        entry    = (data.get("data") or {}).get("entry", {})

        for entity in (entry.get("polymer_entities") or []):
            for instance in (entity.get("polymer_entity_instances") or []):
                ids = instance.get(
                    "rcsb_polymer_entity_instance_container_identifiers", {}
                )
                start = ids.get("auth_seq_id_1")
                end   = ids.get("auth_seq_id_2")
                if start and end:
                    residues.update(range(int(start), int(end) + 1))

        return residues

    except Exception as e:
        print(f"[RCSB] Residue fetch error: {e}")
        return set()