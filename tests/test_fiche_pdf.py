"""The fiche 281.27 as a PDF (R14.2)."""

import io
from decimal import Decimal

from pypdf import PdfReader

from dimonapp.fiche_pdf import build_fiche_pdf
from dimonapp.french import NO_BREAK_SPACE
from factories import build_fiche_line, build_organisation_form


def read_pdf_text(content: bytes) -> str:
    """Give the text of a PDF, with ordinary spaces."""
    reader = PdfReader(io.BytesIO(content))
    pages = [page.extract_text() for page in reader.pages]
    return '\n'.join(pages).replace(NO_BREAK_SPACE, ' ')


def test_r14_2_fiche_pdf_holds_the_boxes_of_the_281_27() -> None:
    """The debtor, the worker, the national number, the amount and the hours per quarter."""
    content = build_fiche_pdf(
        line=build_fiche_line(),
        organisation=build_organisation_form(),
        year=2025,
        sequence_number=7,
    )

    text = read_pdf_text(content=content)
    assert content.startswith(b'%PDF')
    assert 'FICHE N° 281.27 - ANNÉE 2025' in text
    assert "Revenus des activités d'association" in text
    assert '1. N° : 7' in text
    assert 'Brussels Monkeys Climbing ASBL' in text
    assert "Numéro d'entreprise (BCE) : 0123.456.789" in text
    assert 'Peeters Lotte' in text
    assert 'Rue Imaginaire 12' in text
    assert '1050 Ixelles' in text
    assert 'N° national : 85.07.30-033.28' in text
    assert 'pour des prestations effectuées en 2025' in text
    assert '1 234,50 €' in text
    assert 'A (secteur sportif)' in text
    assert '10,5 h' in text
    assert '3 h' in text


def test_r14_2_fiche_pdf_accepts_names_outside_western_europe() -> None:
    """A name with letters the standard PDF fonts do not know is printed as it is."""
    line = build_fiche_line(first_name='Michaël', last_name='Łukasz', amount=Decimal('60'))

    content = build_fiche_pdf(
        line=line,
        organisation=build_organisation_form(),
        year=2025,
        sequence_number=1,
    )

    assert 'Łukasz Michaël' in read_pdf_text(content=content)
