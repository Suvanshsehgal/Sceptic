import ast
import inspect
import importlib
import builtins
from typing import List, Dict, Any, Optional

class FactCheckerFinding:
    def __init__(self, severity: str, type: str, title: str, description: str, line_number: int, api_name: str):
        self.agent_name = "Fact-Checker"
        self.severity = severity
        self.type = type # VALID, INVALID, UNRESOLVED
        self.title = title
        self.description = description
        self.line_number = line_number
        self.api_name = api_name
        self.evidence = f"Line {line_number}: {description}"

    def to_dict(self):
        return {
            "agent_name": self.agent_name,
            "severity": self.severity,
            "status": self.type,
            "title": self.title,
            "description": self.description,
            "line_number": self.line_number,
            "evidence": self.evidence
        }

class APIChecker(ast.NodeVisitor):
    def __init__(self):
        self.findings: List[FactCheckerFinding] = []
        self.imports: Dict[str, str] = {} # alias -> module_name
        
    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            name = alias.asname if alias.asname else alias.name
            self.imports[name] = alias.name
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.module:
            for alias in node.names:
                name = alias.asname if alias.asname else alias.name
                self.imports[name] = f"{node.module}.{alias.name}"
        self.generic_visit(node)

    def _resolve_name(self, node: ast.expr) -> Optional[str]:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            base = self._resolve_name(node.value)
            if base:
                return f"{base}.{node.attr}"
        return None

    def visit_Call(self, node: ast.Call):
        api_name = self._resolve_name(node.func)
        
        if not api_name:
            raw_name = "unknown_call"
            if isinstance(node.func, ast.Attribute):
                raw_name = f"*.{node.func.attr}"
                
            self.findings.append(FactCheckerFinding(
                severity="INFO",
                type="UNRESOLVED",
                title="Unresolved Dynamic Call",
                description=f"Cannot statically resolve call to '{raw_name}'.",
                line_number=node.lineno,
                api_name=raw_name
            ))
            self.generic_visit(node)
            return

        parts = api_name.split('.')
        base_name = parts[0]
        
        resolved_full_path = api_name
        if base_name in self.imports:
            import_path = self.imports[base_name]
            if len(parts) > 1:
                resolved_full_path = f"{import_path}.{'.'.join(parts[1:])}"
            else:
                resolved_full_path = import_path
        elif hasattr(builtins, base_name):
            resolved_full_path = f"builtins.{api_name}"
            
        resolved_parts = resolved_full_path.split('.')
        
        target_obj = None
        
        for i in range(len(resolved_parts), 0, -1):
            mod_candidate = ".".join(resolved_parts[:i])
            try:
                mod = importlib.import_module(mod_candidate)
                target_obj = mod
                
                attr_parts = resolved_parts[i:]
                for attr in attr_parts:
                    if hasattr(target_obj, attr):
                        target_obj = getattr(target_obj, attr)
                    else:
                        target_obj = None
                        break
                if target_obj is not None:
                    break
            except ImportError:
                continue

        if not target_obj:
            if base_name in self.imports or hasattr(builtins, base_name) or base_name in ['os', 'sys', 'json', 're']:
                self.findings.append(FactCheckerFinding(
                    severity="HIGH",
                    type="INVALID",
                    title="Non-existent API",
                    description=f"The API '{api_name}' does not exist in the installed environment.",
                    line_number=node.lineno,
                    api_name=api_name
                ))
            else:
                title = "Unresolved Import" if api_name == base_name else "Unresolved Dynamic Call"
                self.findings.append(FactCheckerFinding(
                    severity="INFO",
                    type="UNRESOLVED",
                    title=title,
                    description=f"Cannot resolve module or object for '{api_name}'.",
                    line_number=node.lineno,
                    api_name=api_name
                ))
            self.generic_visit(node)
            return

        if not callable(target_obj):
            self.findings.append(FactCheckerFinding(
                severity="HIGH",
                type="INVALID",
                title="Not Callable",
                description=f"'{api_name}' is not callable.",
                line_number=node.lineno,
                api_name=api_name
            ))
            self.generic_visit(node)
            return
            
        try:
            sig = inspect.signature(target_obj)
        except ValueError:
            self.findings.append(FactCheckerFinding(
                severity="INFO",
                type="UNRESOLVED",
                title="Cannot inspect signature",
                description=f"Signature for '{api_name}' is not introspectable.",
                line_number=node.lineno,
                api_name=api_name
            ))
            self.generic_visit(node)
            return
            
        valid = True
        provided_kwargs = [kw.arg for kw in node.keywords if kw.arg is not None]
        
        for kw in provided_kwargs:
            if kw not in sig.parameters:
                has_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
                if not has_kwargs:
                    self.findings.append(FactCheckerFinding(
                        severity="MEDIUM",
                        type="INVALID",
                        title="Invalid Keyword Parameter",
                        description=f"Parameter '{kw}' does not exist in '{api_name}'.",
                        line_number=node.lineno,
                        api_name=api_name
                    ))
                    valid = False
                    
        provided_args = len(node.args)
        required_params = [p.name for p in sig.parameters.values() if p.default == inspect.Parameter.empty and p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)]
        
        unmet_required = [p for p in required_params if p not in provided_kwargs]
        
        if len(unmet_required) > provided_args:
            has_varargs = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in sig.parameters.values())
            if not has_varargs:
                missing = unmet_required[provided_args:]
                self.findings.append(FactCheckerFinding(
                    severity="HIGH",
                    type="INVALID",
                    title="Missing Required Parameter",
                    description=f"Missing required parameter(s): {', '.join(missing)} for '{api_name}'.",
                    line_number=node.lineno,
                    api_name=api_name
                ))
                valid = False

        if valid:
            self.findings.append(FactCheckerFinding(
                severity="INFO",
                type="VALID",
                title="Valid API Usage",
                description=f"API '{api_name}' and its arguments are valid.",
                line_number=node.lineno,
                api_name=api_name
            ))

        self.generic_visit(node)

def analyze_code(source_code: str) -> List[Dict]:
    try:
        tree = ast.parse(source_code)
    except SyntaxError as e:
        return [FactCheckerFinding("CRITICAL", "INVALID", "Syntax Error", str(e), e.lineno or 1, "syntax").to_dict()]
        
    checker = APIChecker()
    checker.visit(tree)
    return [f.to_dict() for f in checker.findings]
