"""
app/agent/schemas.py

Tool schemas in Groq/OpenAI function calling format.
These tell the LLM what tools exist, what parameters they take,
and when to use them.
"""

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_drug_info",
            "description": (
                "Get full profile for an oncology drug including indication, "
                "mechanism of action, approval date, molecular weight, SMILES, "
                "ATC codes, PubChem and ChEMBL IDs. Use this when asked about "
                "a specific drug's properties, approval, or general information."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "drug_name": {
                        "type": "string",
                        "description": "Drug name e.g. 'Imatinib', 'Afatinib'"
                    }
                },
                "required": ["drug_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_drug_targets",
            "description": (
                "Get all protein targets for a drug with UniProt accessions, "
                "gene names, cellular location, and whether the action is confirmed. "
                "Use this when asked what proteins a drug targets or inhibits."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "drug_name": {
                        "type": "string",
                        "description": "Drug name e.g. 'Imatinib'"
                    }
                },
                "required": ["drug_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_resistance_mutations",
            "description": (
                "Get all resistance mutations for a drug from the COSMIC database, "
                "grouped by gene with on-target vs off-target classification. "
                "Use this when asked about resistance mechanisms, mutations that "
                "cause resistance, or how resistance develops for a drug."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "drug_name": {
                        "type": "string",
                        "description": "Drug name e.g. 'Imatinib'"
                    }
                },
                "required": ["drug_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_target_info",
            "description": (
                "Get full profile for a protein target by gene name including "
                "protein name, cellular location, general function, and all drugs "
                "that target it. Use this when asked about a specific gene or protein."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "gene_name": {
                        "type": "string",
                        "description": "Gene symbol e.g. 'ABL1', 'EGFR', 'BRAF'"
                    }
                },
                "required": ["gene_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_mutations",
            "description": (
                "Find all drugs affected by a specific resistance mutation. "
                "Use this when asked about a specific mutation like T315I, E255K "
                "or when asked which drugs a mutation affects."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mutation_code": {
                        "type": "string",
                        "description": "Mutation code e.g. 'T315I' or 'p.T315I'"
                    }
                },
                "required": ["mutation_code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_related_drugs",
            "description": (
                "Find drugs that share protein targets with a given drug. "
                "Use this when asked about related drugs, drugs in the same class, "
                "or drugs that target the same proteins."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "drug_name": {
                        "type": "string",
                        "description": "Drug name e.g. 'Imatinib'"
                    }
                },
                "required": ["drug_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_shared_mutations",
            "description": (
                "Find resistance mutations shared between two drugs. "
                "Use this when comparing resistance profiles of two drugs "
                "or asking about cross-resistance."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "drug1_name": {
                        "type": "string",
                        "description": "First drug name"
                    },
                    "drug2_name": {
                        "type": "string",
                        "description": "Second drug name"
                    }
                },
                "required": ["drug1_name", "drug2_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_resistance_landscape",
            "description": (
                "Get the full resistance landscape for a protein target — "
                "all drugs targeting that protein and their resistance mutations. "
                "Use this when asked about the treatment landscape for a target, "
                "drug generations, or overall resistance patterns for a gene."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "gene_name": {
                        "type": "string",
                        "description": "Gene symbol e.g. 'ABL1', 'EGFR'"
                    }
                },
                "required": ["gene_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_pan_resistant_mutations",
            "description": (
                "Find mutations that confer resistance across multiple drugs. "
                "These are clinically the most significant — pan-resistant mutations "
                "that are hard to treat. Use this when asked about the most important "
                "resistance mutations, treatment-refractory mutations, or mutations "
                "that affect multiple drugs."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compute_admet",
            "description": (
                "Compute physicochemical and ADMET properties for a drug from its "
                "SMILES structure using RDKit. Returns MW, logP, TPSA, HBD, HBA, "
                "rotatable bonds, and Lipinski/Veber drug-likeness rule compliance. "
                "Use this when asked about drug-likeness, oral bioavailability, "
                "or physicochemical properties of a single drug."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "drug_name": {
                        "type": "string",
                        "description": "Drug name e.g. 'Imatinib'"
                    }
                },
                "required": ["drug_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compare_admet",
            "description": (
                "Compare ADMET physicochemical properties of two drugs side by side. "
                "Returns properties for both drugs with plain-language comparison notes. "
                "Use this when asked to compare drug-likeness, bioavailability, or "
                "physicochemical profiles of two specific drugs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "drug1_name": {
                        "type": "string",
                        "description": "First drug name"
                    },
                    "drug2_name": {
                        "type": "string",
                        "description": "Second drug name"
                    }
                },
                "required": ["drug1_name", "drug2_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_drugs_by_cancer_type",
            "description": (
                "Find all drugs in the database indicated for a specific cancer type. "
                "Use this when asked about drugs for a particular cancer like colorectal, "
                "lung, leukemia, melanoma, breast cancer etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cancer_type": {
                        "type": "string",
                        "description": "Cancer type e.g. 'colorectal', 'lung cancer', 'leukemia'"
                    }
                },
                "required": ["cancer_type"]
            }
        }
    },
    
]


# Map tool name → function for the execution engine
TOOL_REGISTRY = {
    "get_drug_info":             "get_drug_info",
    "get_drug_targets":          "get_drug_targets",
    "get_resistance_mutations":  "get_resistance_mutations",
    "get_target_info":           "get_target_info",
    "search_mutations":          "search_mutations",
    "find_related_drugs":        "find_related_drugs",
    "find_shared_mutations":     "find_shared_mutations",
    "get_resistance_landscape":  "get_resistance_landscape",
    "find_pan_resistant_mutations": "find_pan_resistant_mutations",
    "compute_admet":             "compute_admet",
    "compare_admet":             "compare_admet",
}