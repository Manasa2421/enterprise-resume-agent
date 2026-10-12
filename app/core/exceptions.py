"""Typed application errors. Each maps to a stable error code and HTTP status."""


class AppError(Exception):
    code = "internal_error"
    status_code = 500
    message = "An unexpected error occurred."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message


class AgentExecutionError(AppError):
    code = "agent_failure"
    status_code = 502
    message = "A resume generation agent failed to complete."

    def __init__(self, agent: str) -> None:
        super().__init__(f"Agent '{agent}' failed to complete.")
        self.agent = agent


class PipelineTimeoutError(AppError):
    code = "pipeline_timeout"
    status_code = 504
    message = "Resume generation exceeded the allowed processing time."


class LLMError(Exception):
    """Raised by LLM clients; agents catch this and fall back to deterministic logic."""
