"""
Multi-language parsing helper using tree-sitter.
Extracts functions, classes, imports, and calls into universal models.
"""
from typing import Dict, Any, List, Optional
import tree_sitter
import tree_sitter_python
import tree_sitter_javascript
import tree_sitter_typescript
import tree_sitter_java

from languages.models import (
    ParsedCodeFile,
    CodeFunction,
    CodeClass,
    CodeImport,
    CodeCall,
    CodeParameter
)

# Initialize tree-sitter Language instances
LANG_PYTHON = tree_sitter.Language(tree_sitter_python.language())
LANG_JAVASCRIPT = tree_sitter.Language(tree_sitter_javascript.language())
LANG_TYPESCRIPT = tree_sitter.Language(tree_sitter_typescript.language_typescript())
LANG_TSX = tree_sitter.Language(tree_sitter_typescript.language_tsx())
LANG_JAVA = tree_sitter.Language(tree_sitter_java.language())


def get_tree_sitter_parser(language: str, is_tsx: bool = False) -> tree_sitter.Parser:
    lang_key = language.lower()
    if lang_key == "python":
        return tree_sitter.Parser(LANG_PYTHON)
    elif lang_key == "javascript":
        return tree_sitter.Parser(LANG_JAVASCRIPT)
    elif lang_key == "typescript":
        return tree_sitter.Parser(LANG_TSX if is_tsx else LANG_TYPESCRIPT)
    elif lang_key == "java":
        return tree_sitter.Parser(LANG_JAVA)
    else:
        raise ValueError(f"Unsupported tree-sitter language: {language}")


class UniversalParser:
    """
    Parses source code for Python, JavaScript, TypeScript, and Java using Tree-sitter.
    Produces normalized ParsedCodeFile models.
    """
    @staticmethod
    def parse(source_code: str, language: str, file_path: str = "target") -> ParsedCodeFile:
        lang_norm = language.lower()
        is_tsx = file_path.endswith(".tsx") or file_path.endswith(".jsx")
        
        parsed = ParsedCodeFile(
            file_path=file_path,
            language=lang_norm,
            source_code=source_code
        )

        try:
            parser = get_tree_sitter_parser(lang_norm, is_tsx=is_tsx)
            source_bytes = source_code.encode("utf-8")
            tree = parser.parse(source_bytes)
        except Exception as e:
            parsed.syntax_errors.append(f"Parser initialization failed: {str(e)}")
            return parsed

        root = tree.root_node
        if root.has_error:
            # Note syntax error but proceed with best-effort AST extraction
            parsed.syntax_errors.append("Syntax error detected in source code.")

        # Walk AST
        if lang_norm == "python":
            UniversalParser._extract_python(root, source_bytes, parsed)
        elif lang_norm in ("javascript", "typescript"):
            UniversalParser._extract_js_ts(root, source_bytes, parsed)
        elif lang_norm == "java":
            UniversalParser._extract_java(root, source_bytes, parsed)

        return parsed

    @staticmethod
    def _node_text(node: tree_sitter.Node, source_bytes: bytes) -> str:
        return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

    # ========================================================
    # PYTHON EXTRACTION
    # ========================================================
    @staticmethod
    def _extract_python(root: tree_sitter.Node, source_bytes: bytes, parsed: ParsedCodeFile):
        def walk(node: tree_sitter.Node, current_class: Optional[str] = None):
            ntype = node.type

            if ntype in ("function_definition",):
                name_node = node.child_by_field_name("name")
                func_name = UniversalParser._node_text(name_node, source_bytes) if name_node else "anonymous"
                line_no = node.start_point[0] + 1

                params: List[CodeParameter] = []
                params_node = node.child_by_field_name("parameters")
                if params_node:
                    for p in params_node.children:
                        if p.type in ("identifier",):
                            p_name = UniversalParser._node_text(p, source_bytes)
                            params.append(CodeParameter(name=p_name))
                        elif p.type in ("default_parameter",):
                            p_id = p.child_by_field_name("name")
                            p_val = p.child_by_field_name("value")
                            p_name = UniversalParser._node_text(p_id, source_bytes) if p_id else "param"
                            p_val_str = UniversalParser._node_text(p_val, source_bytes) if p_val else None
                            params.append(CodeParameter(name=p_name, default_value=p_val_str, is_required=False))

                # Check docstring
                body_node = node.child_by_field_name("body")
                docstring = None
                if body_node and body_node.children:
                    first_stmt = body_node.children[0]
                    if first_stmt.type == "expression_statement" and first_stmt.children and first_stmt.children[0].type == "string":
                        docstring = UniversalParser._node_text(first_stmt.children[0], source_bytes).strip('\'"')

                code_func = CodeFunction(
                    name=func_name,
                    file_path=parsed.file_path,
                    line_number=line_no,
                    parameters=params,
                    docstring=docstring,
                    language="python",
                    is_method=current_class is not None,
                    class_name=current_class
                )
                parsed.functions.append(code_func)

            elif ntype == "class_definition":
                name_node = node.child_by_field_name("name")
                cls_name = UniversalParser._node_text(name_node, source_bytes) if name_node else "AnonymousClass"
                line_no = node.start_point[0] + 1
                cls_obj = CodeClass(
                    name=cls_name,
                    file_path=parsed.file_path,
                    line_number=line_no,
                    language="python"
                )
                parsed.classes.append(cls_obj)
                # Recurse with class context
                for child in node.children:
                    walk(child, current_class=cls_name)
                return

            elif ntype == "import_statement":
                # import foo, bar
                for child in node.children:
                    if child.type == "dotted_name":
                        mod = UniversalParser._node_text(child, source_bytes)
                        parsed.imports.append(CodeImport(module=mod, line_number=node.start_point[0] + 1))
                    elif child.type == "aliased_import":
                        name_n = child.child_by_field_name("name")
                        alias_n = child.child_by_field_name("alias")
                        mod = UniversalParser._node_text(name_n, source_bytes) if name_n else ""
                        alias = UniversalParser._node_text(alias_n, source_bytes) if alias_n else None
                        parsed.imports.append(CodeImport(module=mod, alias=alias, line_number=node.start_point[0] + 1))

            elif ntype == "import_from_statement":
                # from mod import foo as bar
                mod_node = node.child_by_field_name("module_name")
                module_name = UniversalParser._node_text(mod_node, source_bytes) if mod_node else ""
                for child in node.children:
                    if child.type == "dotted_name" and child != mod_node:
                        item_name = UniversalParser._node_text(child, source_bytes)
                        parsed.imports.append(CodeImport(module=module_name, name=item_name, line_number=node.start_point[0] + 1))
                    elif child.type == "aliased_import":
                        name_n = child.child_by_field_name("name")
                        alias_n = child.child_by_field_name("alias")
                        item_name = UniversalParser._node_text(name_n, source_bytes) if name_n else ""
                        alias = UniversalParser._node_text(alias_n, source_bytes) if alias_n else None
                        parsed.imports.append(CodeImport(module=module_name, name=item_name, alias=alias, line_number=node.start_point[0] + 1))

            elif ntype == "call":
                func_node = node.child_by_field_name("function")
                callee = UniversalParser._node_text(func_node, source_bytes) if func_node else "unknown"
                line_no = node.start_point[0] + 1
                args_node = node.child_by_field_name("arguments")
                args: List[str] = []
                kwargs: Dict[str, str] = {}
                if args_node:
                    for arg in args_node.children:
                        if arg.type == "keyword_argument":
                            k_node = arg.child_by_field_name("name")
                            v_node = arg.child_by_field_name("value")
                            k = UniversalParser._node_text(k_node, source_bytes) if k_node else ""
                            v = UniversalParser._node_text(v_node, source_bytes) if v_node else ""
                            if k:
                                kwargs[k] = v
                        elif arg.type not in ("(", ")", ","):
                            args.append(UniversalParser._node_text(arg, source_bytes))

                module_class = callee.rsplit(".", 1)[0] if "." in callee else None
                parsed.calls.append(CodeCall(
                    callee_name=callee,
                    module_or_class=module_class,
                    arguments=args,
                    keyword_arguments=kwargs,
                    file_path=parsed.file_path,
                    line_number=line_no,
                    language="python"
                ))

            for child in node.children:
                walk(child, current_class=current_class)

        walk(root)

    # ========================================================
    # JS / TS EXTRACTION
    # ========================================================
    @staticmethod
    def _extract_js_ts(root: tree_sitter.Node, source_bytes: bytes, parsed: ParsedCodeFile):
        def walk(node: tree_sitter.Node, current_class: Optional[str] = None):
            ntype = node.type

            # Function declarations & methods
            if ntype in ("function_declaration", "method_definition", "arrow_function"):
                name_node = node.child_by_field_name("name")
                func_name = UniversalParser._node_text(name_node, source_bytes) if name_node else "anonymous"
                line_no = node.start_point[0] + 1

                params: List[CodeParameter] = []
                params_node = node.child_by_field_name("parameters")
                if params_node:
                    for p in params_node.children:
                        if p.type in ("identifier", "required_parameter"):
                            p_name = UniversalParser._node_text(p, source_bytes)
                            params.append(CodeParameter(name=p_name))

                code_func = CodeFunction(
                    name=func_name,
                    file_path=parsed.file_path,
                    line_number=line_no,
                    parameters=params,
                    language=parsed.language,
                    is_method=ntype == "method_definition" or current_class is not None,
                    class_name=current_class
                )
                parsed.functions.append(code_func)

            elif ntype == "class_declaration":
                name_node = node.child_by_field_name("name")
                cls_name = UniversalParser._node_text(name_node, source_bytes) if name_node else "AnonymousClass"
                line_no = node.start_point[0] + 1
                cls_obj = CodeClass(
                    name=cls_name,
                    file_path=parsed.file_path,
                    line_number=line_no,
                    language=parsed.language
                )
                parsed.classes.append(cls_obj)
                for child in node.children:
                    walk(child, current_class=cls_name)
                return

            elif ntype == "import_statement":
                # import { a, b as c } from 'mod'; or import d from 'mod';
                source_node = node.child_by_field_name("source")
                mod_name = UniversalParser._node_text(source_node, source_bytes).strip("'\"") if source_node else ""
                line_no = node.start_point[0] + 1
                parsed.imports.append(CodeImport(module=mod_name, line_number=line_no))

            elif ntype == "call_expression":
                func_node = node.child_by_field_name("function")
                callee = UniversalParser._node_text(func_node, source_bytes) if func_node else "unknown"
                line_no = node.start_point[0] + 1
                args_node = node.child_by_field_name("arguments")
                args: List[str] = []
                if args_node:
                    for arg in args_node.children:
                        if arg.type not in ("(", ")", ","):
                            args.append(UniversalParser._node_text(arg, source_bytes))

                module_class = callee.rsplit(".", 1)[0] if "." in callee else None
                parsed.calls.append(CodeCall(
                    callee_name=callee,
                    module_or_class=module_class,
                    arguments=args,
                    file_path=parsed.file_path,
                    line_number=line_no,
                    language=parsed.language
                ))

            for child in node.children:
                walk(child, current_class=current_class)

        walk(root)

    # ========================================================
    # JAVA EXTRACTION
    # ========================================================
    @staticmethod
    def _extract_java(root: tree_sitter.Node, source_bytes: bytes, parsed: ParsedCodeFile):
        def walk(node: tree_sitter.Node, current_class: Optional[str] = None):
            ntype = node.type

            if ntype in ("method_declaration", "constructor_declaration"):
                name_node = node.child_by_field_name("name")
                method_name = UniversalParser._node_text(name_node, source_bytes) if name_node else "method"
                line_no = node.start_point[0] + 1

                params: List[CodeParameter] = []
                params_node = node.child_by_field_name("parameters")
                if params_node:
                    for p in params_node.children:
                        if p.type == "formal_parameter":
                            p_type_node = p.child_by_field_name("type")
                            p_name_node = p.child_by_field_name("name")
                            p_type = UniversalParser._node_text(p_type_node, source_bytes) if p_type_node else None
                            p_name = UniversalParser._node_text(p_name_node, source_bytes) if p_name_node else "arg"
                            params.append(CodeParameter(name=p_name, type_annotation=p_type))

                type_node = node.child_by_field_name("type")
                ret_type = UniversalParser._node_text(type_node, source_bytes) if type_node else None

                code_func = CodeFunction(
                    name=method_name,
                    file_path=parsed.file_path,
                    line_number=line_no,
                    parameters=params,
                    return_type=ret_type,
                    language="java",
                    is_method=True,
                    class_name=current_class
                )
                parsed.functions.append(code_func)

            elif ntype in ("class_declaration", "interface_declaration", "enum_declaration"):
                name_node = node.child_by_field_name("name")
                cls_name = UniversalParser._node_text(name_node, source_bytes) if name_node else "AnonymousClass"
                line_no = node.start_point[0] + 1
                cls_obj = CodeClass(
                    name=cls_name,
                    file_path=parsed.file_path,
                    line_number=line_no,
                    language="java"
                )
                parsed.classes.append(cls_obj)
                for child in node.children:
                    walk(child, current_class=cls_name)
                return

            elif ntype == "import_declaration":
                # import java.util.List; or import static ...
                text = UniversalParser._node_text(node, source_bytes).replace("import", "").replace("static", "").replace(";", "").strip()
                line_no = node.start_point[0] + 1
                parsed.imports.append(CodeImport(module=text, line_number=line_no))

            elif ntype == "method_invocation":
                name_node = node.child_by_field_name("name")
                object_node = node.child_by_field_name("object")
                method_name = UniversalParser._node_text(name_node, source_bytes) if name_node else "unknown"
                obj_name = UniversalParser._node_text(object_node, source_bytes) if object_node else None
                full_callee = f"{obj_name}.{method_name}" if obj_name else method_name
                line_no = node.start_point[0] + 1

                args_node = node.child_by_field_name("arguments")
                args: List[str] = []
                if args_node:
                    for arg in args_node.children:
                        if arg.type not in ("(", ")", ","):
                            args.append(UniversalParser._node_text(arg, source_bytes))

                parsed.calls.append(CodeCall(
                    callee_name=full_callee,
                    module_or_class=obj_name,
                    arguments=args,
                    file_path=parsed.file_path,
                    line_number=line_no,
                    language="java"
                ))

            for child in node.children:
                walk(child, current_class=current_class)

        walk(root)
