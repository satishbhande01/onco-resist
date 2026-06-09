"""
app/agent/literature.py

Populates and queries ChromaDB with PubMed abstracts.
Uses sentence-transformers for embeddings (no API key needed).
"""

import sqlite3
import time
import requests
import chromadb
from pathlib import Path

DB_PATH     = Path(__file__).resolve().parent.parent.parent / "data" / "portal.db"
CHROMA_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "chroma"

PUBMED_URL  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
DELAY       = 0.4   # seconds between PubMed requests


# ─────────────────────────────────────────────────────────────
# ChromaDB client
# ─────────────────────────────────────────────────────────────

def get_chroma_collection():
    """Get or create the literature collection."""
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    collection = client.get_or_create_collection(
        name="oncodb_literature",
        metadata={"hnsw:space": "cosine"}
    )
    return collection


# ─────────────────────────────────────────────────────────────
# PubMed fetching
# ─────────────────────────────────────────────────────────────

def fetch_abstract(pmid: str) -> dict:
    """
    Fetch title and abstract for a PMID from PubMed.
    Returns dict with title, abstract, pmid.
    """
    params = {
        "db":      "pubmed",
        "id":      pmid,
        "rettype": "abstract",
        "retmode": "xml",
    }

    try:
        resp = requests.get(PUBMED_URL, params=params, timeout=10)
        resp.raise_for_status()
        xml = resp.text

        # Simple XML extraction without lxml dependency
        title    = _extract_xml_tag(xml, "ArticleTitle")
        abstract = _extract_xml_tag(xml, "AbstractText")

        return {
            "pmid":     pmid,
            "title":    title or "",
            "abstract": abstract or "",
        }
    except Exception as e:
        print(f"  [PubMed] Error fetching {pmid}: {e}")
        return {"pmid": pmid, "title": "", "abstract": ""}


def _extract_xml_tag(xml: str, tag: str) -> str:
    """Extract text content of first XML tag."""
    import re
    pattern = f"<{tag}[^>]*>(.*?)</{tag}>"
    match   = re.search(pattern, xml, re.DOTALL)
    if match:
        # Strip any nested XML tags
        text = re.sub(r"<[^>]+>", "", match.group(1))
        return text.strip()
    return ""


# ─────────────────────────────────────────────────────────────
# Population
# ─────────────────────────────────────────────────────────────

def populate_literature(limit: int = None):
    """
    Fetch PubMed abstracts for all PMIDs in the database
    and store in ChromaDB.

    Skips PMIDs already in ChromaDB.
    """
    conn       = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    collection = get_chroma_collection()

    # Get all unique PMIDs from both tables
    mutation_pmids = conn.execute("""
        SELECT DISTINCT mpr.pmid, rm.gene_symbol, rm.mutation_aa,
               d.name AS drug_name, d.drugbank_id
        FROM mutation_pubmed_refs mpr
        JOIN resistance_mutations rm ON rm.id = mpr.mutation_id
        JOIN drugs d ON d.drugbank_id = rm.drugbank_id
    """).fetchall()

    drug_pmids = conn.execute("""
        SELECT DISTINCT dpr.pmid, d.name AS drug_name,
               d.drugbank_id, d.drug_class
        FROM drug_pubmed_refs dpr
        JOIN drugs d ON d.drugbank_id = dpr.drugbank_id
    """).fetchall()

    conn.close()

    # Build PMID → metadata mapping
    pmid_meta = {}

    for row in mutation_pmids:
        pmid = str(row["pmid"])
        if pmid not in pmid_meta:
            pmid_meta[pmid] = {
                "pmid":      pmid,
                "type":      "mutation",
                "gene":      row["gene_symbol"] or "",
                "mutation":  row["mutation_aa"] or "",
                "drug":      row["drug_name"] or "",
                "drugbank_id": row["drugbank_id"] or "",
            }

    for row in drug_pmids:
        pmid = str(row["pmid"])
        if pmid not in pmid_meta:
            pmid_meta[pmid] = {
                "pmid":       pmid,
                "type":       "drug",
                "gene":       "",
                "mutation":   "",
                "drug":       row["drug_name"] or "",
                "drugbank_id": row["drugbank_id"] or "",
            }

    total = len(pmid_meta)
    print(f"Total unique PMIDs: {total}")

    # Check which are already in ChromaDB
    existing = set()
    try:
        existing_ids = collection.get(include=[])["ids"]
        existing     = set(existing_ids)
        print(f"Already in ChromaDB: {len(existing)}")
    except Exception:
        pass

    to_fetch = [
        (pmid, meta)
        for pmid, meta in pmid_meta.items()
        if pmid not in existing
    ]

    if limit:
        to_fetch = to_fetch[:limit]

    print(f"To fetch: {len(to_fetch)}")

    added   = 0
    skipped = 0

    for i, (pmid, meta) in enumerate(to_fetch):
        print(f"[{i+1:>4}/{len(to_fetch)}] PMID {pmid} — {meta['drug']}")

        paper = fetch_abstract(pmid)
        time.sleep(DELAY)

        if not paper["abstract"] and not paper["title"]:
            skipped += 1
            continue

        # Build document text
        document = f"{paper['title']}\n\n{paper['abstract']}".strip()

        if len(document) < 50:
            skipped += 1
            continue

        # Store in ChromaDB
        try:
            collection.add(
                ids=[pmid],
                documents=[document],
                metadatas=[{
                    "pmid":        pmid,
                    "title":       paper["title"][:500],
                    "type":        meta["type"],
                    "gene":        meta["gene"],
                    "mutation":    meta["mutation"],
                    "drug":        meta["drug"],
                    "drugbank_id": meta["drugbank_id"],
                }]
            )
            added += 1
        except Exception as e:
            print(f"  [ChromaDB] Error adding {pmid}: {e}")
            skipped += 1

        # Commit every 50 entries
        if (i + 1) % 50 == 0:
            print(f"  → Progress: {added} added, {skipped} skipped")

    print(f"\nDone. Added: {added}, Skipped: {skipped}")
    print(f"Total in ChromaDB: {collection.count()}")


# ─────────────────────────────────────────────────────────────
# Search
# ─────────────────────────────────────────────────────────────

def search_literature(query: str, n_results: int = 5) -> list:
    """
    Search ChromaDB for relevant literature passages.
    Returns list of dicts with title, abstract snippet, pmid, metadata.
    """
    collection = get_chroma_collection()

    if collection.count() == 0:
        return []

    try:
        results = collection.query(
            query_texts=[query],
            n_results=min(n_results, collection.count()),
            include=["documents", "metadatas", "distances"]
        )

        output = []
        for i, doc in enumerate(results["documents"][0]):
            meta     = results["metadatas"][0][i]
            distance = results["distances"][0][i]

            # Skip low relevance results
            if distance > 0.8:
                continue

            # Truncate document for LLM context
            snippet = doc[:600] + "..." if len(doc) > 600 else doc

            output.append({
                "pmid":     meta.get("pmid", ""),
                "title":    meta.get("title", ""),
                "snippet":  snippet,
                "gene":     meta.get("gene", ""),
                "mutation": meta.get("mutation", ""),
                "drug":     meta.get("drug", ""),
                "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{meta.get('pmid', '')}/",
                "relevance": round(1 - distance, 3),
            })

        return output

    except Exception as e:
        print(f"[ChromaDB] Search error: {e}")
        return []