from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RELEASE_CHECKLIST = ROOT / "docs" / "superpowers" / "reports" / "2026-06-03-production-release-checklist.md"


def test_readme_links_release_checklist():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "2026-06-03-production-release-checklist.md" in readme


def test_release_checklist_covers_private_cloud_hardening_topics():
    checklist = RELEASE_CHECKLIST.read_text(encoding="utf-8")

    for topic in [
        "HTTPS/TLS",
        "Backups",
        "Secrets",
        "Android APK",
        "Online regression",
        "Rollback",
    ]:
        assert topic in checklist


def test_smoke_test_only_accepts_nomi_public_marker():
    smoke = (ROOT / "scripts" / "smoke-test.sh").read_text(encoding="utf-8")

    assert 'grep -Eq "Nomi"' in smoke
    assert "Nomi|PAR" not in smoke
