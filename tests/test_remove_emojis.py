"""Regression tests for scripts/remove_emojis.py (#470).

The catch-all emoji pattern used to span U+24C2 to U+1F251, which also
matched ordinary text such as CJK ideographs and Cyrillic letters.
"""

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "remove_emojis", Path(__file__).parent.parent / "scripts" / "remove_emojis.py"
)
remove_emojis = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(remove_emojis)


def _clean(tmp_path, text):
    f = tmp_path / "doc.md"
    f.write_text(text, encoding="utf-8")
    remove_emojis.remove_emojis_from_file(f.resolve())
    return f.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "text",
    ["患者 cohort", "Привет world", "café naïve", "price €5 → ok", "box ─ drawing"],
)
def test_non_emoji_text_is_preserved(tmp_path, monkeypatch, text):
    monkeypatch.chdir(tmp_path)
    assert _clean(tmp_path, text + "\n") == text + "\n"


@pytest.mark.parametrize(
    "emoji",
    [
        "\U0001f600",  # emoticon
        "\U0001f4a9",  # pictograph (not in the replacement map)
        "\U0001f6a2",  # transport
        "\U0001f1fa\U0001f1f8",  # regional-indicator flag
        "✂",  # dingbat scissors
        "Ⓜ",  # circled M
        "\U0001f170",  # negative squared A
        "\U0001f251",  # circled ideograph accept
        "\u26a1",  # high voltage
        "\u2611",  # ballot box with check
        "\u26d4",  # no entry
        "\u25b6",  # play button
        "\u2b06",  # up arrow emoji
        "\u2b55",  # hollow red circle
        "\u267b",  # recycling
        "\u2615",  # hot beverage
        "\u3297",  # circled ideograph congratulation
        "\U0001f004",  # mahjong red dragon
        "\U0001f0cf",  # joker card
    ],
)
def test_emoji_is_removed(tmp_path, monkeypatch, emoji):
    monkeypatch.chdir(tmp_path)
    assert _clean(tmp_path, f"a{emoji}b\n") == "ab\n"


def test_variation_selector_is_removed_with_its_emoji(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert _clean(tmp_path, "a\u2702\ufe0fb\n") == "ab\n"
