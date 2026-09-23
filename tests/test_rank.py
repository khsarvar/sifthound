from trawl.rank import best_chunks, bm25_scores, chunk, combine_scores


def test_bm25_prefers_matching_doc():
    scores = bm25_scores("python install", ["the weather is nice", "install python today"])
    assert scores[1] > scores[0] == 0.0


def test_chunk_packs_paragraphs_and_wraps_long_ones():
    text = "short one\n\nshort two\n\n" + "word " * 300
    chunks = chunk(text, max_chars=100)
    assert chunks[0] == "short one\n\nshort two"
    assert all(len(c) <= 100 for c in chunks)


def test_best_chunks_returns_document_order():
    text = "\n\n".join(["alpha " * 120, "install python " * 40, "beta " * 120])
    chunks, top = best_chunks("install python", text, n=1)
    assert len(chunks) == 1 and "install" in chunks[0] and top > 0


def test_combine_scores_bounded_and_rank_prior():
    scores = combine_scores([0.0, 0.0, 0.0])
    assert scores == sorted(scores, reverse=True)
    assert all(0 <= s <= 1 for s in combine_scores([5.0, 1.0, 0.0]))
