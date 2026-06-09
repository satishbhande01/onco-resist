"""
app/agent/tools.py

Tool functions for the OncoDB AI agent.
Each function queries SQLite and returns structured data.
These are called by the agent when the LLM decides to use a tool.

No LLM code here — pure data retrieval.
"""

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "portal.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


# ─────────────────────────────────────────────────────────────
# Basic drug tools
# ─────────────────────────────────────────────────────────────

def get_drug_info(drug_name: str) -> dict:
    """
    Get full profile for a drug by name.
    Searches by exact name first, then partial match.
    """
    conn = get_conn()

    row = conn.execute("""
        SELECT
            drugbank_id, name, drug_class, indication,
            mechanism_of_action, approval_date,
            molecular_weight, smiles, atc_codes,
            pubchem_cid, chembl_id
        FROM drugs
        WHERE LOWER(name) = LOWER(?)
        LIMIT 1
    """, (drug_name,)).fetchone()

    if not row:
        # Try partial match
        row = conn.execute("""
            SELECT
                drugbank_id, name, drug_class, indication,
                mechanism_of_action, approval_date,
                molecular_weight, smiles, atc_codes,
                pubchem_cid, chembl_id
            FROM drugs
            WHERE LOWER(name) LIKE LOWER(?)
            LIMIT 1
        """, (f"%{drug_name}%",)).fetchone()

    if not row:
        conn.close()
        return {"error": f"Drug '{drug_name}' not found in database."}

    drug = dict(row)

    # Parse JSON fields
    for field in ["atc_codes"]:
        if isinstance(drug.get(field), str):
            try:
                drug[field] = json.loads(drug[field])
            except Exception:
                drug[field] = []

    # Add portal link
    drug["portal_link"] = f"/drugs/{drug['drugbank_id']}"

    conn.close()
    return drug

def get_drugs_by_cancer_type(cancer_type: str) -> dict:
    """
    Find drugs indicated for a specific cancer type.
    Searches indication text for cancer type keywords.
    """
    conn = get_conn()

    # Map common cancer type names to search keywords
    keywords = {
    "colorectal":     ["colorectal", "colon cancer", "rectal cancer", "colon or rectum"],
    "lung":           ["lung cancer", "non-small cell", "nsclc", "sclc", "pulmonary"],
    "leukemia":       ["leukemia", "leukaemia", "cml", "all", "aml", "myeloid"],
    "melanoma":       ["melanoma"],
    "breast":         ["breast cancer", "breast carcinoma"],
    "prostate":       ["prostate cancer", "prostate carcinoma"],
    "lymphoma":       ["lymphoma"],
    "myeloma":        ["myeloma", "multiple myeloma"],
    "liver":          ["hepatocellular", "liver cancer", "hepatic", "hcc"],
    "kidney":         ["renal", "kidney cancer", "renal cell carcinoma", "rcc"],
    "thyroid":        ["thyroid cancer", "thyroid carcinoma"],
    "gastric":        ["gastric", "stomach cancer", "gastric carcinoma"],
    "pancreatic":     ["pancreatic", "pancreas cancer"],
    "bladder":        ["bladder cancer", "urothelial"],
    "ovarian":        ["ovarian", "ovary cancer"],
    "brain":          ["glioma", "glioblastoma", "brain cancer", "brain tumor"],
    "sarcoma":        ["sarcoma", "gist", "gastrointestinal stromal"],
    "head and neck":  ["head and neck", "squamous cell carcinoma of the head"],
    "skin":           ["skin cancer", "basal cell", "squamous cell carcinoma"],
    "endometrial":    ["endometrial", "uterine cancer"],
    }

    # Find matching keywords
    cancer_lower = cancer_type.lower()
    search_terms = []
    for key, terms in keywords.items():
        if key in cancer_lower or any(t in cancer_lower for t in terms):
            search_terms = terms
            break

    if not search_terms:
        search_terms = [cancer_lower]

    conditions = " OR ".join(["LOWER(indication) LIKE ?" for _ in search_terms])
    params     = [f"%{t}%" for t in search_terms]

    rows = conn.execute(f"""
        SELECT drugbank_id, name, drug_class, indication
        FROM drugs
        WHERE {conditions}
        ORDER BY name
    """, params).fetchall()

    conn.close()

    return {
        "cancer_type": cancer_type,
        "drugs": [
            {
                "name":        r["name"],
                "drug_class":  r["drug_class"],
                "indication":  (r["indication"] or "")[:200],
                "portal_link": f"/drugs/{r['drugbank_id']}",
            }
            for r in rows
        ],
        "total": len(rows),
    }

def get_drug_targets(drug_name: str) -> dict:
    """
    Get all protein targets for a drug.
    """
    conn = get_conn()

    drug_row = conn.execute("""
        SELECT drugbank_id, name FROM drugs
        WHERE LOWER(name) = LOWER(?) OR LOWER(name) LIKE LOWER(?)
        LIMIT 1
    """, (drug_name, f"%{drug_name}%")).fetchone()

    if not drug_row:
        conn.close()
        return {"error": f"Drug '{drug_name}' not found."}

    targets = conn.execute("""
        SELECT
            t.uniprot_accession,
            t.gene_name,
            t.protein_name,
            t.cellular_location,
            t.general_function,
            dtl.known_action,
            dtl.actions,
            dtl.pdb_ids
        FROM drug_target_links dtl
        JOIN targets t ON t.uniprot_accession = dtl.uniprot_accession
        WHERE dtl.drugbank_id = ?
        ORDER BY dtl.known_action DESC, t.gene_name
    """, (drug_row["drugbank_id"],)).fetchall()

    result = []
    for t in targets:
        entry = dict(t)
        for field in ["actions", "pdb_ids"]:
            if isinstance(entry.get(field), str):
                try:
                    entry[field] = json.loads(entry[field])
                except Exception:
                    entry[field] = []
        entry["portal_link"] = f"/targets/{entry['uniprot_accession']}"
        result.append(entry)

    conn.close()
    return {
        "drug_name":   drug_row["name"],
        "drugbank_id": drug_row["drugbank_id"],
        "targets":     result,
        "total":       len(result),
    }


def get_resistance_mutations(drug_name: str) -> dict:
    """
    Get all resistance mutations for a drug,
    grouped by gene with on-target/off-target classification.
    """
    conn = get_conn()

    drug_row = conn.execute("""
        SELECT drugbank_id, name FROM drugs
        WHERE LOWER(name) = LOWER(?) OR LOWER(name) LIKE LOWER(?)
        LIMIT 1
    """, (drug_name, f"%{drug_name}%")).fetchone()

    if not drug_row:
        conn.close()
        return {"error": f"Drug '{drug_name}' not found."}

    mutations = conn.execute("""
        SELECT
            gene_symbol,
            mutation_aa,
            resistance_type,
            total_samples,
            source
        FROM resistance_mutations
        WHERE drugbank_id = ?
        AND mutation_aa != 'p.?'
        ORDER BY gene_symbol, total_samples DESC
    """, (drug_row["drugbank_id"],)).fetchall()

    # Group by gene
    grouped = {}
    for mut in mutations:
        gene = mut["gene_symbol"]
        if gene not in grouped:
            grouped[gene] = {
                "gene":         gene,
                "on_target":    [],
                "off_target":   [],
                "total_samples": mut["total_samples"],
            }
        entry = {
            "mutation":         mut["mutation_aa"],
            "resistance_type":  mut["resistance_type"],
        }
        if mut["resistance_type"] == "on-target":
            grouped[gene]["on_target"].append(entry)
        else:
            grouped[gene]["off_target"].append(entry)

    conn.close()
    return {
        "drug_name":       drug_row["name"],
        "drugbank_id":     drug_row["drugbank_id"],
        "portal_link":     f"/drugs/{drug_row['drugbank_id']}",
        "mutation_groups": list(grouped.values()),
        "total_mutations": len(mutations),
    }


# ─────────────────────────────────────────────────────────────
# Basic target tools
# ─────────────────────────────────────────────────────────────

def get_target_info(gene_name: str) -> dict:
    """
    Get full profile for a protein target by gene name.
    """
    conn = get_conn()

    row = conn.execute("""
        SELECT
            uniprot_accession, gene_name, protein_name,
            cellular_location, general_function
        FROM targets
        WHERE LOWER(gene_name) = LOWER(?)
        LIMIT 1
    """, (gene_name,)).fetchone()

    if not row:
        conn.close()
        return {"error": f"Target '{gene_name}' not found."}

    target = dict(row)

    # Get drugs targeting this protein
    drugs = conn.execute("""
        SELECT
            d.drugbank_id, d.name, d.drug_class,
            dtl.known_action
        FROM drug_target_links dtl
        JOIN drugs d ON d.drugbank_id = dtl.drugbank_id
        WHERE dtl.uniprot_accession = ?
        ORDER BY dtl.known_action DESC, d.name
    """, (target["uniprot_accession"],)).fetchall()

    target["drugs"] = [
        {
            "name":         d["name"],
            "drug_class":   d["drug_class"],
            "known_action": d["known_action"],
            "portal_link":  f"/drugs/{d['drugbank_id']}",
        }
        for d in drugs
    ]

    target["portal_link"] = f"/targets/{target['uniprot_accession']}"

    conn.close()
    return target


def search_mutations(mutation_code: str) -> dict:
    """
    Find all drugs affected by a specific mutation code.
    e.g. 'T315I' or 'p.T315I'
    """
    conn = get_conn()

    # Normalize — add p. prefix if missing
    if not mutation_code.startswith("p."):
        mutation_code = f"p.{mutation_code}"

    rows = conn.execute("""
        SELECT
            rm.mutation_aa,
            rm.gene_symbol,
            rm.resistance_type,
            rm.total_samples,
            d.drugbank_id,
            d.name AS drug_name,
            d.drug_class
        FROM resistance_mutations rm
        JOIN drugs d ON d.drugbank_id = rm.drugbank_id
        WHERE LOWER(rm.mutation_aa) = LOWER(?)
        ORDER BY rm.total_samples DESC
    """, (mutation_code,)).fetchall()

    if not rows:
        # Try partial match
        rows = conn.execute("""
            SELECT
                rm.mutation_aa,
                rm.gene_symbol,
                rm.resistance_type,
                rm.total_samples,
                d.drugbank_id,
                d.name AS drug_name,
                d.drug_class
            FROM resistance_mutations rm
            JOIN drugs d ON d.drugbank_id = rm.drugbank_id
            WHERE LOWER(rm.mutation_aa) LIKE LOWER(?)
            ORDER BY rm.total_samples DESC
        """, (f"%{mutation_code}%",)).fetchall()

    conn.close()

    if not rows:
        return {"error": f"Mutation '{mutation_code}' not found."}

    return {
        "mutation":      mutation_code,
        "gene_symbol":   rows[0]["gene_symbol"],
        "affected_drugs": [
            {
                "drug_name":       r["drug_name"],
                "drug_class":      r["drug_class"],
                "resistance_type": r["resistance_type"],
                "total_samples":   r["total_samples"],
                "portal_link":     f"/drugs/{r['drugbank_id']}",
            }
            for r in rows
        ],
        "total_drugs": len(rows),
    }


# ─────────────────────────────────────────────────────────────
# Relationship tools
# ─────────────────────────────────────────────────────────────

def find_related_drugs(drug_name: str) -> dict:
    """
    Find drugs that share at least one confirmed target
    with the given drug.
    """
    conn = get_conn()

    drug_row = conn.execute("""
        SELECT drugbank_id, name FROM drugs
        WHERE LOWER(name) = LOWER(?) OR LOWER(name) LIKE LOWER(?)
        LIMIT 1
    """, (drug_name, f"%{drug_name}%")).fetchone()

    if not drug_row:
        conn.close()
        return {"error": f"Drug '{drug_name}' not found."}

    # Get this drug's targets
    my_targets = conn.execute("""
        SELECT uniprot_accession FROM drug_target_links
        WHERE drugbank_id = ?
    """, (drug_row["drugbank_id"],)).fetchall()

    target_ids = [t["uniprot_accession"] for t in my_targets]

    if not target_ids:
        conn.close()
        return {"drug_name": drug_row["name"], "related_drugs": []}

    placeholders = ",".join(["?" for _ in target_ids])

    # Find other drugs sharing these targets
    related = conn.execute(f"""
        SELECT
            d.drugbank_id,
            d.name,
            d.drug_class,
            COUNT(DISTINCT dtl.uniprot_accession) AS shared_targets,
            GROUP_CONCAT(DISTINCT t.gene_name) AS shared_genes
        FROM drug_target_links dtl
        JOIN drugs d ON d.drugbank_id = dtl.drugbank_id
        JOIN targets t ON t.uniprot_accession = dtl.uniprot_accession
        WHERE dtl.uniprot_accession IN ({placeholders})
        AND dtl.drugbank_id != ?
        GROUP BY d.drugbank_id
        ORDER BY shared_targets DESC, d.name
    """, (*target_ids, drug_row["drugbank_id"])).fetchall()

    conn.close()
    return {
        "drug_name":     drug_row["name"],
        "portal_link":   f"/drugs/{drug_row['drugbank_id']}",
        "related_drugs": [
            {
                "name":           r["name"],
                "drug_class":     r["drug_class"],
                "shared_targets": r["shared_targets"],
                "shared_genes":   r["shared_genes"].split(",") if r["shared_genes"] else [],
                "portal_link":    f"/drugs/{r['drugbank_id']}",
            }
            for r in related
        ],
        "total": len(related),
    }


def find_shared_mutations(drug1_name: str, drug2_name: str) -> dict:
    """
    Find resistance mutations shared between two drugs.
    """
    conn = get_conn()

    def get_drug(name):
        return conn.execute("""
            SELECT drugbank_id, name FROM drugs
            WHERE LOWER(name) = LOWER(?) OR LOWER(name) LIKE LOWER(?)
            LIMIT 1
        """, (name, f"%{name}%")).fetchone()

    drug1 = get_drug(drug1_name)
    drug2 = get_drug(drug2_name)

    if not drug1:
        conn.close()
        return {"error": f"Drug '{drug1_name}' not found."}
    if not drug2:
        conn.close()
        return {"error": f"Drug '{drug2_name}' not found."}

    shared = conn.execute("""
        SELECT
            rm1.gene_symbol,
            rm1.mutation_aa,
            rm1.resistance_type AS type_in_drug1,
            rm2.resistance_type AS type_in_drug2,
            rm1.total_samples
        FROM resistance_mutations rm1
        JOIN resistance_mutations rm2
            ON rm1.mutation_aa = rm2.mutation_aa
            AND rm1.gene_symbol = rm2.gene_symbol
        WHERE rm1.drugbank_id = ?
        AND   rm2.drugbank_id = ?
        AND   rm1.mutation_aa != 'p.?'
        ORDER BY rm1.gene_symbol, rm1.total_samples DESC
    """, (drug1["drugbank_id"], drug2["drugbank_id"])).fetchall()

    conn.close()
    return {
        "drug1":            drug1["name"],
        "drug2":            drug2["name"],
        "drug1_link":       f"/drugs/{drug1['drugbank_id']}",
        "drug2_link":       f"/drugs/{drug2['drugbank_id']}",
        "shared_mutations": [dict(r) for r in shared],
        "total_shared":     len(shared),
    }


def get_resistance_landscape(gene_name: str) -> dict:
    """
    Get all drugs targeting a gene and their resistance mutations.
    Shows the full resistance landscape for a target protein.
    """
    conn = get_conn()

    target = conn.execute("""
        SELECT uniprot_accession, gene_name, protein_name
        FROM targets
        WHERE LOWER(gene_name) = LOWER(?)
        LIMIT 1
    """, (gene_name,)).fetchone()

    if not target:
        conn.close()
        return {"error": f"Target '{gene_name}' not found."}

    # Get all drugs targeting this gene
    drugs = conn.execute("""
        SELECT
            d.drugbank_id, d.name, d.drug_class,
            d.approval_date, dtl.known_action
        FROM drug_target_links dtl
        JOIN drugs d ON d.drugbank_id = dtl.drugbank_id
        WHERE dtl.uniprot_accession = ?
        ORDER BY d.approval_date ASC NULLS LAST
    """, (target["uniprot_accession"],)).fetchall()

    landscape = []
    for drug in drugs:
        # Get mutations specific to this drug + gene combination
        mutations = conn.execute("""
            SELECT mutation_aa, resistance_type, total_samples
            FROM resistance_mutations
            WHERE drugbank_id = ?
            AND gene_symbol = ?
            AND mutation_aa != 'p.?'
            ORDER BY total_samples DESC
        """, (drug["drugbank_id"], gene_name)).fetchall()

        landscape.append({
            "drug_name":     drug["name"],
            "drug_class":    drug["drug_class"],
            "approval_date": drug["approval_date"],
            "known_action":  drug["known_action"],
            "portal_link":   f"/drugs/{drug['drugbank_id']}",
            "mutations": [dict(m) for m in mutations],
            "mutation_count": len(mutations),
        })

    conn.close()
    return {
        "gene_name":    target["gene_name"],
        "protein_name": target["protein_name"],
        "portal_link":  f"/targets/{target['uniprot_accession']}",
        "landscape":    landscape,
        "total_drugs":  len(landscape),
    }


def find_pan_resistant_mutations() -> dict:
    """
    Find mutations that confer resistance across multiple drugs.
    Clinically the most important — these are hard to treat.
    """
    conn = get_conn()

    rows = conn.execute("""
        SELECT
            rm.gene_symbol,
            rm.mutation_aa,
            COUNT(DISTINCT rm.drugbank_id) AS drug_count,
            GROUP_CONCAT(DISTINCT d.name) AS affected_drugs,
            MAX(rm.total_samples) AS max_samples
        FROM resistance_mutations rm
        JOIN drugs d ON d.drugbank_id = rm.drugbank_id
        WHERE rm.mutation_aa != 'p.?'
        GROUP BY rm.gene_symbol, rm.mutation_aa
        HAVING drug_count > 1
        ORDER BY drug_count DESC, max_samples DESC
        LIMIT 20
    """).fetchall()

    conn.close()
    return {
        "pan_resistant_mutations": [
            {
                "gene":           r["gene_symbol"],
                "mutation":       r["mutation_aa"],
                "drug_count":     r["drug_count"],
                "affected_drugs": r["affected_drugs"].split(","),
                "max_samples":    r["max_samples"],
            }
            for r in rows
        ],
        "total": len(rows),
    }


# ─────────────────────────────────────────────────────────────
# ADMET tools
# ─────────────────────────────────────────────────────────────

def compute_admet(drug_name: str) -> dict:
    """
    Compute physicochemical / ADMET properties from SMILES
    using RDKit. Returns Lipinski and Veber rule compliance.
    """
    try:
        from rdkit import Chem
        from rdkit.Chem import Descriptors, rdMolDescriptors
    except ImportError:
        return {"error": "RDKit not available."}

    conn = get_conn()
    row  = conn.execute("""
        SELECT drugbank_id, name, smiles, molecular_weight
        FROM drugs
        WHERE LOWER(name) = LOWER(?) OR LOWER(name) LIKE LOWER(?)
        LIMIT 1
    """, (drug_name, f"%{drug_name}%")).fetchone()
    conn.close()

    if not row:
        return {"error": f"Drug '{drug_name}' not found."}
    if not row["smiles"]:
        return {"error": f"No SMILES available for {row['name']}."}

    mol = Chem.MolFromSmiles(row["smiles"])
    if not mol:
        return {"error": f"Could not parse SMILES for {row['name']}."}

    mw    = round(Descriptors.MolWt(mol), 2)
    logp  = round(Descriptors.MolLogP(mol), 2)
    tpsa  = round(rdMolDescriptors.CalcTPSA(mol), 2)
    hbd   = rdMolDescriptors.CalcNumHBD(mol)
    hba   = rdMolDescriptors.CalcNumHBA(mol)
    nrot  = rdMolDescriptors.CalcNumRotatableBonds(mol)
    rings = rdMolDescriptors.CalcNumRings(mol)

    # Lipinski Rule of Five
    lipinski_violations = sum([
        mw   > 500,
        logp > 5,
        hbd  > 5,
        hba  > 10,
    ])

    # Veber rules (oral bioavailability)
    veber_pass = (nrot <= 10 and tpsa <= 140)

    return {
        "drug_name":   row["name"],
        "portal_link": f"/drugs/{row['drugbank_id']}",
        "properties": {
            "molecular_weight": mw,
            "logP":             logp,
            "TPSA":             tpsa,
            "HBD":              hbd,
            "HBA":              hba,
            "rotatable_bonds":  nrot,
            "rings":            rings,
        },
        "drug_likeness": {
            "lipinski_violations": lipinski_violations,
            "lipinski_pass":       lipinski_violations <= 1,
            "veber_pass":          veber_pass,
        }
    }


def compare_admet(drug1_name: str, drug2_name: str) -> dict:
    result1 = compute_admet(drug1_name)
    result2 = compute_admet(drug2_name)

    if "error" in result1:
        return result1
    if "error" in result2:
        return result2

    return {
        "drug1":             result1,
        "drug2":             result2,
        "comparison_notes":  _admet_comparison_notes(result1, result2),
    }

def _admet_comparison_notes(r1: dict, r2: dict) -> list:
    """Generate plain-language notes about ADMET differences."""
    notes = []
    p1 = r1["properties"]
    p2 = r2["properties"]

    if abs(p1["molecular_weight"] - p2["molecular_weight"]) > 50:
        heavier = r1["drug_name"] if p1["molecular_weight"] > p2["molecular_weight"] else r2["drug_name"]
        notes.append(f"{heavier} is significantly heavier (MW difference > 50 Da)")

    if abs(p1["logP"] - p2["logP"]) > 1:
        more_lipophilic = r1["drug_name"] if p1["logP"] > p2["logP"] else r2["drug_name"]
        notes.append(f"{more_lipophilic} is more lipophilic (logP difference > 1)")

    if p1["TPSA"] > 140 and p2["TPSA"] <= 140:
        notes.append(f"{r1['drug_name']} may have poor oral absorption (TPSA > 140)")
    elif p2["TPSA"] > 140 and p1["TPSA"] <= 140:
        notes.append(f"{r2['drug_name']} may have poor oral absorption (TPSA > 140)")

    l1 = r1["drug_likeness"]
    l2 = r2["drug_likeness"]
    if l1["lipinski_pass"] and not l2["lipinski_pass"]:
        notes.append(f"{r2['drug_name']} violates Lipinski rules")
    elif l2["lipinski_pass"] and not l1["lipinski_pass"]:
        notes.append(f"{r1['drug_name']} violates Lipinski rules")

    return notes

def search_literature(query: str) -> dict:
    """
    Search PubMed literature in ChromaDB for relevant passages.
    """
    from app.agent.literature import search_literature as _search
    results = _search(query, n_results=5)

    if not results:
        return {"error": "No relevant literature found.", "results": []}

    return {
        "query":   query,
        "results": results,
        "total":   len(results),
    }

# Alias for the agent — Llama handles this name better
def find_literature(query: str) -> dict:
    return search_literature(query)