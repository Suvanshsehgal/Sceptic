"""
Repository and file language detection component.
Inspects projects, directories, and files to detect programming languages.
"""
import os
from pathlib import Path
from typing import Dict, Any, List, Set, Optional

DEFAULT_IGNORED_DIRS: Set[str] = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "dist",
    "build",
    "target",
    "coverage",
    ".idea",
    ".vscode",
    ".next",
    ".nuxt",
    "out",
    "bin",
    "obj"
}

EXTENSION_MAP: Dict[str, str] = {
    ".py": "python",
    ".java": "java",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
}


class LanguageDetector:
    """
    Detects programming languages present in files or directories.
    """
    def __init__(self, ignored_dirs: Optional[Set[str]] = None):
        self.ignored_dirs = set(ignored_dirs) if ignored_dirs is not None else set(DEFAULT_IGNORED_DIRS)

    def detect_file_language(self, file_path: str) -> Optional[str]:
        """
        Detects the language of a single file from its file extension.
        """
        path = Path(file_path)
        ext = path.suffix.lower()
        return EXTENSION_MAP.get(ext)

    def detect_languages(self, target_path: str) -> Dict[str, Any]:
        """
        Inspects a file or directory and returns structured language statistics.
        Returns:
            {
                "languages": [
                    {"name": "python", "files": 12},
                    {"name": "typescript", "files": 8}
                ],
                "primary_language": "python",
                "total_files": 20
            }
        """
        path_obj = Path(target_path).resolve()
        counts: Dict[str, int] = {}
        file_lists: Dict[str, List[str]] = {}

        if not path_obj.exists():
            return {
                "languages": [],
                "primary_language": None,
                "total_files": 0
            }

        if path_obj.is_file():
            lang = self.detect_file_language(str(path_obj))
            if lang:
                counts[lang] = 1
                file_lists[lang] = [str(path_obj)]
        else:
            for root, dirs, files in os.walk(path_obj):
                # Filter ignored directories in-place
                dirs[:] = [
                    d for d in dirs
                    if d not in self.ignored_dirs and not d.startswith(".")
                ]
                for file in files:
                    ext = Path(file).suffix.lower()
                    lang = EXTENSION_MAP.get(ext)
                    if lang:
                        counts[lang] = counts.get(lang, 0) + 1
                        file_lists.setdefault(lang, []).append(os.path.join(root, file))

        languages_summary = [
            {"name": lang, "files": count}
            for lang, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)
        ]

        primary = languages_summary[0]["name"] if languages_summary else None
        total = sum(counts.values())

        return {
            "languages": languages_summary,
            "primary_language": primary,
            "total_files": total,
            "file_lists": file_lists
        }
