# Third-Party Notices — Osamu Dazai

Last updated: 2026-09-29

This file lists third-party material that is **incorporated** in Osamu Dazai, together with the notices its licenses require. Osamu Dazai's own code is original work of the Osamu Dazai project. Third-party code keeps its original authorship and license, and changing Osamu Dazai's branding never removes or alters these attributions.

---

## 1. Incorporated third-party code

### 1.1 ClassBuild — academic source verification

```
Component:        backend/osamu_dazai/providers/research/academic.py
Origin:           classbuild — src/services/academic/{crossref,semanticScholar,unpaywall,enrich}.ts
                  https://github.com/jtangen/classbuild (v1.0.0, downloaded 2026-09-29)
License:          MIT
Copyright:        Copyright (c) 2026 Jason Tangen
Changes made:     Translated from TypeScript to async Python (httpx); mapped to Osamu Dazai's
                  SourceCandidate / Verification models; Unpaywall made optional (requires a
                  real contact e-mail); a DOI whose Crossref title does not match the claimed
                  title is reported as unverified instead of being silently replaced.
License text:     licenses/classbuild-MIT.txt
```

The file header carries the same notice. The DOI and title verification logic in `backend/osamu_dazai/providers/research/web.py` follows the same approach and is covered by this entry.

### 1.2 ClassBuild — quiz versions and answer-length audit

```
Component:        backend/osamu_dazai/questions/shuffle.py
Origin:           classbuild — src/services/export/quizDocExporter.ts (seededRng, shuffle, generateVersions)
                  and src/services/quiz/answerBalancer.ts (auditQuestions)
                  https://github.com/jtangen/classbuild (v1.0.0, downloaded 2026-09-29)
License:          MIT
Copyright:        Copyright (c) 2026 Jason Tangen
Changes made:     Translated to Python with explicit 32-bit arithmetic (verified bit-identical
                  to the JavaScript original); versions operate on Osamu Dazai's Assessment model;
                  added deterministic answer-position balancing; the audit returns the offending
                  questions deterministically. ClassBuild's LLM distractor-rewrite step was not
                  copied — Osamu Dazai feeds the audit result back to its own generator instead.
License text:     licenses/classbuild-MIT.txt
```

### Entry format

When further code is incorporated, each entry records:

```
Component:        <Osamu Dazai path(s)>
Origin:           <repository, path(s), commit/version>
License:          <SPDX id>
Copyright:        <verbatim copyright line(s)>
Changes made:     <e.g. "translated from TypeScript to Python; adapted to Osamu Dazai schemas">
License text:     <path under licenses/>
```

Each incorporated source file also keeps a header comment naming the origin, the copyright and the license.

---

## 2. Reference repositories reviewed (not incorporated)

These repositories were audited (see `docs/REPOSITORY_AUDIT.md`). They are listed here for transparency. Where only their *ideas* influenced Osamu Dazai's design, Osamu Dazai's implementations are independent.

| Repository | Author / holder | License | Use in Osamu Dazai |
|---|---|---|---|
| classbuild | Copyright (c) 2026 Jason Tangen — https://github.com/jtangen/classbuild | MIT | Incorporated in part (§1.1, §1.2); SCORM packaging may be ported later |
| Study-AI-Agent | djmahe4 and contributors — https://github.com/djmahe4/Study-AI-Agent | Apache-2.0 | Ideas only |
| curriculum ("Educational Course Generator") | docxology — https://github.com/docxology/curriculum (DOI 10.5281/zenodo.17954165) | CC BY-NC-ND 4.0 | Ideas only; **no code or text may be copied** |
| ibook-skills | Dan McCreary — https://github.com/dmccreary/ibook-skills | CC BY-NC-SA 4.0 (some files: CC BY-NC 4.0) | Ideas only; **no code or text may be copied** |
| intelligent-textbooks | Dan McCreary — https://github.com/dmccreary/intelligent-textbooks | CC BY-NC(-SA) 4.0 (inconsistent in repo) | Background reading only |
| CurricuLLM | JWMB — https://codeberg.org/JWMB/CurricuLLM | GPL-3.0 | Ideas only; copying would impose GPL-3.0 |

Acknowledgement of influence (not required by license, given as a courtesy): the learning-graph-centred approach to textbook generation popularised by Dan McCreary's intelligent-textbooks work, and CurricuLLM's "AI drafts, teachers edit" workflow.

---

## 3. Planned incorporations (pending)

| Planned Osamu Dazai component | Origin (classbuild, MIT) | Notes |
|---|---|---|
| SCORM 2004 packaging (future export) | `scripts/package-scorm.ts` | Not started; would get its own §1 entry |

MIT License text for classbuild, stored verbatim at `licenses/classbuild-MIT.txt`:

```
MIT License

Copyright (c) 2026 Jason Tangen

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## 4. Runtime dependencies (planned)

Open-source libraries Osamu Dazai will depend on, not vendor. Their notices will be generated automatically from the lockfiles (`pip-licenses`, `license-checker`) at release time. They are listed here for the license-compatibility decision.

| Library | License | Purpose |
|---|---|---|
| Pydantic | MIT | Schemas |
| SQLAlchemy, Alembic | MIT | Persistence |
| python-docx | MIT | DOCX read/write (in use) |
| anthropic (Anthropic Python SDK) | MIT | Claude provider (in use) |
| httpx | BSD-3 | Local LLM / image / research HTTP clients (in use) |
| resvg-py (bundles resvg/usvg: Apache-2.0 OR MIT, tiny-skia: BSD-3, fontdb: MIT) | MIT | SVG → PNG for DOCX figures (in use) |
| FastAPI, Starlette, Uvicorn, python-multipart | MIT / BSD-3 / BSD-3 / Apache-2.0 | Website (in use) |
| pdfplumber / pypdf | MIT / BSD-3 | PDF import |
| Jinja2, markdown-it-py | BSD-3 / MIT | HTML / Markdown |
| React, Vite, TanStack Query | MIT | Web UI |
| LibreOffice (external process, not linked) | MPL-2.0 | DOCX → PDF |
| Mermaid / mermaid-cli | MIT | Diagrams |

**Excluded on license grounds:** PyMuPDF / fitz (AGPL-3.0).
