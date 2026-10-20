"""Text of the shared page frame (R18.5, R18.6, R18.7)."""

from dimonapp.frame import (
    FRAME_STYLE,
    SOP_URL,
    build_environment_heading,
    build_footer_html,
    build_footer_text,
)


def test_r18_6_heading_shows_test_label() -> None:
    """The test environment is labelled TEST next to the application name."""
    assert build_environment_heading(app_env='TEST') == '### DimonAPP :red-badge[TEST]'


def test_r18_6_heading_shows_acc_label() -> None:
    """Acceptance is labelled ACC next to the application name."""
    assert build_environment_heading(app_env='ACC') == '### DimonAPP :orange-badge[ACC]'


def test_r18_6_heading_shows_prod_label() -> None:
    """Production is labelled PROD next to the application name."""
    assert build_environment_heading(app_env='PROD') == '### DimonAPP :green-badge[PROD]'


def test_r18_5_sop_link_is_fixed() -> None:
    """The SOP button points to the fixed BMC address."""
    assert SOP_URL == 'https://www.brusselsmonkeysclimbing.com/sop'


def test_r18_7_footer_text_shows_version_and_year() -> None:
    """The footer line holds the version, the year and the name of the association."""
    footer_text = build_footer_text(version='3.0.0', year=2026)

    assert footer_text == 'V3.0.0 - © 2026 Brussels Monkeys Climbing'


def test_r18_7_footer_links_to_the_website() -> None:
    """The website link sits below the version line."""
    footer_html = build_footer_html(version='3.0.0', year=2026)
    link = '<a href="https://www.brusselsmonkeysclimbing.com" target="_blank">'

    assert f'{link}www.brusselsmonkeysclimbing.com</a>' in footer_html
    assert footer_html.index('V3.0.0') < footer_html.index(link)


def test_r18_7_footer_names_no_dimona_service() -> None:
    """The footer ends with the website link; the Dimona service is not named in it."""
    footer_html = build_footer_html(version='3.0.0', year=2026)

    assert footer_html.endswith('www.brusselsmonkeysclimbing.com</a></div>')
    assert 'Dimona' not in footer_html
    assert 'socialsecurity' not in footer_html


def test_ios_fields_get_16px_text_so_safari_does_not_zoom_in() -> None:
    """On iPhone and iPad only, fields get 16px text: iOS zooms into smaller text and stays."""
    ios_only = '@supports (-webkit-touch-callout: none) {'
    field_text = 'input, textarea {font-size: 16px !important;}'

    assert f'{ios_only}\n    {field_text}' in FRAME_STYLE
