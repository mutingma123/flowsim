"""Shared fixtures.

Browser tests share one Playwright driver and one launched browser per engine
for the whole test session. Each test gets its own fresh browser context, so no
page state, cookies, or routes carry between tests.
"""

import os
import shutil
from pathlib import Path

import pytest

# The browser engines the builder page is tested in: Chrome's and Firefox's.
# WebKit (Safari's engine) is left out by the owner's ruling of 2026-11-04,
# since Playwright's WebKit needs system libraries installed with sudo.
# Each engine's browser launches once per session, on first use.
ENGINES = ("chromium", "firefox")


@pytest.fixture(scope="session")
def _browser_for():
    """Return a function that gives the session's browser for an engine.

    Playwright starts on the first call and each engine's browser launches on
    its first use, so engines that no test asks for are never started. A
    missing browser skips or fails the calling test, as it would if launched
    per test. Browsers close and Playwright stops at the end of the session.
    """
    sync_api = pytest.importorskip("playwright.sync_api")
    driver = None
    browsers: dict = {}

    def browser_for(engine: str):
        nonlocal driver
        # A browser that crashed or was closed is replaced, so one crash fails
        # only the test it happened in.
        if engine in browsers and browsers[engine].is_connected():
            return browsers[engine]
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
        if driver is None:
            driver = sync_api.sync_playwright().start()
        launcher = getattr(driver, engine)
        if engine != "chromium" and not Path(launcher.executable_path).exists():
            pytest.skip(f"Run 'pixi run playwright install {engine}' to test {engine}.")
        browsers[engine] = launcher.launch(**options)
        return browsers[engine]

    try:
        yield browser_for
    finally:
        for browser in browsers.values():
            browser.close()
        if driver is not None:
            driver.stop()


def offline_pages(browser_for, engine: str):
    """Yield a function that opens saved pages in a fresh context of one engine.

    Every network request is denied, and any page error fails the test.
    Chromium is the installed Chrome or Chromium (set FLOWSIM_CHROME to choose
    one; a FLOWSIM_CHROME path that does not exist fails). Firefox is
    Playwright's own build from `pixi run playwright install firefox`. A
    missing browser skips the test.
    """
    browser = browser_for(engine)
    context = browser.new_context(viewport={"width": 1400, "height": 1000})
    context.route("http://**/*", lambda route: route.abort())
    context.route("https://**/*", lambda route: route.abort())
    errors: list[str] = []

    def open_page(path: Path):
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(path.resolve().as_uri())
        return page

    try:
        yield open_page
    finally:
        context.close()
    assert not errors, errors


@pytest.fixture
def offline_page(_browser_for):
    """Open saved pages in headless Chrome with every network request denied."""
    yield from offline_pages(_browser_for, "chromium")


@pytest.fixture(params=ENGINES)
def engine_page(request, _browser_for):
    """Open saved pages in each browser engine, one test run per engine."""
    yield from offline_pages(_browser_for, request.param)
