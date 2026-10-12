"""Reversible spreadsheet-safe text encoding for our exported input templates."""

ENCODING_COLUMN = "_freight_encoding"
ENCODING_VERSION = "apostrophe-v1"


def safe_cell(value: object) -> object:
    if isinstance(value, str) and (
        value.startswith(("'", "\t", "\r", "\n")) or value.lstrip().startswith(("=", "+", "-", "@"))
    ):
        return "'" + value
    return value


def decode_cell(value: str) -> str:
    if value.startswith("'") and safe_cell(value[1:]) == value:
        return value[1:]
    return value
