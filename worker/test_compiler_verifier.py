import os
import tempfile

import pytest

import compiler_verifier

pytestmark = pytest.mark.skipif(not compiler_verifier._tsc_available(), reason="tsc is not installed")


def _titles(findings):
    return [f["title"] for f in findings]


def test_tsx_file_with_jsx_is_parsed_as_tsx():
    source = (
        "import React from 'react';\n"
        "export const Hello = (props: { name: string }) => <div>{props.name}</div>;\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "Hello.tsx")
        findings = compiler_verifier.verify(source, path, "typescript")
    assert "Syntax Error" not in _titles(findings)


def test_one_broken_token_is_reported_once_not_as_a_cascade():
    source = "export function broken(a: number {\n  return a;\n}\nexport const x = [1, 2,\n"
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "broken.ts")
        findings = compiler_verifier.verify(source, path, "typescript")
    syntax = [f for f in findings if f["title"] == "Syntax Error"]
    assert len(syntax) == 1
    assert syntax[0]["severity"] == "CRITICAL"
    assert syntax[0]["evidence"]["follow_on_syntax_errors"] >= 1


def test_relative_import_from_sibling_file_resolves():
    api = "export interface Order { id: number; total: number }\nexport function load(): Order[] { return []; }\n"
    view = (
        "import { load, Order } from '../api';\n"
        "export const total = (): number => load().reduce((sum: number, o: Order) => sum + o.total, 0);\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "src")
        os.makedirs(os.path.join(src, "components"))
        with open(os.path.join(src, "api.ts"), "w", encoding="utf-8") as f:
            f.write(api)
        path = os.path.join(src, "components", "View.tsx")
        findings = compiler_verifier.verify(view, path, "typescript")
    unresolved = [f for f in findings if f["evidence"].get("code") == "TS2307"]
    assert unresolved == []
    assert "Non-existent API" not in _titles(findings)
