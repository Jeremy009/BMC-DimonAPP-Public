"""The login page: the local username and password form and Google sign-in (R4.2, R4.4)."""

import base64
from pathlib import Path

import sqlalchemy as sa
import streamlit as st

from dimonapp.authentication import authenticate_local_worker
from dimonapp.clock import read_now
from dimonapp.database import open_session
from dimonapp.google_identity import end_google_login, is_google_configured, start_google_login

LOCAL_WORKER_KEY = 'local_worker_id'
LOCAL_SIGNED_IN_AT_KEY = 'local_signed_in_at'
SESSION_EXPIRED_KEY = 'session_expired'

LOGIN_TITLE = 'Connexion'
GOOGLE_HEADING = '**Connexion administrateur**'
GOOGLE_BUTTON_LABEL = 'Se connecter avec Google'
GOOGLE_BUTTON_KEY = 'google_login'
GOOGLE_LOGO_PATH = Path(__file__).parent / 'assets' / 'google-g.svg'
GOOGLE_REFUSED_MESSAGE = (
    "Ce compte Google n'a pas accès à la DimonAPP. Contactez un administrateur BMC."
)
OTHER_GOOGLE_ACCOUNT_LABEL = 'Utiliser un autre compte Google'
LOCAL_HEADING = '**Connexion travailleur**'
USERNAME_LABEL = "Nom d'utilisateur"
PASSWORD_LABEL = 'Mot de passe'
LOCAL_BUTTON_LABEL = 'Se connecter'
WRONG_CREDENTIALS_MESSAGE = "Nom d'utilisateur ou mot de passe incorrect."
DEACTIVATED_MESSAGE = 'Ce compte est désactivé. Contactez un administrateur BMC.'
LOCKED_MESSAGE = 'Trop de tentatives de connexion. Réessayez dans 15 minutes.'
SESSION_EXPIRED_MESSAGE = 'Votre session a expiré. Veuillez vous reconnecter.'

# Streamlit cannot put an image of our own on a button. The key gives the button a CSS class,
# which adds the Google logo before the label; the rest stays a plain Streamlit button.
GOOGLE_BUTTON_STYLE = """
<style>
.st-key-{key} button p::before {{
    content: '';
    display: inline-block;
    width: 1.15em;
    height: 1.15em;
    margin-right: 0.65em;
    vertical-align: -0.2em;
    background: url('data:image/svg+xml;base64,{logo}') no-repeat center / contain;
}}
</style>
"""


def build_google_button_style() -> str:
    """Build the style that puts the Google logo on the Google sign-in button."""
    logo_bytes = GOOGLE_LOGO_PATH.read_bytes()
    logo = base64.b64encode(logo_bytes).decode('ascii')
    return GOOGLE_BUTTON_STYLE.format(key=GOOGLE_BUTTON_KEY, logo=logo)


def render_google_block(is_google_refused: bool, is_google_deactivated: bool) -> None:
    """Render the Google sign-in button, or the refusal when the Google account has no access.

    A refused account stays signed in at Google's side of Streamlit, so the person gets a
    button to drop it and try another account (R4.8). A deactivated account is told so
    (R4.12).
    """
    if is_google_refused:
        message = DEACTIVATED_MESSAGE if is_google_deactivated else GOOGLE_REFUSED_MESSAGE
        st.error(message)
        if st.button(label=OTHER_GOOGLE_ACCOUNT_LABEL, type='primary', width='stretch'):
            end_google_login()
        return

    st.markdown(GOOGLE_HEADING)
    # A style given to st.html takes no room on the page, unlike one given to st.markdown
    st.html(build_google_button_style())
    is_configured = is_google_configured()
    is_clicked = st.button(
        label=GOOGLE_BUTTON_LABEL,
        key=GOOGLE_BUTTON_KEY,
        width='stretch',
        disabled=not is_configured,
    )
    if is_clicked:
        start_google_login()


def render_local_form(engine: sa.Engine) -> None:
    """Render the username and password form and sign the worker in when both are right."""
    st.markdown(LOCAL_HEADING)
    with st.form(key='local_login', border=False):
        # The labels show inside the empty fields; hidden labels stay for screen readers
        username = st.text_input(
            label=USERNAME_LABEL,
            placeholder=USERNAME_LABEL,
            label_visibility='collapsed',
        )
        password = st.text_input(
            label=PASSWORD_LABEL,
            type='password',
            placeholder=PASSWORD_LABEL,
            label_visibility='collapsed',
        )
        is_submitted = st.form_submit_button(label=LOCAL_BUTTON_LABEL, width='stretch')
    if not is_submitted:
        return

    now = read_now()
    with open_session(engine=engine) as session:
        sign_in = authenticate_local_worker(
            session=session,
            username=username,
            password=password,
            now=now,
        )
    if sign_in.outcome != 'accepted':
        # Only a deactivated worker with the right password is told why (R4.12); a locked
        # username is told to wait, known or not (R4.14)
        refusal_messages = {
            'deactivated': DEACTIVATED_MESSAGE,
            'locked': LOCKED_MESSAGE,
            'refused': WRONG_CREDENTIALS_MESSAGE,
        }
        st.error(refusal_messages[sign_in.outcome])
        return

    # Only the worker id is kept, the account is read again on every rerun; the sign-in time
    # lets the sign-in end after 12 hours (R4.13)
    st.session_state[LOCAL_WORKER_KEY] = sign_in.worker_id
    st.session_state[LOCAL_SIGNED_IN_AT_KEY] = now
    st.rerun()


def render_login_page(
    engine: sa.Engine,
    is_google_refused: bool,
    is_google_deactivated: bool,
) -> None:
    """Render the only page a signed-out visitor sees (R1.8); there is no registration (R4.4).

    The page is wide, so the title and the two sign-in blocks sit in a centred column. The
    local form comes first, except after a refused Google sign-in: the refusal is then the
    first thing to read. After an expired sign-in the page says so once (R4.13).
    """
    _, centre_column, _ = st.columns([1, 2, 1])
    with centre_column:
        st.title(LOGIN_TITLE)
        if st.session_state.pop(SESSION_EXPIRED_KEY, False):
            st.info(SESSION_EXPIRED_MESSAGE)
        if not is_google_refused:
            render_local_form(engine=engine)
        render_google_block(
            is_google_refused=is_google_refused,
            is_google_deactivated=is_google_deactivated,
        )
        if is_google_refused:
            render_local_form(engine=engine)
