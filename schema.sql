-- schema.sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS drugs (
    drugbank_id          TEXT PRIMARY KEY,
    name                 TEXT NOT NULL,
    indication           TEXT,
    mechanism_of_action  TEXT,
    pharmacodynamics     TEXT,
    drug_class           TEXT,
    atc_codes            TEXT,
    synonyms             TEXT,
    unmatched_pdb_ids    TEXT,

    -- ── New columns ──────────────────────────────────
    smiles               TEXT,
    molecular_weight     TEXT,
    inchikey             TEXT,
    pubchem_cid          TEXT,
    chembl_id            TEXT,
    approval_date        TEXT,

    created_at           TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS targets (
    uniprot_accession    TEXT PRIMARY KEY,
    gene_name            TEXT NOT NULL,
    protein_name         TEXT,
    general_function     TEXT,
    cellular_location    TEXT,
    created_at           TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS drug_target_links (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    drugbank_id          TEXT NOT NULL REFERENCES drugs(drugbank_id) ON DELETE CASCADE,
    uniprot_accession    TEXT NOT NULL REFERENCES targets(uniprot_accession) ON DELETE CASCADE,
    actions              TEXT,
    known_action         TEXT,
    pdb_ids              TEXT,
    UNIQUE (drugbank_id, uniprot_accession)
);

CREATE TABLE IF NOT EXISTS resistance_mutations (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    drugbank_id          TEXT NOT NULL REFERENCES drugs(drugbank_id) ON DELETE CASCADE,
    uniprot_accession    TEXT REFERENCES targets(uniprot_accession) ON DELETE SET NULL,
    gene_symbol          TEXT NOT NULL,
    mutation_aa          TEXT NOT NULL,
    mutation_type        TEXT,
    resistance_type      TEXT,
    source               TEXT,
    total_samples        INTEGER,
    created_at           TEXT DEFAULT (datetime('now')),
    UNIQUE (drugbank_id, gene_symbol, mutation_aa)
);

CREATE TABLE IF NOT EXISTS mutation_pubmed_refs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    mutation_id INTEGER NOT NULL REFERENCES resistance_mutations(id) ON DELETE CASCADE,
    pmid        TEXT NOT NULL,
    UNIQUE (mutation_id, pmid)
);

CREATE TABLE IF NOT EXISTS drug_pubmed_refs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    drugbank_id TEXT NOT NULL REFERENCES drugs(drugbank_id) ON DELETE CASCADE,
    pmid        TEXT NOT NULL,
    UNIQUE (drugbank_id, pmid)
);

CREATE INDEX IF NOT EXISTS idx_drugs_name     ON drugs(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_dtl_uniprot    ON drug_target_links(uniprot_accession);
CREATE INDEX IF NOT EXISTS idx_dtl_drug       ON drug_target_links(drugbank_id);
CREATE INDEX IF NOT EXISTS idx_mutations_drug ON resistance_mutations(drugbank_id);
CREATE INDEX IF NOT EXISTS idx_mutations_gene ON resistance_mutations(gene_symbol);
CREATE INDEX IF NOT EXISTS idx_mutations_uniprot ON resistance_mutations(uniprot_accession);
