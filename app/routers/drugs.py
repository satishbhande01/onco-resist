from pathlib import Path
from fastapi import APIRouter, Request, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from app.database import get_all_drugs, get_drug_by_id, get_drug_classes, get_cancer_types, get_sifts_mapping
from fastapi.responses import JSONResponse
import molviewspec as mvs
from fastapi.responses import StreamingResponse
import io
import tempfile
import os

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

@router.post("/api/mutated-structure")
def generate_mutated_structure(payload: dict):
    import traceback
    import tempfile
    import os
    import io

    try:
        from Bio.PDB import PDBParser, PDBIO
        print("[Mutant] BioPython imported OK")

        pdb_id    = payload.get("pdb_id", "").upper()
        mutations = payload.get("mutations", [])
        uniprot   = payload.get("uniprot", "")

        print(f"[Mutant] pdb_id={pdb_id}, mutations={mutations}, uniprot={uniprot}")

        if not pdb_id:
            return JSONResponse({"error": "pdb_id required"}, status_code=400)
        if not mutations:
            return JSONResponse({"error": "no mutations provided"}, status_code=400)

        # Download PDB file
        import requests as req
        pdb_url  = f"https://files.rcsb.org/download/{pdb_id}.pdb"
        pdb_resp = req.get(pdb_url, timeout=15)
        print(f"[Mutant] PDB fetch status: {pdb_resp.status_code}")

        if pdb_resp.status_code != 200:
            return JSONResponse(
                {"error": f"Could not fetch PDB file for {pdb_id}"},
                status_code=404
            )

        # Write to temp file for BioPython
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.pdb', delete=False
        ) as tmp:
            tmp.write(pdb_resp.text)
            tmp_path = tmp.name

        # Parse structure
        parser    = PDBParser(QUIET=True)
        structure = parser.get_structure(pdb_id, tmp_path)
        os.unlink(tmp_path)
        print(f"[Mutant] Structure parsed OK")

        # One letter to three letter code map
        ONE_TO_THREE = {
            'A': 'ALA', 'R': 'ARG', 'N': 'ASN', 'D': 'ASP',
            'C': 'CYS', 'E': 'GLU', 'Q': 'GLN', 'G': 'GLY',
            'H': 'HIS', 'I': 'ILE', 'L': 'LEU', 'K': 'LYS',
            'M': 'MET', 'F': 'PHE', 'P': 'PRO', 'S': 'SER',
            'T': 'THR', 'W': 'TRP', 'Y': 'TYR', 'V': 'VAL',
        }

        applied   = []
        not_found = []

        for mut in mutations:
            uniprot_pos = mut.get("uniprot_pos")
            new_aa_1    = mut.get("new_aa")
            mutation_aa = mut.get("mutation_aa")

            if not uniprot_pos or not new_aa_1:
                not_found.append(mutation_aa or str(uniprot_pos))
                continue

            # Use UniProt position directly — most PDB structures
            # use author numbering which matches UniProt positions
            pdb_pos = uniprot_pos
            print(f"[Mutant] Using position {pdb_pos} directly")

            new_resname = ONE_TO_THREE.get(new_aa_1.upper())
            if not new_resname:
                not_found.append(mutation_aa)
                continue

            # Find and mutate the residue
            mutated = False
            for model in structure:
                for chain in model:
                    for residue in chain:
                        res_id = residue.get_id()[1]
                        if res_id == pdb_pos:
                            old_resname = residue.resname
                            residue.resname = new_resname
                            backbone = {'N', 'CA', 'C', 'O', 'CB'}
                            atoms_to_remove = [
                                atom.get_id()
                                for atom in residue
                                if atom.get_id() not in backbone
                            ]
                            for atom_id in atoms_to_remove:
                                residue.detach_child(atom_id)
                            print(f"[Mutant] Mutated {res_id}: {old_resname} → {new_resname}")
                            mutated = True
                            applied.append(mutation_aa or f"pos{pdb_pos}{new_aa_1}")
                            break
                    if mutated:
                        break
                if mutated:
                    break

            if not mutated:
                print(f"[Mutant] Residue {pdb_pos} not found in structure")
                not_found.append(mutation_aa or str(uniprot_pos))

                print(f"[Mutant] Applied: {applied}, Not found: {not_found}")

                if not applied:
                    return JSONResponse(
                        {"error": "No mutations could be applied to this structure."},
                        status_code=400
                    )

        # Write mutated structure to bytes
        output = io.StringIO()
        io_obj = PDBIO()
        io_obj.set_structure(structure)
        io_obj.save(output)
        pdb_bytes = output.getvalue().encode('utf-8')

        # Build filename
        mut_str  = "_".join(
            m.replace("p.", "").replace("*", "X")
            for m in applied
        )
        filename = f"{pdb_id}_{mut_str}_mutated.pdb"
        print(f"[Mutant] Returning file: {filename}")

        return StreamingResponse(
            io.BytesIO(pdb_bytes),
            media_type="chemical/x-pdb",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "X-Applied-Mutations":  ",".join(applied),
                "X-Not-Found":          ",".join(not_found),
            }
        )

    except Exception as e:
        print(f"[Mutant] Error: {e}")
        traceback.print_exc()
        return JSONResponse(
            {"error": f"Failed to generate mutated structure: {str(e)}"},
            status_code=500
        )