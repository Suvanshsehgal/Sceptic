"""
Language-Agnostic Fact-Checker Agent.
Delegates deterministic API and call verification to language-specific adapters.
No longer assumes Python AST, inspect(), or dir() directly.
"""
import os
import sys
from typing import List, Dict, Any, Optional

# Ensure paths
sys.path.insert(0, os.path.dirname(__file__))

from languages.detector import LanguageDetector
from languages.base import LanguageAdapterRegistry
from languages.models import (
    ParsedCodeFile,
    NormalizedFinding,
    VerificationStatus,
    FindingSeverity
)


class FactCheckerAgent:
    """
    Language-Agnostic Fact-Checker Agent.
    
    Architecture:
    Fact Checker
        ↓
    Language Detection
        ↓
    Language Adapter Registry
        ↓
    Language Adapter (Python / Java / JS / TS)
        ↓
    Deterministic Verification
        ↓
    Normalized Findings
    """
    def __init__(self):
        self.detector = LanguageDetector()

    def analyze_code(
        self,
        source_code: str,
        file_path: str = "target.py",
        language: Optional[str] = None,
        project_context: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Analyzes source code deterministically using the appropriate language adapter.
        Returns a list of structured, normalized findings.
        """
        # 1. Detect language if not explicitly provided
        detected_lang = language or self.detector.detect_file_language(file_path)
        if not detected_lang:
            # Fallback heuristic: check if file has python-like or js-like content, default python
            detected_lang = "python"

        # 2. Lookup Adapter from Registry
        adapter = LanguageAdapterRegistry.get_adapter(detected_lang)
        if not adapter:
            return [
                NormalizedFinding(
                    agent_name="Fact-Checker",
                    severity=FindingSeverity.INFO.value,
                    status=VerificationStatus.UNSUPPORTED.value,
                    title=f"Unsupported Language: {detected_lang}",
                    description=f"No verification adapter registered for language '{detected_lang}'.",
                    file_path=file_path,
                    line_number=1,
                    evidence={"language": detected_lang, "status": "UNSUPPORTED"},
                    recommendation=f"Add a LanguageAdapter for '{detected_lang}' to enable verification."
                ).to_dict()
            ]

        # 3. Parse code using adapter
        parsed_file = adapter.parse_code(source_code, file_path=file_path)

        # 4. Perform deterministic verification
        findings = adapter.verify_api_usage(parsed_file, project_context=project_context)

        return [f.to_dict() for f in findings]


# Backwards compatibility helper function
_default_agent = FactCheckerAgent()

def analyze_code(
    source_code: str,
    file_path: str = "target.py",
    language: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Backwards-compatible API entrypoint for fact_checker.py.
    Used by orchestrator, CLI, and legacy tests.
    """
    return _default_agent.analyze_code(source_code, file_path=file_path, language=language)
