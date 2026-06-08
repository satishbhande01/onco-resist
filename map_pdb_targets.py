"""
map_pdb_targets.py

For each drug in oncology_drugs.json, assigns each PDB ID to the
correct target by querying the RCSB GraphQL API.

The problem being solved:
    DrugBank gives PDB IDs at the drug level (not per target).
    e.g. imatinib has 19 PDB IDs — some are ABL1 structures,
    some are KIT structures, some are DDR1 structures.
    We need to know which is which for the 3D viewer.

The approach:
    For each PDB ID → ask RCSB "which UniProt accessions are in
    this structure?" → match against the drug's known targets.

Output adds two fields to each drug:
    target_pdb_links  — targets with their matched PDB IDs
    unmatched_pdb_ids — PDB IDs that matched no known target

Usage:
    python map_pdb_targets.py --in data/oncology_drugs.json
    python map_pdb_targets.py --in data/oncology_drugs.json --drug imatinib
    python map_pdb_targets.py --in data/oncology_drugs.json --out data/oncology_drugs_mapped.json --summary
"""

import argparse
import json
import time
import requests
from collections import defaultdict

UNIPROT_ALIASES = {
    "P00520": "P00519",   # BCR-ABL fusion → ABL1
    "A9UF02": "P00519",   # BCR-ABL alternate accession → ABL1
    "P00519-2": "P00519", # ABL1 isoform 2 → ABL1
    "P10721-2": "P10721", # KIT isoform 2 → KIT
    "P16234-2": "P16234", # PDGFRA isoform → PDGFRA
    "P09619-2": "P09619", # PDGFRB isoform → PDGFRB
    "O43519-2": "O43519", # RET isoform → RET
}

RCSB_GRAPHQL = "https://data.rcsb.org/graphql"
REQUEST_DELAY = 0.15  # seconds between API calls — be polite to RCSB


# ─────────────────────────────────────────────────────────────
# RCSB GraphQL query
# ─────────────────────────────────────────────────────────────

# This query asks RCSB: for a given PDB entry, what UniProt
# accessions appear across all polymer chains in the structure?
QUERY = """
query GetUniProtForEntry($id: String!) {
  entry(entry_id: $id) {
    rcsb_id
    polymer_entities {
      rcsb_polymer_entity_container_identifiers {
        reference_sequence_identifiers {
          database_name
          database_accession
        }
      }
    }
  }
}
"""


def get_uniprot_accessions_for_pdb(pdb_id: str) -> set:
    """
    Query RCSB GraphQL for a PDB entry.
    Returns all UniProt accessions found, normalised through aliases.
    """
    try:
        resp = requests.post(
            RCSB_GRAPHQL,
            json={"query": QUERY, "variables": {"id": pdb_id.upper()}},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"    [WARN] RCSB API error for {pdb_id}: {e}")
        return set()

    accessions = set()
    entry = (data.get("data") or {}).get("entry")
    if not entry:
        return accessions

    for entity in entry.get("polymer_entities") or []:
        container = entity.get(
            "rcsb_polymer_entity_container_identifiers", {}
        )
        for ref in container.get("reference_sequence_identifiers") or []:
            if ref.get("database_name") == "UniProt":
                acc = ref.get("database_accession", "").strip()
                if acc:
                    # Normalise through alias map
                    acc = UNIPROT_ALIASES.get(acc, acc)
                    accessions.add(acc)

    return accessions


# ─────────────────────────────────────────────────────────────
# Map PDB IDs to targets for one drug
# ─────────────────────────────────────────────────────────────


def map_pdb_ids_to_targets(drug: dict, verbose: bool = False) -> dict:
    """
    For one drug, query each of its PDB IDs and assign them
    to the matching target based on UniProt overlap.

    Returns a dict with:
        target_pdb_links  — list of target dicts, each with pdb_ids added
        unmatched_pdb_ids — PDB IDs that did not match any target
    """
    targets = drug.get("targets", [])
    pdb_ids = drug.get("pdb_ids", [])

    # Build lookup: uniprot_accession → index in targets list
    uniprot_to_idx = {}
    for i, t in enumerate(targets):
        acc = t.get("uniprot_accession", "").strip()
        if acc:
            uniprot_to_idx[acc] = i

    # Accumulate matched PDB IDs per target index
    target_pdb_map = defaultdict(list)
    unmatched = []

    for pdb_id in pdb_ids:
        if verbose:
            print(f"    Querying {pdb_id.upper()} ...", end=" ", flush=True)

        pdb_uniprots = get_uniprot_accessions_for_pdb(pdb_id)
        time.sleep(REQUEST_DELAY)

        if verbose:
            print(f"found: {pdb_uniprots or 'none'}")

        # Match against known targets
        matched = False
        for acc in pdb_uniprots:
            if acc in uniprot_to_idx:
                idx = uniprot_to_idx[acc]
                target_pdb_map[idx].append(pdb_id)
                matched = True
                break  # assign to first matching target only

        if not matched:
            unmatched.append(pdb_id)

    # Build final target_pdb_links — one entry per target
    # Each entry is the original target dict plus a pdb_ids list
    target_pdb_links = []
    for i, t in enumerate(targets):
        entry = dict(t)
        entry["pdb_ids"] = sorted(target_pdb_map.get(i, []))
        target_pdb_links.append(entry)

    return {
        "target_pdb_links": target_pdb_links,
        "unmatched_pdb_ids": unmatched,
    }


# ─────────────────────────────────────────────────────────────
# Process all drugs
# ─────────────────────────────────────────────────────────────


def process_all_drugs(
    drugs: list,
    drug_filter: str = None,
    verbose: bool = False,
) -> list:
    """
    Process every drug in the list.
    Adds target_pdb_links and unmatched_pdb_ids to each drug dict.
    If drug_filter is given, only that drug is queried — all others
    are passed through unchanged (useful for testing one drug first).
    """
    results = []

    for i, drug in enumerate(drugs):
        name = drug.get("name", "Unknown")
        n_pdb = len(drug.get("pdb_ids", []))

        # If filtering to one drug, pass others through unchanged
        if drug_filter and name.lower() != drug_filter.lower():
            results.append(drug)
            continue

        print(f"[{i + 1:>3}/{len(drugs)}] {name:<35} {n_pdb} PDB IDs")

        mapping = map_pdb_ids_to_targets(drug, verbose=verbose)

        enriched = dict(drug)
        enriched["target_pdb_links"] = mapping["target_pdb_links"]
        enriched["unmatched_pdb_ids"] = mapping["unmatched_pdb_ids"]

        if mapping["unmatched_pdb_ids"] and verbose:
            print(f"    Unmatched: {mapping['unmatched_pdb_ids']}")

        results.append(enriched)

    return results


# ─────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────


def print_mapping_summary(drugs: list):
    total_pdb = sum(len(d.get("pdb_ids", [])) for d in drugs)
    total_matched = sum(
        sum(len(t["pdb_ids"]) for t in d.get("target_pdb_links", [])) for d in drugs
    )
    total_unmatched = sum(len(d.get("unmatched_pdb_ids", [])) for d in drugs)

    print(f"\n{'=' * 60}")
    print(f"MAPPING SUMMARY")
    print(f"{'=' * 60}")
    print(f"Total PDB IDs      : {total_pdb}")
    print(f"Matched to target  : {total_matched}")
    print(f"Unmatched          : {total_unmatched}")

    print(f"\nTARGET → PDB ASSIGNMENTS (drugs with matches)")
    print(f"{'─' * 60}")

    for d in sorted(drugs, key=lambda x: x["name"]):
        links = d.get("target_pdb_links", [])
        has_any = any(t["pdb_ids"] for t in links)
        if not has_any:
            continue
        print(f"\n  {d['name']}")
        for t in links:
            if t["pdb_ids"]:
                gene = t.get("gene_name", "?")
                acc = t.get("uniprot_accession", "?")
                pdbs = ", ".join(t["pdb_ids"][:4])
                more = (
                    f" (+{len(t['pdb_ids']) - 4} more)" if len(t["pdb_ids"]) > 4 else ""
                )
                print(f"    {gene:<10} ({acc})  →  {pdbs}{more}")


# ─────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Map PDB IDs to drug targets via RCSB GraphQL API"
    )
    parser.add_argument(
        "--in", dest="input", required=True, help="Input JSON from extract_drugbank.py"
    )
    parser.add_argument(
        "--out", default="data/oncology_drugs_mapped.json", help="Output JSON path"
    )
    parser.add_argument(
        "--drug", default=None, help="Test one drug only e.g. --drug imatinib"
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Print per-PDB query results"
    )
    parser.add_argument(
        "--summary", action="store_true", help="Print mapping summary after processing"
    )
    args = parser.parse_args()

    print(f"Loading {args.input} ...")
    with open(args.input, encoding="utf-8") as f:
        drugs = json.load(f)
    print(f"Loaded {len(drugs)} drugs\n")

    enriched = process_all_drugs(
        drugs,
        drug_filter=args.drug,
        verbose=args.verbose,
    )

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(enriched, f, indent=2, ensure_ascii=False)

    print(f"\nSaved → {args.out}")

    if args.summary:
        print_mapping_summary(enriched)


if __name__ == "__main__":
    main()
