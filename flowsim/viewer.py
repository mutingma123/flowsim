"""An offline report page that notebooks display and scripts save or open."""

from __future__ import annotations

import html
import tempfile
import webbrowser
from pathlib import Path


class Viewer:
    """An offline HTML report page.

    A notebook displays the page in an isolated frame, so the page's scripts
    cannot reach the notebook. A script saves it with ``save(path)`` or shows
    it with ``open()``, and ``html`` holds the complete document.

    Example
    -------
    >>> viewer = results.viewer()
    >>> viewer.save("output/viewer.html")
    """

    def __init__(self, document: str, kind: str, height: int):
        self._document = document
        self._kind = kind
        # The frame height in a notebook, in pixels. The page scrolls inside it.
        self._height = height
        self._path: Path | None = None

    @property
    def html(self) -> str:
        """Return the complete HTML document."""
        return self._document

    def save(self, path: str | Path) -> Path:
        """Write the page to a file, creating its folder, and return the path.

        Parameters
        ----------
        path : str or pathlib.Path
            File to write. Its folder is created if needed.

        Returns
        -------
        pathlib.Path
            The file written.

        Example
        -------
        >>> viewer.save("output/viewer.html")
        """
        destination = Path(path)
        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        destination.write_text(
            data=self._document,
            encoding="utf-8",
        )
        self._path = destination
        return destination

    def open(self) -> Path:
        """Show the page in the default web browser and return its file.

        The page is written to its saved path, or to a new temporary file when
        it has not been saved.

        Returns
        -------
        pathlib.Path
            The file shown.

        Example
        -------
        >>> viewer.open()
        """
        if self._path is None:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix="flowsim-",
                suffix=".html",
                delete=False,
            ) as file:
                file.write(self._document)
            path = Path(file.name)
        else:
            path = self.save(self._path)
        webbrowser.open(path.resolve().as_uri())
        return path

    def _repr_html_(self) -> str:
        # srcdoc holds the escaped document, and the sandbox without
        # allow-same-origin gives the page its own origin.
        return (
            f'<iframe srcdoc="{html.escape(self._document, quote=True)}" '
            'sandbox="allow-scripts allow-downloads" '
            f'style="width: 100%; height: {self._height}px; '
            'border: 1px solid #dce3e8;"></iframe>'
        )

    def __repr__(self) -> str:
        size = len(self._document.encode("utf-8")) / 1_000_000
        return (
            f"<Viewer: {self._kind}, {size:.1f} MB. Display it in a notebook, "
            "or call .save(path) or .open(). The document is in .html.>"
        )
