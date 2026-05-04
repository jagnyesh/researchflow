"""Tests for BoundedDict — Phase 2.3 JSON-bomb defense (Issue #4)."""

import pytest
from pydantic import BaseModel, ValidationError

from app.schemas._types import BoundedDict, bound_dict_size


class _Wrap(BaseModel):
    d: BoundedDict


# --- max_keys boundary ---


def test_dict_at_100_keys_passes():
    d = {f"k{i}": i for i in range(100)}
    assert _Wrap(d=d).d == d


def test_dict_at_101_keys_rejects():
    d = {f"k{i}": i for i in range(101)}
    with pytest.raises(ValidationError):
        _Wrap(d=d)


# --- max_depth boundary ---


def test_nested_5_levels_passes():
    # depth 0: outer; depth 5: innermost. _walk counts entry depth, so this builds
    # to exactly the cap.
    d = {"a": {"b": {"c": {"d": {"e": "leaf"}}}}}
    assert _Wrap(d=d).d == d


def test_nested_6_levels_rejects():
    d = {"a": {"b": {"c": {"d": {"e": {"f": "leaf"}}}}}}
    with pytest.raises(ValidationError):
        _Wrap(d=d)


# --- list-of-dicts respects depth ---


def test_list_inside_dict_walks_depth():
    """List elements count toward depth — prevents bypass via [{'a': {'b': ...}}]."""
    # Outer dict at depth 0; list at depth 1; inner dict at depth 2; etc.
    # Build something that should fail because of list-walked depth.
    d = {"a": [{"b": [{"c": [{"d": "too deep"}]}]}]}
    with pytest.raises(ValidationError):
        _Wrap(d=d)


def test_list_of_many_dicts_respects_keys_at_each_node():
    """Each individual dict must respect max_keys, even inside a list."""
    fat_dict = {f"k{i}": i for i in range(101)}
    d = {"items": [fat_dict]}
    with pytest.raises(ValidationError):
        _Wrap(d=d)


# --- non-dict input passes through to Pydantic's normal type check ---


def test_non_dict_passes_through_then_pydantic_rejects():
    """bound_dict_size returns non-dicts unchanged so Pydantic rejects them."""
    with pytest.raises(ValidationError):
        _Wrap(d="not a dict")


# --- empty dict / single-key dict are fine ---


def test_empty_dict_passes():
    assert _Wrap(d={}).d == {}


def test_single_key_dict_passes():
    assert _Wrap(d={"k": "v"}).d == {"k": "v"}


# --- direct function tests (no Pydantic in the loop) ---


def test_bound_dict_size_returns_dict_unchanged():
    d = {"a": 1, "b": [1, 2, 3]}
    assert bound_dict_size(d) is d


def test_bound_dict_size_custom_caps():
    """Confirm caps are tunable via kwargs (default 100/5; tests use lower values)."""
    with pytest.raises(ValueError, match="max_keys=2"):
        bound_dict_size({"a": 1, "b": 2, "c": 3}, max_keys=2)
    with pytest.raises(ValueError, match="max_depth=1"):
        bound_dict_size({"a": {"b": {"c": "deep"}}}, max_depth=1)
