import json
import sqlite3
from pathlib import Path

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


def get_all_drugs(drug_class: str = None, search: str = None) -> list:
    conn = get_conn()
    params = []
    conditions = []

    if drug_class:
        conditions.append("d.drug_class = ?")
        params.append(drug_class)

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

    drug["resistance_mutations"] = [dict(r) for r in mut_rows]  # ← was missing

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
