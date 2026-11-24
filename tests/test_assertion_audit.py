from scripts.audit_test_assertions import classify


def test_audit_distinguishes_called_assertions_from_noop_helpers(tmp_path):
    fixture = tmp_path / "test_sample.py"
    fixture.write_text(
        "def assert_empty(): pass\n"
        "def check_result(value): assert value == 2\n"
        "def test_noop(): assert_empty()\n"
        "def test_delegated(): check_result(2)\n"
        "def test_direct(): assert 1 + 1 == 2\n"
        "def test_uncalled():\n    def never_called(): assert False\n"
    )
    assert {node.split("::")[-1]: kind for node, kind in classify(fixture)} == {
        "test_noop": "unverified",
        "test_uncalled": "unverified",
        "test_direct": "direct",
        "test_delegated": "delegated",
    }
