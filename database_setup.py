"""
database_setup.py
=================
Responsibilities:
  - Create the SQLite database schema (drops and recreates all tables)
  - Load all extracted JSON files from a folder
  - Insert documents, terms, rules, parameters, and architecture components

Usage (standalone):
    python database_setup.py

Or import and call from another module:
    from database_setup import setup_database
    setup_database(json_folder="extracted_jsons", db_path="engineering_knowledge_multidoc.db")
"""

import json
import logging
import sqlite3
from pathlib import Path

# ── Logging setup ──────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# ── Default paths (override when calling setup_database) ──────────────────────
DEFAULT_DB_PATH    = "engineering_knowledge_multidoc.db"
DEFAULT_JSON_FOLDER = "extracted_jsons"


# ── Schema DDL ────────────────────────────────────────────────────────────────

CREATE_SCHEMA_SQL = """
-- Drop child tables first to respect foreign key constraints
DROP TABLE IF EXISTS terms;
DROP TABLE IF EXISTS rules;
DROP TABLE IF EXISTS parameters;
DROP TABLE IF EXISTS architecture_components;
DROP TABLE IF EXISTS documents;

-- Core document metadata
CREATE TABLE documents (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    title              TEXT,
    authors            TEXT,
    year               TEXT,
    source             TEXT,
    engineering_domain TEXT
);

-- Technical dictionary terms extracted from each document
CREATE TABLE terms (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id      INTEGER,
    term             TEXT,
    definition       TEXT,
    context          TEXT,
    system_component TEXT,
    page             TEXT,
    FOREIGN KEY(document_id) REFERENCES documents(id)
);

-- Engineering rules extracted from each document
CREATE TABLE rules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER,
    rule_text   TEXT,
    explanation TEXT,
    component   TEXT,
    page        TEXT,
    FOREIGN KEY(document_id) REFERENCES documents(id)
);

-- Engineering parameters extracted from each document
CREATE TABLE parameters (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id    INTEGER,
    parameter_name TEXT,
    meaning        TEXT,
    effect         TEXT,
    page           TEXT,
    FOREIGN KEY(document_id) REFERENCES documents(id)
);

-- System architecture components extracted from each document
CREATE TABLE architecture_components (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id    INTEGER,
    category       TEXT,
    component_name TEXT,
    FOREIGN KEY(document_id) REFERENCES documents(id)
);
"""


# ── Insert one JSON file ───────────────────────────────────────────────────────

def insert_engineering_json(data: dict, cursor: sqlite3.Cursor, conn: sqlite3.Connection) -> int:
    """
    Insert one extracted engineering JSON file into the database.

    Expected JSON top-level keys:
        "Document Metadata"          -> dict
        "Technical Dictionary Terms" -> list of dicts
        "Engineering Rules"          -> list of dicts
        "Engineering Parameters"     -> list of dicts
        "System Architecture"        -> dict { category: [component, ...] }

    Returns:
        document_id (int) of the newly inserted document row.
    """
    metadata = data.get("Document Metadata", {})

    title   = metadata.get("Title")
    authors = ", ".join(metadata.get("Authors", [])) if metadata.get("Authors") else None
    year    = metadata.get("Year")
    source  = metadata.get("Source")
    domain  = metadata.get("Engineering Domain")

    # Insert the document metadata row first; get its auto-assigned id
    cursor.execute(
        """INSERT INTO documents (title, authors, year, source, engineering_domain)
           VALUES (?, ?, ?, ?, ?)""",
        (title, authors, year, source, domain)
    )
    document_id = cursor.lastrowid

    # ── Terms ─────────────────────────────────────────────────────────────────
    for item in data.get("Technical Dictionary Terms", []):
        cursor.execute(
            """INSERT INTO terms (document_id, term, definition, context, system_component, page)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                document_id,
                item.get("Term"),
                item.get("Definition"),
                item.get("Context"),
                item.get("System Component"),
                item.get("Page"),
            )
        )

    # ── Rules ─────────────────────────────────────────────────────────────────
    for item in data.get("Engineering Rules", []):
        cursor.execute(
            """INSERT INTO rules (document_id, rule_text, explanation, component, page)
               VALUES (?, ?, ?, ?, ?)""",
            (
                document_id,
                item.get("Rule"),
                item.get("Explanation"),
                item.get("Component"),
                item.get("Page"),
            )
        )

    # ── Parameters ────────────────────────────────────────────────────────────
    for item in data.get("Engineering Parameters", []):
        cursor.execute(
            """INSERT INTO parameters (document_id, parameter_name, meaning, effect, page)
               VALUES (?, ?, ?, ?, ?)""",
            (
                document_id,
                item.get("Parameter"),
                item.get("Meaning"),
                item.get("Effect"),
                item.get("Page"),
            )
        )

    # ── Architecture components ───────────────────────────────────────────────
    # "System Architecture" is a dict: { "category_name": ["comp1", "comp2", ...] }
    architecture = data.get("System Architecture", {})
    for category, components in architecture.items():
        for component in components:
            cursor.execute(
                """INSERT INTO architecture_components (document_id, category, component_name)
                   VALUES (?, ?, ?)""",
                (document_id, category, component)
            )

    conn.commit()
    return document_id


# ── Main setup function ────────────────────────────────────────────────────────

def setup_database(json_folder: str = DEFAULT_JSON_FOLDER, db_path: str = DEFAULT_DB_PATH):
    """
    Full database setup routine:
      1. Connect to (or create) the SQLite database file.
      2. Drop and recreate all tables from scratch.
      3. Discover all *.json files in json_folder.
      4. Insert each JSON file into the database.
      5. Print a row-count summary.

    Args:
        json_folder : Path to the folder containing extracted JSON files.
        db_path     : Path to the SQLite database file to create/overwrite.
    """
    json_folder_path = Path(json_folder).resolve()
    db_path_resolved = Path(db_path).resolve()

    log.info("Database path : %s", db_path_resolved)
    log.info("JSON folder   : %s", json_folder_path)

    # Guard: JSON folder must exist
    if not json_folder_path.exists():
        raise FileNotFoundError(
            f"JSON folder not found: {json_folder_path}\n"
            "Create the folder and place your extracted JSON files inside it."
        )

    # ── Connect and apply schema ───────────────────────────────────────────────
    conn   = sqlite3.connect(db_path_resolved)
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.executescript(CREATE_SCHEMA_SQL)
    conn.commit()
    log.info("Schema created (all tables dropped and recreated).")

    # ── Discover JSON files ────────────────────────────────────────────────────
    json_files = sorted(json_folder_path.glob("*.json"))
    log.info("JSON files found: %d", len(json_files))

    if not json_files:
        log.warning("No JSON files found in %s — database will be empty.", json_folder_path)
        conn.close()
        return

    # ── Insert each file ───────────────────────────────────────────────────────
    inserted = []
    failed   = []

    for file_path in json_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            doc_id = insert_engineering_json(data, cursor, conn)
            inserted.append((file_path.name, doc_id))
            log.info("  ✓ %s  ->  document_id=%d", file_path.name, doc_id)
        except Exception as exc:
            failed.append((file_path.name, str(exc)))
            log.error("  ✗ %s  ->  %s", file_path.name, exc)

    # ── Summary ────────────────────────────────────────────────────────────────
    log.info("\n── Insertion summary ──────────────────────────────────")
    log.info("  Successful : %d / %d", len(inserted), len(json_files))
    if failed:
        log.warning("  Failed     : %d", len(failed))
        for name, err in failed:
            log.warning("    %s -> %s", name, err)

    log.info("\n── Row counts per table ───────────────────────────────")
    for table in ["documents", "terms", "rules", "parameters", "architecture_components"]:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        log.info("  %-32s %d rows", table, count)

    conn.close()
    log.info("\nDatabase ready: %s", db_path_resolved)


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    setup_database(
        json_folder=DEFAULT_JSON_FOLDER,
        db_path=DEFAULT_DB_PATH,
    )
