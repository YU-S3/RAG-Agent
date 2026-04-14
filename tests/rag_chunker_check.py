from app.rag.chunker import semantic_chunk_with_sliding_window


def run() -> None:
    text = (
        "第一段：RAG系统需要高质量分段。语义完整的chunk通常可以提升召回准确率。"
        "如果分段过于粗糙，检索会把无关文本带入上下文，导致回答偏离。"
        "因此需要在结构信息和语义完整之间取得平衡。\n\n"
        "第二段：滑动窗口可以减少边界信息丢失。"
        "尤其在长句跨段时，重叠区域有助于保留上下文连续性。"
        "当问题命中边界内容时，带重叠的分块往往能提高召回稳定性。\n\n"
        "第三段：在中文文档中，按句分块比固定字符切割更可靠。"
        "对于超长句子，再做二级标点切分，可以避免单块过大。"
    )
    chunks = semantic_chunk_with_sliding_window(
        text=text,
        chunk_size=120,
        chunk_overlap=24,
        min_chunk_size=20,
        strategy="spacy_auto",
    )
    assert len(chunks) >= 2
    assert all(len(c.strip()) > 0 for c in chunks)
    assert all(len(c) <= 144 for c in chunks)
    # Sliding overlap should keep boundary words in adjacent chunks.
    assert any("滑动窗口" in c for c in chunks)
    assert any("语义完整" in c for c in chunks)

    en_text = (
        "RAG quality depends on chunk quality. Semantic chunks preserve complete meaning. "
        "Sliding windows keep boundary context between adjacent chunks. "
        "This helps retrieval when a query hits sentence boundaries."
    )
    en_chunks = semantic_chunk_with_sliding_window(
        text=en_text,
        chunk_size=90,
        chunk_overlap=18,
        min_chunk_size=20,
        strategy="spacy_auto",
    )
    assert len(en_chunks) >= 2
    assert all(len(x.strip()) > 0 for x in en_chunks)


if __name__ == "__main__":
    run()
