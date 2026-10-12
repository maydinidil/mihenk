"""Recipes: how to capture a page and which states to capture (design §8.3). Data, not code."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mihenk.capture.models import SAFE_SEGMENT, Method


class ClickText(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["click_text"] = "click_text"
    text: str = Field(min_length=1, max_length=200)
    exact: bool = True


class ClickSelector(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["click_selector"] = "click_selector"
    selector: str = Field(min_length=1, max_length=500)


class SelectOption(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["select_option"] = "select_option"
    selector: str = Field(min_length=1, max_length=500)
    value: str = Field(max_length=200)


Action = Annotated[ClickText | ClickSelector | SelectOption, Field(discriminator="kind")]


class State(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    label: str
    actions: list[Action] = Field(default_factory=list, max_length=20)

    @field_validator("label")
    @classmethod
    def _label_is_a_safe_segment(cls, label: str) -> str:
        # Checked here and not with `Field(pattern=...)`: pydantic's regex engine has neither the
        # lookahead nor `\Z`, and `SAFE_SEGMENT` stays the one pattern for every folder name.
        if SAFE_SEGMENT.fullmatch(label) is None:
            raise ValueError("unsafe state label")
        return label


class Recipe(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    method: Method
    states: list[State] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def _rules(self) -> Recipe:
        labels = [state.label for state in self.states]
        if len(set(labels)) != len(labels):
            raise ValueError("state labels must be unique")
        if self.method is not Method.RENDER_INTERACT and (
            len(self.states) != 1 or self.states[0].actions
        ):
            raise ValueError(f"a {self.method.value} recipe has exactly one state and no actions")
        return self
