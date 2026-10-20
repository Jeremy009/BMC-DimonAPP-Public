"""The bulk payment file of a month for Belfius Direct Net: SEPA pain.001 (R13.2).

One file with one payment bulk: a credit transfer from BMC's account to every worker with an
amount due in the monthly report. The IBANs leave the database here and nowhere else in the
payment flow; they are never logged (R3.5).
"""

import logging
import string
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from lxml import etree

from dimonapp.configuration import OrganisationForm
from dimonapp.french import format_month, remove_accents
from dimonapp.iban import is_valid_iban
from dimonapp.monthly_report import ReportLine
from dimonapp.xml_schemas import add_child, write_checked_xml

logger = logging.getLogger(__name__)

# The version of the SEPA credit transfer message; the only place it is named.
# NOTE: to be confirmed with Belfius for BMC's account (open item 1 of the FDS).
PAIN_VERSION = 'pain.001.001.09'
PAIN_NAMESPACE = f'urn:iso:std:iso:20022:tech:xsd:{PAIN_VERSION}'
PAIN_SCHEMA_FILE = f'{PAIN_VERSION}.xsd'

# SEPA accepts only these characters in names and messages.
SEPA_CHARACTERS = set(string.ascii_letters + string.digits + "/-?:().,'+ ")
MAX_NAME_LENGTH = 70
MAX_MESSAGE_LENGTH = 140
# The bank of the debtor is found from the IBAN; the element itself is mandatory.
BANK_NOT_PROVIDED = 'NOTPROVIDED'

MISSING_ORGANISATION_MESSAGE = (
    "Le fichier de paiement a besoin du nom et de l'IBAN de BMC : complétez les coordonnées "
    'de BMC dans Configuration.'
)
NOTHING_TO_PAY_MESSAGE = 'Aucun montant à payer pour ce mois.'


def clean_sepa_text(text: str, max_length: int) -> str:
    """Give a text SEPA accepts: without accents, other characters as a space, cut to length."""
    plain_text = remove_accents(text=text)
    characters = [character if character in SEPA_CHARACTERS else ' ' for character in plain_text]
    return ''.join(characters).strip()[:max_length]


def find_payable_lines(lines: list[ReportLine]) -> list[ReportLine]:
    """Give the lines of the monthly report with an amount to pay."""
    return [line for line in lines if line.amount > 0]


def find_payment_file_problem(
    lines: list[ReportLine],
    organisation: OrganisationForm,
) -> Optional[str]:
    """Give the French message of what keeps the payment file from being built, or None."""
    if not find_payable_lines(lines=lines):
        return NOTHING_TO_PAY_MESSAGE
    if not organisation.name or not is_valid_iban(iban=organisation.iban):
        return MISSING_ORGANISATION_MESSAGE
    return None


def build_payment_file_name(month_start: date) -> str:
    """Name the payment file after its month, for example bmc_paiements_2026-09.xml."""
    return f'bmc_paiements_{month_start:%Y-%m}.xml'


def add_pain_child(parent: etree._Element, name: str, text: Optional[str] = None) -> etree._Element:
    """Add an element of the pain.001 message to its parent."""
    return add_child(parent=parent, tag=f'{{{PAIN_NAMESPACE}}}{name}', text=text)


def add_account(parent: etree._Element, name: str, iban: str) -> None:
    """Add the account of the debtor or of a creditor, named by its IBAN."""
    account = add_pain_child(parent=parent, name=name)
    account_id = add_pain_child(parent=account, name='Id')
    add_pain_child(parent=account_id, name='IBAN', text=iban)


def add_transfer(parent: etree._Element, line: ReportLine, reference: str, message: str) -> None:
    """Add the credit transfer to one worker."""
    transfer = add_pain_child(parent=parent, name='CdtTrfTxInf')
    payment_id = add_pain_child(parent=transfer, name='PmtId')
    add_pain_child(parent=payment_id, name='EndToEndId', text=reference)
    amount = add_pain_child(parent=transfer, name='Amt')
    instructed_amount = add_pain_child(parent=amount, name='InstdAmt', text=f'{line.amount:.2f}')
    instructed_amount.set('Ccy', 'EUR')
    creditor = add_pain_child(parent=transfer, name='Cdtr')
    creditor_name = clean_sepa_text(text=line.worker_name, max_length=MAX_NAME_LENGTH)
    add_pain_child(parent=creditor, name='Nm', text=creditor_name)
    add_account(parent=transfer, name='CdtrAcct', iban=line.iban)
    remittance = add_pain_child(parent=transfer, name='RmtInf')
    add_pain_child(parent=remittance, name='Ustrd', text=message)


def build_payment_file(
    lines: list[ReportLine],
    organisation: OrganisationForm,
    month_start: date,
    created_at: datetime,
) -> bytes:
    """Build the SEPA pain.001 file that pays the amounts due of one month (R13.2).

    Workers without an amount due are left out. The payments are asked for the day the file
    is made, as one bulk (one debit on BMC's account). The file is checked against the ISO
    20022 schema before it is given.
    """
    payable_lines = find_payable_lines(lines=lines)
    if find_payment_file_problem(lines=lines, organisation=organisation) is not None:
        raise ValueError('The payment file cannot be built.')
    n_payments = str(len(payable_lines))
    total = sum((line.amount for line in payable_lines), start=Decimal('0'))
    control_sum = f'{total:.2f}'
    message_id = f'BMC-{created_at:%Y%m%d%H%M%S}'
    organisation_name = clean_sepa_text(text=organisation.name, max_length=MAX_NAME_LENGTH)
    month_name = format_month(year=month_start.year, month=month_start.month)
    message = clean_sepa_text(
        text=f'{organisation.name} {month_name}',
        max_length=MAX_MESSAGE_LENGTH,
    )

    # The header of the message
    root = etree.Element(f'{{{PAIN_NAMESPACE}}}Document', nsmap={None: PAIN_NAMESPACE})
    initiation = add_pain_child(parent=root, name='CstmrCdtTrfInitn')
    header = add_pain_child(parent=initiation, name='GrpHdr')
    add_pain_child(parent=header, name='MsgId', text=message_id)
    add_pain_child(parent=header, name='CreDtTm', text=f'{created_at:%Y-%m-%dT%H:%M:%S}')
    add_pain_child(parent=header, name='NbOfTxs', text=n_payments)
    add_pain_child(parent=header, name='CtrlSum', text=control_sum)
    initiating_party = add_pain_child(parent=header, name='InitgPty')
    add_pain_child(parent=initiating_party, name='Nm', text=organisation_name)

    # The bulk: BMC as debtor
    bulk = add_pain_child(parent=initiation, name='PmtInf')
    add_pain_child(parent=bulk, name='PmtInfId', text=f'{message_id}-1')
    add_pain_child(parent=bulk, name='PmtMtd', text='TRF')
    add_pain_child(parent=bulk, name='BtchBookg', text='true')
    add_pain_child(parent=bulk, name='NbOfTxs', text=n_payments)
    add_pain_child(parent=bulk, name='CtrlSum', text=control_sum)
    payment_type = add_pain_child(parent=bulk, name='PmtTpInf')
    service_level = add_pain_child(parent=payment_type, name='SvcLvl')
    add_pain_child(parent=service_level, name='Cd', text='SEPA')
    execution_date = add_pain_child(parent=bulk, name='ReqdExctnDt')
    add_pain_child(parent=execution_date, name='Dt', text=f'{created_at:%Y-%m-%d}')
    debtor = add_pain_child(parent=bulk, name='Dbtr')
    add_pain_child(parent=debtor, name='Nm', text=organisation_name)
    add_account(parent=bulk, name='DbtrAcct', iban=organisation.iban)
    debtor_agent = add_pain_child(parent=bulk, name='DbtrAgt')
    institution = add_pain_child(parent=debtor_agent, name='FinInstnId')
    other_id = add_pain_child(parent=institution, name='Othr')
    add_pain_child(parent=other_id, name='Id', text=BANK_NOT_PROVIDED)
    add_pain_child(parent=bulk, name='ChrgBr', text='SLEV')

    # One credit transfer per worker
    for position, line in enumerate(payable_lines, start=1):
        reference = f'BMC-{month_start:%Y-%m}-{position:03d}'
        add_transfer(parent=bulk, line=line, reference=reference, message=message)

    payment_file = write_checked_xml(root=root, schema_file_name=PAIN_SCHEMA_FILE)
    logger.info(f'Payment file of {month_start:%Y-%m} built: {n_payments} payments.')
    return payment_file
