# AP Learning OS Online Infrastructure Checklist

This is the list of external services and decisions needed before the online
version can be deployed for other people.

## Required From User Later

### Domain and Server

- public domain name, or permission to start with a temporary deployment URL
- server provider choice, such as Vercel, Railway, Render, Fly.io, or a VPS
- region preference
- whether the service should be public internet, invite-only, or private beta

### Database

- Postgres database URL
- database provider choice, such as Supabase, Neon, Railway, or self-hosted
- backup policy
- whether reviewers/authors from different organizations must be isolated

### Object Storage

Required because PDFs, generated slices, screenshots, and uploaded evidence
should not live in the database.

Options:

- Cloudflare R2
- AWS S3
- Supabase Storage
- Google Cloud Storage

Needed values:

- bucket name
- access key
- secret key
- region or endpoint
- public/private file policy

### Authentication

Required roles:

```text
author
executor
reviewer
admin
```

Possible providers:

- Clerk
- Auth.js / NextAuth
- Supabase Auth
- Google OAuth

Needed decisions:

- email login or Google login
- whether users can self-register
- who can invite reviewers/executors

### Spreadsheet Integration

Minimum viable approach:

- store uploaded Excel files
- write review results into a derived workbook
- let the author download the updated workbook

Later approach:

- Google Sheets integration
- cell comments or review columns updated automatically

Needed decisions:

- Excel-only first, or Google Sheets from the beginning
- whether source spreadsheets can be overwritten
- preferred writeback columns

### PDF Processing

The compiler needs server-side PDF processing:

- page count
- text extraction
- OCR fallback
- page slicing
- generated excerpt storage

Server dependencies:

- Python worker or Node worker
- Poppler or PDFium
- OCR engine if scanned pages are common

Initial recommendation:

- use a background Python worker for PDF indexing and slicing
- use PDF.js in the browser for reading generated slices

### Background Jobs

Needed jobs:

- spreadsheet parsing
- resource indexing
- PDF slicing
- compile generation
- evidence archive packaging
- spreadsheet writeback

Options:

- simple Postgres-backed job table for MVP
- Inngest, Trigger.dev, or BullMQ later

### Privacy and Permissions

Decisions needed:

- whether authors can see executor evidence
- whether reviewers can see all students or assigned students only
- retention period for screenshots and evidence files
- whether deleted evidence is hard-deleted or archived

## Suggested Deployment Shape

MVP:

```text
Next.js web app
Postgres
S3-compatible object storage
Python worker for spreadsheet/PDF processing
PDF.js browser reader
server-side role checks
```

Later:

```text
Google Sheets writeback
live reviewer stream
resource matching improvements
multi-organization billing/isolation
```

## Build Order

1. Keep the local Python compiler as the reference engine.
2. Extract compiler output into JSON contracts.
3. Build web database schema.
4. Build author upload and compile sandbox.
5. Build browser-only executor workspace.
6. Build reviewer queue and decisions.
7. Add schedule delay propagation.
8. Add spreadsheet writeback/export.
9. Add live review stream.

## First Hosted MVP Acceptance Criteria

- Author uploads one spreadsheet and several PDFs.
- System parses rows and shows compile preview.
- System creates material slices with source lineage.
- Author publishes a compile version.
- Executor opens today's tasks in the browser.
- Executor uploads evidence.
- Reviewer marks completed or not completed.
- Not completed shifts the executor schedule from the next day.
- Review result is exported to a derived spreadsheet.

