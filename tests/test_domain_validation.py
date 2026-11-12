"""Regression tests: reject non-letter domain names without repairing them."""
from unittest.mock import patch

import app


def parse(value: str):
    # Keep the fallback parser test deterministic even without public-suffix data.
    with patch.object(app, "_TLDX", None):
        return app.get_sld_and_tld(value)


def test_valid_domains_and_urls():
    assert parse("Example.COM") == ("example", "com")
    assert parse("https://www.realm.sh/path?q=1") == ("realm", "sh")
    assert parse("https://cat.com:443/path") == ("cat", "com")
    assert parse("http://cat.com:8080?q=1") == ("cat", "com")
    assert parse("safe.co.uk") == ("co", "uk")  # pre-existing no-PSL fallback


def test_invalid_names_are_rejected_instead_of_modified():
    for bad in [
        "brand123.com", "brand-name.com", "brand_name.com",
        "brand+name.com", "näme.com", "abc..com", "brand.com-xyz",
        "123.brand.com", "x.com_foo", "br!and.com", "brand.c0m",
        "ｂｒａｎｄ.com", "https://cat123.com:443/path",
        "https://cat.com:invalid/path",
    ]:
        assert parse(bad) == (None, None), bad


def test_broad_mode_cannot_reintroduce_hyphens_or_digits():
    words = {"cat", "dog", "catdog"}
    assert app.is_exact_word("cat", words)
    assert app.is_valid_english_combo("catdog", words)
    assert not app.is_valid_english_combo("cat-dog", words)
    assert not app.is_valid_english_combo("cat123", words)
    assert not app.is_exact_word("cat7", words)


def test_brandables_direct_calls_reject_non_letters():
    settings = {"min_len": 3, "max_len": 12}
    for bad in ["b2b", "two-words", "bränd", "foo_bar"]:
        score, _ = app.brandability_score(bad, settings)
        assert score == -999


def test_broad_pipeline_never_emits_rewritten_names():
    data = b"catdog.com\ncat-dog.com\ncat123.com\ncat_dog.com\n"
    fi = app.FileItem("batch.txt", ".txt", data)
    with patch.object(app, "_TLDX", None), patch.object(app.st, "progress"), patch.object(app.st, "empty"):
        com, other, _, _ = app.run_filter([fi], {"cat", "dog", "catdog"}, "broad")
    assert com == ["catdog.com"]
    assert other == []


def test_exact_pipeline_never_emits_rewritten_names():
    data = b"cat.com\ncat123.com\ncat-.com\ncat_dog.com\n"
    fi = app.FileItem("batch.txt", ".txt", data)
    with patch.object(app, "_TLDX", None), patch.object(app.st, "progress"), patch.object(app.st, "empty"):
        com, other, _, _ = app.run_filter([fi], {"cat"}, "exact")
    assert com == ["cat.com"]
    assert other == []


def test_brandables_pipeline_rejects_invalid_names_before_scoring():
    data = b"maven.com\nma-ven.com\nmaven123.com\nma_ven.com\n"
    fi = app.FileItem("batch.txt", ".txt", data)
    settings = {
        "score_threshold": -1000,
        "min_len": 3, "max_len": 12,
        "vowel_min": 0.2, "vowel_max": 0.8,
        "max_consonant_run": 5, "min_unique_chars": 1,
        "reject_repeats": False, "reject_dictionary_words": False,
        "allowed_run_patterns": set(),
        "strict_brandables": False, "max_rare_letters": 2,
    }
    with patch.object(app, "_TLDX", None), patch.object(app.st, "progress"), patch.object(app.st, "empty"):
        com, other, _, _ = app.run_brandables([fi], set(), settings)
    assert [domain for domain, _, _ in com] == ["maven.com"]
    assert other == []
