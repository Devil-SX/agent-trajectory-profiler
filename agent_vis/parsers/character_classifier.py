"""Character classification runtime wrapper backed by the required native extension."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import cast

Classifier = Callable[[str], tuple[int, int, int, int, int]]


def classify_characters_python_reference(text: str) -> tuple[int, int, int, int, int]:
    """Reference Python implementation kept for parity testing."""
    cjk_count = 0
    latin_count = 0
    digit_count = 0
    whitespace_count = 0
    other_count = 0

    for char in text:
        code_point = ord(char)

        if code_point <= 0x7F:
            if code_point in {9, 10, 11, 12, 13, 32}:
                whitespace_count += 1
            elif 48 <= code_point <= 57:
                digit_count += 1
            elif 65 <= code_point <= 90 or 97 <= code_point <= 122:
                latin_count += 1
            else:
                other_count += 1
            continue

        if (
            0x4E00 <= code_point <= 0x9FFF
            or 0x3400 <= code_point <= 0x4DBF
            or 0x3040 <= code_point <= 0x30FF
            or 0xAC00 <= code_point <= 0xD7AF
        ):
            cjk_count += 1
        elif char.isspace():
            whitespace_count += 1
        elif char.isdigit():
            digit_count += 1
        else:
            other_count += 1

    return cjk_count, latin_count, digit_count, whitespace_count, other_count


def _load_native_classifier() -> Classifier:
    try:
        native_module = importlib.import_module("agent_vis._native")
    except ImportError as exc:
        raise RuntimeError(
            "Failed to import required native character classifier 'agent_vis._native'. "
            "Reinstall the package so the Rust extension is built for this environment."
        ) from exc

    classifier = getattr(native_module, "classify_characters", None)
    if classifier is None:
        raise RuntimeError(
            "Native character classifier module 'agent_vis._native' does not expose "
            "'classify_characters'. Reinstall the package to restore the compiled extension."
        )
    return cast(Classifier, classifier)


_NATIVE_CLASSIFIER = _load_native_classifier()


def character_classifier_backend() -> str:
    return "rust_native"


def classify_characters(text: str) -> tuple[int, int, int, int, int]:
    cjk, latin, digit, whitespace, other = _NATIVE_CLASSIFIER(text)
    return int(cjk), int(latin), int(digit), int(whitespace), int(other)


__all__ = [
    "character_classifier_backend",
    "classify_characters",
    "classify_characters_python_reference",
]
