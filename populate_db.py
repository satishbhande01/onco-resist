"""
populate_db.py

Reads oncology_drugs_mapped.json and cosmic.json and populates
the SQLite database defined in schema.sql.

Run once to build data/portal.db. Safe to re-run — INSERT OR IGNORE
means existing rows are skipped rather than duplicated.

Usage:
    python populate_db.py
    python populate_db.py --drugs data/oncology_drugs_mapped.json
                          --cosmic data/raw/cosmic.json
                          --db data/portal.db
                          --schema schema.sql
"""

import argparse
import json
import re
import sqlite3
from pathlib import Path


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────


def jdump(obj) -> str:
    """Serialize a Python list to a compact JSON string for storage."""
    return json.dumps(obj, ensure_ascii=False)


def normalise_name(name: str) -> str:
    """
    Strip pharmaceutical qualifiers so names match across sources.
    'Dasatinib Anhydrous' → 'dasatinib'
    'Imatinib Mesylate'   → 'imatinib'
    This is how COSMIC drug names get matched to DrugBank drug names.
    """
    qualifiers = {
        "anhydrous",
        "hydrochloride",
        "mesylate",
        "sulfate",
        "phosphate",
        "acetate",
        "citrate",
        "hcl",
        "monohydrate",
        "succinate",
        "maleate",
        "tartrate",
        "sodium",
        "chloride",
    }
    words = name.lower().split()
    return " ".join(w for w in words if w not in qualifiers).strip()


# ─────────────────────────────────────────────────────────────
# Database setup
# ─────────────────────────────────────────────────────────────


def create_db(db_path: str, schema_path: str) -> sqlite3.Connection:
    """
    Open (or create) the SQLite database and apply the schema.
    CREATE TABLE IF NOT EXISTS means this is safe to run multiple times.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    with open(schema_path, "r") as f:
        conn.executescript(f.read())

    conn.commit()
    print(f"[DB] Ready: {db_path}")
    return conn


# ─────────────────────────────────────────────────────────────
# Insert drugs, targets, links
# ─────────────────────────────────────────────────────────────


def insert_drugs(conn: sqlite3.Connection, drugs: list):
    """
    Insert all drugs, their targets, drug_target_links,
    and general PubMed references.

    Three tables are populated here:
        drugs             — one row per drug
        targets           — one row per unique UniProt accession
        drug_target_links — one row per drug-target pair
        drug_pubmed_refs  — one row per PubMed reference per drug
    """
    cur = conn.cursor()
    drugs_inserted = 0
    targets_inserted = 0
    links_inserted = 0
    refs_inserted = 0

    for drug in drugs:
        drugbank_id = drug.get("drugbank_id", "").strip()
        if not drugbank_id:
            continue

        # ── Insert drug ──────────────────────────────────────
        cur.execute(
            """
            INSERT OR IGNORE INTO drugs
                (drugbank_id, name, indication, mechanism_of_action,
                 pharmacodynamics, drug_class, atc_codes, synonyms,
                 unmatched_pdb_ids)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                drugbank_id,
                drug.get("name", ""),
                drug.get("indication", ""),
                drug.get("mechanism_of_action", ""),
                drug.get("pharmacodynamics", ""),
                drug.get("drug_class", "Other"),
                jdump(drug.get("atc_codes", [])),
                jdump(drug.get("synonyms", [])),
                jdump(drug.get("unmatched_pdb_ids", [])),
            ),
        )
        if cur.rowcount:
            drugs_inserted += 1

        # ── Insert targets and drug_target_links ─────────────
        # target_pdb_links is the enriched targets list from
        # map_pdb_targets.py — each target has a pdb_ids field
        for t in drug.get("target_pdb_links", []):
            uniprot = t.get("uniprot_accession", "").strip()
            gene = t.get("gene_name", "").strip()

            if not uniprot or not gene:
                continue

            # Insert target — IGNORE if already inserted by another drug
            # (ABL1 is targeted by imatinib, dasatinib, nilotinib etc.
            #  but we only need one row for ABL1 in the targets table)
            cur.execute(
                """
                INSERT OR IGNORE INTO targets
                    (uniprot_accession, gene_name, protein_name,
                     general_function, cellular_location)
                VALUES (?, ?, ?, ?, ?)
            """,
                (
                    uniprot,
                    gene,
                    t.get("protein_name", ""),
                    t.get("general_function", ""),
                    t.get("cellular_location", ""),
                ),
            )
            if cur.rowcount:
                targets_inserted += 1

            # Insert drug_target_link
            cur.execute(
                """
                INSERT OR IGNORE INTO drug_target_links
                    (drugbank_id, uniprot_accession, actions,
                     known_action, pdb_ids)
                VALUES (?, ?, ?, ?, ?)
            """,
                (
                    drugbank_id,
                    uniprot,
                    jdump(t.get("actions", [])),
                    t.get("known_action", "unknown"),
                    jdump(t.get("pdb_ids", [])),
                ),
            )
            if cur.rowcount:
                links_inserted += 1

        # ── Insert general PubMed references ─────────────────
        for pmid in drug.get("pubmed_ids", []):
            if pmid:
                cur.execute(
                    """
                    INSERT OR IGNORE INTO drug_pubmed_refs
                        (drugbank_id, pmid)
                    VALUES (?, ?)
                """,
                    (drugbank_id, pmid),
                )
                if cur.rowcount:
                    refs_inserted += 1

    conn.commit()
    print(f"  Drugs inserted        : {drugs_inserted}")
    print(f"  Targets inserted      : {targets_inserted}")
    print(f"  Drug-target links     : {links_inserted}")
    print(f"  Drug PubMed refs      : {refs_inserted}")


# Insert resistance mutations from cosmic


def insert_cosmic_mutations(
    conn: sqlite3.Connection,
    cosmic: list,
    drugs: list,
):
    """
    Match COSMIC drug names to DrugBank drugs and insert
    resistance mutations.

    COSMIC record structure:
    {
        "drug_name": "Imatinib",
        "mutations": [
            {"gene_symbol": "ABL1", "mutation_aa": "T315I"},
            ...
        ],
        "total_resistance_samples": 866
    }

    The matching uses normalised names so "Imatinib Mesylate" in
    COSMIC matches "Imatinib" in DrugBank.
    """
    cur = conn.cursor()

    # Build lookup: normalised name → drugbank_id
    # Also index all synonyms so brand names match too
    name_to_dbid = {}
    for drug in drugs:
        norm = normalise_name(drug.get("name", ""))
        name_to_dbid[norm] = drug["drugbank_id"]
        for syn in drug.get("synonyms", []):
            norm_syn = normalise_name(syn)
            if norm_syn:
                name_to_dbid[norm_syn] = drug["drugbank_id"]

    # Build lookup: (drugbank_id, gene_symbol) → uniprot_accession
    # Used to link mutations back to their target protein
    cur.execute("""
        SELECT dtl.drugbank_id, t.gene_name, t.uniprot_accession
        FROM drug_target_links dtl
        JOIN targets t ON t.uniprot_accession = dtl.uniprot_accession
    """)
    gene_to_uniprot = {}
    for row in cur.fetchall():
        key = (row["drugbank_id"], row["gene_name"].upper())
        gene_to_uniprot[key] = row["uniprot_accession"]

    mutations_inserted = 0
    unmatched_drugs = set()

    for record in cosmic:
        drug_name = record.get("drug_name", "")
        norm_name = normalise_name(drug_name)
        drugbank_id = name_to_dbid.get(norm_name)

        if not drugbank_id:
            unmatched_drugs.add(drug_name)
            continue

        total_samples = record.get("total_resistance_samples", 0)

        for mutation in record.get("mutations", []):
            gene = (mutation.get("gene_symbol") or "").strip()
            mut_aa = (mutation.get("mutation_aa") or "").strip()

            if not gene or not mut_aa:
                continue

            # Try to find the UniProt for this gene in context of this drug
            uniprot = gene_to_uniprot.get((drugbank_id, gene.upper()), None)

            cur.execute(
                """
                INSERT OR IGNORE INTO resistance_mutations
                    (drugbank_id, uniprot_accession, gene_symbol,
                     mutation_aa, mutation_type, resistance_type,
                     source, total_samples)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    drugbank_id,
                    uniprot,
                    gene,
                    mut_aa,
                    mutation.get("mutation_type", "point_mutation"),
                    "acquired",
                    "COSMIC",
                    total_samples,
                ),
            )
            if cur.rowcount:
                mutations_inserted += 1

    conn.commit()
    print(f"  Mutations inserted    : {mutations_inserted}")

    if unmatched_drugs:
        print(f"  COSMIC unmatched     : {len(unmatched_drugs)}")
        for name in sorted(unmatched_drugs):
            print(f"    - {name}")


# Validation


def validate(conn: sqlite3.Connection):
    """
    Run spot-check queries to confirm the database looks right.
    If imatinib has targets and mutations, everything is wired up.
    """
    cur = conn.cursor()

    print(f"\n{'=' * 60}")
    print("VALIDATION")
    print(f"{'=' * 60}")

    # Row counts for every table
    for table in [
        "drugs",
        "targets",
        "drug_target_links",
        "resistance_mutations",
        "mutation_pubmed_refs",
        "drug_pubmed_refs",
    ]:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        print(f"  {table:<30} {cur.fetchone()[0]:>6} rows")

    # Spot check: imatinib targets
    print(f"\n--- Imatinib targets ---")
    cur.execute("""
        SELECT t.gene_name, t.uniprot_accession,
               dtl.known_action, dtl.pdb_ids
        FROM drug_target_links dtl
        JOIN drugs d  ON d.drugbank_id  = dtl.drugbank_id
        JOIN targets t ON t.uniprot_accession = dtl.uniprot_accession
        WHERE d.name = 'Imatinib'
        ORDER BY dtl.known_action DESC, t.gene_name
    """)
    for row in cur.fetchall():
        pdbs = json.loads(row["pdb_ids"] or "[]")
        pdb_str = ", ".join(pdbs[:3])
        if len(pdbs) > 3:
            pdb_str += f" (+{len(pdbs) - 3} more)"
        print(
            f"  {row['gene_name']:<10} "
            f"({row['uniprot_accession']})  "
            f"known={row['known_action']:<8}  "
            f"PDB: {pdb_str or '—'}"
        )

    # Spot check: imatinib mutations
    print(f"\n--- Imatinib resistance mutations (top 5) ---")
    cur.execute("""
        SELECT rm.gene_symbol, rm.mutation_aa, rm.total_samples
        FROM resistance_mutations rm
        JOIN drugs d ON d.drugbank_id = rm.drugbank_id
        WHERE d.name = 'Imatinib'
        ORDER BY rm.total_samples DESC
        LIMIT 5
    """)
    rows = cur.fetchall()
    if rows:
        for row in rows:
            print(
                f"  {row['gene_symbol']:<8} "
                f"{row['mutation_aa']:<10} "
                f"samples={row['total_samples']}"
            )
    else:
        print("  No mutations found — check COSMIC name matching")

    # Drug class breakdown
    print(f"\n--- Drug class breakdown ---")
    cur.execute("""
        SELECT drug_class, COUNT(*) as n
        FROM drugs
        GROUP BY drug_class
        ORDER BY n DESC
    """)
    for row in cur.fetchall():
        print(f"  {row['drug_class']:<35} {row['n']:>4}")


# Entry point
def main():
    parser = argparse.ArgumentParser(
        description="Populate the oncology portal SQLite database"
    )
    parser.add_argument(
        "--drugs",
        default="data/oncology_drugs_mapped.json",
        help="Path to oncology_drugs_mapped.json",
    )
    parser.add_argument(
        "--cosmic", default="data/raw/cosmic.json", help="Path to cosmic.json"
    )
    parser.add_argument(
        "--db", default="data/portal.db", help="Output SQLite database path"
    )
    parser.add_argument("--schema", default="schema.sql", help="Path to schema.sql")
    args = parser.parse_args()

    # Load source data
    print(f"Loading {args.drugs} ...")
    with open(args.drugs, encoding="utf-8") as f:
        drugs = json.load(f)
    print(f"  {len(drugs)} drugs")

    print(f"Loading {args.cosmic} ...")
    with open(args.cosmic, encoding="utf-8") as f:
        cosmic = json.load(f)
    print(f"  {len(cosmic)} COSMIC records")

    # Create database and apply schema
    conn = create_db(args.db, args.schema)

    # Populate
    print(f"\nInserting drugs, targets, links ...")
    insert_drugs(conn, drugs)

    print(f"\nInserting COSMIC resistance mutations ...")
    insert_cosmic_mutations(conn, cosmic, drugs)

    # Validate
    validate(conn)

    conn.close()
    print(f"\nDone. Database at: {args.db}")


if __name__ == "__main__":
    main()
