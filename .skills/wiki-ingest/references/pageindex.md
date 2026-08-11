# Large-document preprocessing

Structure-aware navigation for large documents (>50 KB by default) before distilling
them into wiki pages. Instead of reading a 300-page book or 80 KB log file linearly into
context, build a **structure map** first, reason over it, then read only the sections
that matter.

## When to use it

Use this branch when **all** hold (otherwise read the document directly):
- `PAGEINDEX_REPO` is set in config.
- The source file is **≥ `PAGEINDEX_MIN_SIZE_KB`** KB (default **50**, configurable in `.env`). Check with:
  ```bash
  stat --printf="%s" "$file" | awk '{printf "%.0f", $1/1024}'
  ```
  macOS fallback:
  ```bash
  stat -f%z "$file" | awk '{printf "%.0f", $1/1024}'
  ```

If `PAGEINDEX_REPO` is unset, the repo is missing, or any step errors, **fall back** to
reading the document directly. Never block an ingest on this step.

## Step 1 — Build the structure map

Choose the extraction method by file extension:

### PDF (`.pdf`)

PageIndex builds a table-of-contents tree via LLM. It runs from its own repo +
venv and calls an LLM via LiteLLM (configured in `$PAGEINDEX_REPO/.env`):

```bash
cd "$PAGEINDEX_REPO"
set -a; source .env; set +a
uv run --no-project python run_pageindex.py \
  --pdf_path "<absolute-path-to.pdf>" \
  --model "${PAGEINDEX_MODEL:-openai/glm-4.6}" \
  --if-add-node-summary yes --if-add-doc-description yes
```

Output: `$PAGEINDEX_REPO/results/<pdfname>_structure.json`. Shape:

```json
{
  "doc_name": "saussure1916",
  "doc_description": "One-paragraph overview of the whole document.",
  "structure": [
    {"title": "Part One: General Principles", "node_id": "0007",
     "start_index": 65, "end_index": 98, "summary": "…",
     "nodes": [ {"title": "Nature of the Sign", "start_index": 65, "end_index": 70, "summary": "…"} ]}
  ]
}
```
`start_index`/`end_index` are **1-indexed physical PDF pages**.

### Markdown (`.md`)

Parse headings (`#`, `##`, `###`) to extract the TOC. Read only the heading lines
(cheap — grep, don't read the whole file) to build a structure map, then read
only relevant sections by heading:

```bash
grep -n '^#' "$file" | head -80
```

For each heading line `N:## Title`, the section runs from line N to the next
heading (or EOF). Read with the **Read tool**: `Read offset: N-1 limit: M-N`.

### Plain text / log / transcript (`.txt`, `.log`, `.json`, `.jsonl`, `.csv`)

Sample the document to understand its shape without reading the whole thing:

```bash
# First 80 lines + last 20 lines for structure
head -n 80 "$file"; echo "=== ... ==="; tail -n 20 "$file"
# Line count
wc -l "$file"
```

Then read in chunks with the **Read tool** (`offset + limit`), focusing on the
portions relevant to the ingest topic. Skip repetitive sections (repeated log
patterns, JSON array boilerplate) — sample every Nth record for structured data.

### Chat exports (`.json`, `.jsonl`)

For conversation history files, extract the list of conversation titles/topics
without loading the full bodies:

```bash
# ChatGPT export: list conversation titles
python3 -c "
import json, sys
data = json.load(open(sys.argv[1], encoding='utf-8'))
for entry in data:
    print(entry.get('title', '(untitled)'))
" "$file"
```

Then pick the relevant conversations and read only those with the Read tool.

### Code repos (directory)

Use `obsidian-wiki ast-extract` (Step 1c) — it already handles large directories
without reading source files into context.

## Step 2 — Reason, then read only what matters

1. Review the structure map (TOC, sample headers, conversation titles) to map the document.
2. Pick the sections relevant to the wiki (skip front-matter, indices, boilerplate).
3. For each chosen section, read the source with the **Read tool** targeting only
   that range (page range for PDF, line offset for text, specific conversation for JSON).
4. Distill those sections into wiki pages per the normal Step 2–5 flow. **Cite
   section title + location** in claims (e.g. "Saussure, *Cours*, Part One ch. 1,
   pp. 65–70" or "`server.log`, lines 3240–3312").

## Configuration

| Variable | Default | Description |
|---|---|---|
| `PAGEINDEX_MIN_SIZE_KB` | `50` | Minimum file size in KB to trigger large-doc preprocessing |
| `PAGEINDEX_REPO` | *(unset)* | Path to PageIndex repo (required for PDF TOC extraction) |
| `PAGEINDEX_MODEL` | `openai/glm-4.6` | LiteLLM model for PageIndex summaries |
| `PAGEINDEX_WORKSPACE` | `$PAGEINDEX_REPO/results` | Output directory for `_structure.json` |

## Notes

- Cache: `_structure.json` persists — re-ingesting the same PDF can reuse it (skip Step 1
  if the JSON already exists and the PDF is unchanged).
- Cost/runtime scales with document size; a full book is minutes of LLM calls.
- Record the produced pages in the manifest as usual; note `source_type: "document"`.
- For non-PDF documents, the structure map is cheap (grep/head/tail/parse) — no LLM
  calls until you actually read the selected sections.
