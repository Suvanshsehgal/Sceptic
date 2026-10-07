"""
Universal models and data structures for language-agnostic code analysis.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Any, Optional


class VerificationStatus(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    UNRESOLVED = "UNRESOLVED"
    ERROR = "ERROR"
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"


class FindingSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


@dataclass
class CodeParameter:
    name: str
    type_annotation: Optional[str] = None
    default_value: Optional[str] = None
    is_required: bool = True
    is_vararg: bool = False
    is_kwarg: bool = False


@dataclass
class CodeFunction:
    name: str
    file_path: str
    line_number: int
    parameters: List[CodeParameter] = field(default_factory=list)
    return_type: Optional[str] = None
    docstring: Optional[str] = None
    language: str = "unknown"
    is_method: bool = False
    class_name: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CodeClass:
    name: str
    file_path: str
    line_number: int
    superclasses: List[str] = field(default_factory=list)
    methods: List[CodeFunction] = field(default_factory=list)
    language: str = "unknown"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CodeImport:
    module: str
    name: Optional[str] = None
    alias: Optional[str] = None
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    is_wildcard: bool = False


@dataclass
class CodeCall:
    callee_name: str
    caller: Optional[str] = None
    module_or_class: Optional[str] = None
    arguments: List[str] = field(default_factory=list)
    keyword_arguments: Dict[str, str] = field(default_factory=dict)
    file_path: str = ""
    line_number: int = 1
    language: str = "unknown"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NormalizedFinding:
    agent_name: str
    severity: str
    status: str
    title: str
    description: str
    file_path: str
    line_number: Optional[int] = None
    evidence: Dict[str, Any] = field(default_factory=dict)
    recommendation: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "severity": self.severity,
            "status": self.status,
            "title": self.title,
            "description": self.description,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "evidence": self.evidence,
            "recommendation": self.recommendation
        }


@dataclass
class ParsedCodeFile:
    file_path: str
    language: str
    source_code: str
    functions: List[CodeFunction] = field(default_factory=list)
    classes: List[CodeClass] = field(default_factory=list)
    imports: List[CodeImport] = field(default_factory=list)
    calls: List[CodeCall] = field(default_factory=list)
    syntax_errors: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CodeProject:
    root_path: str
    languages: List[Dict[str, Any]] = field(default_factory=list)
    files: List[ParsedCodeFile] = field(default_factory=list)
    dependencies: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
