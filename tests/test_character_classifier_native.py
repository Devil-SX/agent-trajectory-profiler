from __future__ import annotations

import importlib

import pytest

from agent_vis.parsers import character_classifier


def test_native_classifier_matches_python_reference_for_core_cases() -> None:
    cases = [
        "",
        "hello world 123",
        "你好abc",
        "A1 \t",
        "９\n?",
        "한글カタカナ漢字 Latin 42\n",
        "emoji🙂mixed１２３",
    ]

    for text in cases:
        assert character_classifier.classify_characters(text) == (
            character_classifier.classify_characters_python_reference(text)
        )


def test_native_classifier_matches_python_reference_for_large_input() -> None:
    text = ("你好abc９ \t?\n한글カタカナ漢字 Latin42 " * 10000).strip()

    assert character_classifier.classify_characters(text) == (
        character_classifier.classify_characters_python_reference(text)
    )


def test_native_classifier_runtime_is_rust_native() -> None:
    assert character_classifier.character_classifier_backend() == "rust_native"


def test_load_native_classifier_raises_helpful_error_when_import_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import_module = importlib.import_module

    def fake_import_module(name: str, package: str | None = None):
        if name == "agent_vis._native":
            raise ImportError("boom")
        return original_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)

    with pytest.raises(RuntimeError, match="agent_vis\\._native"):
        character_classifier._load_native_classifier()
