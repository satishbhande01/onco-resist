"""
extract_drugbank.py

Reads DrugBank XML and extracts approved oncology drugs.

Filters applied:
  1. ATC code starts with "L"  (antineoplastics + endocrine cancer therapy)
  2. Drug group includes "approved"
  3. Indication text contains a cancer keyword

Usage:
    python extract_drugbank.py --file data/raw/drugbank.xml
    python extract_drugbank.py --file data/raw/drugbank.xml --out data/oncology_drugs.json --summary
"""

import argparse
import json
import xml.etree.ElementTree as ET
from collections import Counter

NS = "http://www.drugbank.ca"

CANCER_KEYWORDS = [
    "cancer",
    "carcinoma",
    "leukemia",
    "leukaemia",
    "lymphoma",
    "melanoma",
    "tumor",
    "tumour",
    "neoplasm",
    "sarcoma",
    "myeloma",
    "glioma",
    "oncology",
    "malignant",
    "metastatic",
    "myeloid",
    "lymphocytic",
    "blastoma",
]

# Namespace helper


def tag(name):
    """Return namespace-qualified tag: drug → {http://www.drugbank.ca}drug"""
    return f"{{{NS}}}{name}"


def find_text(element, path, default=""):
    """
    Navigate a chain of child tags and return the text of the last one.
    path is slash-separated e.g. "targets/target/name"
    Returns default if any tag in the chain is missing.
    """
    parts = path.split("/")
    el = element
    for part in parts:
        el = el.find(tag(part))
        if el is None:
            return default
    return (el.text or "").strip()


def find_all_text(element, path):
    """
    Return a list of text values for all matching leaf elements.
    e.g. path="synonyms/synonym" returns all synonym strings.
    """
    parts = path.split("/")
    parent = element
    for part in parts[:-1]:
        parent = parent.find(tag(part))
        if parent is None:
            return []
    return [
        (el.text or "").strip()
        for el in parent.findall(tag(parts[-1]))
        if (el.text or "").strip()
    ]


# Filter functions — all three must pass


def is_approved(drug_el):
    """Drug must have 'approved' in its groups."""
    groups_el = drug_el.find(tag("groups"))
    if groups_el is None:
        return False
    return any(
        (g.text or "").strip().lower() == "approved"
        for g in groups_el.findall(tag("group"))
    )


def has_oncology_atc(drug_el):
    """Drug must have at least one ATC code starting with L."""
    atc_el = drug_el.find(tag("atc-codes"))
    if atc_el is None:
        return False
    return any(
        atc.get("code", "").upper().startswith("L")
        for atc in atc_el.findall(tag("atc-code"))
    )


def has_cancer_indication(drug_el):
    """
    Indication text must mention cancer.
    This removes L03/L04 immunology drugs (MS, RA, transplant)
    that pass the ATC filter but are not oncology drugs.
    """
    indication = find_text(drug_el, "indication").lower()
    if not indication:
        return False
    return any(keyword in indication for keyword in CANCER_KEYWORDS)


# Drug class inference

import re

DRUG_CLASS_RULES = [
    (r"PARP", "PARP Inhibitor"),
    (r"BCR.?ABL|ABL.?kinase", "BCR-ABL Inhibitor"),
    (r"EGFR|epidermal growth factor", "EGFR Inhibitor"),
    (r"\bALK\b", "ALK Inhibitor"),
    (r"\bBRAF\b", "BRAF Inhibitor"),
    (r"\bMEK\b|MAP.?kinase kinase", "MEK Inhibitor"),
    (r"CDK\s*4|CDK\s*6|cyclin.dependent", "CDK4/6 Inhibitor"),
    (r"\bBTK\b|Bruton", "BTK Inhibitor"),
    (r"PI3K|phosphoinositide 3-kinase", "PI3K Inhibitor"),
    (r"\bmTOR\b", "mTOR Inhibitor"),
    (r"VEGF|vascular endothelial", "VEGFR Inhibitor"),
    (r"HER2|erbB.?2|ERBB2", "HER2 Inhibitor"),
    (r"proteasome|PSMB", "Proteasome Inhibitor"),
    (r"HDAC|histone deacetylase", "HDAC Inhibitor"),
    (r"BCL.?2", "BCL-2 Inhibitor"),
    (r"hedgehog|smoothened|\bSMO\b", "Hedgehog Inhibitor"),
    (r"androgen receptor", "Androgen Receptor Antagonist"),
    (r"estrogen receptor|aromatase", "Hormone Therapy"),
    (r"PD.?1|PD.?L1|checkpoint", "Checkpoint Inhibitor"),
    (r"monoclonal antibody|mab\b", "Monoclonal Antibody"),
    (r"tyrosine kinase", "Tyrosine Kinase Inhibitor"),
    (r"kinase inhibitor", "Kinase Inhibitor"),
    (r"antimetabolite|nucleoside analog", "Antimetabolite"),
    (r"alkylat", "Alkylating Agent"),
    (r"topoisomerase", "Topoisomerase Inhibitor"),
    (r"tubulin|microtubule|taxane|vinca", "Tubulin Inhibitor"),
    (r"retinoid|retinoic acid", "Retinoid"),
    (r"interferon", "Interferon"),
]


def infer_drug_class(moa: str) -> str:
    """Infer a drug class label from mechanism_of_action text."""
    if not moa:
        return "Other"
    for pattern, label in DRUG_CLASS_RULES:
        if re.search(pattern, moa, re.IGNORECASE):
            return label
    return "Other"


# Target extraction


def extract_targets(drug_el):
    """
    Extract targets from the <targets> block only.
    Skips transporters, carriers, enzymes — those are pharmacokinetic
    proteins, not the drug's intended pharmacological targets.
    Includes only human targets.
    """
    targets = []
    targets_el = drug_el.find(tag("targets"))
    if targets_el is None:
        return targets

    for target_el in targets_el.findall(tag("target")):
        # Human targets only
        organism = find_text(target_el, "organism")
        if organism.lower() != "human":
            continue

        known_action = find_text(target_el, "known-action")

        # Actions (inhibitor, antagonist, agonist etc.)
        actions = []
        actions_el = target_el.find(tag("actions"))
        if actions_el is not None:
            actions = [
                (a.text or "").strip()
                for a in actions_el.findall(tag("action"))
                if (a.text or "").strip()
            ]

        # Polypeptide block — gene name, UniProt, protein info
        poly_el = target_el.find(tag("polypeptide"))
        if poly_el is None:
            continue

        gene_name = find_text(poly_el, "gene-name")
        protein_name = find_text(poly_el, "name")
        general_fn = find_text(poly_el, "general-function")
        cellular_loc = find_text(poly_el, "cellular-location")

        # Find UniProt accession in external-identifiers
        uniprot_acc = ""
        ext_ids_el = poly_el.find(tag("external-identifiers"))
        if ext_ids_el is not None:
            for ext_el in ext_ids_el.findall(tag("external-identifier")):
                resource = find_text(ext_el, "resource")
                if resource == "UniProtKB":
                    uniprot_acc = find_text(ext_el, "identifier")
                    break

        targets.append(
            {
                "gene_name": gene_name,
                "uniprot_accession": uniprot_acc,
                "protein_name": protein_name,
                "general_function": general_fn,
                "cellular_location": cellular_loc,
                "actions": actions,
                "known_action": known_action,
            }
        )

    return targets


# Single drug extraction
def extract_drug(drug_el):
    """
    Extract all relevant fields from one <drug> element.
    Returns a dict or None if the drug fails any filter.
    """

    # All three filters must pass
    if not is_approved(drug_el):
        return None
    if not has_oncology_atc(drug_el):
        return None
    if not has_cancer_indication(drug_el):
        return None

    # Primary DrugBank ID (the one with primary="true")
    drugbank_id = ""
    for db_id_el in drug_el.findall(tag("drugbank-id")):
        if db_id_el.get("primary") == "true":
            drugbank_id = (db_id_el.text or "").strip()
            break

    if not drugbank_id:
        return None

    moa = find_text(drug_el, "mechanism-of-action")

    return {
        "drugbank_id": drugbank_id,
        "name": find_text(drug_el, "name"),
        "atc_codes": [
            atc.get("code", "")
            for atc in (drug_el.find(tag("atc-codes")) or [])
            if atc.get("code", "")
        ],
        "indication": find_text(drug_el, "indication"),
        "mechanism_of_action": moa,
        "pharmacodynamics": find_text(drug_el, "pharmacodynamics"),
        "drug_class": infer_drug_class(moa),
        "synonyms": find_all_text(drug_el, "synonyms/synonym"),
        "pdb_ids": find_all_text(drug_el, "pdb-entries/pdb-entry"),
        "targets": extract_targets(drug_el),
        "pubmed_ids": [
            find_text(a, "pubmed-id")
            for a in (
                (drug_el.find(tag("general-references")) or ET.Element("x")).find(
                    tag("articles")
                )
                or []
            )
            if find_text(a, "pubmed-id")
        ],
    }


# Main parser — streams through the xml


def parse_drugbank(xml_path):
    """
    Stream through DrugBank XML using iterparse.
    iterparse processes the file element by element without loading
    it all into memory — essential for a file that can be 1-2 GB.
    """
    print(f"Parsing {xml_path} ...")
    print("(Streaming with iterparse — safe for large XML files)\n")

    drugs = []
    skipped = 0
    depth = 0
    current_drug_el = None
    current_depth = 0

    context = ET.iterparse(xml_path, events=("start", "end"))

    for event, elem in context:
        local = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

        if event == "start":
            depth += 1
            if local == "drug" and depth == 2:
                current_drug_el = elem
                current_depth = depth

        if event == "end":
            if (
                local == "drug"
                and depth == current_depth
                and current_drug_el is not None
            ):
                result = extract_drug(current_drug_el)
                if result:
                    drugs.append(result)
                else:
                    skipped += 1
                current_drug_el = None
                elem.clear()  # free memory after processing each drug
            depth -= 1

    return drugs, skipped


# summary


def print_summary(drugs):
    print(f"\n{'=' * 60}")
    print(f"EXTRACTION SUMMARY — {len(drugs)} oncology drugs")
    print(f"{'=' * 60}")
    print(f"With targets        : {sum(1 for d in drugs if d['targets'])}")
    print(f"With PDB entries    : {sum(1 for d in drugs if d['pdb_ids'])}")

    print(f"\n{'─' * 60}")
    print(f"{'Drug':<35} {'Targets':>7} {'PDB':>5}")
    print(f"{'─' * 60}")
    for d in sorted(drugs, key=lambda x: x["name"]):
        print(f"{d['name'][:34]:<35} {len(d['targets']):>7} {len(d['pdb_ids']):>5}")

    print(f"\nDrug class breakdown:")
    classes = Counter(d["drug_class"] for d in drugs)
    for cls, count in classes.most_common():
        print(f"  {cls:<35} {count}")


# Entry point
def main():
    parser = argparse.ArgumentParser(
        description="Extract oncology drugs from DrugBank XML"
    )
    parser.add_argument("--file", required=True, help="Path to drugbank.xml")
    parser.add_argument(
        "--out",
        default="data/oncology_drugs.json",
        help="Output JSON path (default: data/oncology_drugs.json)",
    )
    parser.add_argument(
        "--summary", action="store_true", help="Print summary table after extraction"
    )
    args = parser.parse_args()

    drugs, skipped = parse_drugbank(args.file)

    print(f"Extracted : {len(drugs)} oncology drugs")
    print(f"Skipped   : {skipped} drugs (failed filters)")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(drugs, f, indent=2, ensure_ascii=False)

    print(f"Saved     : {args.out}")

    if args.summary:
        print_summary(drugs)


if __name__ == "__main__":
    main()
