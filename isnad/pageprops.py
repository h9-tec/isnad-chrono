"""Extract the Inertia page JSON embedded in encyclopedia HTML pages."""

import json
import re

_PAGE_RE = re.compile(
    r'<script data-page="app" type="application/json">(.*?)</script>',
    re.DOTALL,
)


class NoPageData(ValueError):
    """Raised when the HTML has no Inertia page-data script tag."""


def _page(html: str) -> dict:
    match = _PAGE_RE.search(html)
    if match is None:
        raise NoPageData("no <script data-page=\"app\"> tag found")
    return json.loads(match.group(1))


def extract(html: str) -> dict:
    """Return the ``props`` dict of the embedded Inertia page JSON."""
    return _page(html)["props"]


def component(html: str) -> str:
    """Return the Inertia component name, e.g. ``Encyclopedia/Rawi/Show``."""
    return _page(html)["component"]
