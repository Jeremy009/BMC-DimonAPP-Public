"""The real Dimona client: the REST service of the RSZ/ONSS (R8.5, R8.9, R9.3).

Ported from the client of DimonAPP V2 (its src/dimona.py and api.py, kept outside this
repository; the RSZ specification is docs/openapi_dimona_v2.yaml), which
is proven against the live service. Kept from V2:

- Authentication is OAuth2 client_credentials with a signed-JWT client assertion (RS256, key
  registered on the RSZ self-service portal). No certificate is sent.
- enterpriseNumber must be a JSON string; an integer gets a 400.
- A 201 on POST /declarations only means "received". The number of the new declaration is in
  the Location header, and GET /declarations/{id} answers 404 until the RSZ has processed it.
- The verdict is declarationStatus.result: A accepted, W accepted with a warning, B refused,
  S waiting for the identification of the worker.

Different from V2: the configuration comes from the settings instead of a config.toml, the
service called follows from the environment (R2.3), the
whole exchange gets DIMONA_TIMEOUT_SECONDS instead of 54 seconds (R8.8), a cancellation
starts from the declaration number instead of a period number typed by the user, a later
article 17 activity of the same day updates the hours of the period of that day (V2 had no
such case), and nothing received from the RSZ is logged, as it may hold a national register
number (R3.5).
"""

import logging
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import jwt
import requests
from cryptography.hazmat.primitives import serialization
from pydantic import BaseModel, Field

from dimonapp.dimona import (
    DIMONA_TIMEOUT_SECONDS,
    CancellationOutcome,
    DeclarationOutcome,
    DimonaClient,
    DimonaDeclaration,
    FakeDimonaClient,
)
from dimonapp.models import WorkerType
from dimonapp.settings import FAKE_DIMONA_ENVIRONMENT, Settings

logger = logging.getLogger(__name__)

# The RSZ service of each environment with real Dimona calls (R2.3): the test (simulation)
# service in ACC, the live service in PROD. TEST has none and gets the fake client.
# The RSZ test service has no sign-in of its own (its token address answers 404): it takes
# the tokens of the live sign-in service, so every environment signs in there. Checked against
# the RSZ on 10/10/2026.
RSZ_TEST_HOST = 'https://services-sim.socialsecurity.be'
RSZ_LIVE_HOST = 'https://services.socialsecurity.be'
RSZ_HOSTS = {'ACC': RSZ_TEST_HOST, 'PROD': RSZ_LIVE_HOST}
DIMONA_PATH = '/REST/dimona/v2'
OAUTH_PATH = '/REST/oauth/v5/token'

OAUTH_ASSERTION_TYPE = 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer'
ACCEPT_HEADER = 'application/json, application/problem+json'

# One HTTP call never waits longer than this, and never past the end of the 2 minutes.
REQUEST_TIMEOUT_SECONDS = 30
# Seconds between two looks at a declaration the RSZ has not processed yet, as in V2 but
# stretched to fill the 2 minutes.
POLL_DELAYS_SECONDS = (1, 1, 2, 3, 5, 8, 13, 21, 21, 21, 21)
# A token is renewed when it has less than this left.
TOKEN_MARGIN_SECONDS = 60
DEFAULT_TOKEN_LIFETIME_SECONDS = 600
ASSERTION_LIFETIME_SECONDS = 3600

# Worker type codes of the RSZ: S17 is article 17 in the sport sector.
RSZ_WORKER_TYPES = {WorkerType.ARTICLE_17: 'S17', WorkerType.FLEXI_JOB: 'FLX'}
# Times go to the RSZ as HHMM.
RSZ_HOUR_FORMAT = '%H%M'
ACCEPTED_RESULTS = ('A', 'W')
REFUSED_RESULT = 'B'

HIDDEN_VALUE = '***'
UNAVAILABLE_REASON = 'service Dimona indisponible'
UNKNOWN_DECLARATION_REASON = 'déclaration introuvable auprès du service Dimona'
NO_PERIOD_REASON = 'aucune période Dimona liée à cette déclaration'


class RszDimonaConfig(BaseModel):
    """Which RSZ service to call, and who BMC is there."""

    base_url: str
    oauth_url: str
    client_id: str
    enterprise_number: str
    employer_id: int
    joint_commission_article_17: str
    joint_commission_flexi_job: str
    # Never shown when the configuration is printed or logged (R2.7).
    private_key_pem: bytes = Field(repr=False)
    private_key_password: Optional[str] = Field(default=None, repr=False)


class RszPeriod(BaseModel):
    """A Dimona period as the RSZ holds it: its number and the worker it belongs to."""

    period_id: int
    # Never shown when the period is printed or logged (R3.5).
    ssin: Optional[str] = Field(default=None, repr=False)


class RszNoAnswerError(Exception):
    """The RSZ did not answer in time."""


class RszUnavailableError(Exception):
    """The RSZ could not be reached or answered with a server error."""


class RszRefusalError(Exception):
    """The RSZ answered and refused the call."""

    def __init__(self, reason: str) -> None:
        """Keep the reason to show to the user."""
        super().__init__(reason)
        self.reason = reason


def hide_value(text: str, hidden: Optional[str]) -> str:
    """Remove a national register number from a text of the RSZ (R3.5)."""
    if not hidden:
        return text
    return text.replace(hidden, HIDDEN_VALUE)


def read_json(response: requests.Response) -> dict[str, Any]:
    """Give the JSON object of a response, or an empty one when the body is something else."""
    try:
        body = response.json()
    except ValueError:
        return {}
    if not isinstance(body, dict):
        return {}
    return body


def describe_problem(response: requests.Response, hidden: Optional[str]) -> str:
    """Give the reason of a refused call from its problem+json body (R8.7)."""
    problem = read_json(response=response)
    issues = problem.get('issues') or []
    details = [problem.get('detail') or problem.get('title')]
    for issue in issues:
        details.append(issue.get('detail') or issue.get('title'))
    texts = [str(detail) for detail in details if detail]
    if not texts:
        return f'réponse HTTP {response.status_code} du service Dimona'
    reason = ' ; '.join(texts)
    return hide_value(text=reason, hidden=hidden)


def describe_anomalies(status: dict[str, Any], hidden: Optional[str]) -> Optional[str]:
    """Give the French anomalies the RSZ attached to its verdict, or None without any."""
    anomalies = status.get('anomalies') or []
    texts = []
    for anomaly in anomalies:
        label = anomaly.get('label') or {}
        text = label.get('fr') or anomaly.get('errorId')
        if text:
            texts.append(str(text))
    if not texts:
        return None
    reason = ' ; '.join(texts)
    return hide_value(text=reason, hidden=hidden)


def read_declaration_id(response: requests.Response) -> str:
    """Give the number of a new declaration, the last part of the Location header."""
    location = response.headers.get('Location', '')
    declaration_id = location.rstrip('/').rsplit('/', 1)[-1]
    if not declaration_id:
        raise RszUnavailableError('No declaration number in the answer of the RSZ.')
    return declaration_id


def build_employer(config: RszDimonaConfig) -> dict[str, Any]:
    """Give the employer block of every declaration."""
    return {'enterpriseNumber': config.enterprise_number, 'employerId': config.employer_id}


def build_period_body(
    config: RszDimonaConfig,
    period: RszPeriod,
    block: dict[str, Any],
) -> dict[str, Any]:
    """Build a Dimona UPDATE or CANCEL of a period, as V2 builds its CANCEL.

    The employer, the worker of the period when the RSZ gave one, and the block itself.
    """
    body = {'employer': build_employer(config=config), **block}
    if period.ssin:
        body['worker'] = {'ssin': period.ssin}
    return body


def build_flexi_job_fields(declaration: DimonaDeclaration) -> dict[str, Any]:
    """Build the dates and times of a flexi-job Dimona IN (R7.15).

    Learned from the refusals of the RSZ: a flexi-job needs a start and an end time, and planned
    hours are forbidden. An activity that runs past midnight ends on the next day.
    """
    if declaration.start_time is None:
        raise ValueError('A flexi-job declaration needs a start time.')
    start = datetime.combine(date=declaration.activity_date, time=declaration.start_time)
    end = start + timedelta(hours=declaration.planned_hours)
    return {
        'startDate': start.date().isoformat(),
        'startHour': start.strftime(RSZ_HOUR_FORMAT),
        'endDate': end.date().isoformat(),
        'endHour': end.strftime(RSZ_HOUR_FORMAT),
    }


def build_declaration_body(
    config: RszDimonaConfig,
    declaration: DimonaDeclaration,
) -> dict[str, Any]:
    """Build the Dimona IN of one activity (R8.5).

    Article 17: one day with its planned whole hours, as in V2. Flexi-job: one day with its
    start and end time.
    """
    worker_type = declaration.worker_type
    if worker_type == WorkerType.FLEXI_JOB:
        joint_commission = config.joint_commission_flexi_job
        fields = build_flexi_job_fields(declaration=declaration)
    else:
        joint_commission = config.joint_commission_article_17
        activity_date = declaration.activity_date.isoformat()
        fields = {
            'startDate': activity_date,
            'endDate': activity_date,
            'plannedHoursNumber': declaration.planned_hours,
        }
    features = {
        'workerType': RSZ_WORKER_TYPES[worker_type],
        'jointCommissionNumber': joint_commission,
    }
    return {
        'employer': build_employer(config=config),
        'worker': {'ssin': declaration.national_register_number},
        'dimonaIn': {**fields, 'features': features},
    }


class RszDimonaClient:
    """The Dimona service of the RSZ, the test one or the live one depending on the config."""

    def __init__(
        self,
        config: RszDimonaConfig,
        http: requests.Session,
        read_seconds: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Load the private key; the clock and the sleep are replaced in the tests."""
        self.config = config
        self.http = http
        self.read_seconds = read_seconds
        self.sleep = sleep
        password = config.private_key_password
        password_bytes = password.encode() if password else None
        self.private_key = serialization.load_pem_private_key(
            data=config.private_key_pem,
            password=password_bytes,
        )
        self.token: Optional[str] = None
        self.token_expiry = 0.0

    def declare(self, declaration: DimonaDeclaration) -> DeclarationOutcome:
        """Send a declaration and wait up to 2 minutes for the verdict of the RSZ (R8.5)."""
        deadline = self.read_seconds() + DIMONA_TIMEOUT_SECONDS
        hidden = declaration.national_register_number
        body = build_declaration_body(config=self.config, declaration=declaration)
        return self.send_and_wait(body=body, deadline=deadline, hidden=hidden)

    def update_hours(self, declaration_id: str, planned_hours: int) -> DeclarationOutcome:
        """Change the planned hours of the period of a declaration, wait up to 2 minutes (R8.9).

        The RSZ keeps one article 17 period per worker and day, so a later activity of the same
        day changes the hours of that period instead of declaring a new one.
        """
        deadline = self.read_seconds() + DIMONA_TIMEOUT_SECONDS

        # Find the period: until the update is sent, a refusal is a rejection
        try:
            period = self.find_period(declaration_id=declaration_id, deadline=deadline)
        except RszRefusalError as refusal:
            logger.info(f'Dimona update of declaration {declaration_id}: period not found.')
            return DeclarationOutcome(status='rejected', message=refusal.reason)
        except (RszNoAnswerError, RszUnavailableError):
            logger.warning(f'Dimona update of declaration {declaration_id}: no answer.')
            return DeclarationOutcome(status='no_answer')

        update = {'periodId': period.period_id, 'plannedHoursNumber': planned_hours}
        body = build_period_body(config=self.config, period=period, block={'dimonaUpdate': update})
        return self.send_and_wait(body=body, deadline=deadline, hidden=period.ssin)

    def send_and_wait(
        self,
        body: dict[str, Any],
        deadline: float,
        hidden: Optional[str],
    ) -> DeclarationOutcome:
        """POST a Dimona IN or UPDATE and wait for the verdict of the RSZ until the deadline."""
        # Send the declaration: until the RSZ has received it, a refusal is a rejection
        try:
            declaration_id = self.submit(body=body, deadline=deadline, hidden=hidden)
        except RszRefusalError as refusal:
            logger.info('Dimona declaration refused by the RSZ before processing.')
            return DeclarationOutcome(status='rejected', message=refusal.reason)
        except (RszNoAnswerError, RszUnavailableError):
            logger.warning('Dimona declaration without an answer of the RSZ.')
            return DeclarationOutcome(status='no_answer')

        # Wait for the verdict: from here on the declaration exists, whatever goes wrong
        waiting_message = f'Déclaration Dimona n° {declaration_id} transmise, sans verdict du RSZ'
        try:
            status = self.wait_for_status(declaration_id=declaration_id, deadline=deadline)
        except (RszNoAnswerError, RszUnavailableError, RszRefusalError):
            status = None
        if status is None:
            logger.warning(f'Dimona declaration {declaration_id} received but not processed.')
            return DeclarationOutcome(status='no_answer', message=waiting_message)

        # Store what the RSZ really decided (R8.6, R8.7)
        result = status.get('result')
        message = describe_anomalies(status=status, hidden=hidden)
        logger.info(f'Dimona declaration {declaration_id} processed with result {result}.')
        if result in ACCEPTED_RESULTS:
            return DeclarationOutcome(
                status='accepted',
                declaration_id=declaration_id,
                message=message,
            )
        if result == REFUSED_RESULT:
            return DeclarationOutcome(status='rejected', message=message)
        return DeclarationOutcome(status='no_answer', message=waiting_message)

    def cancel(self, declaration_id: str) -> CancellationOutcome:
        """Cancel the period of a declaration and wait up to 2 minutes for the verdict (R9.3)."""
        deadline = self.read_seconds() + DIMONA_TIMEOUT_SECONDS
        try:
            status = self.request_cancellation(declaration_id=declaration_id, deadline=deadline)
        except RszNoAnswerError:
            logger.warning(f'Cancellation of Dimona declaration {declaration_id}: no answer.')
            return CancellationOutcome(status='no_answer')
        except RszUnavailableError:
            logger.warning(f'Cancellation of Dimona declaration {declaration_id}: unavailable.')
            return CancellationOutcome(status='refused', message=UNAVAILABLE_REASON)
        except RszRefusalError as refusal:
            logger.info(f'Cancellation of Dimona declaration {declaration_id} refused.')
            return CancellationOutcome(status='refused', message=refusal.reason)
        if status is None:
            logger.warning(f'Cancellation of Dimona declaration {declaration_id} not processed.')
            return CancellationOutcome(status='no_answer')

        # Only a verdict of the RSZ confirms the cancellation (R9.4)
        result = status.get('result')
        logger.info(f'Cancellation of Dimona declaration {declaration_id}: result {result}.')
        if result in ACCEPTED_RESULTS:
            return CancellationOutcome(status='confirmed')
        if result == REFUSED_RESULT:
            message = describe_anomalies(status=status, hidden=None)
            return CancellationOutcome(status='refused', message=message)
        return CancellationOutcome(status='no_answer')

    def request_cancellation(
        self,
        declaration_id: str,
        deadline: float,
    ) -> Optional[dict[str, Any]]:
        """Send the Dimona CANCEL of a declaration and give its verdict, or None without one.

        The RSZ cancels a period, not a declaration, so the period is looked up first.
        """
        period = self.find_period(declaration_id=declaration_id, deadline=deadline)
        cancel = {'periodId': period.period_id}
        body = build_period_body(config=self.config, period=period, block={'dimonaCancel': cancel})
        cancellation_id = self.submit(body=body, deadline=deadline, hidden=period.ssin)
        return self.wait_for_status(declaration_id=cancellation_id, deadline=deadline)

    def find_period(self, declaration_id: str, deadline: float) -> RszPeriod:
        """Give the period a declaration belongs to, with the worker of that period."""
        declared = self.fetch_declaration(declaration_id=declaration_id, deadline=deadline)
        if declared is None:
            raise RszRefusalError(UNKNOWN_DECLARATION_REASON)
        status = declared.get('declarationStatus') or {}
        period = status.get('period') or {}
        period_id = period.get('id')
        if period_id is None:
            raise RszRefusalError(NO_PERIOD_REASON)
        worker = declared.get('worker') or {}
        return RszPeriod(period_id=period_id, ssin=worker.get('ssin'))

    def submit(self, body: dict[str, Any], deadline: float, hidden: Optional[str]) -> str:
        """POST a declaration and give the number the RSZ assigned to it."""
        path = '/declarations'
        response = self.call_service(method='POST', path=path, deadline=deadline, body=body)
        if response.status_code != 201:
            logger.info(f'POST /declarations answered {response.status_code}.')
            reason = describe_problem(response=response, hidden=hidden)
            raise RszRefusalError(reason)
        return read_declaration_id(response=response)

    def fetch_declaration(self, declaration_id: str, deadline: float) -> Optional[dict[str, Any]]:
        """Give a declaration as the RSZ holds it, or None while it is unknown or unprocessed."""
        path = f'/declarations/{declaration_id}'
        response = self.call_service(method='GET', path=path, deadline=deadline)
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            logger.info(f'GET /declarations/{declaration_id} answered {response.status_code}.')
            reason = describe_problem(response=response, hidden=None)
            raise RszRefusalError(reason)
        return read_json(response=response)

    def wait_for_status(self, declaration_id: str, deadline: float) -> Optional[dict[str, Any]]:
        """Look at a declaration until the RSZ has processed it; None when time runs out."""
        for delay in POLL_DELAYS_SECONDS:
            if self.read_seconds() + delay >= deadline:
                return None
            self.sleep(delay)
            declared = self.fetch_declaration(declaration_id=declaration_id, deadline=deadline)
            if declared is not None:
                return declared.get('declarationStatus') or {}
        return None

    def call_service(
        self,
        method: str,
        path: str,
        deadline: float,
        body: Optional[dict[str, Any]] = None,
    ) -> requests.Response:
        """Make one authenticated call to the Dimona service."""
        token = self.find_token(deadline=deadline)
        headers = {'Authorization': f'Bearer {token}', 'Accept': ACCEPT_HEADER}
        url = f'{self.config.base_url}{path}'
        return self.send(method=method, url=url, deadline=deadline, headers=headers, json=body)

    def find_token(self, deadline: float) -> str:
        """Give the cached access token, or sign in again when it is about to expire."""
        now = self.read_seconds()
        if self.token is not None and now < self.token_expiry - TOKEN_MARGIN_SECONDS:
            return self.token

        # Sign a client assertion with the private key registered at the RSZ
        config = self.config
        issued_at = int(time.time())
        claims = {
            'iss': config.client_id,
            'sub': config.client_id,
            'aud': config.oauth_url,
            'exp': issued_at + ASSERTION_LIFETIME_SECONDS,
            'iat': issued_at,
            'jti': str(uuid.uuid4()),
        }
        assertion = jwt.encode(payload=claims, key=self.private_key, algorithm='RS256')
        form = {
            'grant_type': 'client_credentials',
            'client_assertion_type': OAUTH_ASSERTION_TYPE,
            'client_assertion': assertion,
        }
        response = self.send(method='POST', url=config.oauth_url, deadline=deadline, data=form)
        token_data = read_json(response=response)
        token = token_data.get('access_token')
        if response.status_code != 200 or not token:
            logger.error(f'Sign-in at the RSZ refused with status {response.status_code}.')
            reason = f'authentification refusée par le RSZ (HTTP {response.status_code})'
            raise RszRefusalError(reason)
        lifetime = token_data.get('expires_in', DEFAULT_TOKEN_LIFETIME_SECONDS)
        self.token = token
        self.token_expiry = now + lifetime
        return token

    def send(self, method: str, url: str, deadline: float, **content: Any) -> requests.Response:
        """Make one HTTP call that never outlasts the deadline."""
        remaining = deadline - self.read_seconds()
        if remaining <= 0:
            raise RszNoAnswerError('The 2 minutes are over.')
        timeout = min(REQUEST_TIMEOUT_SECONDS, remaining)
        try:
            response = self.http.request(method=method, url=url, timeout=timeout, **content)
        except requests.Timeout as error:
            raise RszNoAnswerError('The RSZ did not answer in time.') from error
        except requests.RequestException as error:
            raise RszUnavailableError('The RSZ could not be reached.') from error
        if response.status_code >= 500:
            logger.warning(f'The RSZ answered with server error {response.status_code}.')
            raise RszUnavailableError('The RSZ answered with a server error.')
        return response


def find_dimona_endpoint(app_env: str) -> Optional[str]:
    """Give the address of the RSZ Dimona service of an environment, none where it is fake (R2.3).

    The single place that turns an environment name into an address: there is no setting
    for it, so an environment cannot be pointed at the service of another one.
    """
    host = RSZ_HOSTS.get(app_env)
    if host is None:
        return None
    return f'{host}{DIMONA_PATH}'


def build_rsz_config(settings: Settings) -> RszDimonaConfig:
    """Pick the RSZ service of the environment and read the private key (R2.3, R2.7)."""
    private_key_pem = (settings.dimona_private_key or '').encode()
    if settings.dimona_private_key_path:
        private_key_pem = Path(settings.dimona_private_key_path).read_bytes()
    return RszDimonaConfig(
        base_url=find_dimona_endpoint(app_env=settings.app_env),
        oauth_url=f'{RSZ_LIVE_HOST}{OAUTH_PATH}',
        client_id=settings.dimona_client_id,
        enterprise_number=settings.dimona_enterprise_number,
        employer_id=settings.dimona_employer_id,
        joint_commission_article_17=settings.dimona_joint_commission_article_17,
        joint_commission_flexi_job=settings.dimona_joint_commission_flexi_job,
        private_key_pem=private_key_pem,
        private_key_password=settings.dimona_private_key_password or None,
    )


def build_dimona_client(settings: Settings) -> DimonaClient:
    """Give the Dimona client of the environment: fake in TEST, the RSZ in ACC and PROD (R2.3)."""
    if settings.app_env == FAKE_DIMONA_ENVIRONMENT:
        logger.info('Dimona client: fake service, no Dimona call is made.')
        return FakeDimonaClient(outcome=settings.fake_dimona_outcome)
    config = build_rsz_config(settings=settings)
    logger.info(f'Dimona client: RSZ service at {config.base_url}.')
    return RszDimonaClient(config=config, http=requests.Session())
