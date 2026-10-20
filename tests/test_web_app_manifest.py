"""Android home screen icon served through a web app manifest (R18.10)."""

import json
from pathlib import Path

import pytest
from PIL import Image

from dimonapp.web_app_manifest import (
    ICON_PATHS,
    build_manifest,
    build_manifest_link,
    inject_manifest_link,
    install_web_app_manifest,
    name_served_manifest,
)

PAGE = '<html>\n  <head>\n    <title>Streamlit</title>\n  </head>\n  <body></body>\n</html>\n'
LOGO_ORANGE = (247, 102, 37)
ICON_NAMES = {192: 'android-icon-192.abc.png', 512: 'android-icon-512.def.png'}


@pytest.mark.parametrize('size', [192, 512])
def test_r18_10_icon_has_the_size_android_asks_for(size: int) -> None:
    """The committed icons are square PNGs of 192 and 512 pixels."""
    with Image.open(ICON_PATHS[size]) as icon:
        assert icon.format == 'PNG'
        assert icon.size == (size, size)


@pytest.mark.parametrize('size', [192, 512])
def test_r18_10_icon_is_full_bleed_with_the_climber_in_the_safe_circle(size: int) -> None:
    """Android cuts the icon to its own shape: orange to the edges, the logo in the middle 80 %."""
    with Image.open(ICON_PATHS[size]) as icon:
        rgb_icon = icon.convert('RGB')
    corners = [rgb_icon.getpixel(xy=(0, 0)), rgb_icon.getpixel(xy=(size - 1, size - 1))]
    dark_pixels = rgb_icon.convert('L').point(lambda value: 255 if value < 100 else 0)
    left, top, right, bottom = dark_pixels.getbbox()
    centre = size / 2
    corner_distances = [
        ((x - centre) ** 2 + (y - centre) ** 2) ** 0.5
        for x, y in [(left, top), (right, top), (left, bottom), (right, bottom)]
    ]

    assert corners == [LOGO_ORANGE, LOGO_ORANGE]
    assert max(corner_distances) <= 0.4 * size


def test_r18_10_manifest_names_the_application_and_opens_it_without_browser_bar() -> None:
    """The home screen shows DimonAPP and the application opens on its start page."""
    manifest = json.loads(build_manifest(icon_names=ICON_NAMES))

    assert manifest['name'] == 'DimonAPP'
    assert manifest['short_name'] == 'DimonAPP'
    assert manifest['start_url'] == './'
    assert manifest['display'] == 'standalone'


def test_r18_10_manifest_points_at_both_served_icons_as_maskable() -> None:
    """Each icon is listed by its served name and size, and may be cut to any shape."""
    manifest = json.loads(build_manifest(icon_names=ICON_NAMES))
    icons = {icon['sizes']: icon for icon in manifest['icons']}

    assert icons['192x192']['src'] == './android-icon-192.abc.png'
    assert icons['512x512']['src'] == './android-icon-512.def.png'
    assert 'maskable' in icons['512x512']['purpose'].split()


def test_r18_10_served_manifest_name_follows_its_content() -> None:
    """A changed manifest gets a new name, and never the name of Streamlit's own manifest.json."""
    first_name = name_served_manifest(manifest='{"name": "first"}')
    second_name = name_served_manifest(manifest='{"name": "second"}')

    assert first_name.startswith('web-app-manifest.')
    assert first_name.endswith('.json')
    assert first_name != second_name


def test_r18_10_link_is_added_inside_the_head_only_once() -> None:
    """The manifest link lands before the closing head tag; patching again changes nothing."""
    manifest_link = build_manifest_link(manifest_name='web-app-manifest.abc.json')
    patched_page = inject_manifest_link(html=PAGE, manifest_link=manifest_link)

    assert patched_page.index(manifest_link) < patched_page.index('</head>')
    assert inject_manifest_link(html=patched_page, manifest_link=manifest_link) == patched_page


def test_r18_10_page_without_head_is_refused() -> None:
    """A page that cannot hold the link is an error at build time, not a silent skip."""
    manifest_link = build_manifest_link(manifest_name='web-app-manifest.abc.json')
    with pytest.raises(ValueError):
        inject_manifest_link(html='<html></html>', manifest_link=manifest_link)


def test_r18_10_install_serves_icons_and_manifest_and_links_it(tmp_path: Path) -> None:
    """Installing puts the icons and the manifest next to index.html and links the manifest."""
    index_path = tmp_path / 'index.html'
    index_path.write_text(PAGE, encoding='utf-8')

    install_web_app_manifest(static_folder=tmp_path)

    manifest_paths = list(tmp_path.glob('web-app-manifest.*.json'))
    assert len(manifest_paths) == 1
    manifest_path = manifest_paths[0]
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    served_icon_names = [icon['src'].removeprefix('./') for icon in manifest['icons']]
    served_icons = [(tmp_path / name).read_bytes() for name in served_icon_names]
    committed_icons = [path.read_bytes() for path in ICON_PATHS.values()]
    manifest_link = build_manifest_link(manifest_name=manifest_path.name)

    assert served_icons == committed_icons
    assert manifest_link in index_path.read_text(encoding='utf-8')
