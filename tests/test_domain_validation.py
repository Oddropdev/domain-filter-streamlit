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


def test_csv_header_domain_column_is_used_even_when_other_websites_appear_first():
    data = (
        "Source URL,Rank,Domain Name,Price\n"
        "https://auctionhouse.com/listing,1,cat.com,12.99\n"
        "https://auctionhouse.com/listing,2,cat123.com,9.99\n"
    ).encode()
    records = list(app.iter_domains_from_text_bytes(data, ".csv"))
    assert records == ["cat.com", "cat123.com"]


def test_csv_without_headers_finds_first_complete_domain_after_id_and_price():
    data = b"123,19.99,cat.com\n124,2.99,cat-name.com\n"
    records = list(app.iter_domains_from_text_bytes(data, ".csv"))
    assert records == ["cat.com", "cat-name.com"]


def test_semicolon_and_tab_delimited_exports_are_supported():
    semicolon = b"id;domain;price\n1;cat.com;19.99\n2;cat123.com;12.99\n"
    tab = b"id\tdomain\tprice\n1\tcat.com\t19.99\n"
    assert list(app.iter_domains_from_text_bytes(semicolon, ".csv")) == ["cat.com", "cat123.com"]
    assert list(app.iter_domains_from_text_bytes(tab, ".csv")) == ["cat.com"]


def test_txt_lines_with_auction_metadata_extract_complete_domain_tokens():
    data = (
        "12345 cat.com $12.99 auction\n"
        "12346 cat123.com $12.99 auction\n"
        "12347 cat-name.com | 3 bids\n"
        "12348 cat_name.com,5.99\n"
        "12349 https://www.dog.com:443/auction 10.00\n"
    ).encode()
    records = list(app.iter_domains_from_text_bytes(data, ".txt"))
    assert records == [
        "cat.com", "cat123.com", "cat-name.com", "cat_name.com",
        "https://www.dog.com:443/auction",
    ]


def test_csv_first_row_is_not_lost_if_it_has_no_header():
    data = b"cat.com,19.99\ndog.com,29.99\n"
    assert list(app.iter_domains_from_text_bytes(data, ".csv")) == ["cat.com", "dog.com"]


def test_auction_export_exact_mode_finds_matches_but_never_repairs_bad_names():
    data = (
        "ID,Price,Domain Name\n"
        "123,19.99,cat.com\n"
        "124,2.99,cat123.com\n"
        "125,2.99,cat-name.com\n"
        "126,2.99,cat_name.com\n"
        "127,2.99,dog.com\n"
    ).encode()
    fi = app.FileItem("auction.csv", ".csv", data)
    with patch.object(app, "_TLDX", None), patch.object(app.st, "progress"), patch.object(app.st, "empty"):
        com, others, processed, count = app.run_filter([fi], {"cat", "dog"}, "exact")
    assert com == ["cat.com", "dog.com"]
    assert others == []
    assert processed == 5
    assert count == 1


def test_quoted_csv_fields_are_supported():
    data = b'"Domain Name","Price"\n"cat.com","12.99"\n"cat123.com","10.00"\n'
    assert list(app.iter_domains_from_text_bytes(data, ".csv")) == ["cat.com", "cat123.com"]


def test_non_domain_prices_are_not_counted_as_candidates():
    data = b"12.99 10.50 no-domains-here\n20.00 5.30\n"
    assert list(app.iter_domains_from_text_bytes(data, ".txt")) == ["", ""]


def test_export_parser_does_not_salvage_domain_substrings():
    data = b"123,cat123.com\n124,cat-name.com\n125,cat_name.com\n126,cat.com\n"
    records = list(app.iter_domains_from_text_bytes(data, ".txt"))
    assert records == ["cat123.com", "cat-name.com", "cat_name.com", "cat.com"]
    assert [parse(x) for x in records] == [(None, None)] * 3 + [("cat", "com")]


def test_namecheap_market_sales_header_uses_name_not_auction_url():
    data = (
        "url,name,endDate,price,startPrice,renewPrice,bidCount\n"
        "https://www.namecheap.com/market/sale/abc123/,dream.film,2026-11-14T16:00:00Z,1.00,1.00,97.98,1\n"
        "https://www.namecheap.com/market/sale/def456/,bank.express,2026-11-15T16:00:00Z,1.00,1.00,19.98,1\n"
        "https://www.namecheap.com/market/sale/ghi789/,marvel78.com,2026-11-15T16:00:00Z,1.00,1.00,19.98,1\n"
        "https://www.namecheap.com/market/sale/jkl987/,brand-name.com,2026-11-15T16:00:00Z,1.00,1.00,19.98,1\n"
    ).encode()
    records = list(app.iter_domains_from_text_bytes(data, ".csv"))
    assert records == [
        "dream.film", "bank.express", "marvel78.com", "brand-name.com",
    ]
    assert "namecheap.com" not in records


def test_namecheap_market_sales_exact_filter_finds_real_domains():
    data = (
        "url,name,endDate,price,startPrice\n"
        "https://www.namecheap.com/market/sale/abc/,dream.film,2026-11-14T16:00:00Z,1.00,1.00\n"
        "https://www.namecheap.com/market/sale/def/,bank.express,2026-11-14T16:00:00Z,1.00,1.00\n"
        "https://www.namecheap.com/market/sale/ghi/,marvel78.com,2026-11-14T16:00:00Z,1.00,1.00\n"
        "https://www.namecheap.com/market/sale/jkl/,brand-name.com,2026-11-14T16:00:00Z,1.00,1.00\n"
    ).encode()
    fi = app.FileItem("Namecheap_Market_Sales.csv", ".csv", data)
    with patch.object(app, "_TLDX", None), patch.object(app.st, "progress"), patch.object(app.st, "empty"):
        com, others, processed, files = app.run_filter(
            [fi], {"dream", "bank", "marvel", "brand"}, "exact"
        )
    assert com == []
    assert others == ["dream.film", "bank.express"]
    assert processed == 4
    assert files == 1
    assert app.st.session_state["last_exact_broad_valid_domains"] == 2


def test_explicit_domain_header_wins_over_generic_name_header():
    data = (
        "url,name,domain,price\n"
        "https://auction.example.com/sale/,auctiontitle.com,cat.com,12.00\n"
    ).encode()
    records = list(app.iter_domains_from_text_bytes(data, ".csv"))
    assert records == ["cat.com"]


def test_unrelated_name_and_url_columns_are_not_assumed_to_be_domains():
    data = (
        "url,name,description\n"
        "https://shop.example.com/item/,My Listing,Not a domain sale\n"
    ).encode()
    records = list(app.iter_domains_from_text_bytes(data, ".csv"))
    assert records == ["shop.example.com", ""]


def test_namecheap_market_sales_header_normalization():
    data = (
        "URL,Name,End Date,Price,Start Price\n"
        "https://www.namecheap.com/market/sale/abc/,news.forum,2026-11-14,1.00,1.00\n"
    ).encode()
    assert list(app.iter_domains_from_text_bytes(data, ".csv")) == ["news.forum"]
