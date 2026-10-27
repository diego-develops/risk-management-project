"""The portal ships under a strict CSP (no inline script/style) and must never ship secrets."""

import re
from pathlib import Path

PORTAL = Path(__file__).parent.parent / "portal"


def test_portal_files_exist():
    assert {p.name for p in PORTAL.iterdir()} == {"index.html", "app.js", "styles.css"}


def test_html_has_no_inline_script_style_or_handlers():
    html = (PORTAL / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)
    assert "<style" not in html
    assert not re.search(r"\sstyle=", html)
    assert not re.search(r"\son[a-z]+=", html)


def test_js_never_uses_innerhtml_and_has_no_api_key():
    js = (PORTAL / "app.js").read_text(encoding="utf-8")
    assert "innerHTML" not in js and "outerHTML" not in js and "eval(" not in js
    assert "x-api-key" not in js.lower()


def test_portal_calls_only_the_same_origin_endpoint():
    js = (PORTAL / "app.js").read_text(encoding="utf-8")
    assert "ENDPOINT = '/api/v1/onboarding/start'" in js
    assert "http://" not in js and "https://" not in js


def test_every_demo_case_is_a_ten_digit_document():
    html = (PORTAL / "index.html").read_text(encoding="utf-8")
    documents = re.findall(r'data-document="([^"]+)"', html)
    assert documents and all(re.fullmatch(r"\d{10}", d) for d in documents)
