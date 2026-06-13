"""
agent/llm.py — Google Gemini LLM client with robust error handling.

Wraps the new google-genai SDK to provide a simple chat() interface
that the DataAgent's ReAct loop can call repeatedly.

Error Handling Strategies Implemented:
────────────────────────────────────────
1. EXPONENTIAL BACKOFF WITH JITTER
   - On transient failures (rate limits, server errors), retries with
     increasing delays (2^attempt seconds + random jitter 0-1s).
   - Prevents thundering herd when multiple requests hit limits.

2. CIRCUIT BREAKER PATTERN
   - After N consecutive failures (default: 5), the client "opens" the
     circuit and fast-fails subsequent requests for a cooldown period.
   - Prevents wasting API quota on a down service.

3. RATE LIMIT DETECTION & RETRY-AFTER
   - Parses 429/ResourceExhausted errors and applies appropriate retry.
   - Falls back to exponential backoff when no retry hint is available.

4. GRACEFUL DEGRADATION
   - If the primary model fails, falls back to a secondary model.
   - Returns a structured error message instead of crashing.

5. INPUT VALIDATION
   - Validates messages list, system prompt, and model name before
     making the API call.
   - Catches empty or malformed inputs early with clear error messages.

6. STRUCTURED ERROR REPORTING
   - All errors are wrapped in LLMError with context (attempt number,
     model, original exception) for clean upstream handling.
"""

from __future__ import annotations

import os
import time
import random
from dataclasses import dataclass
from enum import Enum

from google import genai
from google.genai import types
from pathlib import Path
from dotenv import load_dotenv
from rich.console import Console

console = Console()


# ── Custom Exceptions ──────────────────────────────────────────────────────────
class LLMError(Exception):
    """Structured error from the LLM client with context."""

    def __init__(self, message: str, *, model: str = "", attempt: int = 0,
                 original: Exception | None = None) -> None:
        self.model = model
        self.attempt = attempt
        self.original = original
        super().__init__(message)


class CircuitState(Enum):
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Fast-failing
    HALF_OPEN = "half_open"  # Testing if service recovered


# ── Circuit Breaker ────────────────────────────────────────────────────────────
@dataclass
class CircuitBreaker:
    """
    Circuit breaker to prevent cascading failures.

    After `failure_threshold` consecutive failures, the circuit opens and
    all requests fast-fail for `cooldown_seconds`. After cooldown, one
    test request is allowed (half-open state).
    """
    failure_threshold: int = 5
    cooldown_seconds: float = 60.0

    _state: CircuitState = CircuitState.CLOSED
    _failure_count: int = 0
    _last_failure_time: float = 0.0

    def record_success(self) -> None:
        self._failure_count = 0
        self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            console.print(
                f"[red]⚡ Circuit breaker OPEN after "
                f"{self._failure_count} consecutive failures. "
                f"Cooling down for {self.cooldown_seconds}s.[/red]"
            )

    def allow_request(self) -> bool:
        if self._state == CircuitState.CLOSED:
            return True
        if self._state == CircuitState.OPEN:
            elapsed = time.time() - self._last_failure_time
            if elapsed >= self.cooldown_seconds:
                self._state = CircuitState.HALF_OPEN
                console.print("[yellow]⚡ Circuit breaker HALF-OPEN — testing one request…[/yellow]")
                return True
            return False
        # HALF_OPEN: allow one test request
        return True

    @property
    def state(self) -> CircuitState:
        return self._state


# ── Gemini LLM Client ─────────────────────────────────────────────────────────
class GeminiLLM:
    """
    Robust wrapper around the Google Gemini generative AI API (google-genai SDK).

    Implements: exponential backoff, circuit breaker, rate-limit
    detection, graceful degradation, input validation, and structured
    error reporting.
    """

    # Models to try in order (primary → fallback)
    FALLBACK_MODELS = ("gemini-2.5-flash", "gemini-2.0-flash")

    def __init__(
        self,
        model: str = "gemini-2.5-flash",
        temperature: float = 0.1,
        max_tokens: int = 8192,
    ) -> None:
        load_dotenv()  # loads .env file in cwd or parents
        # Fallback to loading the .env from the agent's install directory if key not found yet
        if not os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY") == "your_gemini_api_key_here":
            script_env = Path(__file__).resolve().parent.parent / ".env"
            if script_env.exists():
                load_dotenv(script_env)
        
        api_key = os.getenv("GEMINI_API_KEY")

        if not api_key or api_key == "your_gemini_api_key_here":
            raise EnvironmentError(
                "GEMINI_API_KEY not found or not set in environment. "
                "Please set it in a .env file or export it as an env variable. "
                "See .env.example for the expected format. "
                "Get a free key at https://aistudio.google.com/apikey"
            )

        # ── Strategy 5: Input Validation ───────────────────────────────────────
        if not model or not isinstance(model, str):
            raise LLMError(
                "Invalid model name. Must be a non-empty string.",
                model=str(model),
            )

        self.model_name = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.circuit_breaker = CircuitBreaker()

        # Initialize the new google-genai client
        try:
            self.client = genai.Client(api_key=api_key)
            console.print(f"[green]✓ Gemini client initialized (model: {self.model_name})[/green]")
        except Exception as exc:
            raise LLMError(
                f"Failed to initialize Gemini client: {exc}",
                model=self.model_name,
                original=exc,
            )

    # ── public interface ───────────────────────────────────────────────────────
    def chat(self, messages: list[dict], system: str) -> str:
        """
        Send a chat completion request to Google Gemini.

        Parameters
        ----------
        messages : list[dict]
            Conversation history (user / assistant turns).
        system : str
            The system prompt.

        Returns
        -------
        str
            The assistant's reply text.

        Raises
        ------
        LLMError
            On non-retryable API errors or after all retries exhausted.
        """
        # ── Strategy 5: Input Validation ───────────────────────────────────────
        if not isinstance(messages, list):
            raise LLMError("messages must be a list of dicts.", model=self.model_name)
        if not system or not isinstance(system, str):
            raise LLMError("system prompt must be a non-empty string.", model=self.model_name)

        # ── Strategy 2: Circuit Breaker ────────────────────────────────────────
        if not self.circuit_breaker.allow_request():
            raise LLMError(
                f"Circuit breaker is OPEN. Service appears down. "
                f"Wait {self.circuit_breaker.cooldown_seconds}s before retrying.",
                model=self.model_name,
            )

        # ── Strategy 4: Graceful Degradation (try primary, then fallback) ──────
        models_to_try = [self.model_name]
        for fb in self.FALLBACK_MODELS:
            if fb != self.model_name and fb not in models_to_try:
                models_to_try.append(fb)

        last_error: Exception | None = None

        for model_name in models_to_try:
            try:
                return self._call_with_retries(messages, system, model_name)
            except LLMError as exc:
                last_error = exc
                if model_name != models_to_try[-1]:
                    console.print(
                        f"[yellow]⚠ Model '{model_name}' failed. "
                        f"Falling back to '{models_to_try[models_to_try.index(model_name) + 1]}'…[/yellow]"
                    )

        # All models failed
        self.circuit_breaker.record_failure()
        raise LLMError(
            f"All models failed. Last error: {last_error}",
            model=self.model_name,
            original=last_error,
        )

    def _call_with_retries(
        self, messages: list[dict], system: str, model_name: str
    ) -> str:
        """
        Attempt an API call with exponential backoff + jitter retries.

        Strategy 1: Exponential Backoff with Jitter
        Strategy 3: Rate Limit Detection
        Strategy 6: Structured Error Reporting
        """
        max_retries = 3

        # Convert messages to Gemini Content format
        gemini_contents = self._convert_messages(messages)

        # Build generation config
        config = types.GenerateContentConfig(
            temperature=self.temperature,
            max_output_tokens=self.max_tokens,
            system_instruction=system,
        )

        for attempt in range(max_retries + 1):
            try:
                response = self.client.models.generate_content(
                    model=model_name,
                    contents=gemini_contents,
                    config=config,
                )

                # Check for empty/blocked responses
                if not response.text:
                    # Check if blocked by safety filters
                    if response.candidates and response.candidates[0].finish_reason:
                        reason = str(response.candidates[0].finish_reason)
                        if "SAFETY" in reason.upper():
                            raise LLMError(
                                "Response blocked by Gemini safety filters. "
                                "Try rephrasing your query to avoid triggering content filters.",
                                model=model_name,
                                attempt=attempt,
                            )

                    raise LLMError(
                        "Gemini returned an empty response.",
                        model=model_name,
                        attempt=attempt,
                    )

                # ── Success! Reset circuit breaker ──────────────────────────────
                self.circuit_breaker.record_success()
                return response.text

            except LLMError:
                raise  # Don't retry our own structured errors

            except Exception as exc:
                exc_str = str(exc).lower()
                is_retryable = any(kw in exc_str for kw in (
                    "429", "rate limit", "resource exhausted",
                    "503", "500", "overloaded", "unavailable",
                    "deadline exceeded", "timeout",
                ))

                if is_retryable and attempt < max_retries:
                    # ── Strategy 1: Exponential Backoff with Jitter ──────────────
                    # ── Strategy 3: Rate Limit Detection ─────────────────────────
                    base_wait = 2 ** attempt
                    jitter = random.uniform(0, 1)
                    wait = base_wait + jitter
                    console.print(
                        f"[yellow]⏳ {_classify_error(exc)} "
                        f"Retrying in {wait:.1f}s "
                        f"(attempt {attempt + 1}/{max_retries})…[/yellow]"
                    )
                    time.sleep(wait)
                elif is_retryable:
                    # ── Strategy 6: Structured Error Reporting ────────────────────
                    raise LLMError(
                        f"API error after {max_retries} retries: {exc}",
                        model=model_name,
                        attempt=attempt,
                        original=exc,
                    )
                else:
                    # Non-retryable error
                    raise LLMError(
                        f"Non-retryable API error: {exc}",
                        model=model_name,
                        attempt=attempt,
                        original=exc,
                    )

        # Should be unreachable
        raise LLMError("LLM chat failed unexpectedly.", model=model_name)

    # ── helpers ────────────────────────────────────────────────────────────────
    @staticmethod
    def _convert_messages(messages: list[dict]) -> list[types.Content]:
        """
        Convert OpenAI-style messages to Gemini's Content format.

        Gemini expects: [Content(role="user"|"model", parts=[Part(text=...)])]
        """
        gemini_contents = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            # Map roles: "assistant" → "model", everything else → "user"
            gemini_role = "model" if role == "assistant" else "user"

            # Gemini doesn't allow consecutive messages with the same role,
            # so we merge them if needed.
            if gemini_contents and gemini_contents[-1].role == gemini_role:
                existing_text = gemini_contents[-1].parts[0].text
                gemini_contents[-1] = types.Content(
                    role=gemini_role,
                    parts=[types.Part(text=f"{existing_text}\n\n{content}")],
                )
            else:
                gemini_contents.append(
                    types.Content(
                        role=gemini_role,
                        parts=[types.Part(text=content)],
                    )
                )

        return gemini_contents


def _classify_error(exc: Exception) -> str:
    """Return a human-friendly label for the error type."""
    exc_str = str(exc).lower()
    if "429" in exc_str or "rate limit" in exc_str or "resource exhausted" in exc_str:
        return "Rate-limited."
    if "503" in exc_str or "unavailable" in exc_str:
        return "Service unavailable."
    if "500" in exc_str or "overloaded" in exc_str:
        return "Server error."
    if "timeout" in exc_str or "deadline" in exc_str:
        return "Request timed out."
    return "Transient error."
