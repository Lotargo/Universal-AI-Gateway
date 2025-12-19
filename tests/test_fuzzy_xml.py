import pytest
from core.common.fuzzy_xml import FuzzyXmlParser

def test_standard_tags():
    text = "<THOUGHT>Thinking...</THOUGHT><ACTION>{\"tool\": \"test\"}</ACTION><DRAFT>Note</DRAFT>"
    res = FuzzyXmlParser.parse(text)
    assert res["thought"] == "Thinking..."
    assert res["action"] == "{\"tool\": \"test\"}"
    assert res["draft"] == "Note"

def test_draft_only():
    text = "<DRAFT>Just a note.</DRAFT>"
    res = FuzzyXmlParser.parse(text)
    assert res["draft"] == "Just a note."

def test_attributes_extraction():
    text = '<THOUGHT title="Phase 4: Divergence">Thinking...</THOUGHT>'
    res = FuzzyXmlParser.parse(text)
    assert res["thought"] == "Thinking..."
    assert res["thought_attrs"]["title"] == "Phase 4: Divergence"

def test_unclosed_tags():
    text = "<THOUGHT>Thinking about life..."
    res = FuzzyXmlParser.parse(text)
    assert "Thinking about life" in res["thought"]

def test_tag_mention_false_positive():
    text = "We should not use <ACTION> tags here because it is not needed."
    res = FuzzyXmlParser.parse(text)
    assert res["action"] is None

def test_messy_log_recovery():
    log_text = '"failed_generation": "The user says... We should use the format: <THOUGHT> tags... No <ACTION> needed. We do it."'
    res = FuzzyXmlParser.extract_from_failed_generation(log_text)
    assert res["action"] is None
    # Heuristic for full text recovery
    assert "The user says" in (res["thought"] or "")
