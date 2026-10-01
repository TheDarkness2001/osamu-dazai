# Repository Audit — Phase 1

Product: **Osamu Dazai** (see ARCHITECTURE.md §0)
Audit date: 2026-09-29
Scope: the six repositories downloaded into this workspace. No repository was modified.

> Not legal advice. This audit reads the license files as shipped. Where a license is ambiguous, it assumes the most restrictive reading. Anything headed for commercial release should get a lawyer's review.

---

## 0. Summary

| # | Repository | Language / stack | License | Can we reuse code? | Main value to us |
|---|---|---|---|---|---|
| 1 | `classbuild-main` | TypeScript, React 19, Vite, Zustand, `docx`, `pptxgenjs`, Anthropic SDK | **MIT** © 2026 Jason Tangen | **Yes**, keep the copyright notice | Pipeline stages, prompt design, DOCX quiz export, academic source verification (Crossref / Semantic Scholar / Unpaywall), answer-position balancing |
| 2 | `Study-AI-Agent-main` | Python, Pydantic, LangChain, Gemini, Streamlit, PyMuPDF | **Apache-2.0** (holder not filled in; author: GitHub `djmahe4`) | **Yes**, keep the license and mark changes | Pydantic education models, exam-paper analysis idea, Mermaid mind maps |
| 3 | `curriculum-main` | Python 3.10, uv, Ollama, pytest (658 tests) | **CC BY-NC-ND 4.0** | **No.** NonCommercial and NoDerivatives | Ideas: outline quality scoring, progression checks, Mermaid cleanup, staged pipeline |
| 4 | `ibook-skills-main` | Markdown agent skills, Python scripts, MkDocs, p5.js | **CC BY-NC-SA 4.0** (some files say BY-NC 4.0) | **No** (NonCommercial + ShareAlike) | Ideas: learning-graph DAG, Bloom's taxonomy, ISO 11179 definitions, glossary/quiz/FAQ workflow |
| 5 | `intelligent-textbooks-main` | Markdown, MkDocs, Python utilities, p5.js | **CC BY-NC-SA 4.0** (`license.md` text says BY-NC; badge says BY-NC-SA) | **No** (NonCommercial) | Ideas: five levels of intelligent textbooks, learning-graph-centred generation |
| 6 | `CurricuLLM-main` | Markdown prompt templates (Swedish) + generated course content; no executable code | **GPL-3.0** | **Not without making Osamu Dazai GPL-3.0** | Ideas: generation driven by the table of contents, "structural context" prompt, image placeholders whose file name is the prompt |

**IELTS components:** none in any repository (`grep -ri ielts` finds nothing). The whole IELTS module (§§15–34 of the spec) is new work.

**DOCX components:** `classbuild` writes quizzes with the MIT `docx` npm package. `ibook-skills` extracts DOCX paragraphs with the standard library, but it is NC-SA, so we reimplement that (it is trivial with `python-docx`). No repository has a general DOCX template engine or a DOCX validator.

---

## 1. classbuild-main

**Repository:** https://github.com/jtangen/classbuild (v1.0.0)
**Purpose:** Browser-only (bring-your-own-key) AI course generator. Pipeline: Setup → Syllabus → Research → Build → Export. Each chapter gets reading HTML/MD, PPTX slides, a DOCX in-class quiz (5 shuffled versions plus answer keys), a gamified practice quiz, a teaching pack, TTS audio, a weekly challenge and SCORM 2004.
**License:** MIT, Copyright (c) 2026 Jason Tangen.
**Package manager / language / framework:** npm; TypeScript 5.9; React 19, Vite 7, Tailwind 4, Zustand 5 (IndexedDB persistence), react-router 7. Node CLI in `scripts/` run with `tsx`.
**Architecture:** 12 prompt builders in `src/prompts/*.ts`. Services in `src/services/{claude,openai,elevenLabs,academic,quiz,export}`. Types in `src/types/course.ts`. HTML templates in `src/templates/`. Six CSS themes. No backend and no database: state lives in the browser.
**AI / agents:** Direct Anthropic SDK calls with streaming, web search and extended thinking (`services/claude/streaming.ts`). Model IDs are hard-coded in `services/claude/client.ts`. There is no provider abstraction.
**Document generation:** `services/export/quizDocExporter.ts` (374 lines, `docx`), `scripts/lib/docx-helpers.ts` (364 lines), `services/export/pptxExporter.ts` (`pptxgenjs`), `publishExporter.ts` (standalone course site), `scripts/package-scorm.ts`.
**Image generation:** `services/openai/imageGen.ts`, `imagePlacer.ts` (replaces image placeholders in HTML), `safetyClause.ts`.
**Curriculum / educational features:** Syllabus with learning-science annotations (spacing, interleaving, retrieval, worked examples, dual coding), learning objectives, activities, discussion prompts, `answerBalancer.ts` (spreads the correct-answer position evenly).
**Research / fact checking:** `services/academic/{crossref,semanticScholar,unpaywall,enrich}.ts` look up DOIs and metadata in real bibliographic databases. This fits spec §44 ("never fabricate sources") directly.
**Tests:** No unit-test suite. There is a manual script, `scripts/test-weekly-challenge.ts`.

**Useful components:**
- Academic reference verification (Crossref, Semantic Scholar, Unpaywall), about 350 lines.
- Seeded PRNG (mulberry32) and Fisher–Yates shuffle for reproducible quiz versions.
- Answer-position balancing.
- DOCX quiz layout (versions and answer-key tables).
- Structure of the prompt builders (one function per artifact, typed inputs).
- SCORM 2004 packaging (a future export format for us).

**Potentially reusable code (MIT permits this):** `services/academic/*`, `services/quiz/answerBalancer.ts` (the parsing and balancing logic), `quizDocExporter.ts` (versioning and shuffling logic), `package-scorm.ts`.
**Potentially reusable ideas:** The five-stage pipeline with a human edit step; a research dossier for each chapter; a single theme choice that carries through every artifact; SCORM export.
**Dependencies:** `@anthropic-ai/sdk`, `docx`, `pptxgenjs`, `jszip`, `dompurify`, `file-saver`, `framer-motion`, React, Tailwind.
**Conflicts:**
- The architecture is browser-only with keys in the browser (`dangerouslyAllowBrowser: true`). Osamu Dazai needs a server with a database, versioning and review workflow.
- It is locked to one provider (Anthropic for text, OpenAI for images) and hard-codes model IDs.
- It is TypeScript. Our document and validation core is Python (see ARCHITECTURE §2).
- Its "Codex" design system and chapter themes are ClassBuild branding and must not be copied.

**Recommended action:** **Port selectively, with attribution.** Reimplement the academic-verification clients and seeded shuffle/balancer in Python. A straight translation of that code is still a derivative work, so record it in `THIRD_PARTY_NOTICES.md` and keep the MIT notice in the file header. Use the pipeline and SCORM packaging as reference designs. Do not copy the UI, themes or prompts verbatim.

---

## 2. Study-AI-Agent-main

**Repository:** https://github.com/djmahe4/Study-AI-Agent
**Purpose:** Personal study assistant. It creates subjects, parses syllabi with Gemini, runs RAG over YouTube transcripts and question banks, draws mind maps (Mermaid), renders OpenCV animations and builds mnemonics.
**License:** Apache License 2.0. The `[yyyy] [name of copyright owner]` placeholder was never filled in and there is no NOTICE file. Attribute to "djmahe4 / Study-AI-Agent contributors".
**Package manager / language / framework:** pip (`requirements.txt`, 190 pinned packages); Python 3.8+; Typer/Rich CLI (`cli.py`, 1,131 lines); Streamlit UI; optional React/Vite terminal front end; SQLite (`data/memory.db`); FAISS.
**Architecture:** `core/models.py` (Pydantic: Topic, Module, Syllabus, Subject, Question, ExamPattern, AnalyzedQuestion, QuestionBank, MermaidDiagram, AnimationScript), `core/exam_analysis.py`, `core/rag.py`, `core/ingest.py`, `visual/mindmap_v2.py`, `visual/animate.py`.
**AI / agents:** LangChain + Gemini (`gemini-2.5-flash`), with structured output into Pydantic models. There is no provider abstraction.
**Document generation:** None. Import: PDF text extraction with PyMuPDF.
**Diagram generation:** Mermaid mind maps built from Topic models.
**Tests:** A CI workflow exists (`.github/workflows/ci.yml`); there is no `tests/` directory.

**Useful components:** The Pydantic models (as a starting vocabulary), the exam-pattern schema (sections, marks), and the approach to parsing question papers: LLM structured output first, falling back to regex splitting by year section.
**Potentially reusable code:** Small. `core/models.py` could be adapted, but our schema is far larger, so rewriting from scratch is cleaner.
**Potentially reusable ideas:** Difference or contrast tables and mnemonics as content types; exam-pattern definitions per exam board; animation scripts as structured specs.
**Dependencies:** LangChain 1.2, langgraph, google-genai, faiss-cpu, opencv-python, **pymupdf**, streamlit, nipype and pyxnat (unused neuroimaging packages), and many others.
**Conflicts:**
- **PyMuPDF is AGPL-3.0** (or commercial). Using it in a networked service would make Osamu Dazai AGPL. **Do not adopt it.** Use `pdfplumber` (MIT) or `pypdf` (BSD) instead.
- The dependency set is heavy, pinned and partly irrelevant.
- It is locked to Gemini.

**Recommended action:** **Ideas only.** Implement our own models. Adopt nothing from its dependency list, and explicitly exclude PyMuPDF.

---

## 3. curriculum-main (docxology "Educational Course Generator")

**Repository:** https://github.com/docxology/curriculum — DOI 10.5281/zenodo.17954165
**Purpose:** A six-stage, config-driven pipeline (setup → tests → outline → primary materials → secondary materials → website) that uses a local Ollama LLM (`gemma3:4b`).
**License:** **Creative Commons BY-NC-ND 4.0.** It forbids commercial use and forbids distributing adapted material. (CC licenses are not designed for software, but they still bind.)
**Package manager / language / framework:** uv (`pyproject.toml`, `uv.lock`); Python 3.10+; hatchling; pytest with 35 test files and 658 tests; black, flake8, mypy (strict).
**Architecture:** `src/config` (YAML: course, LLM, output), `src/llm/{client,health,request_handler}`, `src/generate/{stages,formats,orchestration,processors}`, `src/utils/content_analysis/{consistency,mermaid,question_fixes,analyzers}`, `src/validation`, `src/website`.
**Educational features:** Modules and sessions, lectures, labs, study notes, questions, diagrams (131 `.mmd` files in the sample output), cross-session concept-consistency tracking, and outline quality scoring (topic overlap, learning progression, balance).
**Tests:** The best-tested repository in the workspace.

**Useful components (as references only):**
- `generate/stages/outline_quality.py`: overlap detection (keyword Jaccard), progression validation, balance scoring and an overall quality score.
- `utils/content_analysis/consistency.py`: concept-progression tracking across sessions.
- `utils/content_analysis/mermaid.py`: Mermaid cleanup and syntax validation.
- `utils/content_analysis/question_fixes.py`: repairs missing question marks and normalises multiple-choice options.
- Separating the LLM health check from request handling, and smart retry.

**Potentially reusable code:** **None.** The license (ND) prohibits distributing modified versions and (NC) prohibits commercial use.
**Potentially reusable ideas:** Everything listed above. An idea or a validation *concept* ("flag outline sessions whose keyword sets overlap by more than X") is not copyrightable. We write our own implementation without copying code structure or text.
**Dependencies:** PyYAML, requests, markdown; Ollama at runtime.
**Conflicts:** The license is incompatible with an independent product. It is also Ollama-specific (our `LocalProvider` can cover Ollama).
**Recommended action:** **Clean-room reimplementation of ideas only.** Developers who read this code in detail should not type our equivalents from memory. Write our own specs first (ARCHITECTURE §9), then implement from the specs.

---

## 4. ibook-skills-main (Dan McCreary — "Agent Skills for Intelligent Textbooks")

**Repository:** https://github.com/dmccreary/ibook-skills
**Purpose:** A library of `SKILL.md` agent workflows plus helper scripts. Together they take a course description to a published MkDocs Material textbook with a learning graph, chapters, glossary, FAQ, quizzes, references and p5.js MicroSims.
**License:** **CC BY-NC-SA 4.0** (`docs/license.md`, README badge). Some individual skills declare **CC BY-NC 4.0** in their front matter (for example `skills/quiz-generator/SKILL.md`). There is no top-level `LICENSE` file. Both readings forbid commercial use.
**Package manager / language / framework:** pip/conda; Python 3.8+; MkDocs + Material; p5.js; shell install scripts.
**Architecture:** `skills/<name>/SKILL.md` with `references/`, `scripts/` and `assets/`. Active skills: learning-graph-generator, course-description-analyzer, book-chapter-generator, chapter-content-generator, glossary-generator, faq-generator, quiz-generator, reference-generator, microsim-generator/-utils, book-media-generator, book-publisher, book-installer, docx-to-web-publisher, add-xapi-events-to-microsim.
**Educational features:** A learning graph of concepts (570-concept example) stored as a DAG with taxonomy groups; Bloom's 2001 revision for objectives; ISO 11179 rules for definitions; quizzes aligned to both the graph and Bloom's levels; distractor-writing guide; reading-level analysis; xAPI events.
**Useful components (reference):** `learning-graph-schema.json` (metadata, groups, nodes, edges); `validate-learning-graph.py`, `analyze-graph.py` (cycle and orphan detection, taxonomy distribution); `extract_docx.py` (paragraph and style extraction using only the standard library); the quiz distractor guide.
**Potentially reusable code:** **None** (NC, and SA would force our derivative onto the same license).
**Potentially reusable ideas:** The learning-graph data model (concept DAG plus taxonomy groups); graph quality metrics (orphans, cycles, depth, share of foundational concepts); Bloom's distribution targets; ISO 11179 definition rules (precise, concise, distinct, non-circular); the "course description → concepts → dependencies → chapters" flow.
**Dependencies:** mkdocs, mkdocs-material, pymdown-extensions, jsonschema.
**Conflicts:** NC license; output is tied to MkDocs; it is an agent-skills model rather than an application.
**Recommended action:** **Ideas only; independently designed schema.** Osamu Dazai's `Concept` model (spec §8) differs from theirs anyway (it adds `learning_objectives`, `chapters`, `assessment_items` and `difficulty`). Do not copy their JSON Schema.

---

## 5. intelligent-textbooks-main (Dan McCreary — "Building Intelligent Textbooks With AI")

**Repository:** https://github.com/dmccreary/intelligent-textbooks
**Purpose:** A guide and book (MkDocs site plus an EPUB trade book) about building intelligent textbooks. It also holds prompt collections, workflows, p5.js MicroSims and analytics scripts.
**License:** **Inconsistent.** `license.md` shows a BY-NC-SA badge, but its text says "Attribution-NonCommercial 4.0". `docs/license.md` says BY-NC-SA 4.0. Both are NonCommercial.
**Package manager / language / framework:** conda/pip; MkDocs Material; Python utilities (`src/`: site analytics, CSV→JSON, TOC generation, EPUB via a pandoc shell script, completion estimator); LaTeX (23 `.tex` files); 54 bundled `.ttf` fonts (each with its own license, not audited individually).
**Educational features:** Documentation: five levels of intelligent textbooks, learning-graph workflow, prompt library (`docs/prompts/`), case studies, papers on self-improving textbooks.
**Useful components:** Conceptual material and the prompt library, for reading.
**Potentially reusable code:** **None** (NC). The utility scripts are small and generic in any case.
**Potentially reusable ideas:** A maturity model (Level 1 static → Level 5 adaptive) as a product roadmap; completion-status tracking per book; EPUB as a future export format.
**Dependencies:** mkdocs, mkdocs-material, pandoc (EPUB).
**Conflicts:** NC license; it is documentation, not an application.
**Recommended action:** **Background reading only.** Nothing to incorporate.

---

## 6. CurricuLLM-main (JWMB)

**Repository:** GitHub (abandoned; continues at https://codeberg.org/JWMB/CurricuLLM)
**Purpose:** A Swedish open textbook initiative: LLMs draft raw material, then teachers and experts edit it, with print-on-demand as the goal. It contains prompt templates and generated course content (880 Markdown files) for Swedish school subjects (Physics Year 7, Geography Year 6, Maths Year 1 and Year 7, Religion Year 7, Critical Thinking).
**License:** **GNU GPL-3.0.** The generator code lives on Codeberg and is **not** in this download. What is here are the templates and outputs.
**Package manager / language / framework:** None here. The templates use a `{{ }}` syntax with `{{template:…}}` includes.
**Educational features:** Templates for chapter sections, assignments, assignment evaluation, controversies, curiosities, history, illustrations (for LLMs and image models), TOC, and "structuralContext" (tells the LLM where the current section sits in the book).
**Useful components:** The templates as reference designs.
**Potentially reusable code:** None worth taking. Copying the templates would bring in GPL-3.0 obligations.
**Potentially reusable ideas (strongly aligned with spec §39):**
- AI writes a first draft only; human editors must review before students see anything.
- Hierarchical generation in which every call receives the full TOC plus its position in it.
- Image placeholders whose descriptive file name doubles as the image prompt, rendered later.
- Separate prompt families for student-facing text (which must not contain teacher instructions) and teacher material.
**Dependencies:** None.
**Conflicts:** GPL-3.0 copyleft; content is Swedish.
**Recommended action:** **Ideas only.** Our prompts are written from scratch in English with a language parameter.

---

## 7. Cross-cutting conclusions

### 7.1 Legal reuse matrix

| Reuse type | classbuild (MIT) | Study-AI-Agent (Apache-2.0) | curriculum (BY-NC-ND) | ibook-skills (BY-NC-SA) | intelligent-textbooks (BY-NC[-SA]) | CurricuLLM (GPL-3) |
|---|---|---|---|---|---|---|
| Copy or translate code | ✅ keep notice | ✅ keep license, mark changes | ❌ | ❌ | ❌ | ⚠️ only if Osamu Dazai becomes GPL-3 |
| Copy prompts or text | ✅ keep notice | ✅ | ❌ | ❌ | ❌ | ⚠️ GPL |
| Implement the same idea independently | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

**Open decision for you:** Is Osamu Dazai intended to be commercial or closed-source? This audit assumes it might be, and so rules out NC, ND and GPL material. If you choose an open license later (for example AGPL/GPL for the whole product), CurricuLLM becomes usable. The CC NC/ND repositories stay unusable either way.

### 7.2 Dependency conflicts across repositories

| Area | Repositories disagree | Decision for Osamu Dazai |
|---|---|---|
| Language | TS (classbuild) vs Python (others) | Python back end and core engines; TypeScript/React front end |
| LLM client | Anthropic SDK / LangChain+Gemini / raw Ollama HTTP | Our own thin `LLMProvider` interface; no LangChain dependency in the core |
| DOCX | `docx` (npm) vs stdlib XML | `python-docx` (MIT) for writing and reading, plus raw OOXML inspection in the validator |
| PDF read | PyMuPDF (AGPL) | `pdfplumber` (MIT) / `pypdf` (BSD) |
| PDF write | none | LibreOffice headless (DOCX→PDF, keeps layout identical); optional WeasyPrint (BSD) for HTML→PDF |
| Site / HTML | MkDocs / custom templates | Jinja2 templates of our own |
| Python packaging | uv / pip / conda | uv |
| Persistence | IndexedDB / SQLite / files | SQLAlchemy 2 + Alembic; SQLite for development, PostgreSQL for production |

### 7.3 What does not exist anywhere (net-new work)
- The entire IELTS module: question-type taxonomy, deterministic parser, `IELTSQuestionNumberValidator`, document validator, Format Repair (fixer), exporter compatible with the parser.
- Multi-provider abstraction (LLM, image, research).
- Relational project model with versioning and the Draft → Validation → Review → Approved → Published workflow.
- Terminology knowledge base with enforced translations (Variable = o'zgaruvchi).
- Separate languages for explanation, terminology and assessment.
- Provenance tags for source-backed, AI-generated, teacher-authored and user-provided content.
- Import pipeline (DOCX/PDF/TXT/MD → analysis without rewriting).
- A general DOCX template engine.
