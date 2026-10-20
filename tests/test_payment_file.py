"""The SEPA pain.001 payment file of a month (R13.2)."""

from datetime import date, datetime
from decimal import Decimal

import pytest
from lxml import etree

from dimonapp import payment_file
from dimonapp.models import WorkerType
from dimonapp.monthly_report import ReportLine
from dimonapp.payment_file import (
    build_payment_file,
    build_payment_file_name,
    clean_sepa_text,
    find_payment_file_problem,
)
from dimonapp.xml_schemas import load_schema
from factories import FAKE_IBAN, build_organisation_form

SEPTEMBER = date(2026, 9, 1)
CREATED_AT = datetime(2026, 10, 2, 9, 30, 15)
OTHER_IBAN = 'BE07345678901234'
NAMESPACES = {'pain': 'urn:iso:std:iso:20022:tech:xsd:pain.001.001.09'}


def build_line(
    worker_name: str = 'Lotte Peeters',
    amount: Decimal = Decimal('610.00'),
    iban: str = OTHER_IBAN,
) -> ReportLine:
    """Build the line of one worker in the monthly report."""
    return ReportLine(
        worker_name=worker_name,
        worker_type=WorkerType.ARTICLE_17,
        hours=Decimal('24.5'),
        amount=amount,
        iban=iban,
    )


def build_document(lines: list[ReportLine]) -> etree._Element:
    """Build the payment file of September and parse it again."""
    content = build_payment_file(
        lines=lines,
        organisation=build_organisation_form(),
        month_start=SEPTEMBER,
        created_at=CREATED_AT,
    )
    return etree.fromstring(content)


def read_texts(document: etree._Element, path: str) -> list[str]:
    """Give the texts of the elements a path finds in a payment file."""
    return [element.text for element in document.findall(path, namespaces=NAMESPACES)]


def test_r13_2_payment_file_follows_the_pain_001_schema() -> None:
    """The file is a pain.001 message of the version of the single constant."""
    document = build_document(lines=[build_line()])

    schema = load_schema(file_name=payment_file.PAIN_SCHEMA_FILE)
    assert payment_file.PAIN_VERSION == 'pain.001.001.09'
    assert document.tag == '{urn:iso:std:iso:20022:tech:xsd:pain.001.001.09}Document'
    assert schema.validate(document)


def test_r13_2_payment_file_pays_every_worker_from_the_account_of_bmc() -> None:
    """One bulk from BMC's account, one transfer per worker, with the totals of the report."""
    lines = [
        build_line(),
        build_line(worker_name='Youssef El Amrani', amount=Decimal('625.50'), iban=FAKE_IBAN),
    ]

    document = build_document(lines=lines)

    bulk = './/pain:PmtInf'
    transfer = f'{bulk}/pain:CdtTrfTxInf'
    assert read_texts(document, './/pain:GrpHdr/pain:NbOfTxs') == ['2']
    assert read_texts(document, './/pain:GrpHdr/pain:CtrlSum') == ['1235.50']
    assert read_texts(document, './/pain:GrpHdr/pain:CreDtTm') == ['2026-10-02T09:30:15']
    assert read_texts(document, f'{bulk}/pain:PmtMtd') == ['TRF']
    assert read_texts(document, f'{bulk}/pain:BtchBookg') == ['true']
    assert read_texts(document, f'{bulk}/pain:CtrlSum') == ['1235.50']
    assert read_texts(document, f'{bulk}/pain:ReqdExctnDt/pain:Dt') == ['2026-10-02']
    assert read_texts(document, f'{bulk}/pain:Dbtr/pain:Nm') == ['Brussels Monkeys Climbing ASBL']
    assert read_texts(document, f'{bulk}/pain:DbtrAcct/pain:Id/pain:IBAN') == [FAKE_IBAN]
    assert read_texts(document, f'{transfer}/pain:Cdtr/pain:Nm') == [
        'Lotte Peeters',
        'Youssef El Amrani',
    ]
    assert read_texts(document, f'{transfer}/pain:CdtrAcct/pain:Id/pain:IBAN') == [
        OTHER_IBAN,
        FAKE_IBAN,
    ]
    assert read_texts(document, f'{transfer}/pain:Amt/pain:InstdAmt') == ['610.00', '625.50']
    assert read_texts(document, f'{transfer}/pain:PmtId/pain:EndToEndId') == [
        'BMC-2026-09-001',
        'BMC-2026-09-002',
    ]
    assert read_texts(document, f'{transfer}/pain:RmtInf/pain:Ustrd') == [
        'Brussels Monkeys Climbing ASBL septembre 2026',
        'Brussels Monkeys Climbing ASBL septembre 2026',
    ]
    currencies = [amount.get('Ccy') for amount in document.iterfind('.//pain:InstdAmt', NAMESPACES)]
    assert currencies == ['EUR', 'EUR']


def test_r13_2_worker_without_an_amount_due_is_left_out() -> None:
    """A transfer of zero euro is not a payment."""
    lines = [build_line(), build_line(worker_name='Sofie Claes', amount=Decimal('0'))]

    document = build_document(lines=lines)

    assert read_texts(document, './/pain:Cdtr/pain:Nm') == ['Lotte Peeters']
    assert read_texts(document, './/pain:GrpHdr/pain:NbOfTxs') == ['1']


def test_r13_2_names_only_hold_characters_sepa_accepts() -> None:
    """Accents are dropped and anything else becomes a space; the text is cut to its length."""
    document = build_document(lines=[build_line(worker_name='Michaël Łukasz & Søn')])

    assert read_texts(document, './/pain:Cdtr/pain:Nm') == ['Michael Lukasz   Son']
    assert clean_sepa_text(text='décembre_2026 ', max_length=140) == 'decembre 2026'
    assert clean_sepa_text(text='abcdef', max_length=3) == 'abc'


def test_r13_2_payment_file_needs_something_to_pay() -> None:
    """Without an amount due there is no file, and the admin is told why."""
    lines = [build_line(amount=Decimal('0'))]
    organisation = build_organisation_form()

    problem = find_payment_file_problem(lines=lines, organisation=organisation)

    assert problem == 'Aucun montant à payer pour ce mois.'
    with pytest.raises(ValueError):
        build_payment_file(
            lines=lines,
            organisation=organisation,
            month_start=SEPTEMBER,
            created_at=CREATED_AT,
        )


@pytest.mark.parametrize('field', ['name', 'iban'])
def test_r13_2_payment_file_needs_the_name_and_iban_of_bmc(field: str) -> None:
    """The debtor cannot be left open: the admin is sent to the configuration."""
    organisation = build_organisation_form()
    setattr(organisation, field, '')

    problem = find_payment_file_problem(lines=[build_line()], organisation=organisation)

    assert problem == (
        "Le fichier de paiement a besoin du nom et de l'IBAN de BMC : complétez les "
        'coordonnées de BMC dans Configuration.'
    )


def test_r13_2_payment_file_is_possible_and_named_after_its_month() -> None:
    """With an amount due and BMC's details nothing stands in the way."""
    problem = find_payment_file_problem(
        lines=[build_line()],
        organisation=build_organisation_form(),
    )

    assert problem is None
    assert build_payment_file_name(month_start=SEPTEMBER) == 'bmc_paiements_2026-09.xml'


def test_r3_5_payment_file_logs_no_iban_or_name(caplog: pytest.LogCaptureFixture) -> None:
    """The log only tells the month and the number of payments."""
    caplog.set_level('INFO')

    build_document(lines=[build_line()])

    assert 'Payment file of 2026-09 built: 1 payments.' in caplog.text
    assert OTHER_IBAN not in caplog.text
    assert 'Peeters' not in caplog.text
