# Osamu Dazai — Architecture

Status: Phase 2 draft (proposed; not yet implemented)
Date: 2026-09-29
Companion documents: `REPOSITORY_AUDIT.md`, `../THIRD_PARTY_NOTICES.md`

---

## 0. Identity

- **Product name:** **Osamu Dazai** (repository `osamu-dazai`, Python package `osamu_dazai`). The tagline is "Educational publishing engine".
- The name lives in exactly one place (`osamu_dazai/branding.py`). Display text elsewhere reads it from there or from `/api/config`.
- Osamu Dazai is created by **TechRen Academy** (credited on the website and README, linking to www.techrenacademy.com). It is its own product with its own name and codebase: it is **not** the TechRen platform, REN AI or any REN-branded product, and it shares no code or database with them.
- TechRen appears only as an optional **exporter plugin** (§14), loaded through a plugin entry point. The core never imports it.

---

## 1. Design principles

1. **A structured publishing engine, not a chat wrapper.** Each stage has a typed input and a typed output (Pydantic models). The LLM fills in structured fields and never returns "one giant text".
2. **Determinism wherever correctness matters.** Parsing, numbering, validation, rendering, the learning-graph checks and IELTS layout are all plain code. The LLM *proposes*; deterministic code *checks* and *renders*.
3. **Every artifact is data first, documents second.** The canonical form is JSON in the database. DOCX, PDF, HTML and Markdown are renderings of it.
4. **Provenance on every block:** `source_backed | ai_generated | teacher_authored | user_provided | imported`. We never fabricate sources, and a source that cannot be verified is marked `unverified`.
5. **Humans approve.** Nothing reaches `published` without passing through `human_review`.
6. **Language is a parameter.** English, Uzbek and Russian from day one. Explanation, terminology and assessment languages are configured separately.
7. **Imported content is sacred.** The importer and fixer change *structure*, never wording. Any wording change becomes a review flag.
8. **Providers can be swapped.** There is no hard dependency on any single AI vendor.

---

## 2. Technology stack

| Layer | Choice | Why |
|---|---|---|
| Core and back end | Python 3.12, **FastAPI**, **Pydantic v2** | Best DOCX/PDF tooling; typed schemas become the API contract |
| Persistence | SQLAlchemy 2 + Alembic; SQLite (development) → PostgreSQL (production) | Relational entities, versioning, JSONB for content trees |
| Jobs | A simple DB-backed job queue at first (`GenerationJob` table plus worker); can move to Arq/Celery later | Generation is long-running and must survive restarts |
| DOCX | `python-docx` (MIT) plus direct OOXML access for validation | Full control over paragraphs; no automatic numbering |
| PDF out | LibreOffice headless (DOCX → PDF) | The PDF matches the DOCX exactly |
| PDF in | `pdfplumber` (MIT) / `pypdf` (BSD) | Avoids AGPL PyMuPDF |
| HTML / Markdown | Jinja2 templates of our own; `markdown-it-py` | |
| Diagrams | Mermaid (rendered with `mermaid-cli` when an image is needed) plus our own SVG builders | Deterministic |
| Front end | React + TypeScript + Vite; TanStack Query; a component library of our own | Independent UI |
| Packaging | `uv` (Python), `pnpm` (web) | |
| Tests | pytest, hypothesis (for parser/fixer property tests), Playwright (E2E) | |

---

## 3. Repository layout (proposed)

```
Writer/                          ← workspace root (becomes the Osamu Dazai repo)
├── docs/                        ← ARCHITECTURE, REPOSITORY_AUDIT, specs
├── THIRD_PARTY_NOTICES.md
├── reference/                   ← the six downloaded repos moved here later; git-ignored; never imported
├── backend/
│   ├── pyproject.toml
│   └── osamu_dazai/
│       ├── branding.py
│       ├── domain/              ← Pydantic schemas (§5)
│       ├── storage/             ← ORM models, repositories, versioning (§11)
│       ├── providers/           ← llm/, image/, research/ (§6)
│       ├── pipeline/            ← stage agents and orchestrator (§7)
│       │   ├── stages/          ← planner, curriculum, graph, research, writer, visual,
│       │   │                      exercises, assessment, teacher_guide, formatter, qc, publisher
│       │   └── prompts/         ← versioned prompt templates (prompt_version tracked)
│       ├── knowledge/           ← terminology and consistency knowledge base (§8)
│       ├── graph/               ← learning-graph algorithms (§7.3)
│       ├── visuals/             ← VisualSpec → Mermaid/SVG/image (§7.6)
│       ├── questions/           ← general question and assessment model
│       ├── ielts/               ← IELTS module (§10)
│       │   ├── model.py         ← IELTSTest, Passage, QuestionGroup, typed question blocks
│       │   ├── contract.py      ← the import-contract rules as data (regexes, headings)
│       │   ├── lines.py         ← line-level IR shared by parser, validator, fixer, renderer
│       │   ├── parser.py        ← deterministic parser (mirrors the external parser)
│       │   ├── validators/      ← IELTSQuestionNumberValidator, IELTSDocumentValidator, ...
│       │   ├── fixer/           ← IELTS Format Repair
│       │   ├── generator/       ← LLM stages for passages and questions
│       │   └── render.py        ← model → line IR → DOCX
│       ├── documents/           ← DocumentTemplateEngine, renderers (§9)
│       ├── importers/           ← docx, pdf, txt, md → ImportedDocument (§12)
│       ├── validation/          ← rule framework, ValidationResult (§13)
│       ├── workflow/            ← review states and transitions
│       ├── plugins/             ← entry-point loader; techren exporter lives outside the core
│       └── api/                 ← FastAPI routers
├── web/                         ← React front end (§15)
└── tests/
    ├── fixtures/ielts/          ← good and deliberately broken documents
    └── ...
```

---

## 4. End-to-end flow

```
User idea / imported document
      │
      ▼
[1] Educational Planner ──► CourseBrief (inferred or asked: age, level, duration, languages, style…)
      ▼
[2] Curriculum Architect ─► Curriculum (objectives, modules, lessons, outcomes, assessment plan)
      ▼
[3] Learning Graph ───────► ConceptGraph (DAG) ── deterministic checks (cycles, orphans, order)
      ▼
[4] Research Agent ───────► SourceDossier per chapter (verified or unverified sources)
      ▼
[5] Content Writer ───────► StudentChapter blocks (graph-constrained, terminology-constrained)
      ▼
[6] Visual Planner ───────► VisualSpec[] → rendered Visual/Image
      ▼
[7] Exercise Generator ───► Exercise[] / Project[]
      ▼
[8] Assessment Generator ─► QuestionGroup[] / Assessment / AnswerKey / Rubric
      ▼
[9] Teacher Guide ────────► TeacherLesson[] (timing, misconceptions, expected answers…)
      ▼
[10] Document Formatter ──► DocModel (renderer-neutral document tree)
      ▼
[11] Quality Control ─────► ValidationResult[]  (blocking errors stop export)
      ▼
[12] Publisher ───────────► DOCX / PDF / HTML / MD / JSON (+ plugins)
```

Each stage is a class that implements

```python
class Stage(Protocol[In, Out]):
    name: str
    prompt_version: str
    async def run(self, inp: In, ctx: StageContext) -> StageResult[Out]
```

`StageContext` carries the project, the knowledge base, the providers, the language settings and the job logger. `StageResult` carries the output, token and cost usage, provenance and warnings. The orchestrator stores every stage output as a versioned record, so any stage can be re-run on its own ("regenerate chapter 4 exercises only").

---

## 5. Core domain schema (Phase 3)

These are the entities from spec §37, stored relationally. Rich content trees are stored as JSON.

```
Project ─┬─ Course ─┬─ Module ── Lesson ── (LessonObjective)
         │          ├─ ConceptGraph ── Concept ── edges(prerequisite)
         │          ├─ StudentBook ── Chapter ── Section ── Block
         │          ├─ TeacherGuide ── TeacherLesson
         │          └─ Assessment ── QuestionGroup ── Question ── Answer
         ├─ KnowledgeBase (Term, StyleRule, Decision, ChapterSummary)
         ├─ Source
         ├─ Visual / Image
         ├─ Document ── DocumentVersion
         ├─ GenerationJob
         └─ ValidationResult
```

Key fields (abridged):

- **Concept**: `id, name, description, difficulty(1–5), prerequisites[Concept.id], learning_objectives[LO.id], related_concepts[], chapters[], assessment_items[], taxonomy_group, bloom_levels[]`
- **LearningObjective**: `id, text, bloom_level, concept_ids[], measurable_verb, language`
- **Block** (the content unit): `id, kind (heading|paragraph|example|code|callout|visual_ref|exercise_ref|list|table|equation), content, lang, provenance, source_ids[], concept_ids[], status`
- **Question**: `id, number | number_range, type, stem, options[], answer(s), alternatives[], word_limit, concept_ids[], bloom_level, difficulty, explanation`
- **Image**: `image_id, chapter_id, section_id, concept_ids[], purpose, prompt, provider, model, filename, width, height, alt_text, created_at, provenance`
- **Source**: `id, kind (doi|url|book|user_file), citation, doi, url, verified(bool), verified_via (crossref|semantic_scholar|manual|none), accessed_at`
- **DocumentVersion**: `document_version, created_at, changed_by, generation_model, generation_prompt_version, source_version, validation_status, content_hash, snapshot(json)`

The student book is **not** forced into one chapter template. `ChapterPlan.section_plan` is produced per chapter from a *palette* of section types (objectives, introduction, explanation, worked example, visual explanation, guided practice, independent practice, common mistakes, challenge, mini project, review, quiz, homework). The writer chooses and orders sections to suit the subject. QC only enforces a small required set (objectives, at least one practice item, review).

---

## 6. Provider abstraction

```python
class LLMProvider(ABC):
    async def complete(self, req: LLMRequest) -> LLMResponse          # messages, system, temperature
    async def structured(self, req: LLMRequest, schema: type[T]) -> T # JSON-schema-constrained output
    capabilities: ProviderCaps                                        # context, tools, vision, json_mode

CloudProvider    # adapters: anthropic, openai, google — each a small class, selected by config
LocalProvider    # Ollama / llama.cpp / vLLM (OpenAI-compatible HTTP)
MockProvider     # deterministic fixtures keyed by (stage, prompt hash); used in all unit tests

class ImageProvider(ABC):  generate(ImageRequest) -> ImageResult
    CloudImageProvider / LocalImageProvider (e.g. ComfyUI, SD WebUI) / MockImageProvider (placeholder PNG)

class ResearchProvider(ABC):  search(query) -> list[SourceCandidate];  verify(Source) -> Verification
    WebResearchProvider   # web search + Crossref / Semantic Scholar / Unpaywall verification
    LocalResearchProvider # user-uploaded PDFs/DOCX, indexed locally
```

- Model routing is configured per stage (`config/models.yaml`). For example, the planner can use a strong model and the glossary a cheap one.
- `structured()` validates against the Pydantic schema and retries with the validation error fed back, up to N times. After that it fails loudly; it never "best-effort parses".
- Each call is logged with provider, model, prompt_version and token usage in `GenerationJob`.

---

## 7. Educational engines

### 7.1 Educational Planner (Phase 4)
Input: free text (for example "beginner Python textbook for Uzbek teenagers") and any answers already given. Output: a `CourseBrief` in which every field records whether it was *inferred* or *confirmed*. Before generation starts, the UI shows the inferred fields for confirmation (age, level, duration, frequency, languages, book length, teaching style).

### 7.2 Curriculum Architect (Phase 4)
`CourseBrief → Curriculum`: course objectives, modules, lessons (sized to duration × frequency), outcomes, projects, review points and the assessment plan. Deterministic checks: the lesson count matches the schedule; every outcome is assessed at least once; review points are spaced out.

### 7.3 Learning Graph (Phase 5)
The LLM proposes concepts and prerequisite edges. `osamu_dazai.graph` then enforces:
- the graph is a DAG (cycle detection, and the offending cycle is reported);
- no orphans; no unreachable concepts;
- a topological order exists that is consistent with the chapter order. **A chapter may only use concepts whose prerequisites were introduced in the same or an earlier chapter.** This is the "prerequisite violation" check;
- duplicate or near-duplicate concepts (normalised name plus embedding similarity);
- difficulty grows monotonically along edges (a warning, not an error).

The Content Writer receives `allowed_concepts` (introduced so far) and `new_concepts` (to introduce in this chapter). QC scans the generated text for concepts from the graph that appear *before* their chapter.

### 7.4 Book generator / Content Writer (Phase 6)
Generation is hierarchical: book outline → chapter plan → section drafts. Each call receives the TOC plus its position in it, the terminology constraints and chapter summaries of earlier chapters. After each chapter, a summary is written back to the knowledge base.

### 7.5 Teacher Guide (Phase 7)
The generator takes the *student chapter* and the lesson plan as input and must produce only teacher-facing value: timing, preparation, resources, sequence, demonstrations, questions *with expected answers*, misconceptions, differentiation (support/extend), assessment and homework keys. QC checks n-gram overlap with the student book and flags a guide that copies more than a threshold of it.

### 7.6 Visual system (Phase 8)
1. The Visual Planner reads each section and outputs a `VisualSpec` only where a visual is *justified*. `VisualSpec` holds kind, purpose, `concept_ids`, data, and `render_strategy ∈ {mermaid, svg_template, chart, image_gen}`.
2. Deterministic renderers handle flowcharts, concept and mind maps, timelines, process and comparison diagrams, and charts. Image generation is used only for illustrative scenes.
3. Every visual is linked to concepts and a section, has alt text in the explanation language, and is recorded as a `Visual`/`Image` row.

### 7.7 Questions and assessments (Phase 9)
A general question model shared by quizzes, exams, worksheets and homework. It includes seeded version shuffling and answer-position balancing (ported from classbuild under MIT; see THIRD_PARTY_NOTICES), rubrics, and Bloom's-level distribution targets. Where possible, programming questions are executed in a sandbox (Python/JS subprocess with a timeout) to check syntax and expected output.

---

## 8. Knowledge base and consistency

- **Term**: `canonical_key, lang, preferred, forbidden_variants[], definition, first_introduced_chapter, approved_by`. For example, `variable` → uz: "o'zgaruvchi".
- **StyleRule**: tone, register, reading level, notation (for example the decimal separator), code style.
- **Decision**: a log of curriculum decisions ("recursion is omitted at this level").
- **Enforcement**: prompts receive the approved term table, and a deterministic post-check scans the output for forbidden variants and untranslated terms, then raises QC warnings with suggested fixes.

---

## 9. Document system (Phase 12)

```
Domain objects ──► DocModel (renderer-neutral tree) ──► Renderer
                                                         ├─ DocxRenderer   (DocumentTemplateEngine)
                                                         ├─ HtmlRenderer   (Jinja2)
                                                         ├─ MarkdownRenderer
                                                         ├─ JsonRenderer   (the domain JSON itself)
                                                         └─ PdfRenderer    (DOCX → LibreOffice → PDF)
```

**DocumentTemplateEngine** (DOCX) is configured with a `DocTemplate`: page size, margins, fonts per language/script, heading styles, spacing, header, footer, page numbers, page-break rules, table styles, image sizing and captions.

**IELTS profile:** `DocTemplate(profile="ielts_parser_safe")` uses plain paragraphs only. It has **no automatic numbering, no list styles, no fields, no text boxes, no tables for question content**, and every logical line is one `w:p`. Visual decoration is sacrificed for parser compatibility (spec §35).

Future renderers: PPTX, SCORM, LMS packages, and EPUB.

---

## 10. IELTS module (Phases 10–11) — the critical path

### 10.1 One contract, four consumers

`ielts/contract.py` encodes the import contract (spec §§17–31) **as data**: header regexes, instruction keywords, answer-key headings, blank markers, word-limit phrases. Four components use this same contract:

```
               ┌─────────── contract.py ───────────┐
               ▼            ▼            ▼          ▼
         render.py     parser.py    validators/   fixer/
     (model → lines)  (lines → model) (lines + model) (bad lines → good lines)
```

The **line IR** (`lines.py`) is a list of `Line(text, source_ref, paragraph_index, run_info)`. DOCX export writes exactly one paragraph per Line. DOCX validation reads the file back with python-docx and rebuilds the Line list from `w:p` elements, checking `w:numPr` (automatic numbering) and `w:br` (soft breaks that could glue two questions into one paragraph).

### 10.2 Model

```
IELTSTest(kind=academic|general, module=reading|listening|writing|speaking)
  └─ Passage(n, title, paragraphs[labelled A..], source/provenance)
       └─ QuestionGroup(range=(start,end), type, instructions[], word_limit?, options_list?, heading_list?)
            └─ items: Question(n, ...) | CompoundQuestion(range, choose=2|3, options) | CompletionItem(n, text_with_blank)
AnswerKey: {n | "a-b": [answers], alternatives via "|"}
```

The question types are an enum that covers every type in spec §15 (Reading and Listening). For each type we define instruction keywords, item line grammar, answer grammar and whether auto-detection is safe. **Matching Information is `auto_detect_safe = False`** unless an explicit option list is present (spec §27).

### 10.3 Deterministic parser
A line-oriented state machine: `PREAMBLE → PASSAGE_HEADER → PASSAGE_TITLE → PASSAGE_BODY → QUESTIONS_HEADER → INSTRUCTIONS → ITEMS → … → ANSWER_KEY`. It is written to mirror the external fixed-rule parser. If our parser can round-trip a document, the external one should too. Everything after an `ANSWER KEY | ANSWERS KEY | Answer Sheet | Complete answer sheet` line is excluded from question parsing.

### 10.4 Validators

`IELTSQuestionNumberValidator`
- **glued numbers**: inside a line that belongs to question *n*, it finds a token matching `(?<=[\s.?!…"')])(n+1)[.)]?\s+[A-Z"']`. The *expected next number* is the anchor, which keeps false positives rare (for example "13 cars" in a passage is ignored because we only look inside question lines and only for the expected number);
- missing, duplicate and out-of-order numbers, over the whole test and within each group;
- `Questions a–b` ranges that do not match the items found (compound blocks count as their full range);
- a number embedded in the previous question's text;
- automatic Word numbering (`w:numPr`) and soft line breaks inside question paragraphs.

`IELTSDocumentValidator` runs the full checklist in spec §32, including the number validator. It emits `ValidationIssue(code, severity, location{passage, group, question, line, paragraph_index}, problem, expected, suggestion)`.

**Export gate:** `IELTSExporter.export()` renders, reads its own DOCX back, re-parses and re-validates it. Any `severity=error` raises `ExportBlocked(issues)`, and the UI shows ERROR / Location / Problem / Expected structure / Suggested correction.

### 10.5 IELTS Format Repair (fixer)
Pipeline (spec §33):
1. Import DOCX/TXT/PDF → Line IR (the text is preserved byte for byte).
2. Segment passages, question groups and the answer key using the contract.
3. **Structural repairs only**, each recorded as a `RepairOp` (`split_line_at(offset)`, `move_to_own_line`, `strip_auto_numbering(→ literal text)`, `join_soft_break`, `normalize_range_dash`), with a `confidence` score and a reason.
4. High-confidence ops are applied. Low-confidence ops become `ReviewFlag`s and are **not** applied.
5. An invariant is checked after the fixer runs: `normalize_ws(original_text) == normalize_ws(fixed_text)`. Removing whitespace and newlines from both must give identical character sequences, so any content change is detectable. If it fails, the fixer aborts and flags the problem.
6. Type detection per group; the answer key is built only from answers present in the source.
7. The validator runs, and the result is exported as a corrected DOCX plus a repair report (a diff with every op and flag).

Where it is used, the LLM only *suggests* ambiguous split points and group types. Its suggestions go through the same confidence gate and the same text-preservation invariant.

### 10.6 IELTS generation
The generator creates passages (with provenance), then groups by type, then the answer key, all as `IELTSTest` JSON. Rendering is always deterministic. Writing and Speaking have their own models: task prompts, sample responses tagged by band, and assessment criteria (TR/TA, CC, LR, GRA; FC, LR, GRA, P) with teacher feedback templates.

---

## 11. Versioning

Every `Document` has an append-only history of `DocumentVersion` rows (fields in §5). Restoring a version creates a *new* version that copies the old snapshot; history is never rewritten. Stage outputs are versioned the same way, so "which prompt version produced chapter 3?" is always answerable.

## 12. Import

`DOCX | PDF | TXT | MD → ImportedDocument` (Line IR plus detected structure plus analysis report). Import **never rewrites**. The analysis classifies the document (textbook chapter, IELTS test, exam paper, and so on) and proposes a mapping into domain objects, which the user confirms.

## 13. Validation framework (Phase 13)

- `Rule(id, scope, severity, check(target) -> list[ValidationIssue])`, registered by scope: content, curriculum, graph, document, questions, programming, ielts, terminology.
- Deterministic rules come first. LLM-based rules (contradictions, unsupported claims, difficulty) are marked `method="llm"` and are *warnings only*; they can never block an export on their own.
- `ValidationResult` is stored per document version. The export gate is configurable per profile (IELTS: any error blocks).

## 14. Workflow and plugins

**Review states:** `draft → ai_validated → in_review → approved → published`, plus `changes_requested`. Transitions are role-checked (author, editor, reviewer, admin). Teacher edits create versions with `provenance=teacher_authored`.

**Plugins:** `osamu_dazai.exporters` entry-point group. The core ships DOCX, PDF, HTML, MD and JSON. A **TechRen exporter** (optional, separate package `dazai-export-techren`) maps our JSON to whatever that target needs. The core has zero knowledge of it.

## 15. Web UI (Phase 14)

Navigation: Dashboard · Projects · Courses · Curriculum · Learning Graph · Books · Teacher Guides · IELTS · Visuals · Questions · Assessments · Documents · Validation · Exports · Settings.

Primary actions: Create New Project · Import Existing Document · Fix IELTS Document · Generate Textbook · Generate Teacher Guide · Generate IELTS Test · Validate Document · Export DOCX.

Key screens:
- IELTS Fixer: original and fixed text side by side, with repair ops highlighted and review flags to accept or reject.
- Validation panel: issues grouped by location, clicking an issue jumps to it.
- Learning-graph viewer: DAG layout with violations highlighted.
- Block editor: shows provenance badges.

## 16. Internationalisation

UI strings live in i18n catalogs (en, uz-Latn, ru). Each course has `explanation_lang`, `terminology_lang` and `assessment_lang`. Fonts per script are set in `DocTemplate`. Uzbek Latin apostrophes (o', g', the ʻ U+02BB modifier) are normalised through one configurable rule, never ad hoc.

---

## 17. Recommended implementation order

The spec's phase order is kept, with one change: **the IELTS vertical slice moves forward**, because it is the most precisely specified, fully deterministic, testable without an LLM, and is the first acceptance test (spec §46).

| Step | Phases | Deliverable | Exit criterion |
|---|---|---|---|
| 1 | 1 | Audit docs (this) | ✅ |
| 2 | 2–3 | `backend/` skeleton, domain schemas, storage, versioning, `MockProvider` | Schemas round-trip JSON; migrations run |
| 3 | 10, 11, 12(IELTS profile), 13(IELTS rules) | IELTS contract, Line IR, parser, validators, fixer, DOCX renderer | Test §46: 3 passages / 40 questions round-trip; injected "…energy 13 The author…" is detected, repaired and re-validated |
| 4 | 6 (providers) | LLM, Image and Research providers (cloud, local, mock) | Same stage runs on mock and on one real provider |
| 5 | 4–5 | Planner, curriculum, learning graph and its checks | Python/Uzbek example brief → valid DAG plus curriculum |
| 6 | 6–9 | Book writer, teacher guide, visuals, exercises and assessments | JS textbook, 12 chapters (test §47) |
| 7 | 12–13 | Full DocumentTemplateEngine, all renderers, general QC | DOCX/HTML/JSON outputs pass QC |
| 8 | 14 | Web UI | Primary actions usable end to end |
| 9 | 15–16 | Export plugins (TechRen optional), integration tests, E2E | CI green |

## 18. Open decisions

1. **Final product name** (Osamu Dazai is a working name).
2. **Distribution model** (commercial/closed vs open-source). This decides whether GPL material could ever be used; see the audit §7.1.
3. **The external IELTS parser.** If you can share its source or a sample set of files it accepts and rejects, `parser.py` can be tested against it directly instead of against the written contract alone.
4. **Default cloud LLM and image providers** for the first real runs.
