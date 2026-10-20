"""The fiche 281.27 of one worker as a PDF, to hand to the worker (R14.2).

The fiche follows the boxes and their numbers of the model of FOD Financiën (Belcotax-on-web
brochure, record 281.27), in French. Nothing here is logged (R3.5).
"""

from decimal import Decimal
from pathlib import Path

from fpdf import FPDF

from dimonapp.activities import QUARTERS
from dimonapp.configuration import OrganisationForm
from dimonapp.fiche_lines import FicheLine
from dimonapp.french import format_amount, format_hours
from dimonapp.models import Period
from dimonapp.national_register import format_national_register_number

# A font with every accent and alphabet a name can hold; the standard PDF fonts only know
# Western European characters.
FONT_FOLDER = Path(__file__).parent / 'assets' / 'fonts'
FONT_FAMILY = 'DejaVu'
FONT_FILES = {'': 'DejaVuSans.ttf', 'B': 'DejaVuSans-Bold.ttf'}

FICHE_TITLE = 'FICHE N° 281.27'
FICHE_SUBTITLE = "Revenus des activités d'association"
SECTOR_TEXT = 'A (secteur sportif)'
COUNTRY_TEXT = 'Belgique'
QUARTER_LABELS = {
    Period.Q1: '1er trimestre',
    Period.Q2: '2ème trimestre',
    Period.Q3: '3ème trimestre',
    Period.Q4: '4ème trimestre',
}
LABEL_WIDTH = 120
LINE_HEIGHT = 6
BOX_SPACE = 4


def write_heading(pdf: FPDF, text: str) -> None:
    """Write the heading of a numbered box, in bold, after some space."""
    pdf.ln(h=BOX_SPACE)
    pdf.set_font(family=FONT_FAMILY, style='B', size=10)
    pdf.cell(w=0, h=LINE_HEIGHT, text=text, new_x='LMARGIN', new_y='NEXT')
    pdf.set_font(family=FONT_FAMILY, style='', size=10)


def write_line(pdf: FPDF, text: str) -> None:
    """Write one line of text."""
    pdf.cell(w=0, h=LINE_HEIGHT, text=text, new_x='LMARGIN', new_y='NEXT')


def write_value(pdf: FPDF, label: str, value: str) -> None:
    """Write a label with its value, the value aligned to the right."""
    pdf.cell(w=LABEL_WIDTH, h=LINE_HEIGHT, text=label)
    pdf.cell(w=0, h=LINE_HEIGHT, text=value, align='R', new_x='LMARGIN', new_y='NEXT')


def build_fiche_pdf(
    line: FicheLine,
    organisation: OrganisationForm,
    year: int,
    sequence_number: int,
) -> bytes:
    """Build the fiche 281.27 of one worker for one income year (R14.2).

    The number of the fiche is the one it has in the Belcotax file. Everything was earned in
    the income year itself; the other amounts of the model are zero.
    """
    zero_amount = format_amount(amount=Decimal('0'))
    amount = format_amount(amount=line.amount)
    national_register_number = format_national_register_number(
        number=line.national_register_number,
    )
    pdf = FPDF(format='A4')
    for style in FONT_FILES:
        pdf.add_font(family=FONT_FAMILY, style=style, fname=FONT_FOLDER / FONT_FILES[style])
    pdf.set_title(title=f'{FICHE_TITLE} - {year}')
    pdf.add_page()

    # The title
    pdf.set_font(family=FONT_FAMILY, style='B', size=14)
    write_line(pdf=pdf, text=f'{FICHE_TITLE} - ANNÉE {year}')
    pdf.set_font(family=FONT_FAMILY, style='', size=11)
    write_line(pdf=pdf, text=FICHE_SUBTITLE)

    # Who pays and who receives
    write_heading(pdf=pdf, text=f'1. N° : {sequence_number}')
    write_heading(pdf=pdf, text='3. Nom et adresse du débiteur des revenus')
    write_line(pdf=pdf, text=organisation.name)
    write_line(pdf=pdf, text=organisation.address)
    write_line(pdf=pdf, text=f'{organisation.postal_code} {organisation.city}')
    write_line(pdf=pdf, text=f"Numéro d'entreprise (BCE) : {organisation.company_number}")
    write_heading(pdf=pdf, text='4. Destinataire : bénéficiaire des revenus')
    write_line(pdf=pdf, text=f'{line.last_name} {line.first_name}')
    write_line(pdf=pdf, text=line.street)
    write_line(pdf=pdf, text=f'{line.postal_code} {line.city}')
    write_line(pdf=pdf, text=COUNTRY_TEXT)
    write_heading(pdf=pdf, text="5. N° d'identification")
    write_line(pdf=pdf, text=f'N° national : {national_register_number}')

    # The amounts
    write_heading(pdf=pdf, text='6. Montant brut des rétributions')
    write_value(pdf=pdf, label=f'pour des prestations effectuées en {year}', value=amount)
    previous_years_label = 'pour des prestations effectuées les années antérieures'
    write_value(pdf=pdf, label=previous_years_label, value=zero_amount)
    pdf.set_font(family=FONT_FAMILY, style='B', size=10)
    write_value(pdf=pdf, label='TOTAL', value=amount)
    write_heading(
        pdf=pdf,
        text="7. Indemnités reçues en réparation d'une perte temporaire de revenus",
    )
    write_value(pdf=pdf, label='', value=zero_amount)
    write_heading(pdf=pdf, text="8. Frais propres à l'employeur remboursés")
    write_value(pdf=pdf, label='', value=zero_amount)

    # The hours
    write_heading(pdf=pdf, text="9. Nombre d'heures prestées par trimestre")
    write_value(pdf=pdf, label='Secteur', value=SECTOR_TEXT)
    for quarter in QUARTERS:
        hours = format_hours(hours=line.quarter_hours[quarter])
        write_value(pdf=pdf, label=QUARTER_LABELS[quarter], value=hours)
    return bytes(pdf.output())
