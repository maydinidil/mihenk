from __future__ import annotations

import json

import pytest
from pydantic import TypeAdapter, ValidationError

from mihenk.capture.models import Method
from mihenk.capture.recipe import Action, ClickSelector, ClickText, Recipe, SelectOption, State
from tests.helpers.pages import ACTION_KINDS, load_expectations


def _monthly_toggle() -> Recipe:
    return Recipe(
        method=Method.RENDER_INTERACT,
        states=[
            State(label="annual"),
            State(label="monthly", actions=[ClickText(text="Monthly")]),
        ],
    )


def test_action_kinds_match_the_trap_page_expectations() -> None:
    kinds = {
        model.model_fields["kind"].default for model in (ClickText, ClickSelector, SelectOption)
    }
    assert kinds == ACTION_KINDS


def test_fetch_recipe_with_two_states_is_refused() -> None:
    with pytest.raises(ValidationError, match="exactly one state"):
        Recipe(method=Method.FETCH, states=[State(label="a"), State(label="b")])


def test_render_recipe_with_two_states_is_refused() -> None:
    with pytest.raises(ValidationError, match="exactly one state"):
        Recipe(method=Method.RENDER, states=[State(label="a"), State(label="b")])


def test_fetch_recipe_with_an_action_is_refused() -> None:
    with pytest.raises(ValidationError, match="no actions"):
        Recipe(
            method=Method.FETCH,
            states=[State(label="default", actions=[ClickText(text="Monthly")])],
        )


def test_render_recipe_with_an_action_is_refused() -> None:
    with pytest.raises(ValidationError, match="no actions"):
        Recipe(
            method=Method.RENDER,
            states=[State(label="default", actions=[ClickSelector(selector="#more")])],
        )


@pytest.mark.parametrize("method", [Method.FETCH, Method.RENDER])
def test_single_plain_state_is_accepted_for_fetch_and_render(method: Method) -> None:
    recipe = Recipe(method=method, states=[State(label="default")])
    assert [state.label for state in recipe.states] == ["default"]


def test_recipe_without_states_is_refused() -> None:
    with pytest.raises(ValidationError):
        Recipe(method=Method.RENDER_INTERACT, states=[])


def test_render_interact_recipe_round_trips() -> None:
    recipe = _monthly_toggle()
    again = Recipe.model_validate_json(recipe.model_dump_json())
    assert again == recipe
    assert isinstance(again.states[1].actions[0], ClickText)


def test_every_action_kind_round_trips_through_json() -> None:
    recipe = Recipe(
        method=Method.RENDER_INTERACT,
        states=[
            State(
                label="all",
                actions=[
                    ClickText(text="Monthly", exact=False),
                    ClickSelector(selector="#more"),
                    SelectOption(selector="select#region", value="eu"),
                ],
            )
        ],
    )
    again = Recipe.model_validate_json(recipe.model_dump_json())
    assert again == recipe
    assert [action.kind for action in again.states[0].actions] == [
        "click_text",
        "click_selector",
        "select_option",
    ]


def test_action_is_chosen_by_its_kind() -> None:
    adapter: TypeAdapter[Action] = TypeAdapter(Action)
    action = adapter.validate_python({"kind": "select_option", "selector": "#r", "value": "eu"})
    assert action == SelectOption(selector="#r", value="eu")
    with pytest.raises(ValidationError):
        adapter.validate_python({"kind": "run_script", "source": "alert(1)"})


def test_unknown_fields_are_refused() -> None:
    with pytest.raises(ValidationError):
        ClickText.model_validate({"text": "Monthly", "wait": 5})
    with pytest.raises(ValidationError):
        Recipe.model_validate({"method": "render", "states": [{"label": "a"}], "extra": 1})


def test_empty_click_text_is_refused() -> None:
    with pytest.raises(ValidationError):
        ClickText(text="")


def test_duplicate_labels_are_refused() -> None:
    with pytest.raises(ValidationError, match="unique"):
        Recipe(
            method=Method.RENDER_INTERACT,
            states=[State(label="monthly"), State(label="monthly")],
        )


@pytest.mark.parametrize(
    "label",
    ["Monthly", "a b", "nul", "con", "com1", "lpt9", "", "-a", "a/b", "a.b", "x" * 65, "monthly\n"],
)
def test_unsafe_state_labels_are_refused(label: str) -> None:
    with pytest.raises(ValidationError, match="unsafe state label"):
        State(label=label)


@pytest.mark.parametrize("label", ["monthly", "annual", "plan-2", "a_b", "nul2", "x" * 64])
def test_safe_state_labels_are_accepted(label: str) -> None:
    assert State(label=label).label == label


def test_a_label_checked_from_json_is_refused_too() -> None:
    with pytest.raises(ValidationError, match="unsafe state label"):
        State.model_validate_json('{"label": "Monthly"}')


def test_the_billing_toggle_expectations_make_a_valid_recipe() -> None:
    states = load_expectations("billing-toggle")["states"]
    recipe = Recipe.model_validate(
        {
            "method": "render_interact",
            "states": [{"label": s["label"], "actions": s["actions"]} for s in states],
        }
    )
    assert json.loads(recipe.model_dump_json())["states"][1]["actions"] == [
        {"kind": "click_text", "text": "Monthly", "exact": True}
    ]


# --- bounds: the limit is accepted, one over is refused ---------------------------------------


def test_a_select_value_of_200_characters_is_accepted_and_201_is_refused() -> None:
    assert len(SelectOption(selector="#r", value="x" * 200).value) == 200
    with pytest.raises(ValidationError, match="at most 200 characters"):
        SelectOption(selector="#r", value="x" * 201)


def test_a_state_of_20_actions_is_accepted_and_21_is_refused() -> None:
    actions = [ClickSelector(selector=f"#step-{n}") for n in range(21)]
    assert len(State(label="many", actions=actions[:20]).actions) == 20
    with pytest.raises(ValidationError, match="at most 20 items"):
        State(label="many", actions=actions)


def test_a_recipe_of_20_states_is_accepted_and_21_is_refused() -> None:
    states = [State(label=f"state-{n}") for n in range(21)]
    recipe = Recipe(method=Method.RENDER_INTERACT, states=states[:20])
    assert len(recipe.states) == 20
    with pytest.raises(ValidationError, match="at most 20 items"):
        Recipe(method=Method.RENDER_INTERACT, states=states)


def test_the_bounds_hold_for_json_too() -> None:
    too_many = {"label": "many", "actions": [{"kind": "click_selector", "selector": "#a"}] * 21}
    with pytest.raises(ValidationError, match="at most 20 items"):
        State.model_validate(too_many)
    with pytest.raises(ValidationError, match="at most 200 characters"):
        SelectOption.model_validate_json(
            json.dumps({"kind": "select_option", "selector": "#r", "value": "x" * 201})
        )
