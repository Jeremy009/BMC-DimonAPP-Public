"""Shared page frame: logo, sidebar and footer of every page (R18.2 to R18.7)."""

import datetime
from pathlib import Path
from typing import Optional

import streamlit as st

from dimonapp import __version__
from dimonapp.authentication import SignedInUser

APP_TITLE = 'DimonAPP'
APP_EXPLANATION = (
    'Application de gestion des travailleurs et des déclarations Dimona '
    'pour Brussels Monkeys Climbing ASBL.'
)
SOP_HEADING = 'Comment utiliser la DimonAPP ?'
SOP_BUTTON_LABEL = 'Consulter les SOPs'
SOP_URL = 'https://www.brusselsmonkeysclimbing.com/sop'
SIGNED_IN_AS_LABEL = 'Connecté en tant que :'
SIGN_OUT_LABEL = 'Se déconnecter'
WEBSITE_LABEL = 'www.brusselsmonkeysclimbing.com'
WEBSITE_URL = 'https://www.brusselsmonkeysclimbing.com'
ORGANISATION_NAME = 'Brussels Monkeys Climbing'

ASSETS_FOLDER = Path(__file__).parent / 'assets'
FAVICON_PATH = ASSETS_FOLDER / 'favicon.png'
LOGO_PATH = ASSETS_FOLDER / 'logoarriere.png'

ENVIRONMENT_BADGE_COLOURS = {'TEST': 'red', 'ACC': 'orange', 'PROD': 'green'}

# Streamlit has no full-width footer, so the footer is a fixed block over the whole page.
# iPhone and iPad zoom into a field whose text is under 16px and stay zoomed in; Streamlit's
# fields use 14px, so on iOS (the only browser that knows -webkit-touch-callout) they get 16px.
FRAME_STYLE = """
<style>
.block-container {padding-bottom: 6rem;}
@supports (-webkit-touch-callout: none) {
    input, textarea {font-size: 16px !important;}
}
.bmc-footer {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 1000002;
    padding: 0.55rem 0 0.6rem 0;
    background: #ffffff;
    border-top: 1px solid #e6e6e6;
    text-align: center;
    line-height: 1.5;
}
</style>
"""


def build_environment_heading(app_env: str) -> str:
    """Build the sidebar heading: the application name with its TEST, ACC or PROD label (R18.6)."""
    colour = ENVIRONMENT_BADGE_COLOURS[app_env]
    return f'### {APP_TITLE} :{colour}-badge[{app_env}]'


def build_footer_text(version: str, year: int) -> str:
    """Build the footer line with the deployed version and the current year (R18.7)."""
    return f'V{version} - © {year} {ORGANISATION_NAME}'


def build_footer_html(version: str, year: int) -> str:
    """Build the footer block: the version line, then the website link (R18.7)."""
    footer_text = build_footer_text(version=version, year=year)
    website_line = f'<a href="{WEBSITE_URL}" target="_blank">{WEBSITE_LABEL}</a>'
    return f'<div class="bmc-footer">{footer_text}<br>{website_line}</div>'


def build_signed_in_text(user: SignedInUser) -> str:
    """Build the sidebar lines telling who is signed in, name and type in bold (R18.4)."""
    return f'{SIGNED_IN_AS_LABEL}  \n**{user.display_name} - {user.type_label}**'


def render_sidebar(app_env: str, user: Optional[SignedInUser]) -> bool:
    """Render the sidebar blocks in the FDS order and tell whether sign-out was clicked.

    The two account blocks (who is connected, sign out) are shown once signed in (R18.4, R18.5).
    """
    heading = build_environment_heading(app_env=app_env)
    with st.sidebar:
        st.markdown(heading)
        st.write(APP_EXPLANATION)
        if user is not None:
            st.markdown(build_signed_in_text(user=user))
        st.markdown(f'### {SOP_HEADING}')
        st.link_button(label=SOP_BUTTON_LABEL, url=SOP_URL, width='stretch')
        if user is None:
            return False
        st.markdown(f'### {SIGN_OUT_LABEL}')
        return st.button(label=SIGN_OUT_LABEL, key='sign_out', width='stretch')


def render_footer(today: datetime.date) -> None:
    """Render the full-width footer at the bottom of the page (R18.7)."""
    footer_html = build_footer_html(version=__version__, year=today.year)
    st.markdown(FRAME_STYLE, unsafe_allow_html=True)
    st.markdown(footer_html, unsafe_allow_html=True)


def render_frame(app_env: str, today: datetime.date, user: Optional[SignedInUser]) -> bool:
    """Render what every page shares: page icon, logo, sidebar and footer (R18.2, R18.3).

    Must be the first Streamlit call of a page, because it sets the page configuration.
    Tells whether the signed-in user clicked the sign-out button.
    """
    st.set_page_config(
        page_title=APP_TITLE,
        page_icon=str(FAVICON_PATH),
        layout='wide',
        initial_sidebar_state='expanded',
    )
    st.logo(image=str(LOGO_PATH), size='large')
    is_sign_out_clicked = render_sidebar(app_env=app_env, user=user)
    render_footer(today=today)
    return is_sign_out_clicked
