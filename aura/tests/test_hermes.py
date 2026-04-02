from __future__ import annotations

from pathlib import Path

import pytest

import aura.browser.hermes as hermes
import aura.browser.hermes.tools as hermes_tools
from aura.core.config import AppConfig, FeatureFlags, ModelSettings, PathsSettings
from aura.core.event_bus import EventBus


@pytest.fixture()
def hermes_config(tmp_path):
    config = AppConfig(
        name="AURA",
        offline_mode=True,
        log_level="INFO",
        primary_model=ModelSettings(provider="ollama", name="llama3", host="http://127.0.0.1:11434"),
        fallback_models=[],
        paths=PathsSettings(
            allowed_roots=[tmp_path],
            data_dir=tmp_path,
            log_dir=tmp_path / "logs",
            memory_dir=tmp_path / "memory",
            ipc_socket=tmp_path / "aura.sock",
        ),
        features=FeatureFlags(hotkey=True, tray=True, ipc=True, api=True),
        source_path=tmp_path / "config.yaml",
    )
    hermes.set_config(config)
    hermes.set_event_bus(EventBus())
    return config


def test_open_url_extract_data_and_text(hermes_config, tmp_path):
    html_path = tmp_path / "page.html"
    html_path.write_text(
        """
        <html><head><title>Example</title></head>
        <body>
          <h1>Heading</h1>
          <table>
            <tr><th>Name</th><th>Value</th></tr>
            <tr><td>A</td><td>1</td></tr>
          </table>
          <a href="https://example.com/download">Download</a>
        </body></html>
        """,
        encoding="utf-8",
    )
    handle = hermes.open_url(str(html_path))
    text = hermes.get_page_text(handle.page_id)
    extracted = hermes.extract_data(handle.page_id, {
        "heading": {"selector": "h1", "type": "text"},
        "table": {"selector": "table", "type": "table"},
        "link": {"selector": "a", "type": "href"},
    })
    screenshot = hermes.take_screenshot(handle.page_id)
    assert handle.title == "page.html"
    assert "Heading" in text
    assert extracted.data["heading"] == "Heading"
    assert extracted.data["table"][1][1] == "1"
    assert extracted.data["link"] == "https://example.com/download"
    assert Path(screenshot).exists()


def test_fill_form_upload_and_blocklist_rejects_url(hermes_config, tmp_path):
    html_path = tmp_path / "form.html"
    html_path.write_text('<html><body><input id="name" /><button>Submit</button></body></html>', encoding="utf-8")
    handle = hermes.open_url(str(html_path))
    upload = hermes.upload_file(handle.page_id, "#name", str(html_path))
    fill = hermes.fill_form(handle.page_id, [{"selector_or_description": "#name", "value": "AURA", "field_type": "text"}])
    with pytest.raises(hermes.HermesError):
        hermes.navigate(handle.page_id, "http://phishing.test/")
    assert upload.success is True
    assert fill.success is True


@pytest.mark.asyncio
async def test_event_bus_receives_hermes_actions(hermes_config, tmp_path):
    html_path = tmp_path / "bus.html"
    html_path.write_text("<html><body><p>Hello</p></body></html>", encoding="utf-8")
    seen = []

    async def handler(topic, payload):
        seen.append((topic, payload["action"]))

    await hermes_tools._EVENT_BUS.subscribe("hermes.action", handler)
    handle = hermes.open_url(str(html_path))
    hermes.close_page(handle.page_id)
    assert any(action == "open_url" for _, action in seen)


def test_navigation_click_scroll_download_and_close_browser(hermes_config, tmp_path):
    page1 = tmp_path / "page1.html"
    page2 = tmp_path / "page2.html"
    download = tmp_path / "download.txt"
    page1.write_text('<html><body><a id="next" href="%s">Next</a><input id="field" value="" /></body></html>' % page2.as_uri(), encoding="utf-8")
    page2.write_text("<html><body><p>Second page</p></body></html>", encoding="utf-8")
    download.write_text("payload", encoding="utf-8")

    handle = hermes.open_url(str(page1))
    assert hermes.click(handle.page_id, selector="#next").success is True
    assert hermes.type_text(handle.page_id, selector="#field", text="AURA").success is True
    assert hermes.scroll(handle.page_id, "down", 200).success is True
    assert hermes.navigate(handle.page_id, str(page2)).title == "page2.html"
    assert hermes.wait_for_element(handle.page_id, "p").text == "Second page"
    downloaded = hermes.download_file(handle.page_id, download.as_uri(), str(tmp_path / "copied.txt"))
    assert downloaded.success is True
    assert Path(downloaded.save_path).read_text(encoding="utf-8") == "payload"
    assert hermes.close_page(handle.page_id).success is True
    assert hermes.close_browser().success is True
