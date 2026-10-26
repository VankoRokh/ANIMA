from anima.memory.composer import RuleBasedComposer


def test_extended_new_fact_replaces_shorter_existing_fact():
    composer = RuleBasedComposer()

    result = composer.compose_update(
        "SQLite storage baseline",
        "SQLite storage baseline uses local database",
    )

    assert result["content"] == "SQLite storage baseline uses local database"


def test_explicit_replacement_drops_previous_decision():
    composer = RuleBasedComposer()

    result = composer.compose_update(
        "Decision: use JSONL. Constraint: keep data local.",
        "Replaced JSONL with SQLite instead.",
    )

    assert "Decision: use JSONL." not in result["content"]
    assert "Constraint: keep data local." in result["content"]
    assert "Replaced JSONL with SQLite instead." in result["content"]
