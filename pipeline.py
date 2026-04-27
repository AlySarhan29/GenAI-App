"""
pipeline.py
===========
Responsibilities:
  - Connect to the SQLite database
  - Keyword extraction and expansion helpers
  - SQL LIKE condition builder
  - Multi-document retrieval from SQLite
  - CrewAI LLM, synthesis agent, and validator agent setup
  - run_engineering_pipeline_multidoc(...)
  - ask_engineering_question_multidoc(...)

Usage:
    from pipeline import ask_engineering_question_multidoc, build_agents

    synthesis_agent, validator_agent = build_agents()
    result = ask_engineering_question_multidoc(
        question="What affects transmission quality in telephone circuits?",
        db_path="engineering_knowledge_multidoc.db",
        synthesis_agent=synthesis_agent,
        validator_agent=validator_agent,
    )
    print(result["synthesis_result"])
    print(result["validation_result"])
"""


from dotenv import load_dotenv
load_dotenv()

import os
import re
import sqlite3
import logging
from pathlib import Path

from crewai import Agent, Task, Crew, Process, LLM


# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# ── Default database path ─────────────────────────────────────────────────────
DEFAULT_DB_PATH = "engineering_knowledge_multidoc.db"


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 1 — KEYWORD HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def extract_keywords(question: str) -> list[str]:
    """
    Convert a natural-language question into a list of useful content keywords.

    Steps:
      1. Lowercase and tokenize on word boundaries (keeps hyphens).
      2. Remove very common English stopwords.
      3. Remove tokens shorter than 3 characters.
      4. Deduplicate while preserving order.

    Args:
        question: The user's question string.

    Returns:
        List of keyword strings.
    """
    stopwords = {
        "what", "which", "how", "why", "when", "where", "who",
        "the", "a", "an", "is", "are", "was", "were", "be", "being", "been",
        "in", "on", "at", "to", "for", "of", "and", "or", "by", "with",
        "does", "do", "did", "affect", "affects", "impact", "impacts",
        "system", "systems",
    }

    words    = re.findall(r"[a-zA-Z0-9\-]+", question.lower())
    keywords = [w for w in words if len(w) > 2 and w not in stopwords]

    # Deduplicate while preserving insertion order
    return list(dict.fromkeys(keywords))


def expand_keywords(keywords: list[str]) -> list[str]:
    """
    Augment keyword list with domain-specific related terms.

    Currently expands transmission/telephone circuit topics.
    Add more branches here as your document collection grows.

    Args:
        keywords: Initial keyword list from extract_keywords().

    Returns:
        Expanded list of keywords (as a deduplicated list).
    """
    expanded = set(keywords)

    # Transmission / telephone circuit domain expansions
    if {"transmission", "telephone", "circuits", "circuit"} & set(keywords):
        expanded.update(["loss", "noise", "sidetone", "distortion", "loop", "trunk"])

    return list(expanded)


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 2 — SQL HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def build_like_conditions(columns: list[str], keywords: list[str]) -> tuple[str, list]:
    """
    Build a SQL WHERE fragment using LIKE for each keyword across multiple columns.

    Each keyword produces one OR-group of column LIKE checks, and those groups
    are joined by OR so that any keyword match in any column returns the row.

    Example output for columns=["t.term", "t.definition"] and keywords=["loss", "noise"]:
        "(t.term LIKE ? OR t.definition LIKE ?) OR (t.term LIKE ? OR t.definition LIKE ?)"
        params = ["%loss%", "%loss%", "%noise%", "%noise%"]

    Args:
        columns : List of fully-qualified column expressions (e.g. "t.term").
        keywords: List of keyword strings.

    Returns:
        (sql_fragment, params) tuple.
    """
    if not keywords:
        return "1=1", []

    conditions = []
    params     = []

    for kw in keywords:
        subparts = []
        for col in columns:
            subparts.append(f"{col} LIKE ?")
            params.append(f"%{kw}%")
        conditions.append("(" + " OR ".join(subparts) + ")")

    return " OR ".join(conditions), params


def query_to_dicts(conn: sqlite3.Connection, query: str, params: list = None) -> list[dict]:
    """
    Execute a SQL query and return results as a list of row dictionaries.

    Args:
        conn   : Active SQLite connection.
        query  : SQL query string.
        params : Optional list of bind parameters.

    Returns:
        List of dicts, one per result row.
    """
    if params is None:
        params = []

    cursor  = conn.cursor()
    cursor.execute(query, params)

    columns = [desc[0] for desc in cursor.description]
    rows    = cursor.fetchall()

    return [dict(zip(columns, row)) for row in rows]


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 3 — MULTI-DOCUMENT RETRIEVAL
# ══════════════════════════════════════════════════════════════════════════════

def retrieve_for_question_multidoc(
    question: str,
    db_path: str = DEFAULT_DB_PATH,
    limit_per_section: int = 15,
) -> dict:
    """
    Retrieve relevant evidence from all documents for a given question.

    Queries three tables (terms, rules, parameters) using keyword-based
    LIKE matching, joining back to the documents table for context.

    Args:
        question          : The user's question.
        db_path           : Path to the SQLite database.
        limit_per_section : Maximum rows returned per table (terms/rules/params).

    Returns:
        dict with keys:
            "question"      : original question
            "keywords_used" : expanded keyword list
            "terms"         : list of matching term rows (dicts)
            "rules"         : list of matching rule rows (dicts)
            "parameters"    : list of matching parameter rows (dicts)
    """
    keywords = extract_keywords(question)
    keywords = expand_keywords(keywords)
    log.info("Keywords used for retrieval: %s", keywords)

    conn = sqlite3.connect(Path(db_path).resolve())

    # ── Terms query ────────────────────────────────────────────────────────────
    term_columns = [
        "t.term", "t.definition", "t.context", "t.system_component",
        "d.title", "d.source", "d.engineering_domain",
    ]
    term_where, term_params = build_like_conditions(term_columns, keywords)

    term_query = f"""
    SELECT
        d.id    AS document_id,
        d.title AS document_title,
        d.source AS document_source,
        'term'  AS source_type,
        t.term  AS item_name,
        t.definition AS detail,
        t.page  AS page
    FROM terms t
    JOIN documents d ON t.document_id = d.id
    WHERE {term_where}
    ORDER BY d.title, t.page, t.term
    LIMIT {limit_per_section};
    """

    # ── Rules query ────────────────────────────────────────────────────────────
    rule_columns = [
        "r.rule_text", "r.explanation", "r.component",
        "d.title", "d.source", "d.engineering_domain",
    ]
    rule_where, rule_params = build_like_conditions(rule_columns, keywords)

    rule_query = f"""
    SELECT
        d.id      AS document_id,
        d.title   AS document_title,
        d.source  AS document_source,
        'rule'    AS source_type,
        r.rule_text AS item_name,
        r.explanation AS detail,
        r.page    AS page
    FROM rules r
    JOIN documents d ON r.document_id = d.id
    WHERE {rule_where}
    ORDER BY d.title, r.page
    LIMIT {limit_per_section};
    """

    # ── Parameters query ───────────────────────────────────────────────────────
    param_columns = [
        "p.parameter_name", "p.meaning", "p.effect",
        "d.title", "d.source", "d.engineering_domain",
    ]
    param_where, param_params = build_like_conditions(param_columns, keywords)

    param_query = f"""
    SELECT
        d.id      AS document_id,
        d.title   AS document_title,
        d.source  AS document_source,
        'parameter' AS source_type,
        p.parameter_name AS item_name,
        p.effect  AS detail,
        p.page    AS page
    FROM parameters p
    JOIN documents d ON p.document_id = d.id
    WHERE {param_where}
    ORDER BY d.title, p.page, p.parameter_name
    LIMIT {limit_per_section};
    """

    # ── Execute all three queries ──────────────────────────────────────────────
    retrieved = {
        "question"     : question,
        "keywords_used": keywords,
        "terms"        : query_to_dicts(conn, term_query,  term_params),
        "rules"        : query_to_dicts(conn, rule_query,  rule_params),
        "parameters"   : query_to_dicts(conn, param_query, param_params),
    }

    conn.close()
    log.info(
        "Retrieved — terms: %d, rules: %d, parameters: %d",
        len(retrieved["terms"]),
        len(retrieved["rules"]),
        len(retrieved["parameters"]),
    )
    return retrieved


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 4 — CREWAI LLM AND AGENTS
# ══════════════════════════════════════════════════════════════════════════════

def build_llm() -> LLM:
    """
    Create the CrewAI LLM backed by Groq.

    Requires the GROQ_API_KEY environment variable to be set.
    The model is: groq/meta-llama/llama-4-scout-17b-16e-instruct

    Returns:
        Configured LLM instance.
    """
    from dotenv import load_dotenv
    load_dotenv()  # make sure .env is loaded regardless of entry point

    api_key = os.environ.get("GROQ_API_KEY")
    # api_key = os.environ.get("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")
    if not api_key:
        raise EnvironmentError(
            "GROQ_API_KEY environment variable is not set.\n"
            "Set it with:  export GROQ_API_KEY=your_key_here"
        )

    return LLM(
        model="groq/meta-llama/llama-4-scout-17b-16e-instruct",
        temperature=0.1,
    )


def build_agents() -> tuple[Agent, Agent]:
    """
    Create and return the synthesis and validator agents.

    Both agents share the same LLM instance.

    Returns:
        (synthesis_agent, validator_agent) tuple.
    """
    llm = build_llm()

    # Agent 1: writes the answer from retrieved evidence
    synthesis_agent = Agent(
        role="Engineering Knowledge Synthesis Agent",
        goal="Turn grounded database evidence into a clear engineering answer.",
        backstory=(
            "You are a careful engineering analyst. "
            "You only use the retrieved database evidence given to you. "
            "Do not invent facts. "
            "Write a clear answer based only on the provided evidence."
        ),
        llm=llm,
        verbose=False,
    )

    # Agent 2: validates that the answer is grounded in the evidence
    validator_agent = Agent(
        role="Engineering Answer Validation Agent",
        goal=(
            "Check whether a synthesized engineering answer is fully "
            "supported by the retrieved database evidence."
        ),
        backstory=(
            "You are a strict validation agent. "
            "You compare the final answer against the retrieved evidence. "
            "You do not add new facts. "
            "You identify unsupported claims, overstatements, or mixed evidence."
        ),
        llm=llm,
        verbose=False,
    )

    return synthesis_agent, validator_agent


# ══════════════════════════════════════════════════════════════════════════════
#  SECTION 5 — PIPELINE RUNNERS
# ══════════════════════════════════════════════════════════════════════════════

def run_engineering_pipeline_multidoc(
    question: str,
    retrieved_data: dict,
    synthesis_agent: Agent,
    validator_agent: Agent,
    verbose: bool = False,
) -> dict:
    """
    Run the two-agent CrewAI pipeline on pre-retrieved evidence.

    Stage 1 — Synthesis:
        The synthesis agent writes one grounded paragraph answering the question,
        using only the retrieved evidence.

    Stage 2 — Validation:
        The validator agent checks whether every claim in the synthesis result
        is supported by the retrieved evidence.

    Args:
        question        : The user's original question.
        retrieved_data  : Output dict from retrieve_for_question_multidoc().
        synthesis_agent : CrewAI Agent for writing the answer.
        validator_agent : CrewAI Agent for validating the answer.
        verbose         : If True, CrewAI prints verbose agent logs.

    Returns:
        dict with keys:
            "question"          : original question
            "synthesis_result"  : answer string from synthesis agent
            "validation_result" : validation string from validator agent
    """

    # ── Stage 1: Synthesis ─────────────────────────────────────────────────────
    synthesis_task = Task(
        description=(
            f"Use only the retrieved database evidence below to answer the question.\n\n"
            f"Question:\n{question}\n\n"
            f"Retrieved evidence:\n{retrieved_data}\n\n"
            "Instructions:\n"
            "- Use only the retrieved evidence.\n"
            "- Do not add outside facts.\n"
            "- Write one clear paragraph.\n"
            "- Mention document titles when useful.\n"
            "- Include page numbers.\n"
            "- Return only the answer."
        ),
        expected_output="One grounded paragraph answering the question.",
        agent=synthesis_agent,
    )

    synthesis_crew  = Crew(
        agents=[synthesis_agent],
        tasks=[synthesis_task],
        process=Process.sequential,
        verbose=verbose,
    )
    synthesis_result = str(synthesis_crew.kickoff())
    log.info("Synthesis complete.")

    # ── Stage 2: Validation ────────────────────────────────────────────────────
    validation_task = Task(
        description=(
            f"Check whether this answer is fully supported by the retrieved evidence.\n\n"
            f"Retrieved evidence:\n{retrieved_data}\n\n"
            f"Answer:\n{synthesis_result}\n\n"
            "Instructions:\n"
            "- Use only the retrieved evidence.\n"
            "- Say either FULLY SUPPORTED or NOT FULLY SUPPORTED.\n"
            "- If not fully supported, list only the unsupported phrases.\n"
            "- Keep the response short."
        ),
        expected_output="A short validation result.",
        agent=validator_agent,
    )

    validation_crew  = Crew(
        agents=[validator_agent],
        tasks=[validation_task],
        process=Process.sequential,
        verbose=verbose,
    )
    validation_result = str(validation_crew.kickoff())
    log.info("Validation complete.")

    return {
        "question"         : question,
        "synthesis_result" : synthesis_result,
        "validation_result": validation_result,
    }


def ask_engineering_question_multidoc(
    question: str,
    db_path: str = DEFAULT_DB_PATH,
    synthesis_agent: Agent = None,
    validator_agent: Agent = None,
    verbose: bool = False,
) -> dict:
    """
    Full end-to-end pipeline:
        question -> SQLite retrieval -> synthesis agent -> validator agent -> result

    If synthesis_agent or validator_agent are not provided, they are built
    automatically (requires GROQ_API_KEY to be set).

    Args:
        question        : The user's engineering question.
        db_path         : Path to the SQLite database.
        synthesis_agent : Optional pre-built synthesis Agent.
        validator_agent : Optional pre-built validator Agent.
        verbose         : If True, CrewAI prints verbose logs.

    Returns:
        dict with keys:
            "question"          : original question
            "synthesis_result"  : final answer
            "validation_result" : validation verdict
            "retrieved_data"    : full retrieval dict (terms, rules, parameters)
    """
    # Build agents on-the-fly if not provided
    if synthesis_agent is None or validator_agent is None:
        synthesis_agent, validator_agent = build_agents()

    # Step 1: Retrieve evidence from the database
    retrieved_data = retrieve_for_question_multidoc(
        question=question,
        db_path=db_path,
        limit_per_section=15,
    )

    # Step 2: Run the synthesis + validation pipeline
    result = run_engineering_pipeline_multidoc(
        question=question,
        retrieved_data=retrieved_data,
        synthesis_agent=synthesis_agent,
        validator_agent=validator_agent,
        verbose=verbose,
    )

    # Attach full retrieval data so callers can display it
    result["retrieved_data"] = retrieved_data
    return result
