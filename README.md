# Engineering Knowledge Assistant

> Developing systems engineering rules and technical dictionaries using LLMs
> and historical engineering documents.

---

## Folder structure

```
your_project/
│
├── app.py                              ← Streamlit UI
├── pipeline.py                         ← Retrieval + CrewAI agents
├── database_setup.py                   ← Schema creation + JSON loader
├── requirements.txt                    ← Python dependencies
│
├── extracted_jsons/                    ← ⬅ PUT YOUR JSON FILES HERE
│   ├── paper_001.json
│   ├── paper_002.json
│   └── ...
│
└── engineering_knowledge_multidoc.db   ← Created automatically by setup
```

---

## Step-by-step: running the app locally

### 1. Create and activate a virtual environment

```bash
python -m venv venv
source venv/bin/activate        # macOS / Linux
venv\Scripts\activate           # Windows
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Set your Groq API key

**macOS / Linux:**
```bash
export GROQ_API_KEY=your_groq_api_key_here
```

**Windows (Command Prompt):**
```cmd
set GROQ_API_KEY=your_groq_api_key_here
```

**Windows (PowerShell):**
```powershell
$env:GROQ_API_KEY = "your_groq_api_key_here"
```

> ⚠️ Never hardcode the key in any source file. Always set it as an
> environment variable before launching the app.

### 4. Place your extracted JSON files

Copy all your structured JSON files into the `extracted_jsons/` folder:

```
extracted_jsons/
├── paper_001.json
├── paper_002.json
└── ...
```

Each JSON file must follow this structure:

```json
{
  "Document Metadata": {
    "Title": "...",
    "Authors": ["Author A", "Author B"],
    "Year": "1950",
    "Source": "...",
    "Engineering Domain": "..."
  },
  "Technical Dictionary Terms": [
    { "Term": "...", "Definition": "...", "Context": "...",
      "System Component": "...", "Page": "3" }
  ],
  "Engineering Rules": [
    { "Rule": "...", "Explanation": "...", "Component": "...", "Page": "5" }
  ],
  "Engineering Parameters": [
    { "Parameter": "...", "Meaning": "...", "Effect": "...", "Page": "7" }
  ],
  "System Architecture": {
    "Category Name": ["Component A", "Component B"]
  }
}
```

### 5. Build the database (first time only)

```bash
python database_setup.py
```

This will:
- Create `engineering_knowledge_multidoc.db`
- Load every JSON file from `extracted_jsons/`
- Print a row-count summary per table

You only need to re-run this when you add new JSON files.

### 6. Launch the Streamlit app

```bash
streamlit run app.py
```

Open your browser at: **http://localhost:8501**

---

## Using the app

1. The **sidebar** shows database and API key status.
2. Use the **"Rebuild database"** button in the sidebar to reload JSON files
   at any time without leaving the browser.
3. Type your question in the text area and click **Ask**.
4. The app shows:
   - **Answer** — a grounded paragraph from the synthesis agent
   - **Validation** — FULLY SUPPORTED / NOT FULLY SUPPORTED verdict
   - **Retrieved Evidence** — expandable sections for Terms, Rules, Parameters

---

## Re-running with new documents

1. Add new JSON files to `extracted_jsons/`.
2. Click **Rebuild database** in the sidebar, or run `python database_setup.py`.
3. Ask your question — the new documents are now searchable.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `GROQ_API_KEY is not set` | Run `export GROQ_API_KEY=...` before `streamlit run app.py` |
| `Database not found` | Click **Rebuild database** in the sidebar |
| `JSON folder not found` | Create the `extracted_jsons/` folder and add JSON files |
| `No results returned` | Check that your JSON files have the expected keys |
| `crewai` import error | Run `pip install -r requirements.txt` again |
