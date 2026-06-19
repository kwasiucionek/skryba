from .custom_fields import FieldSpec, extract_custom_fields
from .extractor import extract_metadata
from .schemas import DocumentType, ExtractedMetadata

__all__ = [
    "extract_metadata",
    "extract_custom_fields",
    "FieldSpec",
    "DocumentType",
    "ExtractedMetadata",
]
