"""The real Dimona client, against a scripted RSZ: the real service is never called (R1.11)."""

import logging
from datetime import date, time
from pathlib import Path
from typing import Any, Optional

import jwt
import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from dimonapp.dimona import DIMONA_TIMEOUT_SECONDS, DimonaDeclaration, FakeDimonaClient
from dimonapp.models import WorkerType
from dimonapp.rsz_dimona import (
    OAUTH_ASSERTION_TYPE,
    RszDimonaClient,
    RszDimonaConfig,
    build_declaration_body,
    build_dimona_client,
    build_rsz_config,
    find_dimona_endpoint,
)
from dimonapp.settings import load_settings
from factories import VALID_NATIONAL_REGISTER_NUMBER

BASE_URL = 'https://rsz.test/REST/dimona/v2'
OAUTH_URL = 'https://rsz.test/REST/oauth/v5/token'
DECLARATIONS_URL = f'{BASE_URL}/declarations'
CLIENT_ID = 'self_service_client'
ENTERPRISE_NUMBER = '0123456789'
EMPLOYER_ID = 123456
DECLARATION_ID = '6465484622'
CANCELLATION_ID = '6465484999'
PERIOD_ID = 123456789123
DATABASE_URL = 'postgresql+psycopg://user:password@localhost:5432/database'

DECLARATION = DimonaDeclaration(
    national_register_number=VALID_NATIONAL_REGISTER_NUMBER,
    worker_type=WorkerType.ARTICLE_17,
    activity_date=date(2026, 10, 10),
    planned_hours=3,
)


class FakeResponse:
    """The parts of an HTTP response the client reads."""

    def __init__(
        self,
        status_code: int,
        body: Optional[dict[str, Any]] = None,
        location: Optional[str] = None,
    ) -> None:
        """Set the status, the JSON body and the Location header."""
        self.status_code = status_code
        self.body = body
        self.headers = {'Location': location} if location else {}

    def json(self) -> dict[str, Any]:
        """Give the JSON body, or fail like requests on a body that is not JSON."""
        if self.body is None:
            raise ValueError('No JSON body.')
        return self.body


class ScriptedRsz:
    """An RSZ that gives prepared replies in order and remembers every call."""

    def __init__(self, replies: list[FakeResponse | Exception]) -> None:
        """Set the replies; an exception is raised instead of returned."""
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    def request(self, **call: Any) -> FakeResponse:
        """Answer one HTTP call with the next reply."""
        self.calls.append(call)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class FakeClock:
    """A clock that only moves when the client sleeps."""

    def __init__(self) -> None:
        """Start at zero."""
        self.now = 0.0

    def read_seconds(self) -> float:
        """Give the current time."""
        return self.now

    def sleep(self, seconds: float) -> None:
        """Move the time forward without waiting."""
        self.now += seconds


@pytest.fixture(scope='session')
def private_key() -> rsa.RSAPrivateKey:
    """Generate a throwaway key pair; no real key is ever used in the tests (R2.7)."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope='session')
def private_key_pem(private_key: rsa.RSAPrivateKey) -> bytes:
    """Give the throwaway private key as an unencrypted PEM."""
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


@pytest.fixture
def config(private_key_pem: bytes) -> RszDimonaConfig:
    """Give the configuration of a made-up RSZ."""
    return RszDimonaConfig(
        base_url=BASE_URL,
        oauth_url=OAUTH_URL,
        client_id=CLIENT_ID,
        enterprise_number=ENTERPRISE_NUMBER,
        employer_id=EMPLOYER_ID,
        joint_commission_article_17='XXX',
        joint_commission_flexi_job='XXX',
        private_key_pem=private_key_pem,
    )


def build_token_reply() -> FakeResponse:
    """Build the answer of a successful sign-in."""
    return FakeResponse(status_code=200, body={'access_token': 'token-1', 'expires_in': 600})


def build_received_reply(declaration_id: str = DECLARATION_ID) -> FakeResponse:
    """Build the answer to a declaration the RSZ has received."""
    location = f'{DECLARATIONS_URL}/{declaration_id}'
    return FakeResponse(status_code=201, location=location)


def build_processed_reply(
    result: str,
    anomalies: Optional[list[dict[str, Any]]] = None,
    declaration_id: str = DECLARATION_ID,
) -> FakeResponse:
    """Build a processed declaration with its verdict, its period and its worker."""
    status = {
        'declarationId': int(declaration_id),
        'result': result,
        'period': {'id': PERIOD_ID},
        'anomalies': anomalies or [],
    }
    worker = {'ssin': VALID_NATIONAL_REGISTER_NUMBER}
    return FakeResponse(status_code=200, body={'declarationStatus': status, 'worker': worker})


def build_client(
    config: RszDimonaConfig,
    replies: list[FakeResponse | Exception],
) -> tuple[RszDimonaClient, ScriptedRsz, FakeClock]:
    """Build a client on a scripted RSZ and a clock that does not really wait."""
    rsz = ScriptedRsz(replies=replies)
    clock = FakeClock()
    client = RszDimonaClient(
        config=config,
        http=rsz,
        read_seconds=clock.read_seconds,
        sleep=clock.sleep,
    )
    return client, rsz, clock


def test_r8_5_declaration_is_posted_and_accepted(config: RszDimonaConfig) -> None:
    """An article 17 activity is posted as a one-day Dimona IN and accepted with its number."""
    replies = [
        build_token_reply(),
        build_received_reply(),
        FakeResponse(status_code=404),
        build_processed_reply(result='A'),
    ]
    client, rsz, _ = build_client(config=config, replies=replies)

    outcome = client.declare(declaration=DECLARATION)

    assert outcome.status == 'accepted'
    assert outcome.declaration_id == DECLARATION_ID
    post = rsz.calls[1]
    assert post['method'] == 'POST'
    assert post['url'] == DECLARATIONS_URL
    assert post['headers']['Authorization'] == 'Bearer token-1'
    assert post['json'] == {
        'employer': {'enterpriseNumber': ENTERPRISE_NUMBER, 'employerId': EMPLOYER_ID},
        'worker': {'ssin': VALID_NATIONAL_REGISTER_NUMBER},
        'dimonaIn': {
            'startDate': '2026-10-10',
            'endDate': '2026-10-10',
            'plannedHoursNumber': 3,
            'features': {'workerType': 'S17', 'jointCommissionNumber': 'XXX'},
        },
    }
    poll_urls = [call['url'] for call in rsz.calls[2:]]
    assert poll_urls == [f'{DECLARATIONS_URL}/{DECLARATION_ID}'] * 2


def test_r8_5_flexi_job_is_declared_with_its_own_worker_type(config: RszDimonaConfig) -> None:
    """A flexi-job goes out as FLX with its start and end time and without planned hours."""
    replies = [build_token_reply(), build_received_reply(), build_processed_reply(result='A')]
    client, rsz, _ = build_client(config=config, replies=replies)
    changes = {'worker_type': WorkerType.FLEXI_JOB, 'start_time': time(hour=17, minute=30)}
    declaration = DECLARATION.model_copy(update=changes)

    outcome = client.declare(declaration=declaration)

    assert outcome.status == 'accepted'
    assert rsz.calls[1]['json']['dimonaIn'] == {
        'startDate': '2026-10-10',
        'startHour': '1730',
        'endDate': '2026-10-10',
        'endHour': '2030',
        'features': {'workerType': 'FLX', 'jointCommissionNumber': 'XXX'},
    }


def test_r7_15_flexi_job_past_midnight_ends_on_the_next_day(config: RszDimonaConfig) -> None:
    """Three hours from 22:30 end at 01:30 on the next day."""
    changes = {'worker_type': WorkerType.FLEXI_JOB, 'start_time': time(hour=22, minute=30)}
    declaration = DECLARATION.model_copy(update=changes)

    body = build_declaration_body(config=config, declaration=declaration)

    assert body['dimonaIn']['startDate'] == '2026-10-10'
    assert body['dimonaIn']['endDate'] == '2026-10-11'
    assert body['dimonaIn']['endHour'] == '0130'


def test_r7_15_flexi_job_without_a_start_time_is_not_declared(config: RszDimonaConfig) -> None:
    """The submission gate always gives a start time; without one nothing is built."""
    declaration = DECLARATION.model_copy(update={'worker_type': WorkerType.FLEXI_JOB})

    with pytest.raises(ValueError):
        build_declaration_body(config=config, declaration=declaration)


def test_r8_5_sign_in_uses_an_assertion_signed_with_the_private_key(
    config: RszDimonaConfig,
    private_key: rsa.RSAPrivateKey,
) -> None:
    """The client signs in as in V2: client credentials with a signed JWT assertion."""
    replies = [build_token_reply(), build_received_reply(), build_processed_reply(result='A')]
    client, rsz, _ = build_client(config=config, replies=replies)

    client.declare(declaration=DECLARATION)

    sign_in = rsz.calls[0]
    assert sign_in['url'] == OAUTH_URL
    form = sign_in['data']
    assert form['grant_type'] == 'client_credentials'
    assert form['client_assertion_type'] == OAUTH_ASSERTION_TYPE
    claims = jwt.decode(
        jwt=form['client_assertion'],
        key=private_key.public_key(),
        algorithms=['RS256'],
        audience=OAUTH_URL,
    )
    assert claims['iss'] == CLIENT_ID
    assert claims['sub'] == CLIENT_ID


def test_r8_5_token_is_reused_while_it_is_valid(config: RszDimonaConfig) -> None:
    """A second declaration does not sign in again."""
    replies = [
        build_token_reply(),
        build_received_reply(),
        build_processed_reply(result='A'),
        build_received_reply(),
        build_processed_reply(result='A'),
    ]
    client, rsz, _ = build_client(config=config, replies=replies)

    client.declare(declaration=DECLARATION)
    outcome = client.declare(declaration=DECLARATION)

    assert outcome.status == 'accepted'
    sign_ins = [call for call in rsz.calls if call['url'] == OAUTH_URL]
    assert len(sign_ins) == 1


def test_r8_6_accepted_with_warning_keeps_the_warning(config: RszDimonaConfig) -> None:
    """Result W is an accepted declaration; the warning of the RSZ is kept as message."""
    anomalies = [{'errorId': '90017-510', 'label': {'fr': 'Avertissement du RSZ'}}]
    processed = build_processed_reply(result='W', anomalies=anomalies)
    replies = [build_token_reply(), build_received_reply(), processed]
    client, _, _ = build_client(config=config, replies=replies)

    outcome = client.declare(declaration=DECLARATION)

    assert outcome.status == 'accepted'
    assert outcome.declaration_id == DECLARATION_ID
    assert outcome.message == 'Avertissement du RSZ'


def test_r8_7_refused_declaration_gives_the_french_reason(config: RszDimonaConfig) -> None:
    """Result B is a rejection with the French anomalies of the RSZ and no number."""
    anomalies = [
        {'errorId': '00913-355', 'label': {'fr': 'Période déjà déclarée', 'nl': 'Reeds'}},
        {'errorId': '90017-369'},
    ]
    processed = build_processed_reply(result='B', anomalies=anomalies)
    replies = [build_token_reply(), build_received_reply(), processed]
    client, _, _ = build_client(config=config, replies=replies)

    outcome = client.declare(declaration=DECLARATION)

    assert outcome.status == 'rejected'
    assert outcome.declaration_id is None
    assert outcome.message == 'Période déjà déclarée ; 90017-369'


def test_r8_7_invalid_declaration_gives_the_problem_without_the_national_number(
    config: RszDimonaConfig,
) -> None:
    """A 400 is a rejection with the problem of the RSZ; the national number is cut out."""
    issue_detail = f'ssin {VALID_NATIONAL_REGISTER_NUMBER} is unknown'
    problem = {
        'title': 'Bad Request',
        'detail': 'Invalid input',
        'issues': [{'detail': issue_detail}],
    }
    replies = [build_token_reply(), FakeResponse(status_code=400, body=problem)]
    client, rsz, _ = build_client(config=config, replies=replies)

    outcome = client.declare(declaration=DECLARATION)

    assert outcome.status == 'rejected'
    assert outcome.message == 'Invalid input ; ssin *** is unknown'
    assert len(rsz.calls) == 2


def test_r8_7_refused_sign_in_is_a_rejection(config: RszDimonaConfig) -> None:
    """Without a token nothing is declared, and the worker is told why."""
    replies = [FakeResponse(status_code=401, body={'error': 'invalid_client'})]
    client, rsz, _ = build_client(config=config, replies=replies)

    outcome = client.declare(declaration=DECLARATION)

    assert outcome.status == 'rejected'
    assert outcome.message == 'authentification refusée par le RSZ (HTTP 401)'
    assert len(rsz.calls) == 1


def test_r8_8_unprocessed_declaration_gives_no_answer_within_2_minutes(
    config: RszDimonaConfig,
) -> None:
    """A declaration the RSZ keeps unprocessed ends as no answer, with its number as message."""
    not_processed = [FakeResponse(status_code=404) for _ in range(20)]
    replies = [build_token_reply(), build_received_reply(), *not_processed]
    client, _, clock = build_client(config=config, replies=replies)

    outcome = client.declare(declaration=DECLARATION)

    assert outcome.status == 'no_answer'
    assert outcome.declaration_id is None
    assert DECLARATION_ID in outcome.message
    assert 60 < clock.now <= DIMONA_TIMEOUT_SECONDS


def test_r8_8_waiting_for_identification_gives_no_answer(config: RszDimonaConfig) -> None:
    """Result S is neither accepted nor refused, so nothing is assumed."""
    replies = [build_token_reply(), build_received_reply(), build_processed_reply(result='S')]
    client, _, _ = build_client(config=config, replies=replies)

    outcome = client.declare(declaration=DECLARATION)

    assert outcome.status == 'no_answer'
    assert outcome.declaration_id is None


@pytest.mark.parametrize(
    'failure',
    [
        requests.Timeout(),
        requests.ConnectionError(),
        FakeResponse(status_code=503),
        FakeResponse(status_code=201),
    ],
)
def test_r8_8_declaration_without_a_usable_answer_gives_no_answer(
    config: RszDimonaConfig,
    failure: FakeResponse | Exception,
) -> None:
    """A timeout, a broken connection, a server error or a 201 without number: no answer."""
    client, _, _ = build_client(config=config, replies=[build_token_reply(), failure])

    outcome = client.declare(declaration=DECLARATION)

    assert outcome.status == 'no_answer'
    assert outcome.declaration_id is None


def test_r8_8_no_call_is_made_after_the_2_minutes(config: RszDimonaConfig) -> None:
    """Every HTTP call gets at most the time that is left."""
    not_processed = [FakeResponse(status_code=404) for _ in range(20)]
    replies = [build_token_reply(), build_received_reply(), *not_processed]
    client, rsz, clock = build_client(config=config, replies=replies)
    clock.now = 1000.0

    client.declare(declaration=DECLARATION)

    timeouts = [call['timeout'] for call in rsz.calls]
    assert max(timeouts) <= 30
    assert clock.now <= 1000.0 + DIMONA_TIMEOUT_SECONDS


def test_r9_3_cancellation_cancels_the_period_of_the_declaration(config: RszDimonaConfig) -> None:
    """The period is looked up from the declaration number, then cancelled and confirmed."""
    replies = [
        build_token_reply(),
        build_processed_reply(result='A'),
        build_received_reply(declaration_id=CANCELLATION_ID),
        FakeResponse(status_code=404),
        build_processed_reply(result='A', declaration_id=CANCELLATION_ID),
    ]
    client, rsz, _ = build_client(config=config, replies=replies)

    outcome = client.cancel(declaration_id=DECLARATION_ID)

    assert outcome.status == 'confirmed'
    lookup = rsz.calls[1]
    assert lookup['method'] == 'GET'
    assert lookup['url'] == f'{DECLARATIONS_URL}/{DECLARATION_ID}'
    post = rsz.calls[2]
    assert post['method'] == 'POST'
    assert post['url'] == DECLARATIONS_URL
    assert post['json'] == {
        'employer': {'enterpriseNumber': ENTERPRISE_NUMBER, 'employerId': EMPLOYER_ID},
        'worker': {'ssin': VALID_NATIONAL_REGISTER_NUMBER},
        'dimonaCancel': {'periodId': PERIOD_ID},
    }
    assert rsz.calls[4]['url'] == f'{DECLARATIONS_URL}/{CANCELLATION_ID}'


def test_r9_4_refused_cancellation_gives_the_reason(config: RszDimonaConfig) -> None:
    """Result B on the cancellation is a refusal with the French anomaly."""
    anomalies = [{'errorId': '00913-003', 'label': {'fr': 'Période déjà annulée'}}]
    refused = build_processed_reply(result='B', anomalies=anomalies, declaration_id=CANCELLATION_ID)
    replies = [
        build_token_reply(),
        build_processed_reply(result='A'),
        build_received_reply(declaration_id=CANCELLATION_ID),
        refused,
    ]
    client, _, _ = build_client(config=config, replies=replies)

    outcome = client.cancel(declaration_id=DECLARATION_ID)

    assert outcome.status == 'refused'
    assert outcome.message == 'Période déjà annulée'


def test_r9_4_unknown_declaration_is_refused_without_a_cancellation(
    config: RszDimonaConfig,
) -> None:
    """A declaration the RSZ does not know is not cancelled: nothing is posted."""
    replies = [build_token_reply(), FakeResponse(status_code=404)]
    client, rsz, _ = build_client(config=config, replies=replies)

    outcome = client.cancel(declaration_id=DECLARATION_ID)

    assert outcome.status == 'refused'
    assert outcome.message
    methods = [call['method'] for call in rsz.calls[1:]]
    assert methods == ['GET']


def test_r9_4_unprocessed_cancellation_gives_no_answer(config: RszDimonaConfig) -> None:
    """A cancellation without a verdict within 2 minutes is not confirmed."""
    not_processed = [FakeResponse(status_code=404) for _ in range(20)]
    replies = [
        build_token_reply(),
        build_processed_reply(result='A'),
        build_received_reply(declaration_id=CANCELLATION_ID),
        *not_processed,
    ]
    client, _, clock = build_client(config=config, replies=replies)

    outcome = client.cancel(declaration_id=DECLARATION_ID)

    assert outcome.status == 'no_answer'
    assert clock.now <= DIMONA_TIMEOUT_SECONDS


def test_r9_4_cancellation_follows_an_unreachable_rsz(config: RszDimonaConfig) -> None:
    """A timeout is no answer; an unavailable service is a refusal with that reason."""
    statuses = {}
    failures = {'timeout': requests.Timeout(), 'unavailable': FakeResponse(status_code=503)}
    for name in failures:
        replies = [build_token_reply(), failures[name]]
        client, _, _ = build_client(config=config, replies=replies)
        statuses[name] = client.cancel(declaration_id=DECLARATION_ID).status

    assert statuses == {'timeout': 'no_answer', 'unavailable': 'refused'}


UPDATE_ID = '6465484777'


def test_r8_9_update_raises_the_hours_of_the_period_of_the_declaration(
    config: RszDimonaConfig,
) -> None:
    """The period is looked up from the declaration number, then updated and accepted."""
    replies = [
        build_token_reply(),
        build_processed_reply(result='A'),
        build_received_reply(declaration_id=UPDATE_ID),
        FakeResponse(status_code=404),
        build_processed_reply(result='A', declaration_id=UPDATE_ID),
    ]
    client, rsz, _ = build_client(config=config, replies=replies)

    outcome = client.update_hours(declaration_id=DECLARATION_ID, planned_hours=5)

    assert outcome.status == 'accepted'
    assert outcome.declaration_id == UPDATE_ID
    lookup = rsz.calls[1]
    assert lookup['method'] == 'GET'
    assert lookup['url'] == f'{DECLARATIONS_URL}/{DECLARATION_ID}'
    post = rsz.calls[2]
    assert post['method'] == 'POST'
    assert post['url'] == DECLARATIONS_URL
    assert post['json'] == {
        'employer': {'enterpriseNumber': ENTERPRISE_NUMBER, 'employerId': EMPLOYER_ID},
        'worker': {'ssin': VALID_NATIONAL_REGISTER_NUMBER},
        'dimonaUpdate': {'periodId': PERIOD_ID, 'plannedHoursNumber': 5},
    }
    assert rsz.calls[4]['url'] == f'{DECLARATIONS_URL}/{UPDATE_ID}'


def test_r8_9_refused_update_gives_the_french_reason(config: RszDimonaConfig) -> None:
    """Result B on the update is a rejection with the anomaly and no number."""
    anomalies = [{'errorId': '01135-001', 'label': {'fr': "Nombre d'heures invalide"}}]
    refused = build_processed_reply(result='B', anomalies=anomalies, declaration_id=UPDATE_ID)
    replies = [
        build_token_reply(),
        build_processed_reply(result='A'),
        build_received_reply(declaration_id=UPDATE_ID),
        refused,
    ]
    client, _, _ = build_client(config=config, replies=replies)

    outcome = client.update_hours(declaration_id=DECLARATION_ID, planned_hours=5)

    assert outcome.status == 'rejected'
    assert outcome.declaration_id is None
    assert outcome.message == "Nombre d'heures invalide"


def test_r8_9_unknown_declaration_is_rejected_without_an_update(config: RszDimonaConfig) -> None:
    """A declaration the RSZ does not know leads to no period: nothing is posted."""
    replies = [build_token_reply(), FakeResponse(status_code=404)]
    client, rsz, _ = build_client(config=config, replies=replies)

    outcome = client.update_hours(declaration_id=DECLARATION_ID, planned_hours=5)

    assert outcome.status == 'rejected'
    assert outcome.message
    methods = [call['method'] for call in rsz.calls[1:]]
    assert methods == ['GET']


def test_r8_9_unprocessed_update_gives_no_answer_with_its_number(config: RszDimonaConfig) -> None:
    """An update received without a verdict within 2 minutes is pending, with its number."""
    not_processed = [FakeResponse(status_code=404) for _ in range(20)]
    replies = [
        build_token_reply(),
        build_processed_reply(result='A'),
        build_received_reply(declaration_id=UPDATE_ID),
        *not_processed,
    ]
    client, _, clock = build_client(config=config, replies=replies)

    outcome = client.update_hours(declaration_id=DECLARATION_ID, planned_hours=5)

    assert outcome.status == 'no_answer'
    assert UPDATE_ID in outcome.message
    assert clock.now <= DIMONA_TIMEOUT_SECONDS


def test_r8_9_update_follows_an_unreachable_rsz(config: RszDimonaConfig) -> None:
    """Without an answer to the period lookup, the update is pending and nothing is posted."""
    statuses = {}
    failures = {'timeout': requests.Timeout(), 'unavailable': FakeResponse(status_code=503)}
    for name in failures:
        replies = [build_token_reply(), failures[name]]
        client, _, _ = build_client(config=config, replies=replies)
        statuses[name] = client.update_hours(declaration_id=DECLARATION_ID, planned_hours=5).status

    assert statuses == {'timeout': 'no_answer', 'unavailable': 'no_answer'}


def test_r3_5_national_register_number_never_reaches_the_logs(
    config: RszDimonaConfig,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Declaring, being refused and cancelling log the flow without the national number."""
    problem = {'detail': f'ssin {VALID_NATIONAL_REGISTER_NUMBER} is unknown'}
    replies = [
        build_token_reply(),
        build_received_reply(),
        build_processed_reply(result='A'),
        FakeResponse(status_code=400, body=problem),
        build_processed_reply(result='A'),
        build_received_reply(declaration_id=CANCELLATION_ID),
        build_processed_reply(result='A', declaration_id=CANCELLATION_ID),
    ]
    client, _, _ = build_client(config=config, replies=replies)

    with caplog.at_level(logging.DEBUG):
        client.declare(declaration=DECLARATION)
        client.declare(declaration=DECLARATION)
        client.cancel(declaration_id=DECLARATION_ID)

    assert caplog.records
    assert VALID_NATIONAL_REGISTER_NUMBER not in caplog.text


def test_r2_7_configuration_hides_the_private_key_when_printed(config: RszDimonaConfig) -> None:
    """The key never shows up when the configuration ends in a log line or an error."""
    assert 'PRIVATE KEY' not in repr(config)
    assert 'PRIVATE KEY' not in str(config)


def test_r2_3_test_environment_has_no_dimona_endpoint() -> None:
    """The fake service of TEST has no address; ACC has the one of the RSZ test service."""
    assert find_dimona_endpoint(app_env='TEST') is None
    assert (
        find_dimona_endpoint(app_env='ACC')
        == 'https://services-sim.socialsecurity.be/REST/dimona/v2'
    )


def test_r2_3_test_environment_makes_no_dimona_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """In TEST the application only talks to the fake service (R1.11)."""
    monkeypatch.setenv('APP_ENV', 'TEST')
    monkeypatch.setenv('DATABASE_URL', DATABASE_URL)
    monkeypatch.setenv('FAKE_DIMONA_OUTCOME', 'timeout')

    client = build_dimona_client(settings=load_settings())

    assert isinstance(client, FakeDimonaClient)
    assert client.outcome == 'timeout'


@pytest.mark.parametrize(
    ('app_env', 'host'),
    [
        ('ACC', 'https://services-sim.socialsecurity.be'),
        ('PROD', 'https://services.socialsecurity.be'),
    ],
)
def test_r2_3_environment_decides_the_rsz_service(
    monkeypatch: pytest.MonkeyPatch,
    rsz_environment: None,
    private_key_pem: bytes,
    tmp_path: Path,
    app_env: str,
    host: str,
) -> None:
    """ACC declares at the RSZ test service, PROD at the live one; both sign in at the live one."""
    key_path = tmp_path / 'company_key.pem'
    key_path.write_bytes(private_key_pem)
    monkeypatch.setenv('APP_ENV', app_env)
    monkeypatch.setenv('DATABASE_URL', DATABASE_URL)
    monkeypatch.delenv('DIMONA_PRIVATE_KEY')
    monkeypatch.setenv('DIMONA_PRIVATE_KEY_PATH', str(key_path))

    client = build_dimona_client(settings=load_settings())

    assert isinstance(client, RszDimonaClient)
    assert client.config.base_url == f'{host}/REST/dimona/v2'
    assert client.config.oauth_url == 'https://services.socialsecurity.be/REST/oauth/v5/token'
    assert client.config.employer_id == 123456
    assert client.config.joint_commission_flexi_job == 'XXX'


def test_r2_7_private_key_can_come_from_an_environment_variable(
    monkeypatch: pytest.MonkeyPatch,
    rsz_environment: None,
    private_key_pem: bytes,
) -> None:
    """In GCP the key is injected as text from Secret Manager, without any file.

    Settings are trimmed, so the key arrives without the line break at its end and still loads.
    """
    monkeypatch.setenv('APP_ENV', 'ACC')
    monkeypatch.setenv('DATABASE_URL', DATABASE_URL)
    monkeypatch.setenv('DIMONA_PRIVATE_KEY', private_key_pem.decode())

    config = build_rsz_config(settings=load_settings())

    loaded_key = serialization.load_pem_private_key(data=config.private_key_pem, password=None)
    assert config.private_key_pem == private_key_pem.strip()
    assert isinstance(loaded_key, rsa.RSAPrivateKey)
