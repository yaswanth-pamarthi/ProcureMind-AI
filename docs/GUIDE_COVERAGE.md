# Original guide coverage

Core functional requirements are mapped below. Detailed contracts and acceptance evidence are in the technical companion.

| Guide ID | Implemented process | Source | Verification |
|---|---|---|---|
| FR-01 | Authentication, analyst/manager roles | core.py; main.py /auth/login and /auth/register | test_api.py role tests; browser login |
| FR-02 | Validated RFQ create/update and lifecycle | schemas.py RFQIn; main.py RFQ routes; RFQEditor.tsx | Weight-sum tests; UI RFQ editor; analysis/decision lifecycle |
| FR-03 | Vendor master and sourced history | models.py Vendor/Performance; /vendors and /performance | Three seeded vendors; quality missing-data guard |
| FR-04 | Quotation/contract PDF uploads | documents.py validate_pdf/upload; /submissions/{id}/documents | Spoofed-file tests; three quotation + three contract PDFs |
| FR-05 | Structured extraction with evidence | documents.py process; schemas.py Quotation | 24 labelled commercial fields; arithmetic and page evidence tests |
| FR-06 | Clause findings and missing clauses | documents.py clause catalogue; workflows.py Contract Analysis | Exact excerpt/chunk/page validity tests; Beta risks visible |
| FR-07 | Eligible comparison and contributions | scoring.py; models.py Score; comparison endpoint | Deterministic repeatability, zero-value/mixed-currency/ineligible tests |
| FR-08 | Recommendation with rationale/alternatives | workflows.py Risk; Recommendation model | Three real AI workflow runs and persisted scorecards |
| FR-09 | Manager approval/rejection/override | main.py decision; interrupt/Command in workflows.py | All three golden decisions; unauthorized analyst forbidden |
| FR-10 | Final PDF/DOCX report | reports.py; report/download endpoints | Actual authenticated API and browser downloads; repeat report ID |
| FR-11 | Inspectable agent execution | Run/Output models; /analysis-runs/{id}; UI timeline | Seven outputs with model/prompt/schema/timestamps per completed path |
| FR-12 | Search and source-page inspection | documents.py retrieve; PdfViewer.tsx; evidence endpoint | Metadata-filtered pgvector retrieval and embedded source PDF viewer |

## Non-functional requirements and implementation choices

| Requirement | Implementation / evidence |
|---|---|
| Local zero paid API/cloud dependency | Native Ollama, local pgvector database, local files and frontend/backend. |
| Laptop performance | Measured complete real-LLM paths in execution-results.json; ingestion-benchmark.json for operations. |
| Pinned dependencies | requirements.txt and package-lock.json; Python 3.12 and Node 24. |
| Least privilege | Server JWT roles; procurement object ownership; no agent execution tools. |
| Explainability | Exact document/page/chunk/excerpt or frozen event IDs; deterministic factor/evidence scoring. |
| Reliable repeat operations | Source hashes, unique constraints, PROCESSED reuse, episode dedupe, one approval, existing report reuse. |
| Observability | Persisted runs, errors, prompt/schema versions, model metadata and node timestamps. |
| Human review and durable pause | LangGraph interrupt + Command resume with SQLite checkpoints; relational approvals. |
| Reproducibility and demo | Setup/Start/Doctor/Test scripts, sample data, screenshots, video and recorded validation. |

## Guide scope boundaries

The original documents specify local MVPs and exclude production cloud/ERP/ITSM/SSO integrations, autonomous operations, statistical anomaly models and real notifications. OCR is optional. These are described in the interview companion without inventing a deployed capability. The concrete prepared quotation extractor supports one labelled line item and flags unsupported inputs for review.

## Hardware-specific and operational choices

Qwen3 1.7B is the guide's permitted fallback for the measured 4 GB VRAM. Both projects use separate database/API/UI ports. SQLite holds durable local LangGraph checkpoints, while PostgreSQL holds relational evidence and decisions. GPU calls are serialized inside each application; run one project's inference at a time. Operations sample logs now cover 20 minutes so the ten-minute recovery gate can be exercised.

## Evidence artifacts

execution-results.json, browser-results.json, pytest-results.xml, screenshots/, demo/walkthrough.webm, source tests, pinned manifests and migration files.