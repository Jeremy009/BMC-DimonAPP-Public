"""The Streamlit configuration shared by every environment."""

import tomllib
from pathlib import Path

CONFIG_PATH = Path(__file__).parents[1] / '.streamlit' / 'config.toml'


def test_r3_8_browser_never_shows_error_details() -> None:
    """An unexpected error shows a general message; its details stay in the server log."""
    config = tomllib.loads(CONFIG_PATH.read_text(encoding='utf-8'))

    assert config['client']['showErrorDetails'] == 'none'
