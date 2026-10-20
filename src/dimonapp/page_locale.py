"""French calendar in the browser, whatever its language (R18.1).

Streamlit draws the date picker in the language of the browser: an English browser gets
English month names and weeks starting on Sunday, and Streamlit has no setting for it. This
module adds a small script to the page Streamlit serves, so every browser reports Belgian
French and the calendar starts on Monday. Run when the Docker image is built and by `make run`.
"""

import logging
from pathlib import Path

import streamlit

logger = logging.getLogger(__name__)

LOCALE = 'fr-BE'
LOCALE_SCRIPT = (
    '<script>'
    f"Object.defineProperty(navigator, 'language', {{get: () => '{LOCALE}'}});"
    f"Object.defineProperty(navigator, 'languages', {{get: () => ['{LOCALE}', 'fr']}});"
    '</script>'
)
HEAD_START = '<head>'


def inject_locale_script(html: str) -> str:
    """Add the locale script at the start of the head of a page, once.

    It must come before Streamlit's own scripts, which read the language when they load.
    """
    if LOCALE_SCRIPT in html:
        return html
    if HEAD_START not in html:
        raise ValueError('The page has no head tag to put the locale script in.')
    return html.replace(HEAD_START, f'{HEAD_START}\n    {LOCALE_SCRIPT}', 1)


def install_locale_script(static_folder: Path) -> None:
    """Add the locale script to the index.html of a Streamlit static folder."""
    index_path = static_folder / 'index.html'
    html = index_path.read_text(encoding='utf-8')
    patched_html = inject_locale_script(html=html)
    index_path.write_text(patched_html, encoding='utf-8')
    logger.info('French page locale installed.')


def main() -> None:
    """Install the locale script into the Streamlit package of the current environment."""
    logging.basicConfig(level=logging.INFO)
    static_folder = Path(streamlit.__file__).parent / 'static'
    install_locale_script(static_folder=static_folder)


if __name__ == '__main__':
    main()
