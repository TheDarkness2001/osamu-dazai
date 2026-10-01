# Osamu Dazai — backend

Python 3.12 · Pydantic · SQLAlchemy · python-docx

## Setup

The workspace lives in OneDrive, which locks files inside a local `.venv`. Keep the
virtual environment outside the synced folder:

```bash
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/osamu_dazai"   # PowerShell: $env:UV_PROJECT_ENVIRONMENT="$HOME\.venvs\osamu_dazai"
uv sync
uv run pytest
```

## IELTS Reading tools

```bash
uv run python -m osamu_dazai.ielts validate test.docx          # IELTS document validator
uv run python -m osamu_dazai.ielts fix broken.docx fixed.docx  # IELTS Format Repair → validated DOCX (add --listening for PART N papers)
uv run python -m osamu_dazai.ielts listening out/ --config config/providers.toml --topics "…" "…" "…" "…"
uv run python -m osamu_dazai.ielts writing out/ --config config/providers.toml --module academic --task1 "…" --task2 "…"
uv run python -m osamu_dazai.ielts speaking out/ --config config/providers.toml --theme "…" --band 7
uv run python -m osamu_dazai.ielts generate test.docx --config config/providers.toml --topics "coral reefs" "the history of maps" "language learning in adults"
```

## Course design (planner → learning graph → curriculum)

```bash
uv run python -m osamu_dazai.pipeline plan "Create a beginner Python textbook for Uzbek teenagers." --config config/providers.toml --out brief.json
uv run python -m osamu_dazai.pipeline confirm brief.json --all     # after reviewing the inferred fields
uv run python -m osamu_dazai.pipeline design brief.json --config config/providers.toml --out-dir course/
```

`design` writes `course.json`, `learning_graph.json`, `learning_graph.mmd` (Mermaid concept map) and
`validation.txt`. It refuses a brief with unconfirmed fields.

## Student book

```bash
uv run python -m osamu_dazai.pipeline term kb.json variables uz "o‘zgaruvchi" --forbid variabl   # approved terminology
uv run python -m osamu_dazai.pipeline write course/ --config config/providers.toml --kb kb.json   # → student_book.md/.json
uv run python -m osamu_dazai.pipeline teach course/ --config config/providers.toml --style "project-based"  # → teacher_guide.md/.json
uv run python -m osamu_dazai.pipeline visuals course/ --config config/providers.toml   # figures → course/assets/, embedded in student_book.md
uv run python -m osamu_dazai.pipeline assess course/ --config config/providers.toml --versions 4 --code-language python
```

Diagrams (flowcharts, concept/mind maps, timelines, charts, comparisons, memory diagrams) are rendered
deterministically to SVG (plus Mermaid source); only illustrations use the image provider. Chart data
must be marked as from the text, sourced, or illustrative — illustrative charts are labelled as such.

`--execute-code` additionally runs code examples to compare their stated output (this executes AI-written
code on your machine; off by default — syntax is always checked without executing).

## AI providers

Copy `config/providers.example.toml` to `config/providers.toml`. Claude reads credentials from
`ANTHROPIC_API_KEY` (or an `ant auth login` profile); local models run through any
`/v1/chat/completions` server such as Ollama. Every stage can be routed to a different provider/model.

Live provider tests are opt-in (they cost money): `DAZAI_LIVE_TESTS=1 uv run pytest tests/test_live_providers.py`.

`samples/ielts/` (workspace root) contains a generated test, a deliberately broken copy,
the validator output, the repair report and the repaired DOCX.

## Layout

| Package | Contents |
|---|---|
| `osamu_dazai/domain` | Pydantic schemas for every entity |
| `osamu_dazai/storage` | SQLAlchemy tables, repositories, document versioning |
| `osamu_dazai/workflow` | draft → ai_validated → in_review → approved → published |
| `osamu_dazai/providers` | Claude + local LLMs, cloud/local images, Crossref/Semantic Scholar/web/local research; config-driven per-stage routing |
| `osamu_dazai/graph` | learning-graph algorithms: cycles, topological order, depth, prerequisite violations, Mermaid |
| `osamu_dazai/pipeline` | shared generate→check→feedback loop, Educational Planner, Curriculum Architect, Book Writer, Teacher Guide Writer, CLI |
| `osamu_dazai/knowledge` | terminology enforcement, Uzbek apostrophe-aware matching, chapter memory |
| `osamu_dazai/quality` | code checks: Python/JS syntax (no execution), opt-in output verification |
| `osamu_dazai/visuals` | structured visual specs, Visual Planner stage + checks, SVG layout/rendering, Mermaid, image prompts |
| `osamu_dazai/questions` | assessment blueprints + generator, question validator, seeded balanced versions (ClassBuild port) |
| `osamu_dazai/documents` | renderers (Markdown so far) |
| `osamu_dazai/ielts` | import contract, line IR, parser, validators, renderer, DOCX I/O, Format Repair, export gate; AI generators for Reading, Listening (scripts, plans), Writing (band samples), Speaking |
