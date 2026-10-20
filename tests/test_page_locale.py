"""French calendar in every browser: the locale script in the served page (R18.1)."""

from pathlib import Path

import pytest

from dimonapp.page_locale import LOCALE_SCRIPT, inject_locale_script, install_locale_script

PAGE = (
    '<html>\n  <head>\n    <script type="module" src="./static/js/index.js"></script>\n'
    '  </head>\n  <body></body>\n</html>\n'
)


def test_r18_1_locale_script_comes_before_streamlit_s_scripts() -> None:
    """The browser language is set to Belgian French before Streamlit reads it."""
    patched_page = inject_locale_script(html=PAGE)

    assert "'fr-BE'" in LOCALE_SCRIPT
    assert patched_page.index(LOCALE_SCRIPT) < patched_page.index('<script type="module"')


def test_r18_1_locale_script_is_added_only_once() -> None:
    """Patching an already patched page changes nothing."""
    patched_page = inject_locale_script(html=PAGE)

    assert inject_locale_script(html=patched_page) == patched_page


def test_r18_1_page_without_head_is_refused() -> None:
    """A page that cannot hold the script is an error, not a silent skip."""
    with pytest.raises(ValueError):
        inject_locale_script(html='<html></html>')


def test_r18_1_install_patches_index(tmp_path: Path) -> None:
    """Installing rewrites index.html of the static folder with the script."""
    index_path = tmp_path / 'index.html'
    index_path.write_text(PAGE, encoding='utf-8')

    install_locale_script(static_folder=tmp_path)

    assert LOCALE_SCRIPT in index_path.read_text(encoding='utf-8')
