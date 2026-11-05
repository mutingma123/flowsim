"""Shared fixtures."""

import os
import shutil
from pathlib import Path

import pytest

# The browser engines the builder page is tested in: Chrome's and Firefox's.
# WebKit (Safari's engine) is left out by the owner's ruling of 2026-11-04,
# since Playwright's WebKit needs system libraries installed with sudo.
ENGINES = ("chromium", "firefox")


def offline_pages(engine: str):
    """Yield a function that opens saved pages in one headless browser engine.

    Every network request is denied, and any page error fails the test.
    Chromium is the installed Chrome or Chromium (set FLOWSIM_CHROME to choose
    one; a FLOWSIM_CHROME path that does not exist fails). Firefox is
    Playwright's own build from `pixi run playwright install firefox`. A
    missing browser skips the test.
    """
    sync_api = pytest.importorskip("playwright.sync_api")
    options: dict = {"headless": True}
    if engine == "chromium":
        executable = os.environ.get("FLOWSIM_CHROME")
        if executable is not None and not Path(executable).exists():
            pytest.fail(f"FLOWSIM_CHROME points to a missing file: {executable}")
        executable = (
            executable or shutil.which("google-chrome") or shutil.which("chromium")
        )
        if executable is None:
            pytest.skip("Set FLOWSIM_CHROME to a Chrome or Chromium executable.")
        options.update(executable_path=executable, args=["--no-sandbox"])
    errors: list[str] = []
    with sync_api.sync_playwright() as driver:
        launcher = getattr(driver, engine)
        if engine != "chromium" and not Path(launcher.executable_path).exists():
            pytest.skip(f"Run 'pixi run playwright install {engine}' to test {engine}.")
        browser = launcher.launch(**options)

        def open_page(path: Path):
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("http://**/*", lambda route: route.abort())
            page.route("https://**/*", lambda route: route.abort())
            page.goto(path.resolve().as_uri())
            return page

        try:
            yield open_page
        finally:
            browser.close()
    assert not errors, errors


@pytest.fixture
def offline_page():
    """Open saved pages in headless Chrome with every network request denied."""
    yield from offline_pages("chromium")


@pytest.fixture(params=ENGINES)
def engine_page(request):
    """Open saved pages in each browser engine, one test run per engine."""
    yield from offline_pages(request.param)
