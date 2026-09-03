from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE_INVENTORY_PATHS = (
    "HOSTMARK_REPOSITORY",
    "hosts.json",
    "registry/hosts.json",
)


def test_public_source_checkout_excludes_live_inventory() -> None:
    assert all(not (ROOT / path).exists() for path in LIVE_INVENTORY_PATHS)
    assert (ROOT / "registry/hosts.example.json").is_file()

    ignore_patterns = {
        line.strip()
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert {f"/{path}" for path in LIVE_INVENTORY_PATHS} <= ignore_patterns
