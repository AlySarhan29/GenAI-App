"""
app.py
======
Streamlit application for the Engineering Knowledge Pipeline.

Responsibilities:
  - Load the pipeline (agents + database path)
  - Accept a user question via text input
  - Run the full multi-document pipeline on submit
  - Display: final answer, validation result, and retrieved evidence
  - Show errors clearly if something fails

Run with:
    streamlit run app.py
"""

from dotenv import load_dotenv
load_dotenv()

import os
print("DEBUG KEY:", os.environ.get("GROQ_API_KEY", "NOT FOUND"))
import streamlit as st
from pathlib import Path

from pipeline import ask_engineering_question_multidoc, build_agents
from database_setup import setup_database


# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Engineering Knowledge Assistant",
    page_icon="⚙️",
    layout="wide",
)

# ── Constants ─────────────────────────────────────────────────────────────────
DB_PATH    = "engineering_knowledge_multidoc.db"
JSON_FOLDER = "extracted_jsons"


# ── Helper: cache agents so they are only built once per session ───────────────
@st.cache_resource(show_spinner="Loading AI agents…")
def get_agents():
    """
    Build and cache the CrewAI synthesis + validator agents.
    Cached with st.cache_resource so they survive re-runs.
    """
    return build_agents()


# ── Helper: format retrieved evidence for display ─────────────────────────────
def render_evidence_section(title: str, rows: list[dict], icon: str = "📄"):
    """
    Render one evidence section (terms / rules / parameters) inside an expander.
    """
    label = f"{icon} {title}  ({len(rows)} result{'s' if len(rows) != 1 else ''})"
    with st.expander(label, expanded=False):
        if not rows:
            st.info("No matches found for this category.")
            return
        for i, row in enumerate(rows, start=1):
            doc_label = row.get("document_title", "Unknown document")
            page_label = f"p. {row['page']}" if row.get("page") else ""
            header = f"**{i}. {row.get('item_name', '—')}**"
            if page_label:
                header += f"  ·  {page_label}"
            st.markdown(header)
            if row.get("detail"):
                st.markdown(f"> {row['detail']}")
            st.caption(f"Source: *{doc_label}*")
            if i < len(rows):
                st.divider()


# ══════════════════════════════════════════════════════════════════════════════
#  SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.title("⚙️ Engineering Assistant")
    st.markdown(
        "Ask questions grounded in historical engineering documents stored "
        "in your local SQLite knowledge base."
    )
    st.divider()

    # ── Database status ────────────────────────────────────────────────────────
    st.subheader("Database")
    db_exists = Path(DB_PATH).exists()
    if db_exists:
        st.success(f"✅ `{DB_PATH}` found")
    else:
        st.warning(f"⚠️ `{DB_PATH}` not found")

    # ── Setup button ───────────────────────────────────────────────────────────
    if st.button("🔄 (Re)build database from JSONs", use_container_width=True):
        with st.spinner("Building database…"):
            try:
                setup_database(json_folder=JSON_FOLDER, db_path=DB_PATH)
                st.success("Database built successfully.")
                st.rerun()
            except FileNotFoundError as exc:
                st.error(str(exc))
            except Exception as exc:
                st.error(f"Database setup failed: {exc}")

    st.divider()

    # ── GROQ API key status ────────────────────────────────────────────────────
    st.subheader("API Key")
    if os.environ.get("GROQ_API_KEY"):
        st.success("✅ GROQ_API_KEY is set")
    else:
        st.error("❌ GROQ_API_KEY is not set")
        st.code("export GROQ_API_KEY=your_key_here", language="bash")

    st.divider()
    st.caption("Model: `groq/meta-llama/llama-4-scout-17b-16e-instruct`")
    st.caption("Framework: CrewAI · SQLite · Streamlit")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN PAGE
# ══════════════════════════════════════════════════════════════════════════════

st.title("Engineering Knowledge Assistant")
st.markdown(
    "Type an engineering question below. "
    "The system will retrieve relevant evidence from the database and generate a grounded answer."
)

# ── Question input ─────────────────────────────────────────────────────────────
question = st.text_area(
    label="Your question",
    placeholder="e.g. What affects transmission quality in telephone circuits?",
    height=100,
    key="question_input",
)

run_button = st.button("🔍 Ask", type="primary", use_container_width=False)

# ── Run pipeline ───────────────────────────────────────────────────────────────
if run_button:

    # ── Input guards ───────────────────────────────────────────────────────────
    if not question.strip():
        st.warning("Please enter a question before clicking Ask.")
        st.stop()

    if not Path(DB_PATH).exists():
        st.error(
            f"Database `{DB_PATH}` not found. "
            "Use the **Rebuild database** button in the sidebar first."
        )
        st.stop()

    if not os.environ.get("GROQ_API_KEY"):
        st.error(
            "GROQ_API_KEY is not set. "
            "Set it in your terminal before launching the app:\n\n"
            "```bash\nexport GROQ_API_KEY=your_key_here\n```"
        )
        st.stop()

    # ── Run ────────────────────────────────────────────────────────────────────
    with st.spinner("Retrieving evidence and running agents…"):
        try:
            synthesis_agent, validator_agent = get_agents()

            result = ask_engineering_question_multidoc(
                question=question.strip(),
                db_path=DB_PATH,
                synthesis_agent=synthesis_agent,
                validator_agent=validator_agent,
                verbose=False,
            )
        except Exception as exc:
            st.error(f"Pipeline error: {exc}")
            st.stop()

    retrieved = result["retrieved_data"]

    # ── Keywords used ──────────────────────────────────────────────────────────
    with st.expander("🔑 Keywords used for retrieval", expanded=False):
        st.write(retrieved.get("keywords_used", []))

    st.divider()

    # ── Final answer ───────────────────────────────────────────────────────────
    st.subheader("📝 Answer")
    st.markdown(result["synthesis_result"])

    st.divider()

    # ── Validation result ──────────────────────────────────────────────────────
    st.subheader("✅ Validation")
    validation_text = result["validation_result"]

    if "NOT FULLY SUPPORTED" in validation_text.upper():
        st.warning(validation_text)
    elif "FULLY SUPPORTED" in validation_text.upper():
        st.success(validation_text)
    else:
        # Neutral display for other responses
        st.info(validation_text)

    st.divider()

    # ── Retrieved evidence ─────────────────────────────────────────────────────
    st.subheader("🗄️ Retrieved Evidence")

    render_evidence_section("Terms",      retrieved.get("terms",      []), icon="📘")
    render_evidence_section("Rules",      retrieved.get("rules",      []), icon="📏")
    render_evidence_section("Parameters", retrieved.get("parameters", []), icon="📐")
