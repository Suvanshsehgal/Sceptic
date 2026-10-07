"""
Abstract base class and registry for language adapters.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Type
from languages.models import (
    ParsedCodeFile,
    NormalizedFinding,
    VerificationStatus
)


class LanguageAdapter(ABC):
    """
    Common abstraction for language-specific analysis, parsing, and verification.
    """
    @property
    @abstractmethod
    def language_name(self) -> str:
        """Normalized language identifier (e.g. 'python', 'java', 'javascript', 'typescript')."""
        pass

    @property
    @abstractmethod
    def supported_extensions(self) -> List[str]:
        """File extensions handled by this adapter (e.g. ['.py'])."""
        pass

    @property
    @abstractmethod
    def testing_framework(self) -> str:
        """Default unit testing framework for this language (e.g. 'pytest', 'JUnit', 'Jest')."""
        pass

    @property
    @abstractmethod
    def capabilities(self) -> Dict[str, bool]:
        """
        Reports supported features:
        {
            "parsing": True,
            "api_verification": True,
            "dependency_inspection": True,
            "security_analysis": True,
            "test_execution": False
        }
        """
        pass

    @abstractmethod
    def parse_code(self, source_code: str, file_path: str = "target") -> ParsedCodeFile:
        """
        Parses source code into universal ParsedCodeFile representation.
        """
        pass

    @abstractmethod
    def verify_api_usage(
        self,
        parsed_file: ParsedCodeFile,
        project_context: Optional[Dict[str, Any]] = None
    ) -> List[NormalizedFinding]:
        """
        Performs deterministic API/function/method usage verification.
        Must return normalized findings.
        """
        pass

    def inspect_dependencies(self, project_path: str) -> Dict[str, str]:
        """
        Inspects project dependency metadata where available (e.g. package.json, pom.xml).
        """
        return {}


class LanguageAdapterRegistry:
    """
    Registry for discovering and managing LanguageAdapter implementations.
    """
    _adapters: Dict[str, LanguageAdapter] = {}

    @classmethod
    def register(cls, adapter: LanguageAdapter) -> None:
        cls._adapters[adapter.language_name.lower()] = adapter

    @classmethod
    def get_adapter(cls, language: str) -> Optional[LanguageAdapter]:
        return cls._adapters.get(language.lower())

    @classmethod
    def get_adapter_for_extension(cls, extension: str) -> Optional[LanguageAdapter]:
        ext = extension.lower() if extension.startswith(".") else f".{extension.lower()}"
        for adapter in cls._adapters.values():
            if ext in adapter.supported_extensions:
                return adapter
        return None

    @classmethod
    def list_supported_languages(cls) -> List[str]:
        return sorted(list(cls._adapters.keys()))

    @classmethod
    def get_all_adapters(cls) -> Dict[str, LanguageAdapter]:
        return dict(cls._adapters)
