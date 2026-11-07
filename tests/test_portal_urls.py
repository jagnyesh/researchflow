"""#220: every portal link points at the port table in CLAUDE.md.

exploratory (Research Notebook) 8501, formal (Researcher Portal) 8502, admin 8503.
"""

import re
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
EXPLORATORY, FORMAL, ADMIN = (
    "http://localhost:8501",
    "http://localhost:8502",
    "http://localhost:8503",
)


def test_no_portal_url_literal_outside_the_one_module():
    hits = [
        f"{p.relative_to(APP.parent)}:{n}"
        for p in APP.rglob("*.py")
        if p.name != "portal_urls.py"
        for n, line in enumerate(p.read_text().splitlines(), 1)
        if re.search(r"localhost:850\d", line)
    ]

    assert hits == []


def test_nav_links_open_the_right_portals():
    from app.web_ui.shared.design_system import render_app_navigation_links

    html = render_app_navigation_links(role="admin")
    links = dict(
        (label.strip(), href)
        for href, label in re.findall(r'href="([^"]+)"[^>]*>[^A-Za-z]*([A-Za-z ]+)</a>', html)
    )

    assert links == {
        "Researcher Portal": FORMAL,
        "Admin Dashboard": ADMIN,
        "Research Notebook": EXPLORATORY,
    }


def test_notebook_points_users_to_the_formal_portal():
    source = (APP / "web_ui/research_notebook.py").read_text()

    assert "portal_urls" in source
    assert "Formal" in source and "FORMAL_PORTAL_URL" in source
