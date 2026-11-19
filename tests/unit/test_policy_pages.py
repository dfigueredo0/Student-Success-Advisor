"""The privacy and acceptable-use pages exist, are linked from the site, load nothing from other
sites, and state the retention periods the code actually uses."""

import re
from pathlib import Path

from api.routes.chat import ChatRequest
from settings import Settings
from tools.advisor.parse_transcript import MAX_BYTES

FRONTEND = Path(__file__).parents[2] / "frontend"
PRIVACY = (FRONTEND / "privacy.html").read_text()
AUP = (FRONTEND / "acceptable-use.html").read_text()
INDEX = (FRONTEND / "index.html").read_text()


def test_landing_page_and_sidebar_link_both_policies() -> None:
    for page in ("privacy.html", "acceptable-use.html"):
        assert INDEX.count(f'href="{page}"') >= 2, page  # landing panel + sidebar
    assert 'class="privacy-panel"' in INDEX


def test_policy_pages_load_nothing_from_other_sites() -> None:
    for html in (PRIVACY, AUP):
        assert not re.search(r'(src|href)="(https?:)?//', html)


def test_privacy_policy_matches_the_retention_the_code_uses() -> None:
    defaults = Settings(_env_file=None)
    assert f"{defaults.conversation_ttl_hours} hours without activity" in PRIVACY
    assert f"Deleted after {defaults.langfuse_trace_retention_days} days" in PRIVACY
    assert f"up to {defaults.langfuse_trace_retention_days} days" in AUP


def test_privacy_policy_matches_the_upload_limits() -> None:
    max_chars = ChatRequest.model_fields["message"].metadata
    assert any(getattr(m, "max_length", None) == 4000 for m in max_chars)
    assert "up to 4,000 characters" in PRIVACY
    assert MAX_BYTES == 5 * 1024 * 1024 and "up to 5 MB" in PRIVACY


def test_crisis_line_on_the_acceptable_use_page() -> None:
    assert "988" in AUP and "911" in AUP and "312.808.6363" in AUP
