# DocExtract Backend

This FastAPI backend powers the document extraction workflow described in the PRD. It exposes three routes: `/upload`, `/extract-fields`, and `/highlight`.

## Setup

1. Create and activate a virtual environment (Python 3.10+):
   ```cmd
   python -m venv .venv
   .venv\Scripts\activate
   ```
2. Install dependencies:
   ```cmd
   pip install -r requirements.txt
   ```
3. Copy `.env` to `.env.local` (optional) and populate the API keys:
   ```cmd
   copy .env .env.local
   ```
   Update `LLMWHISPERER_API_KEY` and `GROQ_API_KEY` with valid credentials. Adjust base URLs or models if necessary.
4. Run the server:
   ```cmd
   uvicorn server:app --host 0.0.0.0 --port 8004 --reload
   ```

## Available Routes

- `POST /upload` – Accepts multiple files (`PDF`, `PNG`, `JPG`, `JPEG`, `TIFF`, `DOCX`, `XLSX`) and proxies them to LLMWhisperer with `layout_preserving` mode and line numbers enabled. Returns text, bounding boxes, page metadata, and the whisper hash per file.
- `POST /extract-fields` – Uses Groq to perform template-driven extraction. Returns an array of `{ key, value, line_indexes }` objects that align with the frontend template panels.
- `POST /highlight` – Converts word indexes to merged bounding boxes for the PDF overlay.

### Error Handling

Every endpoint returns informative `detail` messages with appropriate HTTP status codes (400-range for client issues, 502/504 for upstream problems).

### Notes

- Files are processed entirely in memory; nothing is persisted.
- All external calls are asynchronous and use sensible timeouts and polling intervals.
- Adjust CORS origins via the `BACKEND_CORS_ORIGINS` environment variable.
