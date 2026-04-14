import re


def _normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _split_sentences(paragraph: str) -> list[str]:
    if not paragraph.strip():
        return []
    # Split by major Chinese/English sentence punctuation while keeping the delimiter.
    parts = re.split(r"([。！？!?\.]+)", paragraph)
    out: list[str] = []
    current = ""
    for item in parts:
        if not item:
            continue
        if re.fullmatch(r"[。！？!?\.]+", item):
            current += item
            if current.strip():
                out.append(current.strip())
            current = ""
            continue
        current += item
    if current.strip():
        out.append(current.strip())
    return out


def _detect_language(text: str) -> str:
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if cjk > 0 and cjk >= latin:
        return "zh"
    return "en"


def _build_spacy_sentences(text: str, lang: str, zh_model: str, en_model: str) -> list[str]:
    try:
        import spacy
    except Exception:
        return []
    model_name = zh_model if lang == "zh" else en_model
    nlp = None
    try:
        nlp = spacy.load(model_name)
    except Exception:
        try:
            nlp = spacy.blank("zh" if lang == "zh" else "en")
            if "sentencizer" not in nlp.pipe_names:
                nlp.add_pipe("sentencizer")
        except Exception:
            nlp = None
    if nlp is None:
        return []
    doc = nlp(text)
    out: list[str] = []
    for sent in doc.sents:
        row = sent.text.strip()
        if row:
            out.append(row)
    return out


def _split_long_sentence(sentence: str, chunk_size: int) -> list[str]:
    if len(sentence) <= chunk_size:
        return [sentence]
    # Secondary split for very long sentences.
    subs = re.split(r"([,，;；:：])", sentence)
    merged: list[str] = []
    current = ""
    for item in subs:
        if not item:
            continue
        candidate = f"{current}{item}"
        if current and len(candidate) > chunk_size:
            merged.append(current.strip())
            current = item
        else:
            current = candidate
    if current.strip():
        merged.append(current.strip())
    out: list[str] = []
    for seg in merged:
        if len(seg) <= chunk_size:
            out.append(seg)
            continue
        for i in range(0, len(seg), chunk_size):
            block = seg[i : i + chunk_size].strip()
            if block:
                out.append(block)
    return out


def _tail_overlap(text: str, overlap: int) -> str:
    if overlap <= 0:
        return ""
    if len(text) <= overlap:
        return text
    return text[-overlap:]


def semantic_chunk_with_sliding_window(
    text: str,
    chunk_size: int = 400,
    chunk_overlap: int = 80,
    min_chunk_size: int = 80,
    strategy: str = "spacy_auto",
    spacy_model_zh: str = "zh_core_web_sm",
    spacy_model_en: str = "en_core_web_sm",
) -> list[str]:
    text = _normalize_text(text)
    if not text:
        return []
    chunk_size = max(120, int(chunk_size))
    chunk_overlap = max(0, min(int(chunk_overlap), chunk_size // 2))
    min_chunk_size = max(20, min(int(min_chunk_size), chunk_size))

    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    sentence_units: list[str] = []
    for para in paragraphs:
        lang = _detect_language(para)
        semantic_rows: list[str] = []
        if strategy in {"spacy_auto", "spacy"}:
            semantic_rows = _build_spacy_sentences(
                para,
                lang=lang,
                zh_model=spacy_model_zh,
                en_model=spacy_model_en,
            )
        if not semantic_rows:
            semantic_rows = _split_sentences(para)
        for sent in semantic_rows:
            sentence_units.extend(_split_long_sentence(sent, chunk_size))

    if not sentence_units:
        return []

    chunks: list[str] = []
    current = ""
    for unit in sentence_units:
        unit = unit.strip()
        if not unit:
            continue
        candidate = unit if not current else f"{current} {unit}"
        if len(candidate) <= chunk_size:
            current = candidate
            continue
        if current:
            chunks.append(current.strip())
        overlap_prefix = _tail_overlap(current, chunk_overlap).strip()
        if overlap_prefix:
            current = f"{overlap_prefix} {unit}".strip()
        else:
            current = unit
        if len(current) > chunk_size:
            forced = _split_long_sentence(current, chunk_size)
            chunks.extend(forced[:-1])
            current = forced[-1]
    if current.strip():
        chunks.append(current.strip())

    # Avoid tiny tail chunk if possible.
    if len(chunks) >= 2 and len(chunks[-1]) < min_chunk_size:
        merged = f"{chunks[-2]} {chunks[-1]}".strip()
        if len(merged) <= chunk_size + chunk_overlap:
            chunks[-2] = merged
            chunks.pop()

    return [c for c in chunks if c]
