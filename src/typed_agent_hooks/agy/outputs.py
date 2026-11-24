"""Strict Antigravity CLI (`agy`) command-hook output schemas."""

from typing import Literal, TypeAlias

from pydantic import Field, model_validator

from typed_agent_hooks.core import Json, StrictModel


class SystemMessageStep(StrictModel):
    """A system message that the model reads. agy 1.5.16 shows it to the user
    only as a collapsed row, and drops a step that sets the documented
    ``metadata.user_markdown``, so the model never sees it."""

    system_message: str = Field(serialization_alias="systemMessage")


class ErrorMessageStep(StrictModel):
    """An error that agy shows to the user and does not send to the model.
    ``agy -p`` exits 3 after a turn that ends with one."""

    user_message: str = Field(serialization_alias="userMessage")


class InjectStep(StrictModel):
    """One step that agy adds to the conversation."""

    system_message: SystemMessageStep | None = Field(
        default=None, serialization_alias="systemMessage"
    )
    error_message: ErrorMessageStep | None = Field(default=None, serialization_alias="errorMessage")

    @model_validator(mode="after")
    def _one_kind(self) -> "InjectStep":
        if (self.system_message is None) == (self.error_message is None):
            raise ValueError("an inject step holds exactly one of systemMessage and errorMessage")
        return self


class SessionStartOutput(StrictModel):
    inject_steps: list[InjectStep] = Field(serialization_alias="injectSteps")


class PreInvocationOutput(StrictModel):
    inject_steps: list[InjectStep] = Field(serialization_alias="injectSteps")
    # "terminate" ends the turn before the model call.
    termination_behavior: Literal["terminate"] | None = Field(
        default=None, serialization_alias="terminationBehavior"
    )


class PreToolUseOutput(StrictModel):
    decision: Literal["allow", "deny"]
    reason: str | None = None
    # agy merges these keys into the tool call's arguments (a shallow merge).
    overwrite: dict[str, Json] | None = None


class StopOutput(StrictModel):
    # "continue" keeps the turn going; agy injects the reason as a system message.
    decision: Literal["continue"]
    reason: str


StructuredOutput: TypeAlias = (
    SessionStartOutput | PreInvocationOutput | PreToolUseOutput | StopOutput
)
HookResult: TypeAlias = StructuredOutput | None
