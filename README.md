# OncoResist

**A curated database and AI-powered research portal for oncology drug resistance**
---

## Overview

OncoResist integrates resistance mutation data, protein target annotations,
3D structural visualization, and an AI research assistant into a single portal.
Designed for researchers, clinicians, and students who need fast, reliable
answers about how cancer cells develop resistance to targeted therapies.

**Live portal:** https://onco-resist.up.railway.app/

---

## Features

### Drug & Target Database
- **169 FDA-approved oncology drugs** with full DrugBank annotations —
  indication, mechanism of action, approval date, SMILES, ATC codes,
  PubChem CID, ChEMBL ID
- **232 protein targets** with UniProt accessions, cellular location,
  and general function
- **359+ resistance mutations** from COSMIC Drug Resistance Database,
  classified as on-target or off-target

### 3D Structure Viewer
- Live structure fetch from RCSB Protein Data Bank via MolViewSpec
- Click any resistance mutation chip to highlight the mutated residue
  in the 3D viewer
- SIFTS residue mapping for accurate UniProt to PDB position conversion
- Switch between multiple crystal structures per target
- Download computationally generated mutant PDB files from the browser

### ADMET Profile
- Physicochemical property radar chart for small molecule drugs
- MW, logP, TPSA, HBD, HBA, rotatable bonds computed from SMILES via RDKit
- Lipinski Rule of Five and Veber rule compliance per drug

### AI Research Assistant
- Natural language interface powered by Groq API (Llama 3.3 70B)
- 13 structured tools querying SQLite for drug, target, and mutation data
- Cross-drug reasoning — resistance landscapes, pan-resistance mutations,
  shared targets
- Inline PubMed citations from 871 indexed abstracts via ChromaDB
- ADMET comparison of two drugs on demand

### Cross-Drug Relationships
- Find drugs sharing protein targets
- Identify pan-resistant mutations affecting multiple drugs
- Compare resistance profiles across drug generations
- Full resistance landscape for any target gene

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI + Uvicorn |
| Database | SQLite |
| Vector Search | ChromaDB |
| LLM / Agent | Groq API (Llama 3.3 70B) |
| 3D Viewer | Mol* + MolViewSpec |
| ADMET | RDKit |
| Structure Mutation | BioPython |
| Frontend | Jinja2 + Vanilla JS |
| Hosting | Railway |

---

## Data Sources

| Source | Usage |
|---|---|
| COSMIC Drug Resistance | Resistance mutations and patient sample counts |
| DrugBank | Drug profiles, SMILES, targets, mechanisms |
| UniProt | Protein target annotations |
| RCSB PDB | Crystal structures (live fetch) |
| SIFTS / EBI | UniProt to PDB residue mapping |
| PubMed / Europe PMC | Literature references (871 abstracts indexed) |

---

## Local Setup

### Prerequisites
- Python 3.12+
- A Groq API key (free tier at console.groq.com)

### Installation

```bash
git clone https://github.com/satishbhande01/onco-resist.git
cd onco-resist

python -m venv env
source env/bin/activate

pip install -r requirements.txt
```

### Environment

```bash
export GROQ_API_KEY=your_key_here
```

### Run

```bash
uvicorn main:app --reload
```

Open http://localhost:8000

---

## Example Agent Queries
- What mutations cause resistance to imatinib?
- What is the clinical evidence that T315I causes imatinib resistance?
- Compare the resistance landscapes of imatinib and ponatinib
- Which mutations affect the most drugs?
- What drugs are used for colorectal cancer?
- Compare the ADMET profile of imatinib and dasatinib
- What is the resistance landscape for ABL1?


## Disclaimer

OncoResist is a research and portfolio project. Data is sourced from
public databases and provided for informational and educational purposes
only. Not intended for clinical decision-making. Always verify with
primary sources and consult qualified medical professionals for
clinical guidance.