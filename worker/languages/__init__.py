"""
Languages package initialization.
Registers all default language adapters into LanguageAdapterRegistry.
"""
from languages.models import (
    CodeParameter,
    CodeFunction,
    CodeClass,
    CodeImport,
    CodeCall,
    ParsedCodeFile,
    CodeProject,
    NormalizedFinding,
    VerificationStatus,
    FindingSeverity
)
from languages.detector import LanguageDetector
from languages.base import LanguageAdapter, LanguageAdapterRegistry
from languages.universal_parser import UniversalParser
from languages.python_adapter import PythonAdapter
from languages.java_adapter import JavaAdapter
from languages.js_ts_adapter import JavaScriptAdapter, TypeScriptAdapter

# Automatically register initial adapters
LanguageAdapterRegistry.register(PythonAdapter())
LanguageAdapterRegistry.register(JavaAdapter())
LanguageAdapterRegistry.register(JavaScriptAdapter())
LanguageAdapterRegistry.register(TypeScriptAdapter())

__all__ = [
    "CodeParameter",
    "CodeFunction",
    "CodeClass",
    "CodeImport",
    "CodeCall",
    "ParsedCodeFile",
    "CodeProject",
    "NormalizedFinding",
    "VerificationStatus",
    "FindingSeverity",
    "LanguageDetector",
    "LanguageAdapter",
    "LanguageAdapterRegistry",
    "UniversalParser",
    "PythonAdapter",
    "JavaAdapter",
    "JavaScriptAdapter",
    "TypeScriptAdapter"
]
