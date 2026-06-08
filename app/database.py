import json
import sqlite3
from pathlib import Path
import requests

DB_path = Path(__file__).resolve().parent.parent / "data" / "portal.db"

# Connection helpers


def get_conn() -> sqlite3.Connection:
    """
    Open and return a SQLite connection.

    row_factory = sqlite3.Row lets us access columns by name:
        row["name"]  instead of  row[0]
    """
    conn = sqlite3.connect(DB_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    if not DB_path.exists():
        raise RuntimeError(f"\n[DB] Database not found at: {DB_PATH}\nRun populate_db")
    conn = get_conn()
    count = conn.execute("SELECT COUNT(*) FROM drugs").fetchone()[0]
    conn.close()
    print(f"[DB] Connected - {count} drugs in database")


def parse_json_fields(record: dict, fields: list) -> dict:
    """
    Several fields in the database are stored as JSON strings
    because SQLite has no native array type.

    For example, atc_codes is stored as:
        '["L01XE01", "L01XE05"]'   ← a string

    This function converts those strings back to Python lists:
        ["L01XE01", "L01XE05"]     ← a real list

    Call this after converting a sqlite3.Row to a dict.
    """
    for field in fields:
        val = record.get(field)
        if isinstance(val, str):
            try:
                record[field] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                record[field] = []
    return record

CANCER_TYPES = {
    "leukemia":       "Leukemia",
    "leukaemia":      "Leukemia",
    "lymphoma":       "Lymphoma",
    "melanoma":       "Melanoma",
    "lung cancer":    "Lung Cancer",
    "breast cancer":  "Breast Cancer",
    "prostate cancer":"Prostate Cancer",
    "colorectal":     "Colorectal Cancer",
    "ovarian":        "Ovarian Cancer",
    "renal":          "Renal Cancer",
    "hepatocellular": "Liver Cancer",
    "glioma":         "Brain Cancer",
    "glioblastoma":   "Brain Cancer",
    "myeloma":        "Multiple Myeloma",
    "sarcoma":        "Sarcoma",
    "thyroid":        "Thyroid Cancer",
    "gastric":        "Gastric Cancer",
    "pancreatic":     "Pancreatic Cancer",
    "bladder":        "Bladder Cancer",
    "carcinoma":      "Carcinoma",
    "myeloid":        "Myeloid Disorders",
    "kaposi":         "Kaposi's Sarcoma",
}

def fetch_rcsb_structures(uniprot_accession: str) -> list:
    """
    Query RCSB Search API for all PDB structures associated
    with a UniProt accession.
    """
    search_url = "https://search.rcsb.org/rcsbsearch/v2/query"

    query = {
        "query": {
            "type": "terminal",
            "service": "text",
            "parameters": {
                "attribute": "rcsb_polymer_entity_container_identifiers"
                             ".reference_sequence_identifiers"
                             ".database_accession",
                "operator": "exact_match",
                "value":    uniprot_accession
            }
        },
        "return_type": "entry",
        "request_options": {
            "paginate": {
                "start": 0,
                "rows":  50
            },
            "results_content_type": ["experimental"],
            "sort": [
                {
                    "sort_by":   "rcsb_entry_info.resolution_combined",
                    "direction": "asc"
                }
            ]
        }
    }

    try:
        resp = requests.post(
            search_url,
            json=query,
            timeout=10,
            headers={"Content-Type": "application/json"}
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[RCSB] Error fetching structures for {uniprot_accession}: {e}")
        return []

    results = data.get("result_set", [])
    pdb_ids = [r["identifier"] for r in results]

    if not pdb_ids:
        return []

    return fetch_rcsb_details(pdb_ids)


def fetch_rcsb_details(pdb_ids: list) -> list:
    """
    Fetch title, resolution, and experimental method
    for a list of PDB IDs using RCSB GraphQL.
    """
    if not pdb_ids:
        return []

    graphql_url = "https://data.rcsb.org/graphql"

    # Build entries query for multiple IDs at once
    entries_query = " ".join([
        f"""
        e{i}: entry(entry_id: "{pdb_id}") {{
            rcsb_id
            struct {{ title }}
            rcsb_entry_info {{
                resolution_combined
                experimental_method
                deposited_nonpolymer_entity_instance_count
            }}
        }}
        """
        for i, pdb_id in enumerate(pdb_ids[:30])  # cap at 30
    ])

    query = f"{{ {entries_query} }}"

    try:
        resp = requests.post(
            graphql_url,
            json={"query": query},
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
    except Exception as e:
        print(f"[RCSB] GraphQL error: {e}")
        # Fall back to returning just PDB IDs without details
        return [{"pdb_id": pid, "title": None,
                 "resolution": None, "method": None,
                 "has_ligand": False}
                for pid in pdb_ids]

    structures = []
    for i, pdb_id in enumerate(pdb_ids[:30]):
        entry = data.get(f"e{i}", {})
        if not entry:
            continue

        info       = entry.get("rcsb_entry_info", {})
        
        # resolution_combined returns a list
        resolution_raw = info.get("resolution_combined")
        if isinstance(resolution_raw, list):
            resolution = resolution_raw[0] if resolution_raw else None
        else:
            resolution = resolution_raw

        method     = info.get("experimental_method", "")
        has_ligand = (info.get(
            "deposited_nonpolymer_entity_instance_count", 0) or 0) > 0
        title      = (entry.get("struct") or {}).get("title", "")

        structures.append({
            "pdb_id":     pdb_id.lower(),
            "title":      title,
            "resolution": round(resolution, 2) if resolution else None,
            "method":     method,
            "has_ligand": has_ligand,
        })

    return structures

def extract_cancer_types(indication: str) -> list:
    """Extract cancer type labels from indication text."""
    if not indication:
        return []
    indication_lower = indication.lower()
    found = []
    seen  = set()
    for keyword, label in CANCER_TYPES.items():
        if keyword in indication_lower and label not in seen:
            found.append(label)
            seen.add(label)
    return found

def get_cancer_types() -> list:
    """Return all distinct cancer types across all drugs."""
    conn = get_conn()
    rows = conn.execute("SELECT indication FROM drugs WHERE indication IS NOT NULL").fetchall()
    conn.close()
    all_types = set()
    for row in rows:
        for ct in extract_cancer_types(row["indication"]):
            all_types.add(ct)
    return sorted(all_types)

def get_all_drugs(drug_class: str = None, search: str = None,cancer_type: str = None) -> list:
    conn = get_conn()
    params = []
    conditions = []

    if drug_class:
        conditions.append("d.drug_class = ?")
        params.append(drug_class)
    if cancer_type:
        # Find the keyword that maps to this cancer type label
        keywords = [k for k, v in CANCER_TYPES.items() if v == cancer_type]
        if keywords:
            keyword_conditions = " OR ".join(["d.indication LIKE ?" for _ in keywords])
            conditions.append(f"({keyword_conditions})")
            params.extend([f"%{k}%" for k in keywords])

    if search:
        conditions.append("(d.name LIKE ? OR d.synonyms LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    rows = conn.execute(
        f"""
    SELECT
        d.drugbank_id,
        d.name,
        d.drug_class,
        d.indication,
        d.atc_codes,
        d.synonyms,
        COUNT(DISTINCT dtl.uniprot_accession) AS target_count,
        COUNT(DISTINCT rm.id) AS mutation_count
        FROM drugs d 
        LEFT JOIN drug_target_links dtl
            ON dtl.drugbank_id = d.drugbank_id
        LEFT JOIN resistance_mutations rm 
            ON rm.drugbank_id = d.drugbank_id
        {where}
        GROUP BY d.drugbank_id
        ORDER BY d.name
            
    """,
        params,
    ).fetchall()

    conn.close()

    result = [dict(r) for r in rows]
    for r in result:
        parse_json_fields(r, ["atc_codes", "synonyms"])
    print(type(result[0]["synonyms"]), result[0]["synonyms"])
    return result


def get_drug_by_id(drugbank_id: str) -> dict:
    conn = get_conn()

    row = conn.execute(
        "SELECT * FROM drugs WHERE drugbank_id = ?",
        (drugbank_id,)    # ← trailing comma
    ).fetchone()

    if not row:
        conn.close()
        return None

    drug = dict(row)
    parse_json_fields(drug, ["atc_codes", "synonyms", "unmatched_pdb_ids"])

    target_rows = conn.execute("""
        SELECT
            t.uniprot_accession,
            t.gene_name,
            t.protein_name,
            t.general_function,
            t.cellular_location,
            dtl.actions,
            dtl.known_action,
            dtl.pdb_ids
        FROM drug_target_links dtl
        JOIN targets t ON t.uniprot_accession = dtl.uniprot_accession
        WHERE dtl.drugbank_id = ?
        ORDER BY dtl.known_action DESC, t.gene_name
    """, (drugbank_id,)).fetchall()

    drug["targets"] = []
    for t in [dict(r) for r in target_rows]:
        parse_json_fields(t, ["actions", "pdb_ids"])
        drug["targets"].append(t)

    mut_rows = conn.execute("""
        SELECT
            id,
            gene_symbol,
            mutation_aa,
            mutation_type,
            resistance_type,
            source,
            total_samples,
            uniprot_accession
        FROM resistance_mutations
        WHERE drugbank_id = ?
        ORDER BY gene_symbol, total_samples DESC
    """, (drugbank_id,)).fetchall()

    drug["resistance_mutations"] = [
    dict(r) for r in mut_rows
    if (r["mutation_aa"] or "") != "p.?"
]
    # Fetch pubmed refs for each mutation
    for mut in drug["resistance_mutations"]:
        ref_rows = conn.execute("""
            SELECT pmid FROM mutation_pubmed_refs
            WHERE mutation_id = ?
            ORDER BY pmid
        """, (mut["id"],)).fetchall()
        mut["pubmed_refs"] = [r["pmid"] for r in ref_rows]

    ref_rows = conn.execute("""
        SELECT pmid FROM drug_pubmed_refs
        WHERE drugbank_id = ?
        ORDER BY pmid
    """, (drugbank_id,)).fetchall()

    drug["pubmed_ids"] = [r["pmid"] for r in ref_rows]

    conn.close()
    return drug

def get_drug_classes() -> list:
    """
    Return all distinct drug class names.
    Used to populate the filter dropdown on the archive page.
    """
    conn = get_conn()
    rows = conn.execute("""
        SELECT DISTINCT drug_class
        FROM drugs
        WHERE drug_class IS NOT NULL
        ORDER BY drug_class
    """).fetchall()
    conn.close()
    return [r["drug_class"] for r in rows]


# Target Queries


def get_all_targets() -> list:
    """
    Return all targets with drug count and mutation count.
    Used by: Target Archive page (/targets)
    """
    conn = get_conn()
    rows = conn.execute("""
        SELECT
            t.uniprot_accession,
            t.gene_name,
            t.protein_name,
            t.cellular_location,
            COUNT(DISTINCT dtl.drugbank_id) AS drug_count,
            COUNT(DISTINCT rm.id)           AS mutation_count
        FROM targets t
        LEFT JOIN drug_target_links dtl
            ON dtl.uniprot_accession = t.uniprot_accession
        LEFT JOIN resistance_mutations rm
            ON rm.uniprot_accession = t.uniprot_accession
        GROUP BY t.uniprot_accession
        ORDER BY drug_count DESC, t.gene_name
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_target_by_uniprot(uniprot_accession: str) -> dict:
    """
    Return full detail for one target including all drugs
    that target it and all resistance mutations for it.

    Returns None if not found.

    Used by: Target Detail page (/targets/{uniprot_accession})
    """
    conn = get_conn()

    row = conn.execute(
        "SELECT * FROM targets WHERE uniprot_accession = ?", (uniprot_accession,)
    ).fetchone()

    if not row:
        conn.close()
        return None

    target = dict(row)

    # All drugs targeting this protein
    drug_rows = conn.execute(
        """
        SELECT
            d.drugbank_id,
            d.name,
            d.drug_class,
            dtl.actions,
            dtl.known_action,
            dtl.pdb_ids
        FROM drug_target_links dtl
        JOIN drugs d ON d.drugbank_id = dtl.drugbank_id
        WHERE dtl.uniprot_accession = ?
        ORDER BY dtl.known_action DESC, d.name
    """,
        (uniprot_accession,),
    ).fetchall()

    target["drugs"] = []
    for d in [dict(r) for r in drug_rows]:
        parse_json_fields(d, ["actions", "pdb_ids"])
        target["drugs"].append(d)

    # Resistance mutations for this target across all drugs
    mut_rows = conn.execute(
        """
        SELECT
            rm.gene_symbol,
            rm.mutation_aa,
            rm.source,
            rm.total_samples,
            d.name        AS drug_name,
            d.drugbank_id
        FROM resistance_mutations rm
        JOIN drugs d ON d.drugbank_id = rm.drugbank_id
        WHERE rm.uniprot_accession = ?
        ORDER BY rm.total_samples DESC
    """,
        (uniprot_accession,),
    ).fetchall()

    target["resistance_mutations"] = [dict(r) for r in mut_rows]

    conn.close()
    target["rcsb_structures"] = fetch_rcsb_structures(uniprot_accession)
    # Pick viewer PDB from RCSB results — first structure with a ligand
    # preferring ligand-bound structures for biological relevance
    viewer_pdb = None
    for s in target["rcsb_structures"]:
        if s["has_ligand"]:
            viewer_pdb = s["pdb_id"]
            break

    # Fall back to first structure if none has a ligand
    if not viewer_pdb and target["rcsb_structures"]:
        viewer_pdb = target["rcsb_structures"][0]["pdb_id"]

    target["viewer_pdb_id"] = viewer_pdb
    return target


# search


def search_all(query: str) -> dict:
    """
    Search across drugs, targets, and mutations simultaneously.
    Returns a dict with three lists: drugs, targets, mutations.

    Used by: Search page (/search)
    """
    conn = get_conn()
    q = f"%{query}%"

    drugs = conn.execute(
        """
        SELECT drugbank_id, name, drug_class, indication
        FROM drugs
        WHERE name LIKE ? OR synonyms LIKE ? OR indication LIKE ?
        LIMIT 10
    """,
        (q, q, q),
    ).fetchall()

    targets = conn.execute(
        """
        SELECT uniprot_accession, gene_name, protein_name
        FROM targets
        WHERE gene_name LIKE ? OR protein_name LIKE ?
        LIMIT 10
    """,
        (q, q),
    ).fetchall()

    mutations = conn.execute(
        """
        SELECT DISTINCT
            rm.gene_symbol,
            rm.mutation_aa,
            d.name        AS drug_name,
            d.drugbank_id
        FROM resistance_mutations rm
        JOIN drugs d ON d.drugbank_id = rm.drugbank_id
        WHERE rm.gene_symbol LIKE ? OR rm.mutation_aa LIKE ?
        LIMIT 10
    """,
        (q, q),
    ).fetchall()

    conn.close()

    return {
        "query": query,
        "drugs": [dict(r) for r in drugs],
        "targets": [dict(r) for r in targets],
        "mutations": [dict(r) for r in mutations],
    }