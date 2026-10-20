"""Checking generated XML files against their official schema (R13.2, R14.4).

The schemas are stored with the code, in the folder schemas, unmodified.
"""

import functools
from pathlib import Path
from typing import Optional

from lxml import etree

SCHEMA_FOLDER = Path(__file__).parent / 'schemas'


@functools.cache
def load_schema(file_name: str) -> etree.XMLSchema:
    """Read a schema of the folder schemas; kept in memory, because reading one takes a while."""
    schema_path = SCHEMA_FOLDER / file_name
    schema_document = etree.parse(source=schema_path)
    return etree.XMLSchema(etree=schema_document)


def add_child(parent: etree._Element, tag: str, text: Optional[str] = None) -> etree._Element:
    """Add a child element to an element, with its text when there is one."""
    child = etree.SubElement(parent, tag)
    child.text = text
    return child


def write_checked_xml(root: etree._Element, schema_file_name: str) -> bytes:
    """Give an XML document as UTF-8 bytes, after checking it against its schema.

    A document that does not follow the schema is a programming error and never leaves the
    application: a ValueError is raised instead. The message names the element, not its
    content, so no personal data reaches the logs (R3.5).
    """
    schema = load_schema(file_name=schema_file_name)
    if not schema.validate(root):
        error = schema.error_log[0]
        raise ValueError(
            f'XML does not follow {schema_file_name}, line {error.line}: {error.type_name}.'
        )
    return etree.tostring(root, xml_declaration=True, encoding='UTF-8', pretty_print=True)
