# app.py
import io
import re
import csv
import zipfile
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple, List

import streamlit as st

# Optional: parempi TLD-parsinta (co.uk jne.)
try:
    import tldextract
    _TLDX = tldextract.TLDExtract(cache_dir=False)  # nopea, ei levycachea
except Exception:
    _TLDX = None


WORDLIST_FILE = "words_alpha.txt"


@st.cache_resource
def load_words(path: str) -> set[str]:
    with open(path, "r", encoding="utf-8") as f:
        # yli 2 kirjainta, kuten sun skriptissä
        return set(w.strip().lower() for w in f if len(w.strip()) > 2)


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

    sld_clean = re.sub(r"[^a-z\-]", "", sld)
    if not sld_clean or not tld:
        return None, None
    return sld_clean, tld


def is_valid_english_combo(sld: str, word_set: set[str]) -> bool:
    if not sld:
        return False

    if sld in word_set:
        return True

    if "-" in sld:
        parts = [p for p in sld.split("-") if p]
        if len(parts) >= 2 and all(p in word_set for p in parts):
            return True

    # two-word concat
    for i in range(3, len(sld) - 2):
        if sld[:i] in word_set and sld[i:] in word_set:
            return True

    return False


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
                    items.append(FileItem(name=name, suffix="." + lower.split(".")[-1], data=zf.read(info)))
    else:
        for uf in uploaded_files:
            lower = uf.name.lower()
            if lower.endswith(".csv") or lower.endswith(".txt"):
                suffix = "." + lower.split(".")[-1]
                items.append(FileItem(name=uf.name, suffix=suffix, data=uf.getvalue()))

    # Aakkosjärjestys (päivämääränimillä tämä == kronologinen)
    items.sort(key=lambda x: x.name)
    return items


def run_filter(files: List[FileItem], words: set[str]):
    results_com: List[str] = []
    results_others: List[str] = []
    seen: set[str] = set()

    # Arvio kokonaisriveistä progressia varten (kevyt arvio, ei pakollinen)
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

            if is_valid_english_combo(sld, words):
                seen.add(full)
                if tld == "com":
                    results_com.append(full)
                else:
                    results_others.append(full)

    progress.progress(1.0)
    status.write("Valmis.")
    return results_com, results_others, processed, len(files)


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

    if st.button("Aja seulonta", type="primary"):
        with st.spinner("Seulotaan..."):
            results_com, results_others, processed_lines, processed_files = run_filter(files, words)

        st.subheader("Tulokset")
        st.write(f"Käsitelty tiedostoja: **{processed_files}**")
        st.write(f"Käsitelty rivejä (arvioitu domain-riveiksi): **{processed_lines}**")
        st.write(f"Löydetyt .com: **{len(results_com)}**")
        st.write(f"Löydetyt muut: **{len(results_others)}**")

        com_text = "\n".join(results_com).encode("utf-8")
        others_text = "\n".join(results_others).encode("utf-8")

        st.download_button("Lataa results_com.txt", data=com_text, file_name="results_com.txt", mime="text/plain")
        st.download_button("Lataa results_others.txt", data=others_text, file_name="results_others.txt", mime="text/plain")

        # Halutessa pieni esikatselu
        with st.expander("Näytä esikatselu (ensimmäiset 200)"):
            st.write("**.com**")
            st.code("\n".join(results_com[:200]))
            st.write("**others**")
            st.code("\n".join(results_others[:200]))


if __name__ == "__main__":
    main()