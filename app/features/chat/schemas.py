"""Pydantic schemas for the event AI chatbot."""

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    """An attendee's question about an event."""

    question: str = Field(min_length=1, max_length=1000)

    @field_validator("question")
    @classmethod
    def _strip_question(cls, value: str) -> str:
        """Trim surrounding whitespace and reject blank questions."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("Question must not be blank")
        return stripped


class ChatResponse(BaseModel):
    """The chatbot's answer plus the caller's remaining question quota."""

    answer: str
    generated_by_ai: bool
    questions_remaining: int
