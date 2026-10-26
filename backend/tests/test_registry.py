from researchlab.mcp_client import SearchHit
from researchlab.registry import SourceRegistry, canonical_url


def _hit(url="https://x.test/a", content="Some real sentence about the topic."):
    return SearchHit(url=url, title="T", content=content)


def test_ids_are_sequential_and_urls_deduplicated():
    reg = SourceRegistry()
    a, new_a = reg.add_hit(_hit(), "t1", "q1")
    b, new_b = reg.add_hit(_hit("https://X.test/a/"), "t2", "q2")  # same page, different spelling
    assert (a.id, new_a) == ("s1", True)
    assert (b.id, new_b) == ("s1", False)
    assert a.found_by_tasks == ["t1", "t2"] and a.queries == ["q1", "q2"]
    assert len(reg.sources()) == 1


def test_non_http_and_empty_hits_rejected():
    reg = SourceRegistry()
    assert reg.add_hit(_hit("javascript:alert(1)"), "t1", "q") == (None, False)
    assert reg.add_hit(_hit(content="<p> </p>"), "t1", "q") == (None, False)
    assert reg.sources() == []


def test_source_records_url_title_timestamp():
    reg = SourceRegistry()
    s, _ = reg.add_hit(_hit(), "t1", "q")
    assert s.url == "https://x.test/a" and s.title == "T" and s.retrieved_at.tzinfo is not None


def test_claim_requires_known_source_found_by_same_task():
    reg = SourceRegistry()
    reg.add_hit(_hit(), "t1", "q")
    assert reg.add_claim("t1", "claim", "s99", "Some real sentence") is None
    assert reg.add_claim("t2", "claim", "s1", "Some real sentence") is None  # other task's source
    assert reg.claims() == []


def test_claim_quote_verification_and_source_linking():
    reg = SourceRegistry()
    reg.add_hit(_hit(), "t1", "q")
    good = reg.add_claim("t1", "ok", "s1", "some real sentence about the topic")
    bad = reg.add_claim("t1", "fabricated", "s1", "this sentence is not in the source at all")
    assert good.evidence[0].quote_verified and not bad.evidence[0].quote_verified
    assert reg.get("s1").claim_ids == [good.id]  # only verified claims are linked to the source
    assert [c.id for c in reg.verified_claims()] == [good.id]


def test_same_quote_from_same_source_is_one_claim_across_tasks():
    reg = SourceRegistry()
    reg.add_hit(_hit(), "t1", "q")
    reg.add_hit(_hit(), "t2", "q")  # second task surfaces the same page
    first = reg.add_claim("t1", "claim", "s1", "Some real sentence about the topic.")
    again = reg.add_claim("t2", "claim reworded", "s1", "some real sentence about the topic")
    assert again is first and len(reg.claims()) == 1
    assert reg.get("s1").claim_ids == [first.id]


def test_canonical_url_drops_fragment_and_trailing_slash():
    assert canonical_url("HTTPS://A.test/p/#frag") == "https://a.test/p"
