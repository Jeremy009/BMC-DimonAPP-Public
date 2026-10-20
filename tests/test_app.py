"""The running Streamlit page: sign-in, routing, frame and French labels.

Covers R1.5, R1.8, R4.2 to R4.8, R4.12 to R4.14 and R18.2 to R18.7. Google is never called: the
functions of dimonapp.google_identity are replaced.
"""

import datetime

import pytest
import sqlalchemy as sa
from streamlit.testing.v1 import AppTest

import dimonapp
from app_runner import (
    PASSWORD,
    add_account,
    add_ready_worker,
    build_local_worker,
    click_button,
    render_database_url,
    run_app,
    run_app_as_local_worker,
    sign_in_as_ready_worker,
    sign_in_locally,
)
from dimonapp import google_identity, login_page
from dimonapp.clock import read_now, read_today
from dimonapp.database import open_session
from dimonapp.french import format_month_title
from dimonapp.google_identity import GoogleIdentity
from dimonapp.last_actions import record_last_action
from dimonapp.models import (
    Activity,
    Admin,
    AuthMethod,
    DimonaStatus,
    LastAction,
    Worker,
    WorkerType,
)
from dimonapp.widgets import ACTION_REQUESTS_KEY
from dimonapp.worker_view import CANCEL_SELECT_KEY
from factories import build_activity, build_worker

EMAIL = 'lotte@example.com'
SESSION_EXPIRED_MESSAGE = 'Votre session a expiré. Veuillez vous reconnecter.'


def read_main_texts(app: AppTest) -> list[str]:
    """Give the texts of the main area; the footer style and the footer come first."""
    return [element.value for element in app.main.markdown]


def age_last_action(engine: sa.Engine, minutes: int) -> None:
    """Move the last action of every account a number of minutes into the past."""
    acted_at = read_now() - datetime.timedelta(minutes=minutes)
    with open_session(engine=engine) as session:
        session.execute(sa.update(LastAction).values(acted_at=acted_at))


def add_recent_admin_action(engine: sa.Engine) -> None:
    """Note an action of the one admin a minute ago, as the redirect after a Google sign-in does."""
    acted_at = read_now() - datetime.timedelta(minutes=1)
    with open_session(engine=engine) as session:
        admin_id = session.scalars(sa.select(Admin.id)).one()
        record_last_action(
            session=session,
            account_kind='admin',
            account_id=admin_id,
            acted_at=acted_at,
        )


def expire_local_sign_in(app: AppTest, engine: sa.Engine) -> None:
    """Make the local sign-in of the page idle for more than 30 minutes (R4.13)."""
    signed_in_at = read_now() - datetime.timedelta(minutes=40)
    app.session_state[login_page.LOCAL_SIGNED_IN_AT_KEY] = signed_in_at
    age_last_action(engine=engine, minutes=31)


def read_activities(engine: sa.Engine) -> list[Activity]:
    """Read every registered activity, detached from its session."""
    with open_session(engine=engine) as session:
        activities = list(session.scalars(sa.select(Activity).order_by(Activity.id)))
        session.expunge_all()
    return activities


def read_month_headings(app: AppTest) -> list[str]:
    """Give the month shown by the cancel tab and by the overview tab."""
    return [element.value for element in app.main.markdown if element.value.startswith('#### ')]


def build_identity(minutes_ago: int) -> GoogleIdentity:
    """Build the Google identity of a sign-in made a number of minutes ago."""
    signed_in_at = read_now() - datetime.timedelta(minutes=minutes_ago)
    return GoogleIdentity(email=EMAIL, name='Lotte Exemple', signed_in_at=signed_in_at)


def record_calls(monkeypatch: pytest.MonkeyPatch, module: object, name: str) -> list[str]:
    """Replace a function without arguments by one that only records that it was called."""
    calls: list[str] = []
    monkeypatch.setattr(module, name, lambda: calls.append(name))
    return calls


def test_r1_8_signed_out_visitor_sees_only_the_login_page(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without sign-in the main area holds the login page and no application content."""
    app = run_app(monkeypatch=monkeypatch, app_env='TEST')

    titles = [title.value for title in app.title]
    main_texts = ' '.join(element.value for element in app.main.markdown)

    assert titles == ['Connexion']
    assert 'Déclarez et suivez vos activités' not in main_texts
    assert 'Administration des travailleurs' not in main_texts


def test_r4_2_login_page_shows_the_mockup_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    """The login page offers the local form, then Google sign-in, labelled in French."""
    app = run_app(monkeypatch=monkeypatch, app_env='TEST')

    button_labels = [button.label for button in app.button]
    input_labels = [text_input.label for text_input in app.text_input]
    main_texts = [element.value for element in app.main.markdown]

    assert button_labels == ['Se connecter', 'Se connecter avec Google']
    assert input_labels == ["Nom d'utilisateur", 'Mot de passe']
    assert [text_input.placeholder for text_input in app.text_input] == input_labels
    assert app.text_input[1].proto.type == app.text_input[1].proto.PASSWORD
    local_heading = '**Connexion travailleur**'
    google_heading = '**Connexion administrateur**'
    assert main_texts.index(local_heading) < main_texts.index(google_heading)


def test_r4_2_google_button_carries_the_google_logo() -> None:
    """The style targets the label of the button with that key and carries the Google logo."""
    style = login_page.build_google_button_style()

    assert '.st-key-google_login button' in style
    assert "url('data:image/svg+xml;base64," in style
    assert '{' + 'key}' not in style


def test_r4_4_login_page_offers_no_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    """There is no way to create an account: two sign-in buttons and nothing else."""
    app = run_app(monkeypatch=monkeypatch, app_env='TEST')

    assert len(app.button) == 2
    assert len(app.text_input) == 2


def test_r4_8_google_button_is_disabled_when_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without Google settings the button cannot be clicked."""
    app = run_app(monkeypatch=monkeypatch, app_env='TEST')

    assert app.button[1].disabled
    assert len(app.caption) == 0


def test_r4_8_google_button_starts_the_google_login(monkeypatch: pytest.MonkeyPatch) -> None:
    """With Google configured, the button hands over to Streamlit's login."""
    monkeypatch.setattr(login_page, 'is_google_configured', lambda: True)
    calls = record_calls(monkeypatch=monkeypatch, module=login_page, name='start_google_login')
    app = run_app(monkeypatch=monkeypatch, app_env='TEST')

    app.button[1].click()
    app.run()

    assert not app.exception
    assert calls == ['start_google_login']


def test_r4_2_local_worker_reaches_the_worker_view(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """The right username and password lead to the worker view."""
    app = run_app_as_local_worker(monkeypatch=monkeypatch, engine=account_engine)

    assert app.title[0].value == 'DimonAPP'
    assert 'Déclarez et suivez vos activités' in read_main_texts(app=app)
    assert "Nom d'utilisateur" not in [text_input.label for text_input in app.text_input]


def test_r18_2_main_area_shows_title_and_subtitle(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """Once signed in, the main area starts with the title DimonAPP and a one-line subtitle."""
    app = run_app_as_local_worker(monkeypatch=monkeypatch, engine=account_engine)

    titles = [title.value for title in app.title]

    assert titles == ['DimonAPP']
    # The footer style and the footer come first, the tabs after the subtitle
    assert read_main_texts(app=app)[2] == 'Déclarez et suivez vos activités'


def test_r18_4_signed_in_sidebar_shows_the_account_blocks(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """Signed in, the sidebar adds who is connected and the sign-out block, in the FDS order."""
    app = run_app_as_local_worker(monkeypatch=monkeypatch, engine=account_engine)

    sidebar_types = [element.type for element in app.sidebar.children.values()]
    sidebar_texts = [element.value for element in app.sidebar.markdown]

    assert sidebar_types == [
        'markdown',
        'markdown',
        'markdown',
        'markdown',
        'link_button',
        'markdown',
        'button',
    ]
    assert sidebar_texts[0] == '### DimonAPP :red-badge[TEST]'
    assert sidebar_texts[2] == 'Connecté en tant que :  \n**Lotte Exemple - Article 17**'
    assert sidebar_texts[3] == '### Comment utiliser la DimonAPP ?'
    assert sidebar_texts[4] == '### Se déconnecter'
    assert app.sidebar.button[0].label == 'Se déconnecter'


def test_r4_2_wrong_password_shows_a_french_error(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """A wrong password keeps the visitor on the login page with one generic message."""
    add_account(engine=account_engine, account=build_local_worker())
    database_url = render_database_url(engine=account_engine)
    app = run_app(monkeypatch=monkeypatch, app_env='TEST', database_url=database_url)

    sign_in_locally(app=app, username='lotte', password='wrong')

    assert app.error[0].value == "Nom d'utilisateur ou mot de passe incorrect."
    assert app.title[0].value == 'Connexion'
    assert len(app.sidebar.button) == 0


def test_r4_7_worker_deactivated_while_signed_in_is_signed_out(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """An inactive worker is back on the login page at the next rerun."""
    app = run_app_as_local_worker(monkeypatch=monkeypatch, engine=account_engine)
    with open_session(engine=account_engine) as session:
        session.execute(sa.update(Worker).values(is_active=False))

    app.run()

    assert not app.exception
    assert app.title[0].value == 'Connexion'


def test_r18_4_sign_out_returns_to_the_login_page(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """The sign-out button ends the session of a local worker."""
    app = run_app_as_local_worker(monkeypatch=monkeypatch, engine=account_engine)

    app.sidebar.button[0].click()
    app.run()

    assert not app.exception
    assert app.title[0].value == 'Connexion'
    assert len(app.sidebar.button) == 0
    # Signing out is not an expired sign-in (R4.13)
    assert len(app.info) == 0


def test_r4_3_google_admin_reaches_the_admin_console(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """A Google account matching an admin leads to the admin console, shown as Admin."""
    add_account(engine=account_engine, account=Admin(email=EMAIL))
    database_url = render_database_url(engine=account_engine)

    app = run_app(
        monkeypatch=monkeypatch,
        app_env='TEST',
        database_url=database_url,
        identity=build_identity(minutes_ago=0),
    )

    subtitle = 'Administration des travailleurs, des déclarations Dimona et des paiements'
    assert app.title[0].value == 'DimonAPP'
    assert subtitle in read_main_texts(app=app)
    assert app.sidebar.markdown[2].value == 'Connecté en tant que :  \n**Lotte Exemple - Admin**'


def test_r4_8_google_worker_reaches_the_worker_view(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """A Google account matching an active Google worker leads to the worker view."""
    worker = build_worker(username='lotte', email=EMAIL, auth_method=AuthMethod.GOOGLE)
    add_account(engine=account_engine, account=worker)
    database_url = render_database_url(engine=account_engine)

    app = run_app(
        monkeypatch=monkeypatch,
        app_env='TEST',
        database_url=database_url,
        identity=build_identity(minutes_ago=0),
    )

    assert 'Déclarez et suivez vos activités' in read_main_texts(app=app)
    assert app.sidebar.markdown[2].value == 'Connecté en tant que :  \n**Test Worker - Article 17**'


def test_r4_12_deactivated_local_worker_is_told_so_with_the_right_password(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """The right password of a deactivated worker gets the reason; a wrong one does not."""
    worker = build_local_worker()
    worker.is_active = False
    add_account(engine=account_engine, account=worker)
    database_url = render_database_url(engine=account_engine)
    app = run_app(monkeypatch=monkeypatch, app_env='TEST', database_url=database_url)

    sign_in_locally(app=app, username='lotte', password=PASSWORD)

    assert app.error[0].value == 'Ce compte est désactivé. Contactez un administrateur BMC.'
    assert app.title[0].value == 'Connexion'
    assert len(app.sidebar.button) == 0

    sign_in_locally(app=app, username='lotte', password='wrong')

    assert app.error[0].value == "Nom d'utilisateur ou mot de passe incorrect."


def test_r4_12_deactivated_google_worker_is_told_so(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """A deactivated Google worker is refused with the reason and may try another account."""
    worker = build_worker(email=EMAIL, auth_method=AuthMethod.GOOGLE, is_active=False)
    add_account(engine=account_engine, account=worker)
    database_url = render_database_url(engine=account_engine)

    app = run_app(
        monkeypatch=monkeypatch,
        app_env='TEST',
        database_url=database_url,
        identity=build_identity(minutes_ago=0),
    )

    assert app.error[0].value == 'Ce compte est désactivé. Contactez un administrateur BMC.'
    assert app.title[0].value == 'Connexion'
    assert app.button[0].label == 'Utiliser un autre compte Google'


def test_r4_8_unknown_google_account_is_refused_in_french(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """Any other Google account stays on the login page, with a way to try another account."""
    calls = record_calls(monkeypatch=monkeypatch, module=login_page, name='end_google_login')
    database_url = render_database_url(engine=account_engine)

    app = run_app(
        monkeypatch=monkeypatch,
        app_env='TEST',
        database_url=database_url,
        identity=build_identity(minutes_ago=0),
    )

    message = "Ce compte Google n'a pas accès à la DimonAPP. Contactez un administrateur BMC."
    assert app.error[0].value == message
    assert app.title[0].value == 'Connexion'
    assert app.button[0].label == 'Utiliser un autre compte Google'
    assert len(app.sidebar.button) == 0

    app.button[0].click()
    app.run()

    assert calls == ['end_google_login']


def test_r18_4_sign_out_ends_the_google_session(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """Signing out of a Google account goes through Streamlit's logout."""
    calls = record_calls(monkeypatch=monkeypatch, module=google_identity, name='end_google_login')
    add_account(engine=account_engine, account=Admin(email=EMAIL))
    database_url = render_database_url(engine=account_engine)
    app = run_app(
        monkeypatch=monkeypatch,
        app_env='TEST',
        database_url=database_url,
        identity=build_identity(minutes_ago=0),
    )

    app.sidebar.button[0].click()
    app.run()

    assert not app.exception
    assert calls == ['end_google_login']


def test_r18_4_sidebar_blocks_follow_the_fds_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """Signed out, the sidebar shows name and label, explanation, SOP block, without spacers."""
    app = run_app(monkeypatch=monkeypatch, app_env='TEST')

    sidebar_types = [element.type for element in app.sidebar.children.values()]
    sidebar_texts = [element.value for element in app.sidebar.markdown]

    assert sidebar_types == ['markdown', 'markdown', 'markdown', 'link_button']
    assert sidebar_texts[0] == '### DimonAPP :red-badge[TEST]'
    assert sidebar_texts[1].startswith('Application de gestion des travailleurs')
    assert sidebar_texts[2] == '### Comment utiliser la DimonAPP ?'


def test_r18_4_signed_out_sidebar_has_no_account_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """No About heading, no signed-in name and no sign-out block before sign-in."""
    app = run_app(monkeypatch=monkeypatch, app_env='TEST')

    sidebar_text = ' '.join(element.value for element in app.sidebar.markdown)

    assert 'About' not in sidebar_text
    assert 'Connecté en tant que' not in sidebar_text
    assert 'Se déconnecter' not in sidebar_text
    assert len(app.sidebar.button) == 0


def test_r18_5_sop_button_opens_the_sop_page(monkeypatch: pytest.MonkeyPatch) -> None:
    """The sidebar button is labelled in French and links to the SOP page."""
    app = run_app(monkeypatch=monkeypatch, app_env='TEST')

    sop_button = app.sidebar.get('link_button')[0]

    assert sop_button.proto.label == 'Consulter les SOPs'
    assert sop_button.proto.url == 'https://www.brusselsmonkeysclimbing.com/sop'


def test_r18_6_production_shows_prod_label(
    monkeypatch: pytest.MonkeyPatch,
    rsz_environment: None,
) -> None:
    """The same code shows PROD when the environment says so."""
    app = run_app(monkeypatch=monkeypatch, app_env='PROD')

    assert app.sidebar.markdown[0].value == '### DimonAPP :green-badge[PROD]'


def test_r18_7_footer_shows_version_and_current_year(monkeypatch: pytest.MonkeyPatch) -> None:
    """The footer shows the deployed version and the current year."""
    app = run_app(monkeypatch=monkeypatch, app_env='TEST')

    year = datetime.date.today().year
    footer_text = f'V{dimonapp.__version__} - © {year} Brussels Monkeys Climbing'
    main_texts = [element.value for element in app.main.markdown]

    assert any(footer_text in text for text in main_texts)


@pytest.mark.parametrize('app_env', ['ACC', 'PROD'])
def test_r18_7_footer_names_no_dimona_service(
    monkeypatch: pytest.MonkeyPatch,
    rsz_environment: None,
    app_env: str,
) -> None:
    """The footer shows no Dimona service, also where a real RSZ service is called."""
    app = run_app(monkeypatch=monkeypatch, app_env=app_env)

    main_texts = [element.value for element in app.main.markdown]

    assert not any('socialsecurity' in text for text in main_texts)
    assert not any('Dimona' in text for text in main_texts if 'bmc-footer' in text)


def test_r4_13_local_sign_in_ends_after_12_hours(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """A local worker signed in more than 12 hours ago is back on the login page."""
    app = run_app_as_local_worker(monkeypatch=monkeypatch, engine=account_engine)
    signed_in_at = read_now() - datetime.timedelta(hours=12, minutes=1)
    app.session_state[login_page.LOCAL_SIGNED_IN_AT_KEY] = signed_in_at

    app.run()

    assert not app.exception
    assert app.title[0].value == 'Connexion'
    assert app.info[0].value == SESSION_EXPIRED_MESSAGE
    assert len(app.sidebar.button) == 0


def test_r4_13_local_sign_in_ends_after_30_idle_minutes_and_can_start_again(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """After 30 idle minutes the next click shows the login page and says why, once.

    The message is gone at the next rerun, and signing in again works.
    """
    app = run_app_as_local_worker(monkeypatch=monkeypatch, engine=account_engine)
    signed_in_at = read_now() - datetime.timedelta(minutes=40)
    app.session_state[login_page.LOCAL_SIGNED_IN_AT_KEY] = signed_in_at
    age_last_action(engine=account_engine, minutes=31)

    app.run()

    assert not app.exception
    assert app.title[0].value == 'Connexion'
    assert app.info[0].value == SESSION_EXPIRED_MESSAGE

    sign_in_locally(app=app, username='lotte', password='wrong')

    assert len(app.info) == 0

    sign_in_locally(app=app, username='lotte', password=PASSWORD)

    assert app.title[0].value == 'DimonAPP'


def test_r4_13_local_sign_in_goes_on_within_30_idle_minutes(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """A click after 29 quiet minutes keeps the worker signed in."""
    app = run_app_as_local_worker(monkeypatch=monkeypatch, engine=account_engine)
    signed_in_at = read_now() - datetime.timedelta(minutes=40)
    app.session_state[login_page.LOCAL_SIGNED_IN_AT_KEY] = signed_in_at
    age_last_action(engine=account_engine, minutes=29)

    app.run()

    assert not app.exception
    assert app.title[0].value == 'DimonAPP'


def test_r4_13_google_sign_in_ends_after_12_hours(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """A Google sign-in issued more than 12 hours ago goes through Streamlit's logout."""
    calls = record_calls(monkeypatch=monkeypatch, module=google_identity, name='end_google_login')
    add_account(engine=account_engine, account=Admin(email=EMAIL))
    database_url = render_database_url(engine=account_engine)
    signed_in_at = read_now() - datetime.timedelta(hours=12, minutes=1)
    identity = GoogleIdentity(email=EMAIL, name='Lotte Exemple', signed_in_at=signed_in_at)

    app = run_app(
        monkeypatch=monkeypatch,
        app_env='TEST',
        database_url=database_url,
        identity=identity,
    )

    assert calls == ['end_google_login']
    assert 'Administration des travailleurs' not in ' '.join(read_main_texts(app=app))


def test_r4_13_google_sign_in_ends_after_30_idle_minutes(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """After 30 idle minutes the next click of a Google admin goes through Streamlit's logout."""
    calls = record_calls(monkeypatch=monkeypatch, module=google_identity, name='end_google_login')
    add_account(engine=account_engine, account=Admin(email=EMAIL))
    add_recent_admin_action(engine=account_engine)
    database_url = render_database_url(engine=account_engine)
    app = run_app(
        monkeypatch=monkeypatch,
        app_env='TEST',
        database_url=database_url,
        identity=build_identity(minutes_ago=40),
    )
    assert calls == []

    age_last_action(engine=account_engine, minutes=31)
    app.run()

    assert not app.exception
    assert calls == ['end_google_login']


def test_r4_13_new_tab_does_not_restart_the_30_idle_minutes(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """A tab opened after 30 idle minutes, with Google's cookie still there, signs the admin out.

    This is the computer left with the tab closed but without signing out.
    """
    calls = record_calls(monkeypatch=monkeypatch, module=google_identity, name='end_google_login')
    add_account(engine=account_engine, account=Admin(email=EMAIL))
    add_recent_admin_action(engine=account_engine)
    database_url = render_database_url(engine=account_engine)
    identity = build_identity(minutes_ago=40)
    run_app(monkeypatch=monkeypatch, app_env='TEST', database_url=database_url, identity=identity)
    age_last_action(engine=account_engine, minutes=31)

    new_tab = run_app(
        monkeypatch=monkeypatch,
        app_env='TEST',
        database_url=database_url,
        identity=identity,
    )

    assert calls == ['end_google_login']
    assert 'Administration des travailleurs' not in ' '.join(read_main_texts(app=new_tab))


def test_r4_13_fresh_google_sign_in_goes_on_after_an_old_last_action(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """Signing in again counts as an action: yesterday's last action ends nothing."""
    calls = record_calls(monkeypatch=monkeypatch, module=google_identity, name='end_google_login')
    add_account(engine=account_engine, account=Admin(email=EMAIL))
    database_url = render_database_url(engine=account_engine)
    run_app(
        monkeypatch=monkeypatch,
        app_env='TEST',
        database_url=database_url,
        identity=build_identity(minutes_ago=0),
    )
    age_last_action(engine=account_engine, minutes=24 * 60)

    app = run_app(
        monkeypatch=monkeypatch,
        app_env='TEST',
        database_url=database_url,
        identity=build_identity(minutes_ago=1),
    )

    assert calls == []
    assert 'Administration des travailleurs' in ' '.join(read_main_texts(app=app))


def test_r4_13_confirm_on_an_expired_sign_in_never_declares(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """The click that meets an expired sign-in declares nothing, not even after signing in again.

    The click only shows the login page; signing in again then runs nothing by itself.
    """
    add_ready_worker(engine=account_engine)
    app = sign_in_as_ready_worker(monkeypatch=monkeypatch, engine=account_engine)
    app.selectbox[0].set_value('courses')
    app.number_input[0].set_value(5)
    app.run()
    expire_local_sign_in(app=app, engine=account_engine)

    click_button(app=app, label="Confirmer l'activité")

    assert app.title[0].value == 'Connexion'
    sign_in_locally(app=app, username='lotte', password=PASSWORD)
    assert app.title[0].value == 'DimonAPP'
    assert len(app.success) == 0
    assert read_activities(engine=account_engine) == []


def test_r4_13_cancel_on_an_expired_sign_in_never_cancels(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """The cancel click that meets an expired sign-in cancels nothing, also after signing in."""
    worker_id = add_ready_worker(engine=account_engine, worker_type=WorkerType.VRIJWILLIGER)
    with open_session(engine=account_engine) as session:
        for activity_type in ('permanence', 'courses'):
            activity = build_activity(
                worker_id=worker_id,
                worker_type=WorkerType.VRIJWILLIGER,
                activity_date=read_today(),
                activity_type=activity_type,
                dimona_status=DimonaStatus.NOT_APPLICABLE,
            )
            session.add(activity)
    app = sign_in_as_ready_worker(monkeypatch=monkeypatch, engine=account_engine)
    app.selectbox(key=CANCEL_SELECT_KEY).select_index(1)
    app.run()
    expire_local_sign_in(app=app, engine=account_engine)

    click_button(app=app, label='Annuler cette activité')

    assert app.title[0].value == 'Connexion'
    sign_in_locally(app=app, username='lotte', password=PASSWORD)
    activities = read_activities(engine=account_engine)
    assert [activity.is_cancelled for activity in activities] == [False, False]
    assert len(app.success) == 0


def test_r4_13_late_click_after_the_sign_in_ended_never_acts(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """A second click that reaches the page after the sign-in ended is dropped on the login page.

    Streamlit accepts such a click before the page runs, as if the button were still drawn.
    """
    add_ready_worker(engine=account_engine)
    app = sign_in_as_ready_worker(monkeypatch=monkeypatch, engine=account_engine)
    expire_local_sign_in(app=app, engine=account_engine)
    click_button(app=app, label="Confirmer l'activité")

    app.session_state[ACTION_REQUESTS_KEY] = {'confirm_activity'}
    app.run()
    sign_in_locally(app=app, username='lotte', password=PASSWORD)

    assert app.title[0].value == 'DimonAPP'
    assert read_activities(engine=account_engine) == []


def test_r4_13_next_worker_in_the_same_tab_starts_afresh(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """On a shared computer, Noor signing in after Lotte's expired click inherits nothing.

    Nothing runs for Noor, and her tabs open as after any sign-in, on the current month.
    """
    add_ready_worker(engine=account_engine)
    noor = build_local_worker(username='noor', national_register_number='90010112372')
    add_account(engine=account_engine, account=noor)
    app = sign_in_as_ready_worker(monkeypatch=monkeypatch, engine=account_engine)
    click_button(app=app, label=':material/arrow_forward:', index=0)
    expire_local_sign_in(app=app, engine=account_engine)
    click_button(app=app, label="Confirmer l'activité")

    sign_in_locally(app=app, username='noor', password=PASSWORD)

    today = read_today()
    month_name = format_month_title(year=today.year, month=today.month)
    sidebar_texts = [element.value for element in app.sidebar.markdown]
    assert sidebar_texts[2] == 'Connecté en tant que :  \n**Noor Exemple - Article 17**'
    assert read_month_headings(app=app) == [f'#### {month_name}', f'#### {month_name}']
    assert len(app.success) == 0
    assert len(app.error) == 0
    assert read_activities(engine=account_engine) == []


def test_r4_14_five_wrong_passwords_show_the_lock_message(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """After five wrong passwords even the right one is refused, with the French lock message."""
    add_account(engine=account_engine, account=build_local_worker())
    database_url = render_database_url(engine=account_engine)
    app = run_app(monkeypatch=monkeypatch, app_env='TEST', database_url=database_url)
    for _ in range(5):
        sign_in_locally(app=app, username='lotte', password='wrong')

    sign_in_locally(app=app, username='lotte', password=PASSWORD)

    assert app.error[0].value == 'Trop de tentatives de connexion. Réessayez dans 15 minutes.'
    assert app.title[0].value == 'Connexion'
