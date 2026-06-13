"""
Functional smoke test — exercises the core pipeline without needing a Gemini API key.
Tests: data loading, schema extraction, executor sandbox, response parsing, server endpoints.
"""
import sys
sys.path.insert(0, ".")

# ── 1. Data loading ──────────────────────────────────────────────────────────
from data.loader import discover_files, load_multiple

files = discover_files("./test_data")
assert len(files) == 1, f"Expected 1 file, got {len(files)}"
print(f"✓ Discovered {len(files)} file(s)")

dfs = load_multiple(files)
assert "sales" in dfs, f"Expected 'sales' key, got {list(dfs.keys())}"
df = dfs["sales"]
assert df.shape == (8, 4), f"Expected (8,4), got {df.shape}"
print(f"✓ Loaded 'sales' DataFrame: {df.shape}")

# ── 2. Schema extraction ────────────────────────────────────────────────────
from data.schema import extract_all_schemas

schema = extract_all_schemas(dfs)
assert "Dataset: sales" in schema
assert "region" in schema
assert "revenue" in schema
print(f"✓ Schema extracted ({len(schema)} chars)")

# ── 3. System prompt ────────────────────────────────────────────────────────
from agent.prompt import build_system_prompt

prompt = build_system_prompt(dfs, output_dir="./test_output")
assert "<execute>" in prompt
assert "sales" in prompt
assert "EXECUTION RULES" in prompt
assert "quick_bar" in prompt
assert "./test_output" in prompt
print(f"✓ System prompt built ({len(prompt)} chars)")

# ── 4. Executor sandbox ─────────────────────────────────────────────────────
from agent.executor import Executor

executor = Executor(dfs=dfs, output_dir="./test_output")

# Test basic code execution
result = executor.run("x = dfs['sales']['revenue'].mean(); print(f'Mean revenue: {x}')")
assert result.success, f"Expected success, got error: {result.error}"
assert "Mean revenue:" in result.stdout
print(f"✓ Executor ran code successfully: {result.stdout.strip()}")

# Test variable persistence across runs
result2 = executor.run("print(f'Still have x = {x}')")
assert result2.success, f"Expected success, got error: {result2.error}"
assert "Still have x" in result2.stdout
print(f"✓ Executor persists variables: {result2.stdout.strip()}")

# Test error handling
result3 = executor.run("print(1/0)")
assert not result3.success
assert "ZeroDivisionError" in result3.error
print("✓ Executor catches errors with traceback")

# Test plt.savefig (the builtins fix)
result4 = executor.run("""
import matplotlib.pyplot as plt
fig, ax = plt.subplots()
ax.bar(['A', 'B', 'C'], [1, 2, 3])
plt.savefig('./test_output/test_chart.png', bbox_inches='tight', dpi=72)
plt.close()
print('Chart saved')
""")
assert result4.success, f"savefig failed: {result4.error}"
print(f"✓ plt.savefig works in sandbox: {result4.stdout.strip()}")

import os
assert os.path.exists("./test_output/test_chart.png"), "Chart file not created"
print("✓ Chart file exists on disk")

# Test custom quick_bar plotter function
result_plot = executor.run("path = quick_bar(dfs['sales'], 'region', 'sales', title='Test Bar Chart'); print(f'Saved to {path}')")
assert result_plot.success, f"quick_bar failed: {result_plot.error}"
assert os.path.exists("./test_output/bar_region_sales.png"), "Quick bar chart file not created"
print(f"✓ Custom quick_bar works in sandbox: {result_plot.stdout.strip()}")

# ── 5. Response parser ──────────────────────────────────────────────────────
from agent.core import parse_response, extract_thinking

# Test with execute block
resp1 = "Let me check.\n<execute>\nprint(dfs['sales'].shape)\n</execute>"
blocks, answer = parse_response(resp1)
assert len(blocks) == 1
assert answer is None
assert extract_thinking(resp1) == "Let me check."
print("✓ parse_response extracts execute blocks")

# Test with answer block
resp2 = "Here is the answer.\n<answer>The mean revenue is $42,000.</answer>"
blocks, answer = parse_response(resp2)
assert len(blocks) == 0
assert answer == "The mean revenue is $42,000."
assert extract_thinking(resp2) == "Here is the answer."
print("✓ parse_response extracts answer blocks")

# Test with both
resp3 = "<execute>\nprint('hi')\n</execute>\n\n<answer>Done.</answer>"
blocks, answer = parse_response(resp3)
assert len(blocks) == 1
assert answer == "Done."
assert extract_thinking(resp3) is None
print("✓ parse_response handles both execute + answer")

# ── 6. Markdown fence stripping ──────────────────────────────────────────────
from agent.executor import Executor

result5 = executor.run("```python\nprint('fenced')\n```")
assert result5.success
assert "fenced" in result5.stdout
print("✓ Executor strips markdown fences")

# ── 7. Terminal command execution (run_command) ──────────────────────────────
from unittest.mock import patch

# Test run_command with approval
with patch("builtins.input", return_value="y"):
    result_cmd = executor.run("out = run_command('echo Hello Terminal'); print(out.strip())")
assert result_cmd.success, f"run_command failed: {result_cmd.error}"
assert "Hello Terminal" in result_cmd.stdout
print("✓ run_command works with user approval")

# Test run_command with denial
with patch("builtins.input", return_value="n"):
    result_cmd_deny = executor.run("out = run_command('echo Hello Terminal'); print(out.strip())")
assert not result_cmd_deny.success
assert "PermissionError" in result_cmd_deny.error
print("✓ run_command raises PermissionError when denied")

# ── 8. GeminiLLM import & error handling ─────────────────────────────────────
from agent.llm import GeminiLLM, LLMError, CircuitBreaker, CircuitState

# Test LLMError structured exception
try:
    raise LLMError("Test error", model="test-model", attempt=2)
except LLMError as exc:
    assert exc.model == "test-model"
    assert exc.attempt == 2
    assert "Test error" in str(exc)
print("✓ LLMError carries structured context")

# Test CircuitBreaker logic
cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=0.1)
assert cb.allow_request()
assert cb.state == CircuitState.CLOSED

cb.record_success()
assert cb.state == CircuitState.CLOSED

for _ in range(3):
    cb.record_failure()
assert cb.state == CircuitState.OPEN
assert not cb.allow_request()
print("✓ CircuitBreaker opens after threshold failures")

import time
time.sleep(0.15)
assert cb.allow_request()  # should be HALF_OPEN now
assert cb.state == CircuitState.HALF_OPEN

cb.record_success()
assert cb.state == CircuitState.CLOSED
print("✓ CircuitBreaker recovers after cooldown")

# Test GeminiLLM initialization without API key
# Must clear both env var AND override dotenv loading
saved_key = os.environ.pop("GEMINI_API_KEY", None)
os.environ["GEMINI_API_KEY"] = ""  # Set empty to override .env file
try:
    GeminiLLM()
    assert False, "Should have raised EnvironmentError"
except EnvironmentError as exc:
    assert "GEMINI_API_KEY" in str(exc)
finally:
    if saved_key:
        os.environ["GEMINI_API_KEY"] = saved_key
    else:
        os.environ.pop("GEMINI_API_KEY", None)
print("✓ GeminiLLM raises EnvironmentError when API key missing")

# Test input validation (need a dummy API key so we actually reach model validation)
os.environ["GEMINI_API_KEY"] = "test_dummy_key_for_validation"
try:
    GeminiLLM(model="")
except LLMError as exc:
    assert "Invalid model name" in str(exc)
print("✓ GeminiLLM validates model name")

# ── 9. FastAPI endpoint tests ────────────────────────────────────────────────
# Set a dummy API key for server tests (won't actually call Gemini)
os.environ["GEMINI_API_KEY"] = "test_key_for_smoke_test"

from fastapi.testclient import TestClient
from server import app

client = TestClient(app)

# Test root serves landing page
response = client.get("/")
assert response.status_code == 200
print("✓ GET / serves landing page")

# Test /app serves frontend dashboard
response = client.get("/app")
assert response.status_code == 200
print("✓ GET /app serves dashboard")

# Test download endpoints are valid routes
response = client.get("/download/dagent.exe")
assert response.status_code in (200, 404)
response_unix = client.get("/download/dagent")
assert response_unix.status_code in (200, 404)
print("✓ Download routes are valid")

# Test upload with unsupported file
import io
response = client.post(
    "/api/upload",
    files=[("files", ("test.txt", io.BytesIO(b"hello"), "text/plain"))],
)
assert response.status_code == 400
print("✓ Upload rejects unsupported file types")

# Test query without session
response = client.post(
    "/api/query",
    json={"session_id": "nonexistent", "query": "test"},
)
assert response.status_code == 404
print("✓ Query rejects invalid session")

# Test delete nonexistent session
response = client.delete("/api/session/nonexistent")
assert response.status_code == 404
print("✓ Delete rejects nonexistent session")

# Clean up test env var
os.environ.pop("GEMINI_API_KEY", None)

# ── Cleanup ──────────────────────────────────────────────────────────────────
import shutil
shutil.rmtree("./test_output", ignore_errors=True)

print()
print("=" * 50)
print("ALL TESTS PASSED ✓")
print("=" * 50)
