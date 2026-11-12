# Domain Filter Streamlit

A Streamlit app for screening uploaded domain lists in three modes: **TÄSMÄ**, **LAAJA**, and **BRANDABLES**.

## Letters-only validation

Every hostname label must contain only ASCII letters `a-z`. Digits, hyphens, underscores, symbols and non-ASCII characters cause the **entire original candidate to be rejected**. The parser does not remove invalid characters to manufacture a different domain. The `.` between labels remains valid.

- Accepted: `cat.com`, `catdog.com`, `realm.sh`
- Rejected: `cat2.com`, `cat-dog.com`, `cat_dog.com`, `cät.com`

This applies to all three modes. LAAJA supports one English word or two concatenated dictionary words, but no longer accepts hyphen-separated word combinations.

The app still accepts CSV/TXT/ZIP lists, URL prefixes and paths, and splits .com from other domains. Optional `tldextract` continues to handle multi-part suffixes. Without it, the previous last-two-label fallback remains.

## Run and test

```bash
pip install -r requirements.txt
streamlit run app.py
```

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```
