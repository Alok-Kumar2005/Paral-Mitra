"""Unit tests for internationalization dictionary parity and formatting."""

import pytest
from src.bot.i18n import STRINGS, t


def test_i18n_key_parity():
    """Verify that all strings defined in English also have Hindi and Punjabi translations."""
    for key, translations in STRINGS.items():
        assert "en" in translations, f"Missing 'en' translation for key {key}"
        assert "hi" in translations, f"Missing 'hi' translation for key {key}"
        assert "pa" in translations, f"Missing 'pa' translation for key {key}"


def test_t_function_fallback_and_formatting():
    # Valid formatting
    res = t("location_saved", lang="en", location="Patiala")
    assert "Patiala" in res

    # Hindi formatting
    res_hi = t("location_saved", lang="hi", location="पटियाला")
    assert "पटियाला" in res_hi

    # Fallback to English when key in requested lang is missing
    assert len(t("welcome", lang="unknown_lang")) > 10
