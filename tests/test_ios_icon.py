"""iOS home screen icon and browser tab icon installed in the served page (R18.3)."""

from pathlib import Path

import pytest
from PIL import Image

from dimonapp.ios_icon import (
    ICON_LINK,
    ICON_NAME,
    ICON_PATH,
    STREAMLIT_FAVICON_LINK,
    TAB_ICON_LINK,
    TAB_ICON_NAME,
    TAB_ICON_PATH,
    inject_apple_touch_icon_link,
    install_apple_touch_icon,
    install_tab_icon,
    link_tab_icon,
    name_served_icon,
)

PAGE_HEAD = f'  <head>\n    <title>Streamlit</title>\n    {STREAMLIT_FAVICON_LINK}\n  </head>\n'
PAGE = f'<html>\n{PAGE_HEAD}  <body></body>\n</html>\n'
LOGO_ORANGE = (247, 102, 37)


def test_r18_3_icon_is_180_pixels_square() -> None:
    """The committed icon has the size iOS asks for."""
    with Image.open(ICON_PATH) as icon:
        assert icon.format == 'PNG'
        assert icon.size == (180, 180)


def test_r18_3_icon_fills_its_square_with_the_logo_orange() -> None:
    """iOS rounds the corners itself; a transparent or white margin would show as a border."""
    with Image.open(ICON_PATH) as icon:
        assert icon.mode == 'RGB'
        corners = [icon.getpixel(xy=(0, 0)), icon.getpixel(xy=(179, 179))]

    assert corners == [LOGO_ORANGE, LOGO_ORANGE]


def test_r18_3_served_icon_name_follows_its_content(tmp_path: Path) -> None:
    """A changed icon gets a new name, so a browser that kept the old one fetches it again."""
    icon_path = tmp_path / 'icon.png'
    icon_path.write_bytes(b'first drawing')
    first_name = name_served_icon(icon_path=icon_path)
    icon_path.write_bytes(b'second drawing')
    second_name = name_served_icon(icon_path=icon_path)

    assert first_name.startswith('icon.')
    assert first_name.endswith('.png')
    assert first_name != second_name


def test_r18_3_link_is_added_inside_the_head() -> None:
    """The apple-touch-icon link lands before the closing head tag."""
    patched_page = inject_apple_touch_icon_link(html=PAGE)

    assert patched_page.index(ICON_LINK) < patched_page.index('</head>')


def test_r18_3_link_is_added_only_once() -> None:
    """Patching an already patched page changes nothing."""
    patched_page = inject_apple_touch_icon_link(html=PAGE)

    assert inject_apple_touch_icon_link(html=patched_page) == patched_page
    assert patched_page.count(ICON_LINK) == 1


def test_r18_3_page_without_head_is_refused() -> None:
    """A page that cannot hold the link is an error, not a silent skip."""
    with pytest.raises(ValueError):
        inject_apple_touch_icon_link(html='<html></html>')


def test_r18_3_install_copies_icon_and_patches_index(tmp_path: Path) -> None:
    """Installing puts the icon next to index.html and links it."""
    index_path = tmp_path / 'index.html'
    index_path.write_text(PAGE, encoding='utf-8')

    install_apple_touch_icon(static_folder=tmp_path)

    assert (tmp_path / ICON_NAME).read_bytes() == ICON_PATH.read_bytes()
    assert ICON_LINK in index_path.read_text(encoding='utf-8')


def test_r18_3_tab_icon_is_a_small_square_png() -> None:
    """The committed tab icon is small enough to serve as a favicon."""
    with Image.open(TAB_ICON_PATH) as icon:
        assert icon.format == 'PNG'
        assert icon.size == (96, 96)


def test_r18_3_tab_icon_link_replaces_the_streamlit_one_only_once() -> None:
    """The page links the tab icon instead of the default; patching again changes nothing."""
    patched_page = link_tab_icon(html=PAGE)

    assert TAB_ICON_LINK in patched_page
    assert STREAMLIT_FAVICON_LINK not in patched_page
    assert link_tab_icon(html=patched_page) == patched_page


def test_r18_3_page_without_streamlit_icon_link_is_refused() -> None:
    """A page Streamlit changed is an error at build time, not a silent default icon."""
    with pytest.raises(ValueError):
        link_tab_icon(html='<html><head></head></html>')


def test_r18_3_install_serves_the_tab_icon_and_replaces_the_default(tmp_path: Path) -> None:
    """Installing links the tab icon and overwrites the icon Streamlit's script falls back to."""
    index_path = tmp_path / 'index.html'
    index_path.write_text(PAGE, encoding='utf-8')
    default_icon_path = tmp_path / 'favicon.png'
    default_icon_path.write_bytes(b'streamlit default icon')

    install_tab_icon(static_folder=tmp_path)

    assert (tmp_path / TAB_ICON_NAME).read_bytes() == TAB_ICON_PATH.read_bytes()
    assert default_icon_path.read_bytes() == TAB_ICON_PATH.read_bytes()
    assert TAB_ICON_LINK in index_path.read_text(encoding='utf-8')
