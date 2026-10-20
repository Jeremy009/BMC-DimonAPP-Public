"""Android home screen icon, through a web app manifest (R18.10).

Android ignores the apple-touch-icon of iOS: it reads the home screen icon, the name and the
way the application opens from a web app manifest, which Streamlit does not serve. When the
Docker image is built, this module copies the two Android icons and a manifest into
Streamlit's static folder and links the manifest from the page Streamlit serves.

Streamlit lets browsers keep its static files for a year, so the icons and the manifest are
served under a name that holds a digest of their content, as in `ios_icon`.
"""

import hashlib
import json
import logging
import shutil
from pathlib import Path

import streamlit

from dimonapp.ios_icon import name_served_icon

logger = logging.getLogger(__name__)

ASSETS_FOLDER = Path(__file__).parent / 'assets'
ICON_PATHS = {
    192: ASSETS_FOLDER / 'android-icon-192.png',
    512: ASSETS_FOLDER / 'android-icon-512.png',
}
APP_NAME = 'DimonAPP'
BACKGROUND_COLOUR = '#f76625'
THEME_COLOUR = '#ffffff'
HEAD_END = '</head>'


def build_manifest(icon_names: dict[int, str]) -> str:
    """Write the web app manifest that points at the served icons, by their size in pixels.

    The icons are full bleed with the climber inside the safe circle, so Android may cut
    them to any shape ("maskable") and show them as they are ("any").
    """
    icons = [
        {
            'src': f'./{icon_name}',
            'sizes': f'{size}x{size}',
            'type': 'image/png',
            'purpose': 'any maskable',
        }
        for size, icon_name in icon_names.items()
    ]
    manifest = {
        'name': APP_NAME,
        'short_name': APP_NAME,
        'lang': 'fr',
        'start_url': './',
        'scope': './',
        'display': 'standalone',
        'background_color': BACKGROUND_COLOUR,
        'theme_color': THEME_COLOUR,
        'icons': icons,
    }
    return json.dumps(manifest, ensure_ascii=False, indent=2)


def name_served_manifest(manifest: str) -> str:
    """Name the manifest after its content, so browsers fetch a changed manifest again.

    The name avoids manifest.json, a file of Streamlit's own build in the same folder.
    """
    digest = hashlib.sha256(manifest.encode('utf-8')).hexdigest()
    short_digest = digest[:8]
    return f'web-app-manifest.{short_digest}.json'


def build_manifest_link(manifest_name: str) -> str:
    """Write the link that makes the served page announce the manifest."""
    return f'<link rel="manifest" href="./{manifest_name}" />'


def inject_manifest_link(html: str, manifest_link: str) -> str:
    """Add the manifest link to the head of a page, once."""
    if manifest_link in html:
        return html
    if HEAD_END not in html:
        raise ValueError('The page has no closing head tag to put the manifest link in.')
    return html.replace(HEAD_END, f'  {manifest_link}\n  {HEAD_END}', 1)


def install_web_app_manifest(static_folder: Path) -> None:
    """Copy the icons and the manifest into a Streamlit static folder and link the manifest."""
    # Serve the icons under their content-based names
    icon_names = {size: name_served_icon(icon_path=path) for size, path in ICON_PATHS.items()}
    for size, icon_name in icon_names.items():
        shutil.copyfile(src=ICON_PATHS[size], dst=static_folder / icon_name)

    # Serve the manifest and link it from the page
    manifest = build_manifest(icon_names=icon_names)
    manifest_name = name_served_manifest(manifest=manifest)
    manifest_path = static_folder / manifest_name
    manifest_path.write_text(manifest, encoding='utf-8')
    manifest_link = build_manifest_link(manifest_name=manifest_name)
    index_path = static_folder / 'index.html'
    html = index_path.read_text(encoding='utf-8')
    patched_html = inject_manifest_link(html=html, manifest_link=manifest_link)
    index_path.write_text(patched_html, encoding='utf-8')
    logger.info(f'Web app manifest installed as {manifest_name}.')


def main() -> None:
    """Install the manifest into the Streamlit package of the current environment."""
    logging.basicConfig(level=logging.INFO)
    static_folder = Path(streamlit.__file__).parent / 'static'
    install_web_app_manifest(static_folder=static_folder)


if __name__ == '__main__':
    main()
