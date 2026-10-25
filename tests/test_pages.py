"""Retired borrower pages must enter chat without breaking the lender workspace."""
from fastapi.testclient import TestClient
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from app.main import app

client = TestClient(app)


def test_retired_borrower_urls_redirect_to_chat_and_keep_language_and_live_mode():
    for path in ('/borrower', '/exchange', '/static/borrower.html', '/static/exchange.html'):
        response = client.get(path + '?lang=es&live=0', follow_redirects=False)
        assert response.status_code == 307
        assert response.headers['location'] == '/phone?lang=es&live=0'
        chat = client.get(response.headers['location'])
        assert chat.status_code == 200 and chat.text == client.get('/phone').text


def test_lender_uses_lender_assets_and_removed_assets_are_not_served():
    html = client.get('/lender').text
    assert '/static/lender.css' in html and '/static/lender.js' in html
    for asset in ('lender.css', 'lender.js', 'chat-access.css', 'chat-access.js'):
        assert client.get('/static/' + asset).status_code == 200
    for removed in ('portals.css', 'portals.js', 'borrower-access.css', 'borrower-access.js'):
        assert client.get('/static/' + removed).status_code == 404
    script = client.get('/static/lender.js').text
    assert 'addSavings' not in script and 'celebrate' not in script
    assert 'renderRows' in script and 'resolveCase' in script


def test_navigation_has_chat_and_lender_without_a_separate_borrower_app():
    html = client.get('/').text
    assert 'href="/phone"' in html and 'href="/lender"' in html
    assert 'href="/borrower"' not in html


def test_app_and_log_do_not_contain_unresolved_merge_markers():
    root = Path(__file__).resolve().parents[1]
    for name in ("app/main.py", "app/static/demo.html", "docs/decisions/LOG.md"):
        assert not re.search(r"(?m)^(?:<{7}|={7}|>{7})", (root/name).read_text(encoding="utf8")), name


def test_chat_javascript_parses():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed for the page JavaScript syntax check")
    html = client.get("/phone").text
    scripts = re.findall(r"<script>([\s\S]*?)</script>", html)
    assert scripts
    for script in scripts:
        result = subprocess.run([node, "--check"], input=script, text=True, encoding="utf8", capture_output=True)
        assert result.returncode == 0, result.stderr


def test_every_borrower_path_on_the_phone_asks_the_person_before_settling():
    html = client.get('/phone').text
    # the chat and the form both request approval=1; only the laptop story view replays without it
    assert html.count('await loadExchange(true)') == 2
    assert 'async function formDecision' in html and 'await decide(choice)' in html


def test_spanish_translation_note_only_shows_in_spanish():
    js = client.get('/static/chat-access.js').text
    css = client.get('/static/chat-access.css').text
    assert "footer.hidden=lang!=='es'" in js and '.borrower-translation[hidden]{display:none!important}' in css
