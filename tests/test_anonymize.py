import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "anonymize", Path(__file__).parent.parent / "scripts" / "anonymize.py"
)
assert spec and spec.loader
anonymize_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(anonymize_mod)


def test_strips_identifying_data() -> None:
    raw = {
        "items": [
            {
                "id": 123456,
                "name": "Our House",
                "model": "iTec",
                "isOnline": True,
                "macAddress": "AA:BB:CC:DD:EE:FF",
                "address": {"city": "Somewhere"},
                "note": "mail me at someone@example.com from AA-BB-CC-DD-EE-FF",
            }
        ],
        "installationId": 123456,
    }
    out = anonymize_mod.anonymize(raw)
    text = str(out)
    for secret in ("123456", "Our House", "AA:BB", "Somewhere", "someone@example.com", "AA-BB"):
        assert secret not in text
    assert out["items"][0]["model"] == "iTec"
    assert out["installationId"] == 0
