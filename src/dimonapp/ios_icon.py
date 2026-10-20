"""iOS home screen icon and browser tab icon (R18.3).

Streamlit sets the browser favicon but not the apple-touch-icon link iOS needs. When the
Docker image is built, this module copies the 180 x 180 px icon into Streamlit's static
folder and adds the link to the page Streamlit serves.

Streamlit also sets the favicon only from JavaScript, after the page has loaded; the page it
serves links its own default icon, and Safari keeps showing that one. The same build step
therefore replaces that default icon with a 96 x 96 px version of the favicon.

Streamlit lets browsers keep its static files for a year, so both icons are served under a
name that holds a digest of their content: a changed icon gets a new address.
"""

import hashlib
import logging
import shutil
from pathlib import Path

import streamlit

logger = logging.getLogger(__name__)

ASSETS_FOLDER = Path(__file__).parent / 'assets'
ICON_PATH = ASSETS_FOLDER / 'apple-touch-icon.png'
TAB_ICON_PATH = ASSETS_FOLDER / 'tab-icon.png'
HEAD_END = '</head>'
STREAMLIT_FAVICON_NAME = 'favicon.png'
STREAMLIT_FAVICON_LINK = f'<link rel="shortcut icon" href="./{STREAMLIT_FAVICON_NAME}" />'


def name_served_icon(icon_path: Path) -> str:
    """Name an icon after its content, so browsers fetch a changed icon again."""
    digest = hashlib.sha256(icon_path.read_bytes()).hexdigest()
    short_digest = digest[:8]
    return f'{icon_path.stem}.{short_digest}{icon_path.suffix}'


ICON_NAME = name_served_icon(icon_path=ICON_PATH)
ICON_LINK = f'<link rel="apple-touch-icon" href="./{ICON_NAME}" />'
TAB_ICON_NAME = name_served_icon(icon_path=TAB_ICON_PATH)
TAB_ICON_LINK = f'<link rel="shortcut icon" href="./{TAB_ICON_NAME}" />'


def inject_apple_touch_icon_link(html: str) -> str:
    """Add the apple-touch-icon link to the head of a page, once."""
    if ICON_LINK in html:
        return html
    if HEAD_END not in html:
        raise ValueError('The page has no closing head tag to put the icon link in.')
    return html.replace(HEAD_END, f'  {ICON_LINK}\n  {HEAD_END}', 1)


def install_apple_touch_icon(static_folder: Path) -> None:
    """Copy the icon into a Streamlit static folder and link it from index.html."""
    shutil.copyfile(src=ICON_PATH, dst=static_folder / ICON_NAME)
    index_path = static_folder / 'index.html'
    html = index_path.read_text(encoding='utf-8')
    patched_html = inject_apple_touch_icon_link(html=html)
    index_path.write_text(patched_html, encoding='utf-8')
    logger.info('Apple touch icon installed.')


def link_tab_icon(html: str) -> str:
    """Point the icon link of a page at the tab icon instead of Streamlit's default, once."""
    if TAB_ICON_LINK in html:
        return html
    if STREAMLIT_FAVICON_LINK not in html:
        raise ValueError('The page has no Streamlit icon link to replace.')
    return html.replace(STREAMLIT_FAVICON_LINK, TAB_ICON_LINK, 1)


def install_tab_icon(static_folder: Path) -> None:
    """Serve the tab icon from a Streamlit static folder and link it from index.html.

    The default icon is overwritten too, because Streamlit's own script falls back to it.
    """
    shutil.copyfile(src=TAB_ICON_PATH, dst=static_folder / TAB_ICON_NAME)
    shutil.copyfile(src=TAB_ICON_PATH, dst=static_folder / STREAMLIT_FAVICON_NAME)
    index_path = static_folder / 'index.html'
    html = index_path.read_text(encoding='utf-8')
    patched_html = link_tab_icon(html=html)
    index_path.write_text(patched_html, encoding='utf-8')
    logger.info('Browser tab icon installed.')


def main() -> None:
    """Install the icons into the Streamlit package of the current environment."""
    logging.basicConfig(level=logging.INFO)
    static_folder = Path(streamlit.__file__).parent / 'static'
    install_apple_touch_icon(static_folder=static_folder)
    install_tab_icon(static_folder=static_folder)


if __name__ == '__main__':
    main()
