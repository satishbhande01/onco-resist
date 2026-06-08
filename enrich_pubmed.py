"""
enrich_pubmed.py

Queries Europe PMC for literature references for each
resistance mutation in the database and populates the
mutation_pubmed_refs table.

Europe PMC is used instead of PubMed directly because it has
a clean REST API with no API key required.

Usage:
    python enrich_pubmed.py
    python enrich_pubmed.py --db data/portal.db --limit 10
"""

import argparse
import sqlite3
import time
import requests


EPMC_URL   = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
DELAY      = 0.5    # seconds between API calls — be polite
MAX_PMIDS  = 5      # max references to store per mutation


# ─────────────────────────────────────────────────────────────
# Europe PMC query
# ─────────────────────────────────────────────────────────────

def search_epmc(query: str, max_results: int = 5) -> list[str]:
    """
    Search Europe PMC and return a list of PMIDs.
    Returns empty list on any failure.
    """
    params = {
        "query":        query,
        "format":       "json",
        "pageSize":     max_results,
        "resultType":   "lite",
        "cursorMark":   "*",
        "sort":         "CITED desc",  # most cited first
    }

    try:
        resp = requests.get(EPMC_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"    [WARN] Europe PMC error: {e}")
        return []

    results = data.get("resultList", {}).get("result", [])
    pmids   = []

    for r in results:
        pmid = r.get("pmid")
        # Only include actual PubMed entries (not preprints etc.)
        if pmid and r.get("source") == "MED":
            pmids.append(str(pmid))

    return pmids[:max_results]


# ─────────────────────────────────────────────────────────────
# Build search query for a mutation
# ─────────────────────────────────────────────────────────────

def build_query(gene: str, mutation_aa: str, drug_name: str) -> str:
    """
    Build a targeted search query for a specific resistance mutation.

    Example:
        gene="ABL1", mutation_aa="p.T315I", drug_name="Imatinib"
        → 'ABL1 T315I imatinib resistance'

    Strips the 'p.' prefix from HGVS notation if present.
    """
    # Strip p. prefix — "p.T315I" → "T315I"
    mut = mutation_aa
    if mut.startswith("p."):
        mut = mut[2:]

    return f"{gene} {mut} {drug_name} resistance"


# ─────────────────────────────────────────────────────────────
# Main enrichment
# ─────────────────────────────────────────────────────────────

def enrich_mutations(
    conn: sqlite3.Connection,
    limit: int = None,
    verbose: bool = False,
):
    """
    For each resistance mutation, search Europe PMC and
    insert found PMIDs into mutation_pubmed_refs.

    Skips mutations that already have references.
    """
    cur = conn.cursor()

    # Fetch all mutations that don't yet have pubmed refs
    cur.execute("""
        SELECT
            rm.id,
            rm.gene_symbol,
            rm.mutation_aa,
            d.name AS drug_name
        FROM resistance_mutations rm
        JOIN drugs d ON d.drugbank_id = rm.drugbank_id
        WHERE rm.id NOT IN (
            SELECT DISTINCT mutation_id FROM mutation_pubmed_refs
        )
        ORDER BY rm.gene_symbol, rm.mutation_aa
    """)

    mutations = cur.fetchall()

    if limit:
        mutations = mutations[:limit]

    total        = len(mutations)
    enriched     = 0
    skipped      = 0
    refs_added   = 0

    print(f"Enriching {total} mutations with PubMed references...")
    print(f"(Using Europe PMC API, {DELAY}s delay between calls)\n")

    for i, mut in enumerate(mutations):
        mut_id    = mut["id"]
        gene      = mut["gene_symbol"]
        mut_aa    = mut["mutation_aa"]
        drug_name = mut["drug_name"]

        query = build_query(gene, mut_aa, drug_name)

        if verbose:
            print(f"[{i+1:>3}/{total}] {gene} {mut_aa} + {drug_name}")
            print(f"         Query: {query}")
        else:
            print(f"[{i+1:>3}/{total}] {gene:<8} {mut_aa:<12} {drug_name}")

        pmids = search_epmc(query, max_results=MAX_PMIDS)
        time.sleep(DELAY)

        if not pmids:
            skipped += 1
            if verbose:
                print(f"         No results found")
            continue

        # Insert PMIDs
        inserted = 0
        for pmid in pmids:
            try:
                cur.execute("""
                    INSERT OR IGNORE INTO mutation_pubmed_refs
                        (mutation_id, pmid)
                    VALUES (?, ?)
                """, (mut_id, pmid))
                if cur.rowcount:
                    inserted += 1
                    refs_added += 1
            except Exception as e:
                print(f"    [WARN] Insert error: {e}")

        if inserted:
            enriched += 1

        if verbose:
            print(f"         Found {len(pmids)} PMIDs, inserted {inserted}")

        # Commit every 20 mutations to avoid losing progress
        if (i + 1) % 20 == 0:
            conn.commit()
            print(f"  → Committed at {i+1}/{total}")

    conn.commit()

    print(f"\n{'='*50}")
    print(f"ENRICHMENT COMPLETE")
    print(f"{'='*50}")
    print(f"Mutations processed : {total}")
    print(f"Enriched with refs  : {enriched}")
    print(f"No results found    : {skipped}")
    print(f"Total refs added    : {refs_added}")
    print(f"Avg refs/mutation   : {refs_added/max(enriched,1):.1f}")


# ─────────────────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────────────────

def validate(conn: sqlite3.Connection):
    """Show sample results after enrichment."""
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM mutation_pubmed_refs")
    total = cur.fetchone()[0]
    print(f"\nTotal refs in mutation_pubmed_refs: {total}")

    print(f"\nSample — imatinib ABL1 T315I references:")
    cur.execute("""
        SELECT mpr.pmid
        FROM mutation_pubmed_refs mpr
        JOIN resistance_mutations rm ON rm.id = mpr.mutation_id
        JOIN drugs d ON d.drugbank_id = rm.drugbank_id
        WHERE d.name = 'Imatinib'
        AND rm.gene_symbol = 'ABL1'
        AND rm.mutation_aa LIKE '%T315I%'
        LIMIT 5
    """)
    rows = cur.fetchall()
    if rows:
        for row in rows:
            print(f"  PMID: {row['pmid']}")
    else:
        print("  No results — mutation may use different notation")

    print(f"\nMutations with most references:")
    cur.execute("""
        SELECT
            rm.gene_symbol,
            rm.mutation_aa,
            d.name AS drug_name,
            COUNT(mpr.id) AS ref_count
        FROM mutation_pubmed_refs mpr
        JOIN resistance_mutations rm ON rm.id = mpr.mutation_id
        JOIN drugs d ON d.drugbank_id = rm.drugbank_id
        GROUP BY mpr.mutation_id
        ORDER BY ref_count DESC
        LIMIT 10
    """)
    for row in cur.fetchall():
        print(f"  {row['gene_symbol']:<8} {row['mutation_aa']:<12} "
              f"{row['drug_name']:<20} {row['ref_count']} refs")


# ─────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Enrich resistance mutations with PubMed references"
    )
    parser.add_argument("--db",      default="data/portal.db")
    parser.add_argument("--limit",   type=int, default=None,
                        help="Process only N mutations (for testing)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    enrich_mutations(conn, limit=args.limit, verbose=args.verbose)
    validate(conn)

    conn.close()


if __name__ == "__main__":
    main()