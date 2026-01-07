# app.py
import io
import re
import csv
import zipfile
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple, List, Dict, Set

import streamlit as st

# Optional: parempi TLD-parsinta (co.uk jne.)
try:
    import tldextract
    _TLDX = tldextract.TLDExtract(cache_dir=False)  # nopea, ei levycachea
except Exception:
    _TLDX = None

WORDLIST_FILE = "words_alpha.txt"

# -------------------- WORDLIST --------------------
@st.cache_resource
def load_words(path: str) -> set[str]:
    with open(path, "r", encoding="utf-8") as f:
        return set(w.strip().lower() for w in f if len(w.strip()) > 2)

# -------------------- DOMAIN PARSING --------------------
def get_sld_and_tld(domain: str) -> Tuple[Optional[str], Optional[str]]:
    d = domain.strip().lower().replace('"', "")
    d = re.sub(r"^https?://", "", d)
    if d.startswith("www."):
        d = d[4:]

    if _TLDX is not None:
        ext = _TLDX(d)
        if not ext.domain or not ext.suffix:
            return None, None
        sld = ext.domain
        tld = ext.suffix
    else:
        parts = d.split(".")
        if len(parts) < 2:
            return None, None
        tld = parts[-1]
        sld = parts[-2]

    # Puhdista sld kaikesta paitsi a-z ja -
    sld_clean = re.sub(r"[^a-z\-]", "", sld)
    if not sld_clean or not tld:
        return None, None
    return sld_clean, tld

# -------------------- MATCH MODES --------------------
def is_exact_word(sld: str, word_set: set[str]) -> bool:
    """Täsmäosuma: vain yksi sana, ei väliviivaa eikä yhdistelmiä."""
    if not sld or "-" in sld:
        return False
    return sld in word_set

def is_valid_english_combo(sld: str, word_set: set[str]) -> bool:
    """Laaja: yksi sana, väliviiva-yhdistelmä, tai kahden sanan concat."""
    if not sld:
        return False

    # 1) Yksi sana
    if sld in word_set:
        return True

    # 2) Väliviiva (word-word)
    if "-" in sld:
        parts = [p for p in sld.split("-") if p]
        if len(parts) >= 2 and all(p in word_set for p in parts):
            return True

    # 3) Kahden sanan concat (wordword)
    for i in range(3, len(sld) - 2):
        if sld[:i] in word_set and sld[i:] in word_set:
            return True

    return False

# -------------------- INPUT READING --------------------
def iter_domains_from_text_bytes(data: bytes, suffix: str) -> Iterable[str]:
    # Domain oletetaan ensimmäiseksi sarakkeeksi (CSV) tai rivin alkuun (TXT)
    text = data.decode("utf-8", errors="ignore")

    if suffix.lower() == ".csv":
        reader = csv.reader(io.StringIO(text))
        for row in reader:
            if not row:
                continue
            yield row[0].strip()
    else:
        for line in text.splitlines():
            raw = line.strip()
            if not raw:
                continue
            yield raw.split(",")[0].strip()

@dataclass
class FileItem:
    name: str
    suffix: str
    data: bytes

def collect_inputs(uploaded_files) -> List[FileItem]:
    items: List[FileItem] = []

    # Jos yksi zip on annettu, puretaan siitä
    if len(uploaded_files) == 1 and uploaded_files[0].name.lower().endswith(".zip"):
        zdata = uploaded_files[0].getvalue()
        with zipfile.ZipFile(io.BytesIO(zdata), "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = info.filename.split("/")[-1]
                if not name:
                    continue
                lower = name.lower()
                if lower.endswith(".csv") or lower.endswith(".txt"):
                    items.append(
                        FileItem(
                            name=name,
                            suffix="." + lower.split(".")[-1],
                            data=zf.read(info),
                        )
                    )
    else:
        for uf in uploaded_files:
            lower = uf.name.lower()
            if lower.endswith(".csv") or lower.endswith(".txt"):
                suffix = "." + lower.split(".")[-1]
                items.append(FileItem(name=uf.name, suffix=suffix, data=uf.getvalue()))

    # Aakkosjärjestys (päivämääränimillä tämä == kronologinen)
    items.sort(key=lambda x: x.name)
    return items

# -------------------- STANDARD FILTER (EXACT/BROAD) --------------------
def run_filter(files: List[FileItem], words: set[str], mode: str):
    """
    mode:
      - "exact": vain täsmäsanat
      - "broad": sana / sana-sana / sanasana
    """
    results_com: List[str] = []
    results_others: List[str] = []
    seen: set[str] = set()

    total_lines_est = max(1, sum(max(1, f.data.count(b"\n")) for f in files))
    processed = 0

    progress = st.progress(0)
    status = st.empty()

    for fi in files:
        status.write(f"Käsitellään: **{fi.name}**")
        for raw in iter_domains_from_text_bytes(fi.data, fi.suffix):
            processed += 1
            if processed % 5000 == 0:
                progress.progress(min(1.0, processed / total_lines_est))

            sld, tld = get_sld_and_tld(raw)
            if not sld or not tld:
                continue

            full = f"{sld}.{tld}"
            if full in seen:
                continue

            ok = is_exact_word(sld, words) if mode == "exact" else is_valid_english_combo(sld, words)
            if not ok:
                continue

            seen.add(full)
            if tld == "com":
                results_com.append(full)
            else:
                results_others.append(full)

    progress.progress(1.0)
    status.write("Valmis.")
    return results_com, results_others, processed, len(files)

def render_results(results_com: List[str], results_others: List[str], processed_lines: int, processed_files: int, label: str):
    st.subheader(f"Tulokset ({label})")
    st.write(f"Käsitelty tiedostoja: **{processed_files}**")
    st.write(f"Käsitelty rivejä (arvioitu domain-riveiksi): **{processed_lines}**")
    st.write(f"Löydetyt .com: **{len(results_com)}**")
    st.write(f"Löydetyt muut: **{len(results_others)}**")

    com_text = "\n".join(results_com).encode("utf-8")
    others_text = "\n".join(results_others).encode("utf-8")

    st.download_button(
        f"Lataa results_com_{label}.txt",
        data=com_text,
        file_name=f"results_com_{label}.txt",
        mime="text/plain",
    )
    st.download_button(
        f"Lataa results_others_{label}.txt",
        data=others_text,
        file_name=f"results_others_{label}.txt",
        mime="text/plain",
    )

    with st.expander("Näytä esikatselu (ensimmäiset 200)"):
        st.write("**.com**")
        st.code("\n".join(results_com[:200]))
        st.write("**others**")
        st.code("\n".join(results_others[:200]))

# -------------------- BRANDABLES --------------------
VOWELS = set("aeiouy")

# Täysi C/V-kuvio (ei tiivistetty): reseptit 4–8 kirjaimeen
# Esim. nanovian (8): n a n o v i a n -> C V C V C V V C = CVCVCVVC
DEFAULT_ALLOWED_RUN_PATTERNS = [
    # 4
    "CVCV", "CVVC", "VCCV", "VCVC",

    # 5
    "CVCVC", "CVCCV", "CVCVV", "VCVCV", "VCCVC",

    # 6
    "CVCVCV", "CVCVVC", "CVCCVC", "CVCCVV", "VCVCVC", "VCCVCV",

    # 7
    "CVCVCVC", "CVCVVCV", "CVCVCVV", "CVCCVCV", "CVCCVVC", "VCCVCVC",

    # 8 (sis. nanovian = CVCVCVVC)
    "CVCVCVCV", "CVCVCVVC", "CVCVVCVC", "CVCCVCVC", "CVCCVVCV", "VCCVCVCV",
]

# Tiukennukset: harvinaiset kirjaimet ja huonot bigramit
RARE_LETTERS = set("qxzj")
DISALLOW_START = set("qx")
DISALLOW_END = set("qx")
BAD_BIGRAMS = {
    "qx", "xq", "qj", "jq", "qz", "zq",
    "wx", "xw", "vj", "jv", "zx", "xz",
    "qh", "qk", "qc", "qg", "qt", "qd", "qb",
}

def cv_full_pattern(s: str) -> str:
    """Täysi C/V-kuvio (ei tiivistystä). Esim. 'boon' -> CVVC."""
    return "".join("V" if ch in VOWELS else "C" for ch in s)

def has_repeated_chunk(s: str, chunk_min: int = 2, repeats: int = 3) -> bool:
    """Etsii toistuvia paloja (kakaka/akakaka)."""
    for n in range(chunk_min, min(4, len(s) // repeats) + 1):
        if re.search(rf"(.{{{n}}})\1{{{repeats-1},}}", s):
            return True
    return False

def brandability_score(s: str, settings: Dict) -> Tuple[int, str]:
    """
    Palauttaa (score, run_pattern). Score korkeampi = parempi.
    run_pattern on TÄYSI C/V-kuvio.
    """
    s = s.lower()

    if not s.isalpha():
        return -999, ""
    if len(s) < settings["min_len"] or len(s) > settings["max_len"]:
        return -999, ""

    # Ei väliviivoja brandables-tilassa
    if "-" in s:
        return -999, ""

    # Jos halutaan nimenomaan ei-sanakirjaisia, hylätään oikeat sanat
    if settings["reject_dictionary_words"] and s in settings["words"]:
        return -999, ""

    # ---- STRICT: hylkää q/x/z/j ja rumat bigramit ----
    rare_count = sum(1 for ch in s if ch in RARE_LETTERS)
    if rare_count > settings["max_rare_letters"]:
        return -999, ""

    if settings["strict_brandables"]:
        if s[0] in DISALLOW_START or s[-1] in DISALLOW_END:
            return -999, ""
        if any((s[i:i+2] in BAD_BIGRAMS) for i in range(len(s) - 1)):
            return -999, ""

    # Kova hylkäys: 3 samaa peräkkäin
    if re.search(r"(.)\1\1", s):
        return -999, ""

    # Kova hylkäys: tavutoisto
    if settings["reject_repeats"] and has_repeated_chunk(s, chunk_min=2, repeats=3):
        return -999, ""

    # Liian pieni diversiteetti (esim. {a,k})
    if len(set(s)) < settings["min_unique_chars"]:
        return -999, ""

    run_pat = cv_full_pattern(s)

    # Runko-rajoitin (täysi kuvio)
    allowed: Set[str] = settings["allowed_run_patterns"]
    if allowed and run_pat not in allowed:
        return -50, run_pat

    score = 0

    # Pituusbonus
    if 5 <= len(s) <= 9:
        score += 12
    elif 4 <= len(s) <= 11:
        score += 6
    else:
        score -= 8

    # Pehmeä penalti harvinaisille kirjaimille (vaikka sallittaisiin)
    score -= 10 * rare_count

    # Vokaalisuhde
    vcount = sum(1 for c in s if c in VOWELS)
    v_ratio = vcount / len(s)
    if settings["vowel_min"] <= v_ratio <= settings["vowel_max"]:
        score += 25
    elif (settings["vowel_min"] - 0.08) <= v_ratio <= (settings["vowel_max"] + 0.08):
        score += 10
    else:
        score -= 18

    # Konsonanttijonot
    max_run = settings["max_consonant_run"]
    if re.search(rf"[^{''.join(VOWELS)}]{{{max_run+1},}}", s):
        score -= 30
    elif re.search(rf"[^{''.join(VOWELS)}]{{{max_run},}}", s):
        score -= 12

    # Monotoninen CV-vuorottelu pitkästi (kakakaka)
    full_pat = run_pat  # täysi kuvio
    if re.search(r"(CV){4,}", full_pat) or re.search(r"(VC){4,}", full_pat):
        score -= 18

    # Bonus resepteille 4–8 (sis. nanovian = CVCVCVVC)
    if run_pat in {
        # 4
        "CVCV", "CVVC", "VCCV", "VCVC",
        # 5
        "CVCVC", "CVCCV", "CVCVV", "VCVCV", "VCCVC",
        # 6
        "CVCVCV", "CVCVVC", "CVCCVC", "CVCCVV", "VCVCVC", "VCCVCV",
        # 7
        "CVCVCVC", "CVCVVCV", "CVCVCVV", "CVCCVCV", "CVCCVVC", "VCCVCVC",
        # 8
        "CVCVCVCV", "CVCVCVVC", "CVCVVCVC", "CVCCVCVC", "CVCCVVCV", "VCCVCVCV",
    }:
        score += 6

    return score, run_pat

def run_brandables(files: List[FileItem], words: set[str], settings: Dict):
    # talletetaan words settingsiin (jotta voidaan reject_dictionary_words)
    settings = dict(settings)
    settings["words"] = words

    results_com = []     # list of (domain, score, run_pat)
    results_others = []  # list of (domain, score, run_pat)
    seen: set[str] = set()

    total_lines_est = max(1, sum(max(1, f.data.count(b"\n")) for f in files))
    processed = 0

    progress = st.progress(0)
    status = st.empty()

    for fi in files:
        status.write(f"Käsitellään: **{fi.name}**")
        for raw in iter_domains_from_text_bytes(fi.data, fi.suffix):
            processed += 1
            if processed % 5000 == 0:
                progress.progress(min(1.0, processed / total_lines_est))

            sld, tld = get_sld_and_tld(raw)
            if not sld or not tld:
                continue

            full = f"{sld}.{tld}"
            if full in seen:
                continue

            score, run_pat = brandability_score(sld, settings)
            if score < settings["score_threshold"]:
                continue

            seen.add(full)
            item = (full, score, run_pat)
            if tld == "com":
                results_com.append(item)
            else:
                results_others.append(item)

    # Paras ensin
    results_com.sort(key=lambda x: x[1], reverse=True)
    results_others.sort(key=lambda x: x[1], reverse=True)

    progress.progress(1.0)
    status.write("Valmis.")
    return results_com, results_others, processed, len(files)

def render_brandables(res_com, res_oth, processed_lines: int, processed_files: int, include_score: bool):
    st.subheader("Tulokset (brandables)")
    st.write(f"Käsitelty tiedostoja: **{processed_files}**")
    st.write(f"Käsitelty rivejä (arvioitu domain-riveiksi): **{processed_lines}**")
    st.write(f"Löydetyt .com: **{len(res_com)}**")
    st.write(f"Löydetyt muut: **{len(res_oth)}**")

    def to_text(rows):
        if include_score:
            # domain<TAB>score<TAB>run_pattern
            return "\n".join([f"{d}\t{sc}\t{pat}" for (d, sc, pat) in rows]).encode("utf-8")
        return "\n".join([d for (d, _, _) in rows]).encode("utf-8")

    st.download_button(
        "Lataa results_com_brandables.txt",
        data=to_text(res_com),
        file_name="results_com_brandables.txt",
        mime="text/plain",
    )
    st.download_button(
        "Lataa results_others_brandables.txt",
        data=to_text(res_oth),
        file_name="results_others_brandables.txt",
        mime="text/plain",
    )

    with st.expander("Näytä esikatselu (top 100)"):
        st.write("**.com**")
        st.code("\n".join([f"{d}  (score={sc}, {pat})" for (d, sc, pat) in res_com[:100]]))
        st.write("**others**")
        st.code("\n".join([f"{d}  (score={sc}, {pat})" for (d, sc, pat) in res_oth[:100]]))

# -------------------- UI --------------------
def main():
    st.set_page_config(page_title="Domain Filter", layout="centered")
    st.title("Domain-seulonta (Streamlit)")
    st.caption("Upload: useita .csv/.txt tai yksi .zip (sisällä .csv/.txt). Tuloksena .com ja muut erikseen.")

    try:
        words = load_words(WORDLIST_FILE)
    except FileNotFoundError:
        st.error(f"Puuttuu {WORDLIST_FILE} samasta kansiosta kuin app.py")
        st.stop()

    st.write(f"Sanalista ladattu: **{len(words)}** sanaa")

    uploaded = st.file_uploader(
        "Lataa tiedostot",
        type=["csv", "txt", "zip"],
        accept_multiple_files=True,
    )
    if not uploaded:
        st.stop()

    files = collect_inputs(uploaded)
    if not files:
        st.warning("Ei kelvollisia .csv/.txt tiedostoja (tai zipissä ei ollut niitä).")
        st.stop()

    st.write(f"Tiedostoja käsittelyyn: **{len(files)}** (aakkosjärjestyksessä)")

    st.markdown("### Ajotavat")

    with st.expander("Brandables-asetukset", expanded=False):
        score_threshold = st.slider("Score-kynnys", min_value=-20, max_value=80, value=20, step=1)

        # Oletukset 4–8
        min_len = st.slider("Min pituus", 3, 12, 4, 1)
        max_len = st.slider("Max pituus", 4, 20, 8, 1)
        if max_len < min_len:
            max_len = min_len

        vowel_min = st.slider("Vokaalisuhde min", 0.10, 0.70, 0.33, 0.01)
        vowel_max = st.slider("Vokaalisuhde max", 0.20, 0.85, 0.60, 0.01)
        max_consonant_run = st.slider("Max konsonanttijono (C-run)", 2, 5, 3, 1)
        min_unique_chars = st.slider("Min uniikkeja kirjaimia", 3, 8, 5, 1)
        reject_repeats = st.checkbox("Hylkää toistot (akakaka-tyyppiset)", value=True)
        reject_dictionary_words = st.checkbox("Hylkää oikeat sanakirjasanat (etsi vain 'keksittyjä')", value=False)

        strict_brandables = st.checkbox("Strict brandables (hylkää q/x/z/j ja rumat bigramit)", value=True)
        max_rare_letters = st.slider(
            "Max harvinaisia kirjaimia (q/x/z/j)",
            min_value=0,
            max_value=2,
            value=0 if strict_brandables else 1,
            step=1,
        )

        allowed = st.multiselect(
            "Sallitut C/V-kuviot (täysi kuvio, 4–8 kirjainta; esim. CVVC, VCCV, CVCVCVVC)",
            options=DEFAULT_ALLOWED_RUN_PATTERNS,
            default=["CVCV", "CVCVC", "CVCCV", "CVCVCV", "CVCVVC", "CVVC", "VCCV", "CVCVCVVC"],
        )

        include_score = st.checkbox("Sisällytä score downloadiin (TAB-eroteltu)", value=True)

    brand_settings = {
        "score_threshold": score_threshold,
        "min_len": min_len,
        "max_len": max_len,
        "vowel_min": vowel_min,
        "vowel_max": vowel_max,
        "max_consonant_run": max_consonant_run,
        "min_unique_chars": min_unique_chars,
        "reject_repeats": reject_repeats,
        "reject_dictionary_words": reject_dictionary_words,
        "allowed_run_patterns": set(allowed),
        "strict_brandables": strict_brandables,
        "max_rare_letters": max_rare_letters,
    }

    col1, col2, col3 = st.columns(3)
    run_exact = col1.button("Aja TÄSMÄ", type="primary")
    run_broad = col2.button("Aja LAAJA")
    run_brand = col3.button("Aja BRANDABLES")

    if run_exact:
        with st.spinner("Seulotaan (täsmä)..."):
            results_com, results_others, processed_lines, processed_files = run_filter(files, words, mode="exact")
        render_results(results_com, results_others, processed_lines, processed_files, label="exact")

    if run_broad:
        with st.spinner("Seulotaan (laaja)..."):
            results_com, results_others, processed_lines, processed_files = run_filter(files, words, mode="broad")
        render_results(results_com, results_others, processed_lines, processed_files, label="broad")

    if run_brand:
        with st.spinner("Seulotaan (brandables)..."):
            res_com, res_oth, processed_lines, processed_files = run_brandables(files, words, brand_settings)
        render_brandables(res_com, res_oth, processed_lines, processed_files, include_score=include_score)

if __name__ == "__main__":
    main()