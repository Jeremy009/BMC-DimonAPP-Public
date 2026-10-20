"""The running admin console: eight tabs on the real pages (R10.x to R15.x as the admin sees them).

The rules themselves are tested without Streamlit in the test files of their modules; these
tests check that the pages pass the admin's input on and show the result in French.
"""

import io
import zipfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from streamlit.testing.v1 import AppTest

from app_runner import (
    PASSWORD,
    add_ready_worker,
    click_key,
    read_tab_order,
    record_downloads,
    render_database_url,
    run_app,
    run_app_as_admin,
    sign_in_locally,
)
from dimonapp.admin_fiches_tab import build_deadline_text
from dimonapp.clock import read_today
from dimonapp.configuration import save_organisation
from dimonapp.database import open_session
from dimonapp.french import NO_BREAK_SPACE, format_date, format_month_title
from dimonapp.models import (
    RATE_CODES,
    Activity,
    AuthMethod,
    Authorisation,
    CompensationRate,
    DimonaStatus,
    DocumentType,
    OrganisationConfig,
    Worker,
    WorkerType,
    YearlyLimit,
)
from dimonapp.months import shift_month
from dimonapp.passwords import verify_password
from dimonapp.payment_file import MISSING_ORGANISATION_MESSAGE
from dimonapp.rate_sheets import DEFAULT_RATES
from dimonapp.worker_tables import COURSE_ACTIVITY_TYPES, ROUTE_ACTIVITY_TYPES
from factories import (
    build_activity,
    build_authorisation,
    build_complete_limits,
    build_organisation_form,
)

TAB_NAMES = [
    'Tableau de bord',
    'Rapport mensuel',
    'Activités',
    'Travailleurs',
    'Autorisations',
    'Rémunération',
    'Fiches fiscales',
    'Configuration',
]
CONTENT = b'%PDF-1.4 original \x00\xff bytes'


def read_alerts(app: AppTest) -> dict[str, list[str]]:
    """Give the messages shown in the main area, per kind."""
    return {
        'success': [element.value for element in app.main.success],
        'error': [element.value for element in app.main.error],
        'warning': [element.value for element in app.main.warning],
        'info': [element.value for element in app.main.info],
    }


def read_metrics(app: AppTest) -> dict[str, str]:
    """Give the figures shown, by label."""
    return {metric.label: metric.value for metric in app.metric}


def read_table(app: AppTest, first_column: str) -> list[dict[str, str]]:
    """Give the rows of the table whose first column has the given header."""
    for element in app.table:
        table = element.value
        if list(table.columns)[0] == first_column:
            return table.to_dict(orient='records')
    return []


def read_worker(engine: sa.Engine, username: str) -> Worker:
    """Read a worker by username, detached from its session."""
    with open_session(engine=engine) as session:
        worker = session.scalars(sa.select(Worker).where(Worker.username == username)).one()
        session.expunge(worker)
    return worker


def read_authorisations(engine: sa.Engine, worker_id: int) -> list[Authorisation]:
    """Read the documents of a worker, newest last, detached from their session."""
    with open_session(engine=engine) as session:
        query = (
            sa.select(Authorisation)
            .where(Authorisation.worker_id == worker_id)
            .order_by(Authorisation.id)
        )
        authorisations = list(session.scalars(query))
        session.expunge_all()
    return authorisations


def add_activity(engine: sa.Engine, activity: Activity) -> int:
    """Commit an activity and give its id."""
    with open_session(engine=engine) as session:
        session.add(activity)
        session.flush()
        return activity.id


def add_organisation(engine: sa.Engine) -> None:
    """Commit BMC's complete details, as the exports need them."""
    with open_session(engine=engine) as session:
        save_organisation(session=session, form=build_organisation_form())


def find_download(downloads: list[dict[str, object]], key: str) -> dict[str, object]:
    """Give what the download button with a key offered on the last run."""
    matches = [download for download in downloads if download['key'] == key]
    return matches[-1]


def read_tab_captions(app: AppTest, label: str) -> list[str]:
    """Give the small notes shown in the tab with the given name."""
    tab = next(tab for tab in app.tabs if tab.label == label)
    return [caption.value for caption in tab.caption]


def captions_of_workers_tab(app: AppTest) -> list[str]:
    """Give the small notes shown in the workers tab; the forms carry none."""
    return read_tab_captions(app=app, label='Travailleurs')


def fill_worker_form(app: AppTest, prefix: str = 'create_0') -> None:
    """Fill in the create form for a local article 17 worker, rates included."""
    app.text_input(key=f'{prefix}_first_name').set_value('Emma')
    app.text_input(key=f'{prefix}_last_name').set_value('Janssens')
    app.text_input(key=f'{prefix}_national_register_number').set_value('91.02.03-123.63')
    app.selectbox(key=f'{prefix}_worker_type').set_value(WorkerType.ARTICLE_17)
    app.text_input(key=f'{prefix}_iban').set_value('BE07 3456 7890 1234')
    app.text_input(key=f'{prefix}_username').set_value('e.janssens')
    app.text_input(key=f'{prefix}_email').set_value('emma.janssens@example.com')
    app.text_input(key=f'{prefix}_street').set_value('Rue Imaginaire 12')
    app.text_input(key=f'{prefix}_postal_code').set_value('1050')
    app.text_input(key=f'{prefix}_city').set_value('Ixelles')
    app.text_input(key=f'{prefix}_password').set_value('first-password')
    for rate_code in RATE_CODES:
        app.number_input(key=f'{prefix}_rate_{rate_code}').set_value(22.5)


def upload_document(app: AppTest, worker_id: int, filename: str = 'contrat_2026.pdf') -> AppTest:
    """Open the upload form, fill it in for a contract covering routes and courses, and save."""
    click_key(app=app, key='upload_document')
    prefix = f'upload_{worker_id}_0'
    uploader = [item for item in app.get('file_uploader') if item.key == f'{prefix}_file'][0]
    uploader.upload(filename=filename, content=CONTENT, mime_type='application/pdf')
    app.multiselect(key=f'{prefix}_cover').set_value(['courses', 'route'])
    app.date_input(key=f'{prefix}_start_date').set_value(date(2026, 9, 1))
    return click_key(app=app, key='save_document')


def test_r10_1_admin_console_has_eight_tabs_and_opens_on_the_dashboard(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """Eight tabs in the FDS order, each starting with its own name as heading (R18.2)."""
    app = run_app_as_admin(monkeypatch=monkeypatch, engine=account_engine)

    today = read_today()
    tab_labels = [tab.label for tab in app.tabs]
    headings = [header.value for header in app.header]

    assert tab_labels == TAB_NAMES
    assert headings == TAB_NAMES
    assert app.subheader[0].value == format_month_title(year=today.year, month=today.month)
    assert read_metrics(app=app)['Coût prévu ce mois'] == f'0,00{NO_BREAK_SPACE}€'
    # Without any alert, the alerts section is left out entirely
    markdown_texts = [element.value for element in app.main.markdown]
    assert '#### Alertes' not in markdown_texts
    assert 'Aucune alerte.' not in read_alerts(app=app)['info']


def test_r10_2_dashboard_shows_the_figures_and_every_kind_of_alert(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """Cost of the month, limit flag, pending Dimona, missing limits and ending contract."""
    today = read_today()
    worker_id = add_ready_worker(engine=account_engine)
    with open_session(engine=account_engine) as session:
        limits = build_complete_limits(year=today.year)
        for limit in limits:
            # The hours columns of the database hold less than the high test limit
            if limit.hours_limit is not None:
                limit.hours_limit = Decimal('9000')
        limits[1].hours_limit = Decimal('100')
        # The ready worker already holds the flexi-job row of this year
        session.execute(sa.delete(YearlyLimit))
        session.add_all(limits)
        counted = build_activity(
            worker_id=worker_id,
            activity_date=today,
            duration_hours=Decimal('95'),
            compensation_amount=Decimal('1234.50'),
        )
        pending = build_activity(
            worker_id=worker_id,
            activity_date=today,
            dimona_status=DimonaStatus.PENDING,
            compensation_amount=Decimal('10'),
        )
        other_year = build_activity(worker_id=worker_id, activity_date=date(today.year + 2, 1, 5))
        contract = build_authorisation(
            activity_types=('permanence', 'courses'),
            start_date=date(2020, 1, 1),
            end_date=today + timedelta(days=5),
            worker_id=worker_id,
        )
        session.add_all([counted, pending, other_year, contract])

    app = run_app_as_admin(monkeypatch=monkeypatch, engine=account_engine)

    alerts = read_alerts(app=app)
    metrics = read_metrics(app=app)
    year = today.year
    assert metrics['Coût prévu ce mois'] == f'1{NO_BREAK_SPACE}244,50{NO_BREAK_SPACE}€'
    assert metrics['Travailleurs actifs'] == '1'
    assert metrics['Dimona en attente'] == '1'
    assert metrics['Alertes de limites'] == '1'
    assert '#### Alertes' in [element.value for element in app.main.markdown]
    assert alerts['error'] == [
        f'**Lotte Exemple** (Article 17) : 97 des 100 heures utilisées en {year}.'
    ]
    assert alerts['warning'][0].startswith(
        f'**Dimona en attente** : Lotte Exemple, Cours BMC le {format_date(day=today)}'
    )
    assert alerts['warning'][1].startswith(f'**Aucune limite configurée pour {year + 2}**')
    assert alerts['info'][0].startswith(
        '**Contrat bientôt échu** : Lotte Exemple, contrat Article 17 pour Permanence, Cours '
    )
    assert alerts['info'][0].endswith('(dans 5 jours).')


def test_r10_5_admin_resolves_a_pending_declaration_as_ok(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """With the declaration ID the activity becomes ok and leaves the list (R17.1)."""
    worker_id = add_ready_worker(engine=account_engine)
    pending = build_activity(worker_id=worker_id, dimona_status=DimonaStatus.PENDING)
    activity_id = add_activity(engine=account_engine, activity=pending)
    app = run_app_as_admin(monkeypatch=monkeypatch, engine=account_engine)

    assert app.selectbox(key=f'resolve_as_{activity_id}').label == 'Résoudre comme'
    assert app.text_input(key=f'resolve_id_{activity_id}').label == (
        'ID de déclaration Dimona (si OK)'
    )
    click_key(app=app, key=f'resolve_{activity_id}')
    refused_alerts = read_alerts(app=app)
    app.text_input(key=f'resolve_id_{activity_id}').set_value('2026-10-DIM-0048390')
    click_key(app=app, key=f'resolve_{activity_id}')

    with open_session(engine=account_engine) as session:
        activity = session.get(Activity, activity_id)
        dimona_status = activity.dimona_status
        declaration_id = activity.dimona_declaration_id
    assert refused_alerts['error'] == [
        "Déclaration non résolue : indiquez l'ID de déclaration Dimona pour la marquer OK."
    ]
    assert dimona_status == DimonaStatus.OK
    assert declaration_id == '2026-10-DIM-0048390'
    assert read_alerts(app=app)['success'] == ['Déclaration Dimona résolue : marquée OK.']
    assert read_metrics(app=app)['Dimona en attente'] == '0'


def test_r10_5_admin_resolves_a_pending_declaration_as_rejected(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """Marked rejected, the activity is no longer pending and no longer counts."""
    worker_id = add_ready_worker(engine=account_engine)
    pending = build_activity(
        worker_id=worker_id,
        activity_date=read_today(),
        dimona_status=DimonaStatus.PENDING,
    )
    activity_id = add_activity(engine=account_engine, activity=pending)
    app = run_app_as_admin(monkeypatch=monkeypatch, engine=account_engine)

    app.selectbox(key=f'resolve_as_{activity_id}').set_value('rejected')
    click_key(app=app, key=f'resolve_{activity_id}')

    with open_session(engine=account_engine) as session:
        dimona_status = session.get(Activity, activity_id).dimona_status
    assert dimona_status == DimonaStatus.REJECTED
    assert read_alerts(app=app)['success'] == ['Déclaration Dimona résolue : marquée refusée.']
    assert read_metrics(app=app)['Coût prévu ce mois'] == f'0,00{NO_BREAK_SPACE}€'


def test_r11_1_admin_creates_a_worker_who_can_then_sign_in(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """The form creates the account with its eleven rates; the worker signs in at once (R4.4)."""
    app = run_app_as_admin(monkeypatch=monkeypatch, engine=account_engine)

    fill_worker_form(app=app)
    click_key(app=app, key='create_worker')

    worker = read_worker(engine=account_engine, username='e.janssens')
    with open_session(engine=account_engine) as session:
        n_rates = session.scalar(sa.select(sa.func.count()).select_from(CompensationRate))
    row = read_table(app=app, first_column='Prénom')[0]
    assert read_alerts(app=app)['success'] == ['Travailleur créé : Emma Janssens.']
    assert worker.national_register_number == '91020312363'
    assert worker.auth_method == AuthMethod.LOCAL
    assert n_rates == len(RATE_CODES)
    assert list(row) == ['Prénom', 'Nom', 'Type de travailleur', 'E-mail', 'IBAN', 'Statut']
    assert row['E-mail'] == 'emma.janssens@example.com'
    assert row['Statut'] == 'Actif'
    assert worker.street == 'Rue Imaginaire 12'
    assert app.text_input(key='create_1_first_name').value == ''

    database_url = render_database_url(engine=account_engine)
    worker_app = run_app(monkeypatch=monkeypatch, app_env='TEST', database_url=database_url)
    sign_in_locally(app=worker_app, username='e.janssens', password='first-password')
    assert [tab.label for tab in worker_app.tabs][0] == 'Déclarer une activité'


def test_r11_3_create_form_refuses_a_wrong_national_register_number(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """The checksum is checked on entry; the form keeps what was typed."""
    app = run_app_as_admin(monkeypatch=monkeypatch, engine=account_engine)

    fill_worker_form(app=app)
    app.text_input(key='create_0_national_register_number').set_value('91.02.03-123.64')
    click_key(app=app, key='create_worker')

    with open_session(engine=account_engine) as session:
        n_workers = session.scalar(sa.select(sa.func.count()).select_from(Worker))
    assert read_alerts(app=app)['error'] == [
        "Travailleur non enregistré : le numéro de registre national n'est pas valide "
        '(clé de contrôle).'
    ]
    assert n_workers == 0
    assert app.text_input(key='create_0_first_name').value == 'Emma'


def test_r11_2_create_form_has_the_mockup_labels(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """Every field of a worker record, the eleven rates, and a masked password (R18.1)."""
    app = run_app_as_admin(monkeypatch=monkeypatch, engine=account_engine)

    text_labels = [item.label for item in app.text_input if item.key.startswith('create_0_')]
    select_labels = [item.label for item in app.selectbox if item.key.startswith('create_0_')]
    rate_labels = [item.label for item in app.number_input if item.key.startswith('create_0_')]
    type_options = list(app.selectbox(key='create_0_worker_type').options)
    password_input = app.text_input(key='create_0_password')

    assert sorted(text_labels) == [
        'Code postal',
        'Commune',
        'E-mail',
        'IBAN',
        'Mot de passe',
        'Nom',
        "Nom d'utilisateur",
        'Numéro de registre national',
        'Prénom',
        'Rue et numéro',
    ]
    assert sorted(select_labels) == ['Méthode de connexion', 'Type de travailleur']
    assert type_options == ['Volontaire', 'Article 17', 'Flexijob', 'Indépendant']
    assert sorted(rate_labels) == [
        'Cours BMC',
        'Cours groupe avec mono',
        'Cours groupe sans mono',
        'Démontage difficile',
        'Démontage facile',
        'Déplacement groupe',
        'Ouverture 4A - 5C',
        'Ouverture 6A - 6C',
        'Ouverture 7A et plus',
        'Permanence',
        'Supplément corde 9 à 14',
    ]
    assert captions_of_workers_tab(app=app) == []
    assert password_input.proto.type == password_input.proto.PASSWORD


def test_r11_2_tab_key_moves_left_to_right_then_down_in_the_worker_forms(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """The create and edit forms are filled row by row, the order the tab key visits them."""
    worker_id = add_ready_worker(engine=account_engine)
    app = run_app_as_admin(monkeypatch=monkeypatch, engine=account_engine)

    create_order = read_tab_order(block=app.main, prefix='create_0_')
    edit_order = read_tab_order(block=app.main, prefix=f'edit_{worker_id}_0_')

    worker_order = [
        'Prénom',
        'Nom',
        'Numéro de registre national',
        'Type de travailleur',
        'IBAN',
        'Méthode de connexion',
        "Nom d'utilisateur",
        'E-mail',
    ]
    address_order = ['Rue et numéro', 'Code postal', 'Commune']
    assert create_order == [
        *worker_order,
        'Mot de passe',
        *address_order,
        'Permanence',
        'Cours BMC',
        'Cours groupe sans mono',
        'Cours groupe avec mono',
        'Déplacement groupe',
        'Ouverture 4A - 5C',
        'Ouverture 6A - 6C',
        'Ouverture 7A et plus',
        'Supplément corde 9 à 14',
        'Démontage facile',
        'Démontage difficile',
    ]
    assert edit_order == [*worker_order, *address_order, 'Compte actif']


def test_r11_5_admin_deactivates_a_worker_without_deleting(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """Unticking "Compte actif" blocks the sign-in; the worker stays in the list."""
    worker_id = add_ready_worker(engine=account_engine)
    app = run_app_as_admin(monkeypatch=monkeypatch, engine=account_engine)

    app.checkbox(key=f'edit_{worker_id}_0_is_active').set_value(False)
    app.text_input(key=f'edit_{worker_id}_0_last_name').set_value('Peeters')
    click_key(app=app, key='save_worker')

    worker = read_worker(engine=account_engine, username='lotte')
    row = read_table(app=app, first_column='Prénom')[0]
    button_labels = [button.label for button in app.main.button]
    assert worker.is_active is False
    assert worker.last_name == 'Peeters'
    assert row['Statut'] == 'Inactif'
    assert read_alerts(app=app)['success'] == ['Travailleur modifié : Lotte Peeters.']
    assert not [label for label in button_labels if 'upprimer le travailleur' in label]

    database_url = render_database_url(engine=account_engine)
    worker_app = run_app(monkeypatch=monkeypatch, app_env='TEST', database_url=database_url)
    sign_in_locally(app=worker_app, username='lotte', password=PASSWORD)
    assert worker_app.title[0].value == 'Connexion'


def test_r11_6_admin_sets_a_password_through_two_masked_fields(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """Both fields are masked and empty; a mismatch is refused; the saved one signs in."""
    add_ready_worker(engine=account_engine)
    app = run_app_as_admin(monkeypatch=monkeypatch, engine=account_engine)

    new_input = app.text_input(key='password_0_new')
    confirmation_input = app.text_input(key='password_0_confirmation')
    assert new_input.label == 'Nouveau mot de passe'
    assert confirmation_input.label == 'Confirmer le mot de passe'
    assert new_input.proto.type == new_input.proto.PASSWORD
    assert confirmation_input.proto.type == confirmation_input.proto.PASSWORD
    assert new_input.value == ''
    new_input.set_value('new-password')
    confirmation_input.set_value('other-password')
    click_key(app=app, key='save_password')
    mismatch_alerts = read_alerts(app=app)
    app.text_input(key='password_0_confirmation').set_value('new-password')
    click_key(app=app, key='save_password')

    worker = read_worker(engine=account_engine, username='lotte')
    assert mismatch_alerts['error'] == [
        'Mot de passe non enregistré : les deux mots de passe ne sont pas identiques.'
    ]
    assert read_alerts(app=app)['success'] == ['Mot de passe enregistré pour Lotte Exemple.']
    assert verify_password(password='new-password', password_hash=worker.password_hash)
    assert app.text_input(key='password_1_new').value == ''
    shown_values = [item.value for item in app.text_input]
    shown_values.extend(element.value for element in app.main.markdown)
    shown_values.extend(read_alerts(app=app)['success'])
    page_texts = ' '.join(shown_values)
    assert 'new-password' not in page_texts
    assert worker.password_hash not in page_texts


def test_r11_7_worker_view_offers_no_password_change(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """A signed-in worker has no password field anywhere."""
    add_ready_worker(engine=account_engine)
    database_url = render_database_url(engine=account_engine)
    app = run_app(monkeypatch=monkeypatch, app_env='TEST', database_url=database_url)
    sign_in_locally(app=app, username='lotte', password=PASSWORD)

    password_inputs = [item for item in app.text_input if item.proto.type == item.proto.PASSWORD]

    assert password_inputs == []


def test_r18_1_read_only_tables_are_static_without_the_english_column_menu(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """Read-only tables are plain tables: no English sort, format or CSV export menu.

    The two exceptions: the activities of the month (R19.1), interactive on purpose with its
    English menus, and the yearly limits editor (R15.1).
    """
    today = read_today()
    worker_id = add_ready_worker(engine=account_engine)
    activity = build_activity(worker_id=worker_id, activity_date=today)
    add_activity(engine=account_engine, activity=activity)

    app = run_app_as_admin(monkeypatch=monkeypatch, engine=account_engine)

    first_columns = [list(element.value.columns)[0] for element in app.table]
    assert first_columns == [
        'Travailleur',
        'Prénom',
        'Type',
        "Type d'activité",
        "Type d'activité",
        f'Travailleur (statut article 17 en {today.year})',
    ]
    dataframe_columns = [list(element.value.columns)[:2] for element in app.dataframe]
    assert dataframe_columns[0] == ['Date', 'Travailleur']
    assert [element.key for element in app.dataframe] == [None, f'limits_{today.year}_0']


def test_r12_2_authorisations_tab_lists_the_documents_of_the_chosen_worker(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """A worker dropdown, then that worker's table with the upload date."""
    add_ready_worker(engine=account_engine)
    app = run_app_as_admin(monkeypatch=monkeypatch, engine=account_engine)

    worker_select = app.selectbox(key='authorisations_worker')
    rows = read_table(app=app, first_column='Type')

    assert worker_select.label == 'Travailleur'
    assert list(worker_select.options) == ['Lotte Exemple (Article 17)']
    assert [row['Type'] for row in rows] == ['Contrat (Article 17)', 'Qualification']
    assert list(rows[0]) == ['Type', 'Couvre', 'Début', 'Fin', 'Statut', 'Fichier', 'Ajouté le']
    assert rows[0]['Couvre'] == 'Permanence, Cours, Ouverture de voies'


def test_r12_3_admin_uploads_a_document(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
    tmp_path: Path,
) -> None:
    """The upload button opens the form; the file is stored as-is in the storage (R3.6)."""
    worker_id = add_ready_worker(engine=account_engine)
    with open_session(engine=account_engine) as session:
        session.execute(sa.delete(Authorisation))
    app = run_app_as_admin(monkeypatch=monkeypatch, engine=account_engine)
    assert len(app.get('file_uploader')) == 0

    click_key(app=app, key='upload_document')
    prefix = f'upload_{worker_id}_0'
    form_labels = [
        app.get('file_uploader')[0].label,
        app.radio(key=f'{prefix}_document_type').label,
        app.selectbox(key=f'{prefix}_worker_type').label,
        app.multiselect(key=f'{prefix}_cover').label,
        app.date_input(key=f'{prefix}_start_date').label,
        app.date_input(key=f'{prefix}_end_date').label,
    ]
    cover_options = list(app.multiselect(key=f'{prefix}_cover').options)
    click_key(app=app, key='save_document')
    missing_file_alerts = read_alerts(app=app)
    upload_document(app=app, worker_id=worker_id)

    authorisation = read_authorisations(engine=account_engine, worker_id=worker_id)[0]
    stored_file = tmp_path / 'local_storage' / authorisation.file_path
    assert form_labels == [
        'Fichier (conservé tel quel, non analysé)',
        'Type de document',
        'Type de travailleur du contrat',
        'Activités couvertes',
        'Date de début',
        'Date de fin (vide = sans fin)',
    ]
    assert cover_options == ['Permanence', 'Cours', 'Ouverture de voies']
    assert missing_file_alerts['error'] == [
        'Document non enregistré : choisissez le fichier du document.'
    ]
    assert read_alerts(app=app)['success'] == ['Document enregistré.']
    assert authorisation.document_type == DocumentType.CONTRACT
    assert authorisation.worker_type == WorkerType.ARTICLE_17
    assert authorisation.activity_types == [*COURSE_ACTIVITY_TYPES, *ROUTE_ACTIVITY_TYPES]
    assert authorisation.start_date == date(2026, 9, 1)
    assert authorisation.end_date is None
    assert authorisation.original_filename == 'contrat_2026.pdf'
    assert stored_file.read_bytes() == CONTENT
    assert read_table(app=app, first_column='Type')[0]['Couvre'] == 'Cours, Ouverture de voies'
    assert len(app.get('file_uploader')) == 0


def test_r12_10_contract_form_asks_the_worker_type_and_opens_on_the_current_one(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """The four types are offered; another one than the worker's own can be stored."""
    worker_id = add_ready_worker(engine=account_engine)
    with open_session(engine=account_engine) as session:
        session.execute(sa.delete(Authorisation))
    app = run_app_as_admin(monkeypatch=monkeypatch, engine=account_engine)

    click_key(app=app, key='upload_document')
    prefix = f'upload_{worker_id}_0'
    worker_type_select = app.selectbox(key=f'{prefix}_worker_type')
    opened_worker_type = worker_type_select.value
    worker_type_options = list(worker_type_select.options)
    worker_type_select.set_value(WorkerType.FLEXI_JOB)
    uploader = [item for item in app.get('file_uploader') if item.key == f'{prefix}_file'][0]
    uploader.upload(filename='flexi.pdf', content=CONTENT, mime_type='application/pdf')
    app.multiselect(key=f'{prefix}_cover').set_value(['permanence'])
    click_key(app=app, key='save_document')

    authorisation = read_authorisations(engine=account_engine, worker_id=worker_id)[0]
    assert opened_worker_type == WorkerType.ARTICLE_17
    assert worker_type_options == ['Volontaire', 'Article 17', 'Flexijob', 'Indépendant']
    assert authorisation.worker_type == WorkerType.FLEXI_JOB
    assert read_table(app=app, first_column='Type')[0]['Type'] == 'Contrat (Flexijob)'


def test_r12_6_admin_edits_a_document_and_replaces_its_file(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
    tmp_path: Path,
) -> None:
    """The edit form opens on the stored values; a new file takes the place of the old one."""
    worker_id = add_ready_worker(engine=account_engine)
    with open_session(engine=account_engine) as session:
        session.execute(sa.delete(Authorisation))
    app = run_app_as_admin(monkeypatch=monkeypatch, engine=account_engine)
    upload_document(app=app, worker_id=worker_id)
    old_authorisation = read_authorisations(engine=account_engine, worker_id=worker_id)[0]
    document_id = old_authorisation.id

    click_key(app=app, key='edit_document')
    prefix = f'edit_document_{document_id}_1'
    opened_cover = app.multiselect(key=f'{prefix}_cover').value
    opened_worker_type = app.selectbox(key=f'{prefix}_worker_type').value
    app.radio(key=f'{prefix}_document_type').set_value(DocumentType.QUALIFICATION).run()
    worker_type_fields = [item for item in app.selectbox if item.key == f'{prefix}_worker_type']
    app.multiselect(key=f'{prefix}_cover').set_value(['permanence'])
    app.date_input(key=f'{prefix}_end_date').set_value(date(2027, 8, 31))
    uploader = [item for item in app.get('file_uploader') if item.key == f'{prefix}_file'][0]
    uploader.upload(filename='signed.png', content=b'new file', mime_type='image/png')
    click_key(app=app, key='save_document_changes')

    authorisation = read_authorisations(engine=account_engine, worker_id=worker_id)[0]
    storage_folder = tmp_path / 'local_storage'
    assert opened_cover == ['courses', 'route']
    assert opened_worker_type == WorkerType.ARTICLE_17
    assert worker_type_fields == []
    assert read_alerts(app=app)['success'] == ['Document modifié.']
    assert authorisation.document_type == DocumentType.QUALIFICATION
    assert authorisation.worker_type is None
    assert authorisation.activity_types == ['permanence']
    assert authorisation.end_date == date(2027, 8, 31)
    assert authorisation.original_filename == 'signed.png'
    assert (storage_folder / authorisation.file_path).read_bytes() == b'new file'
    assert not (storage_folder / old_authorisation.file_path).exists()


def test_r12_7_admin_deletes_a_document_after_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
    tmp_path: Path,
) -> None:
    """Delete asks first; "Annuler" keeps the document, the confirmation removes it and its file."""
    worker_id = add_ready_worker(engine=account_engine)
    with open_session(engine=account_engine) as session:
        session.execute(sa.delete(Authorisation))
    app = run_app_as_admin(monkeypatch=monkeypatch, engine=account_engine)
    upload_document(app=app, worker_id=worker_id)
    authorisation = read_authorisations(engine=account_engine, worker_id=worker_id)[0]
    stored_file = tmp_path / 'local_storage' / authorisation.file_path

    click_key(app=app, key='delete_document')
    question = read_alerts(app=app)['warning']
    n_after_click = len(read_authorisations(engine=account_engine, worker_id=worker_id))
    click_key(app=app, key='keep_document')
    n_after_keep = len(read_authorisations(engine=account_engine, worker_id=worker_id))
    click_key(app=app, key='delete_document')
    click_key(app=app, key='confirm_delete')

    assert question == [
        'Supprimer définitivement ce document et son fichier ? '
        'Contrat (Article 17) · Cours, Ouverture de voies · contrat_2026.pdf'
    ]
    assert n_after_click == 1
    assert n_after_keep == 1
    assert read_authorisations(engine=account_engine, worker_id=worker_id) == []
    assert not stored_file.exists()
    assert read_alerts(app=app)['success'] == ['Document supprimé, avec son fichier.']


def test_r12_7_document_in_use_cannot_be_deleted_and_only_its_end_date_changes(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """Once an activity relied on a document, Delete and every field but the end date are off."""
    worker_id = add_ready_worker(engine=account_engine)
    with open_session(engine=account_engine) as session:
        session.execute(sa.delete(Authorisation))
    app = run_app_as_admin(monkeypatch=monkeypatch, engine=account_engine)
    upload_document(app=app, worker_id=worker_id)
    document_id = read_authorisations(engine=account_engine, worker_id=worker_id)[0].id
    activity = build_activity(worker_id=worker_id, activity_date=date(2026, 10, 12))
    add_activity(engine=account_engine, activity=activity)
    app.run()

    is_delete_disabled = app.button(key='delete_document').disabled
    captions = read_tab_captions(app=app, label='Autorisations')
    click_key(app=app, key='edit_document')
    prefix = f'edit_document_{document_id}_1'
    uploader = [item for item in app.get('file_uploader') if item.key == f'{prefix}_file'][0]
    locked_fields = [
        app.radio(key=f'{prefix}_document_type'),
        app.selectbox(key=f'{prefix}_worker_type'),
        app.multiselect(key=f'{prefix}_cover'),
        app.date_input(key=f'{prefix}_start_date'),
    ]
    end_date_field = app.date_input(key=f'{prefix}_end_date')

    assert is_delete_disabled
    assert captions == [
        'Ce document a servi à déclarer des activités : il ne peut plus être supprimé, '
        'et seule sa date de fin peut encore être modifiée.'
    ]
    assert uploader.proto.disabled
    assert all(field.disabled for field in locked_fields)
    assert not end_date_field.disabled


def test_r12_2_admin_downloads_the_original_file(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """The download offers the stored bytes under the original file name."""
    worker_id = add_ready_worker(engine=account_engine)
    with open_session(engine=account_engine) as session:
        session.execute(sa.delete(Authorisation))
    downloads = record_downloads(monkeypatch=monkeypatch)
    app = run_app_as_admin(monkeypatch=monkeypatch, engine=account_engine)

    upload_document(app=app, worker_id=worker_id)

    assert downloads[-1]['data'] == CONTENT
    assert downloads[-1]['file_name'] == 'contrat_2026.pdf'
    assert app.get('download_button')[0].label == 'Télécharger le document'


def test_r6_6_compensation_tab_shows_the_sheet_and_adds_a_version(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """Eight rates with their model; a new version is stored with its start date (R6.7)."""
    worker_id = add_ready_worker(engine=account_engine)
    app = run_app_as_admin(monkeypatch=monkeypatch, engine=account_engine)

    sheet = read_table(app=app, first_column="Type d'activité")
    prefix = f'rate_{worker_id}_0'
    hourly_label = app.number_input(key=f'{prefix}_amount').label
    app.selectbox(key=f'{prefix}_activity_type').set_value('courses')
    app.run()
    courses_label = app.number_input(key=f'{prefix}_amount').label
    app.number_input(key=f'{prefix}_amount').set_value(22.5)
    app.date_input(key=f'{prefix}_valid_from').set_value(date(2030, 1, 1))
    click_key(app=app, key='save_rate')

    with open_session(engine=account_engine) as session:
        query = sa.select(CompensationRate).where(
            CompensationRate.worker_id == worker_id,
            CompensationRate.valid_from == date(2030, 1, 1),
        )
        rate = session.scalars(query).one()
        new_amount = rate.amount
        new_type = rate.activity_type
    assert len(sheet) == len(RATE_CODES)
    assert list(sheet[0]) == ["Type d'activité", 'Modèle', 'Tarif actuel', 'Valable depuis']
    assert sheet[0]['Modèle'] == 'Prix fixe'
    assert sheet[1]['Tarif actuel'] == f'20,00{NO_BREAK_SPACE}€ / heure'
    assert hourly_label == 'Nouveau tarif (€ / activité)'
    assert courses_label == 'Nouveau tarif (€ / heure)'
    assert new_amount == Decimal('22.50')
    assert new_type == 'courses'
    assert read_alerts(app=app)['success'] == ['Tarif enregistré, valable à partir du 01/01/2030.']


def test_r13_1_monthly_report_shows_totals_and_iban_per_worker(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """The current month opens; the table and the total follow the counted activities."""
    today = read_today()
    worker_id = add_ready_worker(engine=account_engine)
    counted = build_activity(
        worker_id=worker_id,
        activity_date=today,
        duration_hours=Decimal('2.5'),
        compensation_amount=Decimal('50'),
    )
    cancelled = build_activity(worker_id=worker_id, activity_date=today, is_cancelled=True)
    add_activity(engine=account_engine, activity=counted)
    add_activity(engine=account_engine, activity=cancelled)

    app = run_app_as_admin(monkeypatch=monkeypatch, engine=account_engine)

    export_button = app.button(key='export_payments')
    month_title = format_month_title(year=today.year, month=today.month)
    assert f'#### {month_title}' in [element.value for element in app.main.markdown]
    assert read_table(app=app, first_column='Travailleur') == [
        {
            'Travailleur': 'Lotte Exemple',
            'Type': 'Article 17',
            'Heures': '2,5',
            'Montant dû': f'50,00{NO_BREAK_SPACE}€',
            'IBAN': 'BE97 0000 0000 0099',
        }
    ]
    assert read_metrics(app=app)['Total à payer'] == f'50,00{NO_BREAK_SPACE}€'
    assert export_button.label == 'Exporter le fichier de paiement (SEPA pain.001 pour Belfius)'
    # BMC's details are not configured yet: no payment file, and the admin is told why
    assert export_button.disabled
    assert MISSING_ORGANISATION_MESSAGE in read_alerts(app=app)['warning']


def test_r10_8_dashboard_shows_the_accepted_activities_of_the_month_in_a_calendar(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """Only the accepted activity shows; the monthly report has no calendar."""
    today = read_today()
    worker_id = add_ready_worker(engine=account_engine)
    accepted = build_activity(worker_id=worker_id, activity_date=today)
    cancelled = build_activity(worker_id=worker_id, activity_date=today, is_cancelled=True)
    pending = build_activity(
        worker_id=worker_id,
        activity_date=today,
        dimona_status=DimonaStatus.PENDING,
    )
    for activity in (accepted, cancelled, pending):
        add_activity(engine=account_engine, activity=activity)

    app = run_app_as_admin(monkeypatch=monkeypatch, engine=account_engine)

    bodies = [element.proto.body for element in app.get('html')]
    calendars = [body for body in bodies if 'bmc-cal-grid' in body]
    assert len(calendars) == 1
    assert calendars[0].count('<span class="bmc-cal-name">Lotte Exemple</span>') == 1
    assert '#### Activités du mois' in [element.value for element in app.main.markdown]


def test_r13_1_monthly_report_moves_between_months_with_the_arrows(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """The previous arrow shows the previous month, without its activities; next comes back."""
    today = read_today()
    worker_id = add_ready_worker(engine=account_engine)
    activity = build_activity(
        worker_id=worker_id,
        activity_date=today,
        compensation_amount=Decimal('50'),
    )
    add_activity(engine=account_engine, activity=activity)
    previous_month = shift_month(month_start=today.replace(day=1), n_months=-1)
    previous_title = format_month_title(year=previous_month.year, month=previous_month.month)

    app = run_app_as_admin(monkeypatch=monkeypatch, engine=account_engine)
    app.button(key='report_previous').click().run()

    assert f'#### {previous_title}' in [element.value for element in app.main.markdown]
    assert read_metrics(app=app)['Total à payer'] == f'0,00{NO_BREAK_SPACE}€'
    assert 'Aucune activité comptabilisée pour ce mois.' in read_alerts(app=app)['info']

    app.button(key='report_next').click().run()

    assert read_metrics(app=app)['Total à payer'] == f'50,00{NO_BREAK_SPACE}€'


def test_r10_8_dashboard_says_when_the_month_has_no_accepted_activity(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """Without an accepted activity this month, a note replaces the calendar."""
    app = run_app_as_admin(monkeypatch=monkeypatch, engine=account_engine)

    assert '#### Activités du mois' in [element.value for element in app.main.markdown]
    assert 'Aucune activité acceptée pour ce mois.' in read_alerts(app=app)['info']


def test_r19_1_activities_tab_lists_every_activity_of_the_month_read_only(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """Cancelled ones included, with the worker's name; the arrows move between months."""
    today = read_today()
    worker_id = add_ready_worker(engine=account_engine)
    accepted = build_activity(worker_id=worker_id, activity_date=today)
    cancelled = build_activity(worker_id=worker_id, activity_date=today, is_cancelled=True)
    for activity in (accepted, cancelled):
        add_activity(engine=account_engine, activity=activity)

    app = run_app_as_admin(monkeypatch=monkeypatch, engine=account_engine)

    tables = [element.value for element in app.dataframe if element.key is None]
    assert len(tables) == 1
    rows = tables[0].to_dict(orient='records')
    assert list(rows[0]) == [
        'Date',
        'Travailleur',
        'Activité',
        'Description',
        'Heures',
        'Supplément',
        'Rémunération',
        'Dimona',
        'Annulée',
    ]
    assert [row['Travailleur'] for row in rows] == ['Lotte Exemple', 'Lotte Exemple']
    assert [row['Annulée'] for row in rows] == ['', 'Annulée']

    app.button(key='activities_previous').click().run()

    # Only the yearly limits editor is left: the month has no activity table
    assert all(element.key is not None for element in app.dataframe)
    assert 'Aucune activité pour ce mois.' in read_alerts(app=app)['info']


def test_r13_2_admin_exports_the_payment_file_of_the_month(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """The export button offers a pain.001 file paying the amount due from BMC's account."""
    today = read_today()
    worker_id = add_ready_worker(engine=account_engine)
    activity = build_activity(
        worker_id=worker_id,
        activity_date=today,
        compensation_amount=Decimal('50'),
    )
    add_activity(engine=account_engine, activity=activity)
    add_organisation(engine=account_engine)
    downloads = record_downloads(monkeypatch=monkeypatch)

    app = run_app_as_admin(monkeypatch=monkeypatch, engine=account_engine)

    export = find_download(downloads=downloads, key='export_payments')
    payment_file = export['data']()
    assert export['label'] == 'Exporter le fichier de paiement (SEPA pain.001 pour Belfius)'
    assert export['file_name'] == f'bmc_paiements_{today:%Y-%m}.xml'
    assert b'pain.001.001.09' in payment_file
    assert b'<Nm>Lotte Exemple</Nm>' in payment_file
    assert b'<InstdAmt Ccy="EUR">50.00</InstdAmt>' in payment_file
    assert payment_file.count(b'<IBAN>BE97000000000099</IBAN>') == 2
    assert MISSING_ORGANISATION_MESSAGE not in read_alerts(app=app)['warning']


def test_r14_1_fiches_tab_shows_the_totals_and_downloads_the_zip(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """The article 17 workers of the year with their totals, and one button for the zip."""
    today = read_today()
    year = today.year
    worker_id = add_ready_worker(engine=account_engine)
    with open_session(engine=account_engine) as session:
        worker = session.get(Worker, worker_id)
        worker.street = 'Rue Imaginaire 12'
        worker.postal_code = '1050'
        worker.city = 'Ixelles'
    accepted = build_activity(
        worker_id=worker_id,
        activity_date=date(year, 1, 15),
        duration_hours=Decimal('2.5'),
        compensation_amount=Decimal('50'),
    )
    refused = build_activity(
        worker_id=worker_id,
        activity_date=date(year, 1, 16),
        dimona_status=DimonaStatus.REJECTED,
    )
    add_activity(engine=account_engine, activity=accepted)
    add_activity(engine=account_engine, activity=refused)
    add_organisation(engine=account_engine)
    downloads = record_downloads(monkeypatch=monkeypatch)

    app = run_app_as_admin(monkeypatch=monkeypatch, engine=account_engine)

    year_select = app.selectbox(key='fiches_year')
    generate = find_download(downloads=downloads, key='generate_fiches')
    with zipfile.ZipFile(io.BytesIO(generate['data']())) as archive:
        names = archive.namelist()
    assert year_select.label == 'Année de revenus'
    assert year_select.value == year
    assert read_table(app=app, first_column=f'Travailleur (statut article 17 en {year})') == [
        {
            f'Travailleur (statut article 17 en {year})': 'Lotte Exemple',
            'Rémunération totale': f'50,00{NO_BREAK_SPACE}€',
            'Heures': '2,5',
        }
    ]
    assert generate['label'] == 'Générer les fiches 281.27 (PDF) + XML Belcotax-on-web (zip)'
    assert generate['file_name'] == f'fiches_281_27_{year}.zip'
    assert names == [f'belcotax_281_27_{year}.xml', f'281.27_{year}_001_Exemple_Lotte.pdf']
    assert build_deadline_text(year=year) in read_alerts(app=app)['info']


def test_r14_2_fiches_tab_names_what_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """Without BMC's details the button is disabled, with the reason."""
    worker_id = add_ready_worker(engine=account_engine)
    activity = build_activity(worker_id=worker_id, activity_date=date(read_today().year, 1, 15))
    add_activity(engine=account_engine, activity=activity)

    app = run_app_as_admin(monkeypatch=monkeypatch, engine=account_engine)

    warnings = read_alerts(app=app)['warning']
    assert app.button(key='generate_fiches').disabled
    assert 'Les coordonnées de BMC sont incomplètes : complétez-les dans Configuration.' in warnings


def test_r14_1_fiches_tab_without_article_17_activity_offers_nothing(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """An empty year says so and keeps the button disabled."""
    app = run_app_as_admin(monkeypatch=monkeypatch, engine=account_engine)

    infos = read_alerts(app=app)['info']
    assert app.button(key='generate_fiches').disabled
    assert 'Aucune activité article 17 acceptée par Dimona pour cette année.' in infos


def test_r14_4_deadline_text_names_the_schema_and_its_successor() -> None:
    """For a year after the stored schema, the text says which schema must replace it."""
    assert build_deadline_text(year=2025) == (
        'Échéance légale : fin février 2026. Schéma XML : belcotax-2025.xsd.'
    )
    assert build_deadline_text(year=2026) == (
        'Échéance légale : fin février 2027. Schéma XML : belcotax-2025.xsd, à mettre à jour '
        'vers belcotax-2026.xsd dès sa publication.'
    )


def test_r15_1_admin_sets_the_limits_of_a_year_in_the_table(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """Edited cells are stored for the chosen year; an incomplete year is saved with a warning."""
    year = read_today().year
    app = run_app_as_admin(monkeypatch=monkeypatch, engine=account_engine)

    year_select = app.selectbox(key='configuration_year')
    year_options = list(year_select.options)
    edited_rows = {0: {'Limite en euros': 1900.0}, 3: {"Limite d'heures": 285.0}}
    app.session_state[f'limits_{year}_0'] = {
        'edited_rows': edited_rows,
        'added_rows': [],
        'deleted_rows': [],
    }
    click_key(app=app, key='save_limits')

    with open_session(engine=account_engine) as session:
        limits = list(session.scalars(sa.select(YearlyLimit).where(YearlyLimit.year == year)))
        euro_limits = {limit.euro_limit for limit in limits if limit.euro_limit is not None}
        hours_limits = {
            limit.period: limit.hours_limit for limit in limits if limit.hours_limit is not None
        }
    assert year_select.label == 'Année'
    assert year_select.value == year
    assert year_options == [f'{year} (non configurée)', f'{year + 1} (non configurée)']
    assert len(limits) == 7
    assert euro_limits == {Decimal('1900.00')}
    assert hours_limits == {'Q3': Decimal('285.00')}
    assert read_alerts(app=app)['warning'] == [
        f"Limites {year} enregistrées, mais l'année reste non configurée : il manque des "
        'limites obligatoires.'
    ]


def test_r15_4_admin_saves_the_organisation_details(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """The nine fields are stored and shown again."""
    app = run_app_as_admin(monkeypatch=monkeypatch, engine=account_engine)

    labels = [item.label for item in app.text_input if item.key.startswith('organisation_0_')]
    app.text_input(key='organisation_0_company_number').set_value('0123.456.789')
    app.text_input(key='organisation_0_name').set_value('Brussels Monkeys Climbing ASBL')
    click_key(app=app, key='save_organisation')
    incomplete_alerts = read_alerts(app=app)
    app.text_input(key='organisation_0_address').set_value('Rue Exemple 1')
    app.text_input(key='organisation_0_postal_code').set_value('1000')
    app.text_input(key='organisation_0_city').set_value('Bruxelles')
    app.text_input(key='organisation_0_contact_person').set_value('Ada Admin')
    app.text_input(key='organisation_0_phone').set_value('021234567')
    app.text_input(key='organisation_0_contact_details').set_value('info@example.com')
    app.text_input(key='organisation_0_iban').set_value('BE97 0000 0000 0099')
    click_key(app=app, key='save_organisation')

    with open_session(engine=account_engine) as session:
        organisation = session.scalars(sa.select(OrganisationConfig)).one()
        company_number = organisation.company_number
        iban = organisation.iban
    assert sorted(labels) == [
        'Code postal',
        'Commune',
        'E-mail de contact',
        'IBAN de BMC (compte des paiements)',
        'Nom',
        "Numéro d'entreprise",
        'Personne de contact',
        'Rue et numéro',
        'Téléphone',
    ]
    assert incomplete_alerts['error'] == [
        'Coordonnées non enregistrées : remplissez tous les champs.'
    ]
    assert company_number == '0123.456.789'
    assert iban == 'BE97000000000099'
    assert read_alerts(app=app)['success'] == ['Coordonnées de BMC enregistrées.']
    assert app.text_input(key='organisation_1_name').value == 'Brussels Monkeys Climbing ASBL'
    assert app.text_input(key='organisation_1_iban').value == 'BE97 0000 0000 0099'


def test_r15_4_tab_key_moves_left_to_right_then_down_in_the_organisation_details(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """The two columns of BMC's details are filled row by row, the order the tab key follows."""
    app = run_app_as_admin(monkeypatch=monkeypatch, engine=account_engine)

    assert read_tab_order(block=app.main, prefix='organisation_0_') == [
        "Numéro d'entreprise",
        'Nom',
        'Rue et numéro',
        'Code postal',
        'Commune',
        'Personne de contact',
        'Téléphone',
        'E-mail de contact',
        'IBAN de BMC (compte des paiements)',
    ]


def test_r6_12_rate_fields_open_on_the_standard_bmc_rates(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """The create form proposes the rates of the BMC timesheet; the admin can change them."""
    app = run_app_as_admin(monkeypatch=monkeypatch, engine=account_engine)

    proposed_rates = {
        rate_code: Decimal(str(app.number_input(key=f'create_0_rate_{rate_code}').value))
        for rate_code in RATE_CODES
    }

    assert proposed_rates == DEFAULT_RATES
