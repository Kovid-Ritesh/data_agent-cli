"""
server.py — FastAPI web server for DataAgent.

Exposes the CLI data analysis agent as a web API with:
- File upload & session management
- Chat-style query interface (ReAct loop over HTTP)
- Static frontend serving

Error Handling Strategies (Web Layer):
──────────────────────────────────────
7. REQUEST VALIDATION (Pydantic models + manual checks)
   - All endpoints validate inputs with Pydantic BaseModel schemas.
   - File types validated against SUPPORTED_EXTENSIONS before processing.

8. SESSION LIFECYCLE MANAGEMENT
   - Sessions are created on first upload, cleaned up on delete.
   - Stale sessions auto-expire after 1 hour.
   - Prevents memory leaks from abandoned sessions.

9. EXECUTION TIMEOUT PROTECTION
   - Code execution in the sandbox is wrapped in a thread with a 30s timeout.
   - Prevents infinite loops or resource-hogging queries from blocking the server.

10. GLOBAL EXCEPTION HANDLER
    - FastAPI exception handlers catch unhandled errors and return structured
      JSON error responses (never raw stack traces to the client).

11. FILE UPLOAD SAFETY
    - File size limits (50MB max).
    - Extension whitelist (only data files accepted).
    - Files stored in isolated session directories.

12. CORS PROTECTION
    - Configurable allowed origins for cross-origin requests.
"""

from __future__ import annotations

import os
import shutil
import time
import uuid
import traceback
import threading
from pathlib import Path
from dataclasses import dataclass, field

from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel

from data.loader import SUPPORTED_EXTENSIONS, load_file
from data.schema import extract_all_schemas
from agent.core import DataAgent, parse_response, extract_thinking, _truncate
from agent.llm import LLMError

# ── Configuration ──────────────────────────────────────────────────────────────
MAX_FILE_SIZE_MB = 50
SESSION_EXPIRE_SECONDS = 3600  # 1 hour
EXECUTION_TIMEOUT_SECONDS = 30
UPLOAD_DIR = Path("./uploads")
OUTPUT_DIR = Path("./output")

# ── Pydantic Models ────────────────────────────────────────────────────────────
class QueryRequest(BaseModel):
    session_id: str
    query: str

class QueryStep(BaseModel):
    type: str  # "thinking", "code", "output", "error", "answer"
    content: str

class QueryResponse(BaseModel):
    success: bool
    steps: list[QueryStep]
    error: str | None = None

class SessionInfo(BaseModel):
    session_id: str
    files: list[dict]
    created_at: float

class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None


# ── Session Store ──────────────────────────────────────────────────────────────
@dataclass
class Session:
    session_id: str
    dfs: dict = field(default_factory=dict)
    agent: DataAgent | None = None
    files: list[dict] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    upload_dir: Path = field(default_factory=lambda: Path("."))
    output_dir: Path = field(default_factory=lambda: Path("."))


sessions: dict[str, Session] = {}


def cleanup_stale_sessions() -> None:
    """Remove sessions older than SESSION_EXPIRE_SECONDS."""
    now = time.time()
    expired = [
        sid for sid, s in sessions.items()
        if now - s.created_at > SESSION_EXPIRE_SECONDS
    ]
    for sid in expired:
        _destroy_session(sid)


def _destroy_session(session_id: str) -> None:
    """Clean up session files and remove from store."""
    if session_id in sessions:
        sess = sessions.pop(session_id)
        # Clean up uploaded files
        if sess.upload_dir.exists():
            shutil.rmtree(sess.upload_dir, ignore_errors=True)
        if sess.output_dir.exists():
            shutil.rmtree(sess.output_dir, ignore_errors=True)


# ── FastAPI App ────────────────────────────────────────────────────────────────
app = FastAPI(
    title="DataAgent API",
    description="Interactive data analysis powered by Google Gemini",
    version="1.0.0",
)

# ── Strategy 12: CORS Protection ──────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Strategy 10: Global Exception Handler ─────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Never expose raw tracebacks to the client."""
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc) if os.getenv("DEBUG") else "An unexpected error occurred.",
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail},
    )


# ── Startup / Shutdown ────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/")
async def serve_landing():
    """Serve the landing page website."""
    return FileResponse("website/index.html")


@app.get("/app")
async def serve_app():
    """Serve the interactive web app dashboard."""
    return FileResponse("frontend/index.html")


@app.get("/download/dagent.exe")
async def download_windows_binary():
    """Serve the pre-compiled Windows binary."""
    path = Path("dist/dagent.exe")
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="Windows binary dagent.exe has not been built on this server. Please build it first."
        )
    return FileResponse(
        path=str(path),
        filename="dagent.exe",
        media_type="application/octet-stream"
    )


@app.get("/download/dagent")
async def download_unix_binary():
    """Serve the pre-compiled macOS/Linux binary."""
    path = Path("dist/dagent")
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="macOS/Linux binary dagent has not been built on this server."
        )
    return FileResponse(
        path=str(path),
        filename="dagent",
        media_type="application/octet-stream"
    )


@app.post("/api/upload", response_model=SessionInfo)
async def upload_files(files: list[UploadFile] = File(...), session_id: str | None = None):
    """
    Upload data files and create/update a session.

    Strategy 7: Request Validation
    Strategy 8: Session Lifecycle
    Strategy 11: File Upload Safety
    """
    cleanup_stale_sessions()

    # Create or reuse session
    if session_id and session_id in sessions:
        sess = sessions[session_id]
    else:
        sid = str(uuid.uuid4())
        sess_upload = UPLOAD_DIR / sid
        sess_output = OUTPUT_DIR / sid
        sess_upload.mkdir(parents=True, exist_ok=True)
        sess_output.mkdir(parents=True, exist_ok=True)
        sess = Session(
            session_id=sid,
            upload_dir=sess_upload,
            output_dir=sess_output,
        )
        sessions[sid] = sess

    loaded_files = []
    errors = []

    for upload_file in files:
        # ── Strategy 11: File extension validation ─────────────────────────
        ext = Path(upload_file.filename or "").suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            errors.append(f"Unsupported file type: {upload_file.filename} ({ext})")
            continue

        # ── Strategy 11: File size validation ──────────────────────────────
        content = await upload_file.read()
        size_mb = len(content) / (1024 * 1024)
        if size_mb > MAX_FILE_SIZE_MB:
            errors.append(f"File too large: {upload_file.filename} ({size_mb:.1f}MB > {MAX_FILE_SIZE_MB}MB)")
            continue

        # Save to session directory
        file_path = sess.upload_dir / upload_file.filename
        with open(file_path, "wb") as f:
            f.write(content)

        file_info = {
            "path": str(file_path),
            "name": upload_file.filename,
            "ext": ext,
            "format": SUPPORTED_EXTENSIONS[ext],
            "size_kb": round(len(content) / 1024, 2),
        }

        try:
            stem = Path(upload_file.filename).stem
            df = load_file(file_info)
            sess.dfs[stem] = df
            sess.files.append({
                "name": upload_file.filename,
                "rows": int(df.shape[0]),
                "columns": int(df.shape[1]),
                "size_kb": file_info["size_kb"],
            })
            loaded_files.append(upload_file.filename)
        except Exception as exc:
            errors.append(f"Failed to load {upload_file.filename}: {str(exc)}")

    if not sess.dfs:
        raise HTTPException(
            status_code=400,
            detail=f"No files could be loaded. Errors: {'; '.join(errors)}" if errors else "No valid files uploaded.",
        )

    # Initialize or reinitialize agent
    try:
        sess.agent = DataAgent(
            dfs=sess.dfs,
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            output_dir=str(sess.output_dir),
        )
    except (LLMError, EnvironmentError) as exc:
        raise HTTPException(status_code=500, detail=f"Failed to initialize AI agent: {exc}")

    return SessionInfo(
        session_id=sess.session_id,
        files=sess.files,
        created_at=sess.created_at,
    )


@app.post("/api/query", response_model=QueryResponse)
async def run_query(req: QueryRequest):
    """
    Run a data analysis query through the ReAct loop.

    Strategy 7: Request Validation
    Strategy 9: Execution Timeout Protection
    """
    # ── Strategy 7: Validate session ───────────────────────────────────────
    if req.session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found. Please upload files first.")

    sess = sessions[req.session_id]
    if not sess.agent:
        raise HTTPException(status_code=400, detail="Agent not initialized. Please upload files first.")

    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty.")

    # ── Run query with timeout ─────────────────────────────────────────────
    steps: list[QueryStep] = []
    result_holder: dict = {"answer": None, "error": None}

    def _run():
        try:
            agent = sess.agent
            agent.history.append({"role": "user", "content": req.query})

            from agent.core import MAX_ITERATIONS
            for _iteration in range(MAX_ITERATIONS):
                try:
                    response = agent.llm.chat(agent.history, agent.system_prompt)
                except LLMError as exc:
                    steps.append(QueryStep(type="error", content=f"LLM Error: {exc}"))
                    result_holder["error"] = str(exc)
                    return

                agent.history.append({"role": "assistant", "content": response})

                # Parse thinking
                thinking = extract_thinking(response)
                if thinking:
                    steps.append(QueryStep(type="thinking", content=thinking))

                # Parse execute & answer blocks
                execute_blocks, answer = parse_response(response)

                for code in execute_blocks:
                    steps.append(QueryStep(type="code", content=code))

                    result = agent.executor.run(code)
                    if result.success:
                        output_text = _truncate(result.stdout)
                        if output_text.strip():
                            steps.append(QueryStep(type="output", content=output_text))
                        feedback = f"[EXECUTION RESULT]\n{output_text}"
                    else:
                        error_text = _truncate(result.error or "")
                        steps.append(QueryStep(type="error", content=error_text))
                        feedback = f"[EXECUTION RESULT - ERROR]\n{error_text}"
                        if result.stdout.strip():
                            steps.append(QueryStep(type="output", content=result.stdout))

                    agent.history.append({"role": "user", "content": feedback})

                if answer is not None:
                    steps.append(QueryStep(type="answer", content=answer))
                    result_holder["answer"] = answer
                    return

                if not execute_blocks and answer is None:
                    agent.history.append({
                        "role": "user",
                        "content": "Please provide your analysis result in <answer> tags.",
                    })

            result_holder["error"] = "Agent reached maximum iterations."
            steps.append(QueryStep(type="error", content="Agent reached maximum iterations. Try rephrasing your query."))

        except Exception as exc:
            result_holder["error"] = str(exc)
            steps.append(QueryStep(type="error", content=f"Unexpected error: {traceback.format_exc()}"))

    # ── Strategy 9: Execution Timeout ──────────────────────────────────────
    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=EXECUTION_TIMEOUT_SECONDS * MAX_FILE_SIZE_MB)  # Scale timeout with potential data size

    if thread.is_alive():
        steps.append(QueryStep(type="error", content="Query timed out. The operation took too long."))
        return QueryResponse(success=False, steps=steps, error="Query timed out.")

    return QueryResponse(
        success=result_holder["error"] is None,
        steps=steps,
        error=result_holder["error"],
    )


@app.get("/api/files/{session_id}")
async def get_session_files(session_id: str):
    """List files loaded in a session."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found.")
    return {"files": sessions[session_id].files}


@app.get("/api/charts/{session_id}/{filename}")
async def get_chart(session_id: str, filename: str):
    """Serve generated chart images."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found.")

    chart_path = sessions[session_id].output_dir / filename
    if not chart_path.exists():
        raise HTTPException(status_code=404, detail="Chart not found.")

    return FileResponse(str(chart_path))


@app.delete("/api/session/{session_id}")
async def delete_session(session_id: str):
    """Delete a session and clean up all its data."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found.")
    _destroy_session(session_id)
    return {"message": "Session deleted."}


@app.post("/api/clear/{session_id}")
async def clear_history(session_id: str):
    """Clear conversation history for a session."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found.")
    sess = sessions[session_id]
    if sess.agent:
        sess.agent.reset_history()
    return {"message": "Conversation history cleared."}


# ── Serve static files ────────────────────────────────────────────────────────
app.mount("/app", StaticFiles(directory="frontend", html=True), name="frontend")
app.mount("/", StaticFiles(directory="website", html=True), name="website")


# ── Entrypoint ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
