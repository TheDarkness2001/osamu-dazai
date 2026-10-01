# Osamu Dazai — educational publishing engine

Osamu Dazai turns a teaching idea into a complete, checked educational product: curriculum, learning graph,
student book, teacher's guide, visuals, assessments and IELTS materials. AI drafts the content; deterministic
checks verify every step, and drafts that fail are sent back — never published.

**Website (first version):** IELTS Document Validator and IELTS Format Repair — upload a Reading or Listening
Word document, get an exact report, and download a corrected `.docx`. No AI and no account needed.

## What's inside

| Area | Status |
|---|---|
| IELTS Reading/Listening import contract, validator, Format Repair, parser-safe DOCX export | ✅ |
| AI providers (Claude, local models, images, Crossref/Semantic Scholar source checks) | ✅ |
| Planner → curriculum → learning graph → student book → teacher guide → visuals → assessments | ✅ (CLI) |
| IELTS Reading, Listening, Writing, Speaking generators | ✅ (CLI) |
| DOCX / HTML / PDF / Markdown / JSON output | ✅ |
| Website: IELTS validator + repair | ✅ |
| Website: generators, import, review workflow UI | planned |

## Run locally

```bash
cd backend
uv sync --extra web
uv run uvicorn osamu_dazai.web.app:app --reload     # http://localhost:8000
uv run pytest                                  # test suite
```

More commands (course design, book writing, IELTS generation): [backend/README.md](backend/README.md).

## Deploy (Render, free)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/TheDarkness2001/osamu-dazai)

The blueprint is [render.yaml](render.yaml). Optional settings in the Render dashboard:
`DAZAI_SITE_PASSWORD` (password-protect the tools) and `ANTHROPIC_API_KEY` (enable AI — set a password first).

## Documentation

- [Architecture](docs/ARCHITECTURE.md) · [Repository audit](docs/REPOSITORY_AUDIT.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md) — Osamu Dazai ports small parts of ClassBuild (MIT); the other
  reviewed projects were used for ideas only and none of their code or text is included.
