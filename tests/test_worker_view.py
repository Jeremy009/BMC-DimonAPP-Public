"""The running worker view: four tabs, create, cancel, overview and authorisations.

Covers R7.1 to R7.13, R8.x and R9.x as the worker sees them. The Dimona service is the fake,
set through FAKE_DIMONA_OUTCOME (R1.11).
"""

from datetime import date, time, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from streamlit.testing.v1 import AppTest

from app_runner import (
    add_ready_worker,
    click_button,
    find_button,
    read_tab_order,
    record_downloads,
    run_app_as_ready_worker,
    sign_in_as_ready_worker,
)
from dimonapp import clock
from dimonapp.clock import read_today
from dimonapp.database import open_session
from dimonapp.french import format_date, format_month_title
from dimonapp.models import ACTIVITY_TYPE_CODES, Activity, DimonaStatus, WorkerType
from dimonapp.months import add_months, find_month_start, shift_month
from dimonapp.storage import LocalFileStorage
from dimonapp.submission import find_latest_date
from dimonapp.worker_view import CANCEL_SELECT_KEY
from factories import build_activity, build_authorisation, build_worker

TAB_NAMES = [
    'Déclarer une activité',
    'Annuler une activité',
    'Aperçu mensuel',
    'Mes documents',
]
PREVIOUS = ':material/arrow_back:'
NEXT = ':material/arrow_forward:'


def fill_create_form(app: AppTest, activity_type: str, duration: int, description: str) -> None:
    """Fill in the create form, leaving the date on today.

    The description only exists once a route setting or démontage type is picked.
    """
    app.selectbox[0].set_value(activity_type)
    app.number_input[0].set_value(duration)
    app.run()
    if description:
        app.text_input[0].set_value(description)


def create_activity(
    app: AppTest,
    activity_type: str = 'courses',
    duration: int = 2,
    description: str = '',
) -> AppTest:
    """Declare an activity for today through the create form."""
    fill_create_form(
        app=app,
        activity_type=activity_type,
        duration=duration,
        description=description,
    )
    return click_button(app=app, label="Confirmer l'activité")


def choose_activity_to_cancel(app: AppTest, position: int = 0) -> AppTest:
    """Pick an activity in the list of the cancel tab, which opens without a choice."""
    app.selectbox(key=CANCEL_SELECT_KEY).select_index(position)
    app.run()
    assert not app.exception
    return app


def add_today_activities(engine: sa.Engine, worker_id: int, activity_types: list[str]) -> None:
    """Commit volunteer activities of today, one per activity type, in that order."""
    with open_session(engine=engine) as session:
        for activity_type in activity_types:
            activity = build_activity(
                worker_id=worker_id,
                worker_type=WorkerType.VRIJWILLIGER,
                activity_date=read_today(),
                activity_type=activity_type,
                dimona_status=DimonaStatus.NOT_APPLICABLE,
            )
            session.add(activity)


def read_activities(engine: sa.Engine) -> list[Activity]:
    """Read every registered activity, detached from its session."""
    with open_session(engine=engine) as session:
        activities = list(session.scalars(sa.select(Activity).order_by(Activity.id)))
        session.expunge_all()
    return activities


def read_month_headings(app: AppTest) -> list[str]:
    """Give the month shown by the cancel tab and by the overview tab."""
    return [element.value for element in app.main.markdown if element.value.startswith('#### ')]


def test_r7_1_worker_view_has_four_tabs_with_their_heading(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """Four tabs in the FDS order, each starting with its own name as heading (R18.2)."""
    app = run_app_as_ready_worker(monkeypatch=monkeypatch, engine=account_engine)

    tab_labels = [tab.label for tab in app.tabs]
    headings = [header.value for header in app.header]

    assert tab_labels == TAB_NAMES
    assert headings == TAB_NAMES


def test_r7_3_create_form_asks_date_type_duration_and_description(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """The form has the fields with the mockup labels and the nine activity types.

    The description only shows once a route setting or démontage type is picked.
    """
    app = run_app_as_ready_worker(monkeypatch=monkeypatch, engine=account_engine)

    type_labels = list(app.selectbox[0].options)

    assert app.date_input[0].label == 'Date'
    assert app.selectbox[0].label == "Type d'activité"
    assert app.number_input[0].label == 'Durée (heures)'
    assert len(app.text_input) == 0
    for activity_type in ('route_setting_easy', 'route_cleaning_hard'):
        app.selectbox[0].set_value(activity_type)
        app.run()
        assert app.text_input[0].label == 'Description'
    app.selectbox[0].set_value('permanence')
    app.run()
    assert len(app.text_input) == 0
    assert type_labels == [
        'Permanence',
        'Cours BMC',
        'Cours groupe sans mono',
        'Cours groupe avec mono',
        'Ouverture 4A - 5C',
        'Ouverture 6A - 6C',
        'Ouverture 7A et plus',
        'Démontage facile',
        'Démontage difficile (cordes 9 à 14)',
    ]


@pytest.mark.parametrize(
    ('worker_type', 'expected_order'),
    [
        (WorkerType.ARTICLE_17, ['Date', 'Durée (heures)', "Type d'activité"]),
        (WorkerType.FLEXI_JOB, ['Date', 'Heure de début', "Type d'activité", 'Durée (heures)']),
    ],
)
def test_r7_3_tab_key_moves_left_to_right_then_down(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
    worker_type: WorkerType,
    expected_order: list[str],
) -> None:
    """The fields follow each other row by row, the order the tab key visits them."""
    app = run_app_as_ready_worker(
        monkeypatch=monkeypatch,
        engine=account_engine,
        worker_type=worker_type,
    )

    assert read_tab_order(block=app.tabs[0]) == expected_order


def test_r7_4_date_opens_on_today_and_stays_within_three_months(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """The date picker starts today, offers no earlier date and none after 3 months (R7.14)."""
    app = run_app_as_ready_worker(monkeypatch=monkeypatch, engine=account_engine)

    today = read_today()

    assert app.date_input[0].value == today
    assert app.date_input[0].min == today
    assert app.date_input[0].max == add_months(day=today, n_months=3)


def test_r7_4_date_picked_before_midnight_is_declared_after_midnight(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """A confirm sent just after midnight declares the day the worker picked, not the new today."""
    app = run_app_as_ready_worker(monkeypatch=monkeypatch, engine=account_engine)
    picked_date = read_today() + timedelta(days=7)
    app.date_input[0].set_value(picked_date)
    app.run()
    tomorrow = read_today() + timedelta(days=1)
    monkeypatch.setattr(clock, 'read_today', lambda: tomorrow)

    click_button(app=app, label="Confirmer l'activité")

    activities = read_activities(engine=account_engine)
    assert [activity.activity_date for activity in activities] == [picked_date]


def test_r7_4_date_that_turned_past_at_midnight_is_emptied_not_moved(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """Today, picked before midnight, is never declared as the next day: the date is emptied."""
    app = run_app_as_ready_worker(monkeypatch=monkeypatch, engine=account_engine)
    tomorrow = read_today() + timedelta(days=1)
    monkeypatch.setattr(clock, 'read_today', lambda: tomorrow)

    click_button(app=app, label="Confirmer l'activité")

    assert read_activities(engine=account_engine) == []
    assert app.error[0].value == "Activité non enregistrée : indiquez la date de l'activité."
    assert app.date_input[0].value is None


def test_r7_5_duration_opens_on_one_hour(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """The duration field starts at 1 hour, only takes whole hours and registers that value."""
    app = run_app_as_ready_worker(monkeypatch=monkeypatch, engine=account_engine)

    assert app.number_input[0].value == 1
    assert app.number_input[0].step == 1
    assert app.number_input[0].min == 1
    click_button(app=app, label="Confirmer l'activité")

    activity = read_activities(engine=account_engine)[0]
    assert activity.duration_hours == Decimal('1.00')


def test_r7_5_caption_explains_the_model_of_the_chosen_type(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """The caption under the form follows the selected activity type."""
    app = run_app_as_ready_worker(monkeypatch=monkeypatch, engine=account_engine)

    app.selectbox[0].set_value('route_setting_medium')
    app.run()

    captions = [caption.value for caption in app.caption]
    expected = (
        "L'ouverture 6A - 6C est payée à prix fixe par activité. "
        'Les heures sont enregistrées mais ne changent pas la rémunération.'
    )
    assert expected in captions


def test_r8_6_accepted_declaration_shows_the_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """An accepted declaration is confirmed with its ID and the compensation."""
    app = run_app_as_ready_worker(monkeypatch=monkeypatch, engine=account_engine)

    create_activity(app=app, activity_type='route_setting_medium', description='Secteur B')

    activity = read_activities(engine=account_engine)[0]
    declaration_id = activity.dimona_declaration_id
    assert activity.dimona_status == DimonaStatus.OK
    assert activity.activity_date == read_today()
    assert app.success[0].value == (
        f'Activité confirmée. Déclaration Dimona acceptée (ID {declaration_id}). '
        'Rémunération : 20,00 €'
    )


def test_r7_3_confirm_and_cancel_buttons_are_enabled_again_after_their_action(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """Each action ends on a refreshed page whose buttons can be clicked again (R7.9).

    While the action waits on the Dimona service the button is disabled, see test_widgets.py.
    """
    app = run_app_as_ready_worker(monkeypatch=monkeypatch, engine=account_engine)

    create_activity(app=app)
    is_confirm_disabled = find_button(app=app, label="Confirmer l'activité").disabled
    choose_activity_to_cancel(app=app)
    click_button(app=app, label='Annuler cette activité')
    create_activity(app=app)
    is_cancel_disabled = find_button(app=app, label='Annuler cette activité').disabled

    activities = read_activities(engine=account_engine)
    assert is_confirm_disabled is False
    assert is_cancel_disabled is False
    assert [activity.is_cancelled for activity in activities] == [True, False]


def test_r8_7_rejected_declaration_shows_an_error(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """A rejection is shown as an error with the reason, and stored as rejected."""
    app = run_app_as_ready_worker(
        monkeypatch=monkeypatch,
        engine=account_engine,
        fake_dimona_outcome='reject',
    )

    create_activity(app=app)

    activity = read_activities(engine=account_engine)[0]
    assert activity.dimona_status == DimonaStatus.REJECTED
    assert app.error[0].value == (
        'Déclaration Dimona refusée : déclaration refusée par le faux service Dimona. '
        'Activité enregistrée comme refusée.'
    )


def test_r8_8_declaration_without_answer_shows_the_pending_warning(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """No answer: the mockup warning, and the activity is stored as pending."""
    app = run_app_as_ready_worker(
        monkeypatch=monkeypatch,
        engine=account_engine,
        fake_dimona_outcome='timeout',
    )

    create_activity(app=app)

    activity = read_activities(engine=account_engine)[0]
    assert activity.dimona_status == DimonaStatus.PENDING
    assert app.warning[0].value == (
        "Activité enregistrée EN ATTENTE : le service Dimona n'a pas répondu dans les 2 minutes. "
        'Un administrateur fera le suivi.'
    )


def test_r8_4_volunteer_activity_is_confirmed_without_dimona(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """A volunteer gets the confirmation at once, whatever the Dimona service would answer."""
    app = run_app_as_ready_worker(
        monkeypatch=monkeypatch,
        engine=account_engine,
        worker_type=WorkerType.VRIJWILLIGER,
        fake_dimona_outcome='reject',
    )

    create_activity(app=app, duration=2)

    activity = read_activities(engine=account_engine)[0]
    assert activity.dimona_status == DimonaStatus.NOT_APPLICABLE
    assert app.success[0].value == 'Activité confirmée. Rémunération : 40,00 €'


def test_r8_2_failed_check_shows_an_error_and_registers_nothing(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """Route setting without description names the failed check; no activity appears."""
    app = run_app_as_ready_worker(monkeypatch=monkeypatch, engine=account_engine)

    create_activity(app=app, activity_type='route_setting_easy')

    assert app.error[0].value == (
        'Activité non enregistrée : une description courte est obligatoire '
        "pour l'ouverture de voies."
    )
    assert len(app.success) == 0
    assert read_activities(engine=account_engine) == []


def test_r7_7_flexi_job_below_the_minimum_is_refused_on_the_page(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """A flexi-jobber declaring less than the configured 3 hours gets an error."""
    app = run_app_as_ready_worker(
        monkeypatch=monkeypatch,
        engine=account_engine,
        worker_type=WorkerType.FLEXI_JOB,
    )

    create_activity(app=app, duration=2)

    assert app.error[0].value == (
        'Activité non enregistrée : une activité Flexijob dure au minimum 3 h.'
    )
    assert read_activities(engine=account_engine) == []


def test_r7_10_overview_lists_the_month_with_totals(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """A new activity shows in both monthly tables and in the totals of the overview."""
    app = run_app_as_ready_worker(monkeypatch=monkeypatch, engine=account_engine)

    create_activity(
        app=app,
        activity_type='route_cleaning_hard',
        duration=3,
        description='Secteur B',
    )

    today = read_today()
    month_name = format_month_title(year=today.year, month=today.month)
    overview = app.table[1].value
    metrics = {metric.label: metric.value for metric in app.metric}
    assert read_month_headings(app=app) == [f'#### {month_name}', f'#### {month_name}']
    assert list(overview.columns) == [
        'Date',
        'Activité',
        'Description',
        'Heures',
        'Supplément',
        'Rémunération',
        'Dimona',
        'Annulée',
    ]
    assert list(overview.iloc[0]) == [
        format_date(day=today),
        'Démontage difficile (cordes 9 à 14)',
        'Secteur B',
        '3',
        '',
        '20,00 €',
        'OK',
        '',
    ]
    assert metrics == {'Total des heures': '3 h', 'Rémunération totale': '20,00 €'}


def test_r18_1_worker_tables_are_static_without_the_english_column_menu(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """Cancel list, overview and authorisations are plain tables: no English column menu."""
    app = run_app_as_ready_worker(monkeypatch=monkeypatch, engine=account_engine)

    create_activity(
        app=app,
        activity_type='route_cleaning_hard',
        duration=3,
        description='Secteur B',
    )

    assert len(app.table) == 3
    assert len(app.dataframe) == 0


def add_month_activities(engine: sa.Engine, worker_id: int, day: date) -> None:
    """Commit a counted, a cancelled and a rejected activity on one day."""
    with open_session(engine=engine) as session:
        counted = build_activity(worker_id=worker_id, activity_date=day)
        cancelled = build_activity(worker_id=worker_id, activity_date=day, is_cancelled=True)
        rejected = build_activity(
            worker_id=worker_id,
            activity_date=day,
            dimona_status=DimonaStatus.REJECTED,
        )
        session.add_all([counted, cancelled, rejected])


def test_r7_12_totals_exclude_cancelled_and_rejected_activities(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """The overview shows all three activities but only totals the counted one."""
    worker_id = add_ready_worker(engine=account_engine)
    add_month_activities(engine=account_engine, worker_id=worker_id, day=read_today())

    app = sign_in_as_ready_worker(monkeypatch=monkeypatch, engine=account_engine)

    overview = app.table[1].value
    metrics = {metric.label: metric.value for metric in app.metric}
    assert list(overview['Annulée']) == ['', 'Annulée', '']
    assert list(overview['Dimona']) == ['OK', 'OK', 'Refusée']
    assert metrics == {'Total des heures': '2 h', 'Rémunération totale': '30,00 €'}


def test_r7_9_cancel_tab_lists_only_non_cancelled_activities(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """The cancelled activity is left out; the rejected one can still be selected."""
    worker_id = add_ready_worker(engine=account_engine)
    add_month_activities(engine=account_engine, worker_id=worker_id, day=read_today())

    app = sign_in_as_ready_worker(monkeypatch=monkeypatch, engine=account_engine)

    cancel_table = app.table[0].value
    assert list(cancel_table.columns) == [
        'Date',
        'Activité',
        'Description',
        'Heures',
        'Supplément',
        'Rémunération',
        'Dimona',
    ]
    assert list(cancel_table['Dimona']) == ['OK', 'Refusée']
    assert app.selectbox[1].label == 'Activité à annuler'
    assert len(app.selectbox[1].options) == 2


def test_r7_2_worker_sees_only_own_activities(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """A colleague's activity of the same month appears in neither monthly table."""
    with open_session(engine=account_engine) as session:
        colleague = build_worker(username='colleague', national_register_number='90010112372')
        session.add(colleague)
        session.flush()
        session.add(build_activity(worker_id=colleague.id, activity_date=read_today()))

    app = run_app_as_ready_worker(monkeypatch=monkeypatch, engine=account_engine)

    infos = [info.value for info in app.info]
    assert len(app.table) == 1
    assert 'Aucune activité à annuler pour ce mois.' in infos
    assert 'Aucune activité pour ce mois.' in infos


def test_r9_4_confirmed_cancellation_removes_the_activity_from_the_list(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """Cancelling an accepted activity: success message, flagged in the overview, no total."""
    app = run_app_as_ready_worker(monkeypatch=monkeypatch, engine=account_engine)
    create_activity(app=app)
    choose_activity_to_cancel(app=app)

    click_button(app=app, label='Annuler cette activité')

    activity = read_activities(engine=account_engine)[0]
    overview = app.table[0].value
    metrics = {metric.label: metric.value for metric in app.metric}
    assert activity.is_cancelled is True
    assert app.success[0].value == 'Activité annulée. Annulation confirmée par le service Dimona.'
    assert 'Aucune activité à annuler pour ce mois.' in [info.value for info in app.info]
    assert list(overview['Annulée']) == ['Annulée']
    assert metrics['Total des heures'] == '0 h'


def test_r9_2_pending_activity_cannot_be_cancelled(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """A pending declaration has no ID: the worker gets a warning and the activity stays."""
    app = run_app_as_ready_worker(
        monkeypatch=monkeypatch,
        engine=account_engine,
        fake_dimona_outcome='timeout',
    )
    create_activity(app=app)
    choose_activity_to_cancel(app=app)

    click_button(app=app, label='Annuler cette activité')

    activity = read_activities(engine=account_engine)[0]
    assert activity.is_cancelled is False
    assert app.warning[0].value == (
        "Activité non annulée : elle n'a pas d'identifiant de déclaration Dimona. "
        'Contactez un administrateur BMC.'
    )
    assert len(app.table[0].value) == 1


def test_r9_4_refused_cancellation_leaves_the_activity_active(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """When the Dimona service refuses, the worker gets a warning and the activity stays."""
    worker_id = add_ready_worker(engine=account_engine)
    with open_session(engine=account_engine) as session:
        activity = build_activity(
            worker_id=worker_id,
            activity_date=read_today(),
            dimona_declaration_id='123456',
        )
        session.add(activity)
    app = sign_in_as_ready_worker(
        monkeypatch=monkeypatch,
        engine=account_engine,
        fake_dimona_outcome='reject',
    )
    choose_activity_to_cancel(app=app)

    click_button(app=app, label='Annuler cette activité')

    assert read_activities(engine=account_engine)[0].is_cancelled is False
    assert app.warning[0].value.startswith('Activité non annulée : le service Dimona a refusé')
    assert len(app.table[0].value) == 1


def test_r7_9_cancel_list_opens_without_a_choice(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """Nothing is chosen in advance: a click without a choice warns and cancels nothing."""
    app = run_app_as_ready_worker(monkeypatch=monkeypatch, engine=account_engine)
    create_activity(app=app)

    cancel_select = app.selectbox(key=CANCEL_SELECT_KEY)
    assert cancel_select.value is None
    assert cancel_select.proto.placeholder == 'Choisissez une activité'
    click_button(app=app, label='Annuler cette activité')

    assert read_activities(engine=account_engine)[0].is_cancelled is False
    assert app.warning[0].value == "Activité non annulée : choisissez l'activité à annuler."


def test_r7_9_cancel_acts_on_the_chosen_activity_when_the_list_changed(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """An activity declared meanwhile on another device changes the list; the chosen one goes."""
    worker_id = add_ready_worker(engine=account_engine, worker_type=WorkerType.VRIJWILLIGER)
    activity_types = ['permanence', 'courses']
    add_today_activities(engine=account_engine, worker_id=worker_id, activity_types=activity_types)
    app = sign_in_as_ready_worker(monkeypatch=monkeypatch, engine=account_engine)
    choose_activity_to_cancel(app=app, position=1)
    other_types = ['route_cleaning_easy']
    add_today_activities(engine=account_engine, worker_id=worker_id, activity_types=other_types)

    click_button(app=app, label='Annuler cette activité')

    activities = read_activities(engine=account_engine)
    cancelled_types = [activity.activity_type for activity in activities if activity.is_cancelled]
    assert cancelled_types == ['courses']


def test_r7_9_choice_cancelled_on_another_device_cancels_nothing_else(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """When the chosen activity was cancelled meanwhile on another device, no other one goes."""
    worker_id = add_ready_worker(engine=account_engine, worker_type=WorkerType.VRIJWILLIGER)
    activity_types = ['permanence', 'courses']
    add_today_activities(engine=account_engine, worker_id=worker_id, activity_types=activity_types)
    app = sign_in_as_ready_worker(monkeypatch=monkeypatch, engine=account_engine)
    choose_activity_to_cancel(app=app, position=1)
    is_courses = Activity.activity_type == 'courses'
    statement = sa.update(Activity).where(is_courses).values(is_cancelled=True)
    with open_session(engine=account_engine) as session:
        session.execute(statement)

    click_button(app=app, label='Annuler cette activité')

    activities = read_activities(engine=account_engine)
    states = [(activity.activity_type, activity.is_cancelled) for activity in activities]
    assert states == [('permanence', False), ('courses', True)]
    assert app.warning[0].value == "Activité non annulée : choisissez l'activité à annuler."


def test_r7_8_cancel_tab_moves_between_months(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """The arrow buttons of the cancel tab change its month only and come back to this month."""
    app = run_app_as_ready_worker(monkeypatch=monkeypatch, engine=account_engine)
    create_activity(app=app)
    month_start = find_month_start(day=read_today())
    next_month_start = shift_month(month_start=month_start, n_months=1)
    month_name = format_month_title(year=month_start.year, month=month_start.month)
    next_month_name = format_month_title(year=next_month_start.year, month=next_month_start.month)

    click_button(app=app, label=NEXT, index=0)

    assert read_month_headings(app=app) == [f'#### {next_month_name}', f'#### {month_name}']
    assert 'Aucune activité à annuler pour ce mois.' in [info.value for info in app.info]

    click_button(app=app, label=PREVIOUS, index=0)

    assert read_month_headings(app=app) == [f'#### {month_name}', f'#### {month_name}']
    assert len(app.table[0].value) == 1


def test_r7_11_overview_moves_between_months_and_totals_follow(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """The previous month has no activity and totals zero; the current month comes back."""
    app = run_app_as_ready_worker(monkeypatch=monkeypatch, engine=account_engine)
    create_activity(app=app)
    month_start = find_month_start(day=read_today())
    previous_month_start = shift_month(month_start=month_start, n_months=-1)
    previous_month_name = format_month_title(
        year=previous_month_start.year,
        month=previous_month_start.month,
    )

    click_button(app=app, label=PREVIOUS, index=1)

    metrics = {metric.label: metric.value for metric in app.metric}
    assert read_month_headings(app=app)[1] == f'#### {previous_month_name}'
    assert 'Aucune activité pour ce mois.' in [info.value for info in app.info]
    assert metrics == {'Total des heures': '0 h', 'Rémunération totale': '0,00 €'}

    click_button(app=app, label=NEXT, index=1)

    metrics = {metric.label: metric.value for metric in app.metric}
    assert metrics['Total des heures'] == '2 h'


def test_r7_13_authorisations_are_listed_read_only_with_expired_marked(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """Contract and qualification are valid, the old contract is expired and listed last."""
    worker_id = add_ready_worker(engine=account_engine)
    with open_session(engine=account_engine) as session:
        expired = build_authorisation(
            activity_types=('courses', 'permanence'),
            start_date=date(2019, 9, 1),
            end_date=date(2019, 12, 31),
            worker_id=worker_id,
        )
        session.add(expired)

    app = sign_in_as_ready_worker(monkeypatch=monkeypatch, engine=account_engine)

    table = app.table[0].value
    assert list(table.columns) == ['Type', 'Couvre', 'Début', 'Fin', 'Statut', 'Fichier']
    contract = 'Contrat (Article 17)'
    assert list(table['Type']) == [contract, 'Qualification', contract]
    assert list(table['Statut']) == ['Valide', 'Valide', 'Expiré']
    assert table.iloc[2]['Couvre'] == 'Cours, Permanence'
    assert table.iloc[0]['Couvre'] == ('Permanence, Cours, Ouverture de voies')
    assert table.iloc[2]['Fin'] == '31/12/2019'


def test_r7_13_worker_cannot_upload_edit_or_delete_documents(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """The tab only offers the download: no upload, edit or delete control."""
    app = run_app_as_ready_worker(monkeypatch=monkeypatch, engine=account_engine)

    button_labels = [button.label for button in app.main.button]

    assert button_labels == [
        "Confirmer l'activité",
        PREVIOUS,
        NEXT,
        PREVIOUS,
        NEXT,
        'Télécharger le document',
    ]
    assert len(app.get('file_uploader')) == 0


def test_r7_13_worker_downloads_the_original_file_of_an_own_document(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """The chosen document is offered with its stored bytes and its original name."""
    content = b'%PDF-1.4 original bytes'
    storage = LocalFileStorage(folder=Path('local_storage'))
    storage.save(object_path='fake/document.pdf', content=content)
    downloads = record_downloads(monkeypatch=monkeypatch)

    app = run_app_as_ready_worker(monkeypatch=monkeypatch, engine=account_engine)

    document_select = app.selectbox(key='own_document')
    assert document_select.label == 'Document'
    assert list(document_select.options) == [
        'Contrat (Article 17) · Permanence, Cours, Ouverture de voies · document.pdf',
        'Qualification · Permanence, Cours, Ouverture de voies · document.pdf',
    ]
    assert downloads[-1]['data'] == content
    assert downloads[-1]['file_name'] == 'document.pdf'
    assert app.get('download_button')[0].label == 'Télécharger le document'


def test_r7_13_download_is_disabled_when_the_file_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """A document whose file is not in the storage shows a disabled button, not an error."""
    app = run_app_as_ready_worker(monkeypatch=monkeypatch, engine=account_engine)

    download_button = find_button(app=app, label='Télécharger le document')

    assert download_button.disabled
    assert len(app.get('download_button')) == 0


def test_r7_2_worker_is_only_offered_own_documents(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """The document of another worker is not in the list to download from."""
    add_ready_worker(engine=account_engine)
    with open_session(engine=account_engine) as session:
        other_worker = build_worker(national_register_number='00000000097', username='other')
        session.add(other_worker)
        session.flush()
        other_document = build_authorisation(
            activity_types=('permanence',),
            worker_id=other_worker.id,
        )
        session.add(other_document)

    app = sign_in_as_ready_worker(monkeypatch=monkeypatch, engine=account_engine)

    assert len(app.selectbox(key='own_document').options) == 2


def test_r7_15_flexi_jobber_enters_a_start_time_in_half_hour_steps(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """A flexi-jobber gets the start time field, and its value is registered."""
    app = run_app_as_ready_worker(
        monkeypatch=monkeypatch,
        engine=account_engine,
        worker_type=WorkerType.FLEXI_JOB,
    )

    start_time_input = app.time_input[0]
    assert start_time_input.label == 'Heure de début'
    assert start_time_input.step == 30 * 60
    start_time_input.set_value(time(hour=17, minute=30))
    create_activity(app=app, duration=3)

    activity = read_activities(engine=account_engine)[0]
    assert activity.start_time == time(hour=17, minute=30)
    assert activity.dimona_status == DimonaStatus.OK


def test_r7_15_other_worker_types_see_no_start_time(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """The start time is only asked of flexi-jobbers."""
    app = run_app_as_ready_worker(monkeypatch=monkeypatch, engine=account_engine)

    assert len(app.time_input) == 0


@pytest.mark.parametrize('worker_type', [WorkerType.FLEXI_JOB, WorkerType.ARTICLE_17])
def test_r7_16_date_picker_stops_at_the_latest_date_of_the_worker_type(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
    worker_type: WorkerType,
) -> None:
    """The calendar of a flexi-jobber follows the quarters, the others get three months."""
    app = run_app_as_ready_worker(
        monkeypatch=monkeypatch,
        engine=account_engine,
        worker_type=worker_type,
    )

    latest_date = find_latest_date(today=read_today(), worker_type=worker_type)
    assert app.date_input[0].max == latest_date


def test_r7_3_supplement_tick_box_only_shows_for_a_type_that_offers_one(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """Group travel on a group course, the rope supplement on a route setting, else no box."""
    app = run_app_as_ready_worker(monkeypatch=monkeypatch, engine=account_engine)

    box_labels = {}
    for activity_type in ACTIVITY_TYPE_CODES:
        app.selectbox[0].set_value(activity_type)
        app.run()
        box_labels[activity_type] = [checkbox.label for checkbox in app.checkbox]

    assert box_labels == {
        'permanence': [],
        'courses': [],
        'group_without_instructor': ['Déplacement groupe'],
        'group_with_instructor': ['Déplacement groupe'],
        'route_setting_easy': ['Supplément corde 9 à 14'],
        'route_setting_medium': ['Supplément corde 9 à 14'],
        'route_setting_hard': ['Supplément corde 9 à 14'],
        'route_cleaning_easy': [],
        'route_cleaning_hard': [],
    }


def test_r7_3_supplement_tick_box_is_not_ticked_by_default(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """Without a tick the group course is paid its hours only."""
    app = run_app_as_ready_worker(
        monkeypatch=monkeypatch,
        engine=account_engine,
        worker_type=WorkerType.VRIJWILLIGER,
    )

    create_activity(app=app, activity_type='group_with_instructor', duration=2)

    activity = read_activities(engine=account_engine)[0]
    assert activity.supplement_amount == Decimal('0')
    assert app.success[0].value == 'Activité confirmée. Rémunération : 40,00 €'


def test_r6_9_ticked_supplement_is_paid_and_shown_in_the_overview(
    monkeypatch: pytest.MonkeyPatch,
    account_engine: sa.Engine,
) -> None:
    """The ticked group travel is added to the compensation and listed in its own column."""
    app = run_app_as_ready_worker(
        monkeypatch=monkeypatch,
        engine=account_engine,
        worker_type=WorkerType.VRIJWILLIGER,
    )
    fill_create_form(app=app, activity_type='group_with_instructor', duration=2, description='')
    app.checkbox[0].check()

    click_button(app=app, label="Confirmer l'activité")

    activity = read_activities(engine=account_engine)[0]
    overview = app.table[1].value
    assert activity.supplement_amount == Decimal('20')
    assert activity.compensation_amount == Decimal('60')
    assert app.success[0].value == 'Activité confirmée. Rémunération : 60,00 €'
    assert overview.iloc[0]['Supplément'] == '20,00 €'
    assert overview.iloc[0]['Rémunération'] == '60,00 €'
