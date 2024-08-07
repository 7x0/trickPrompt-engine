import os
import simplejson
from typing import Dict
import re
from antlr4.CommonTokenStream import CommonTokenStream
from antlr4.InputStream import InputStream as ANTLRInputStream

from .parser.SolidityLexer import SolidityLexer
from .parser.SolidityParser import SolidityParser

from .sgp_visitor import SGPVisitorOptions, SGPVisitor,SolidityInfoVisitor
from .sgp_error_listener import SGPErrorListener
from .ast_node_types import SourceUnit
from .tokens import build_token_list
from .utils import string_from_snake_to_camel_case


class ParserError(Exception):
    """
    An exception raised when the parser encounters an error.            
    """

    def __init__(self, errors) -> None:
        """
        Parameters
        ----------
        errors : List[Dict[str, Any]] - A list of errors encountered by the parser.        
        """
        super().__init__()
        error = errors[0]
        self.message = f"{error['message']} ({error['line']}:{error['column']})"
        self.errors = errors


def parse(
    input_string: str,
    options: SGPVisitorOptions = SGPVisitorOptions(),
    dump_json: bool = False,
    dump_path: str = "./out",
) -> SourceUnit:
    """
    Parse a Solidity source string into an AST.

    Parameters
    ----------
    input_string : str - The Solidity source string to parse.
    options : SGPVisitorOptions - Options to pass to the parser.
    dump_json : bool - Whether to dump the AST as a JSON file.
    dump_path : str - The path to dump the AST JSON file to.

    Returns
    -------
    SourceUnit - The root of an AST of the Solidity source string.    
    """

    input_stream = ANTLRInputStream(input_string)
    lexer = SolidityLexer(input_stream)
    token_stream = CommonTokenStream(lexer)
    parser = SolidityParser(token_stream)

    listener = SGPErrorListener()
    lexer.removeErrorListeners()
    lexer.addErrorListener(listener)

    parser.removeErrorListeners()
    parser.addErrorListener(listener)
    source_unit = parser.sourceUnit()


    ast_builder = SGPVisitor(options)
    try:
        source_unit: SourceUnit = ast_builder.visit(source_unit)
    except Exception as e:
        raise Exception("AST was not generated")
    else:
        if source_unit is None:
            raise Exception("AST was not generated")

    # TODO: sort it out
    token_list = []
    if options.tokens:
        token_list = build_token_list(token_stream.getTokens(), options)

    if not options.errors_tolerant and listener.has_errors():
        raise ParserError(errors=listener.get_errors())

    if options.errors_tolerant and listener.has_errors():
        source_unit.errors = listener.get_errors()

    # TODO: sort it out
    if options.tokens:
        source_unit["tokens"] = token_list

    if dump_json:
        os.makedirs(dump_path, exist_ok=True)
        with open(os.path.join(dump_path, "ast.json"), "w") as f:
            s = simplejson.dumps(
                source_unit,
                default=lambda obj: {
                    string_from_snake_to_camel_case(k): v
                    for k, v in obj.__dict__.items()
                },
            )
            f.write(s)
    return source_unit

def find_rust_functions(text, filename,hash):
    regex = r"((?:pub(?:\s*\([^)]*\))?\s+)?fn\s+\w+(?:<[^>]*>)?\s*\([^{]*\)(?:\s*->\s*[^{]*)?\s*\{)"
    matches = re.finditer(regex, text)

    # 函数列表
    functions = []

    # 将文本分割成行，用于更容易地计算行号
    lines = text.split('\n')
    line_starts = {i: sum(len(line) + 1 for line in lines[:i]) for i in range(len(lines))}

    # 先收集所有函数体，构建完整的函数代码
    function_bodies = []
    for match in matches:
        brace_count = 1
        function_body_start = match.start()
        inside_braces = True

        for i in range(match.end(), len(text)):
            if text[i] == '{':
                brace_count += 1
            elif text[i] == '}':
                brace_count -= 1

            if inside_braces and brace_count == 0:
                function_body_end = i + 1
                function_bodies.append(text[function_body_start:function_body_end])
                break

    # 完整的函数代码字符串
    contract_code = "\n".join(function_bodies).strip()

    # 再次遍历匹配，创建函数定义
    for match in re.finditer(regex, text):
        start_line_number = next(i for i, pos in line_starts.items() if pos > match.start()) - 1
        brace_count = 1
        function_body_start = match.start()
        inside_braces = True

        for i in range(match.end(), len(text)):
            if text[i] == '{':
                brace_count += 1
            elif text[i] == '}':
                brace_count -= 1

            if inside_braces and brace_count == 0:
                function_body_end = i + 1
                # Modified part starts here
                end_line_number = next((i for i, pos in line_starts.items() if pos > function_body_end), len(lines)) - 1
                # Modified part ends here
                function_body = text[function_body_start:function_body_end]
                function_body_lines = function_body.count('\n') + 1
                visibility = 'public' if 'pub' in match.group(1) else 'private'
                functions.append({
                    'type': 'FunctionDefinition',
                    'name': 'special_'+re.search(r'\bfn\s+(\w+)', match.group(1)).group(1),
                    'start_line': start_line_number + 1,
                    'end_line': end_line_number,
                    'offset_start': 0,
                    'offset_end': 0,
                    'content': function_body,
                    'contract_name': filename.replace('.rs','_rust'+str(hash)),
                    'contract_code': contract_code,
                    'modifiers': [],
                    'stateMutability': None,
                    'returnParameters': None,
                    'visibility': visibility,
                    'node_count': function_body_lines
                })
                break

    return functions
def find_move_functions(text, filename, hash):
    # regex = r"((?:public\s+)?(?:entry\s+)?(?:native\s+)?(?:inline\s+)?fun\s+(?:<[^>]+>\s*)?(\w+)\s*(?:<[^>]+>)?\s*\([^)]*\)(?:\s*:\s*[^{]+)?(?:\s+acquires\s+[^{]+)?\s*\{)"
    regex = r"((?:public\s+)?(?:entry\s+)?(?:native\s+)?(?:inline\s+)?fun\s+(?:<[^>]+>\s*)?(\w+)\s*(?:<[^>]+>)?\s*\([^)]*\)(?:\s*:\s*[^{]+)?(?:\s+acquires\s+[^{]+)?\s*(?:\{|;))"
    matches = re.finditer(regex, text)

    functions = []
    lines = text.split('\n')
    line_starts = {i: sum(len(line) + 1 for line in lines[:i]) for i in range(len(lines))}

    function_bodies = []
    for match in matches:
        if match.group(1).strip().endswith(';'):  # native function
            function_bodies.append(match.group(1))
        else:
            brace_count = 1
            function_body_start = match.start()
            inside_braces = True

            for i in range(match.end(), len(text)):
                if text[i] == '{':
                    brace_count += 1
                elif text[i] == '}':
                    brace_count -= 1

                if inside_braces and brace_count == 0:
                    function_body_end = i + 1
                    function_bodies.append(text[function_body_start:function_body_end])
                    break

    contract_code = "\n".join(function_bodies).strip()

    for match in re.finditer(regex, text):
        start_line_number = next(i for i, pos in line_starts.items() if pos > match.start()) - 1
        
        if match.group(1).strip().endswith(';'):  # native function
            function_body = match.group(1)
            end_line_number = start_line_number
            function_body_lines = 1
        else:
            brace_count = 1
            function_body_start = match.start()
            inside_braces = True

            for i in range(match.end(), len(text)):
                if text[i] == '{':
                    brace_count += 1
                elif text[i] == '}':
                    brace_count -= 1

                if inside_braces and brace_count == 0:
                    function_body_end = i + 1
                    end_line_number = next(i for i, pos in line_starts.items() if pos > function_body_end) - 1
                    function_body = text[function_body_start:function_body_end]
                    function_body_lines = function_body.count('\n') + 1
                    break

        visibility = 'public' if 'public' in match.group(1) else 'private'
        is_native = 'native' in match.group(1)
        
        functions.append({
            'type': 'FunctionDefinition',
            'name':  'special_' + match.group(2),
            'start_line': start_line_number + 1,
            'end_line': end_line_number,
            'offset_start': 0,
            'offset_end': 0,
            'content': function_body,
            'header': match.group(1).strip(),  # 新增：函数头部
            'contract_name': filename.replace('.move', '_move' + str(hash)),
            'contract_code': contract_code,
            'modifiers': ['native'] if is_native else [],
            'stateMutability': None,
            'returnParameters': None,
            'visibility': visibility,
            'node_count': function_body_lines
        })

    return functions
import re
def find_go_functions(text, filename, hash):
    regex = r"func\s+.*\{"
    matches = re.finditer(regex, text)

    functions = []
    lines = text.split('\n')
    line_starts = {i: sum(len(line) + 1 for line in lines[:i]) for i in range(len(lines))}

    for match in matches:
        function_body_start = match.start()
        start_line_number = next(i for i, pos in line_starts.items() if pos > function_body_start) - 1
        
        # Find the end of the function body
        brace_count = 1
        function_body_end = function_body_start
        for i in range(match.end(), len(text)):
            if text[i] == '{':
                brace_count += 1
            elif text[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    function_body_end = i + 1
                    break

        end_line_number = next(i for i, pos in line_starts.items() if pos > function_body_end) - 1
        function_body = text[function_body_start:function_body_end]
        function_body_lines = function_body.count('\n') + 1

        functions.append({
            'type': 'FunctionDefinition',
            'name': 'special_func',
            'start_line': start_line_number + 1,
            'end_line': end_line_number,
            'offset_start': 0,
            'offset_end': 0,
            'content': function_body,
            'contract_name': filename.replace('.go', '_go' + str(hash)),
            'contract_code': text,
            'modifiers': [],
            'stateMutability': None,
            'returnParameters': None,
            'visibility': 'public',
            'node_count': function_body_lines
        })

    return functions
def find_python_functions(text, filename, hash_value):
    # 更新后的正则表达式，使返回类型部分可选
    regex = r"def\s+(\w+)\s*\((.*?)\)(?:\s*->\s*(\w+))?\s*:"
    matches = re.finditer(regex, text)

    # 函数列表
    functions = []

    # 将文本分割成行，用于更容易地计算行号
    lines = text.split('\n')
    line_starts = {i: sum(len(line) + 1 for line in lines[:i]) for i in range(len(lines))}

    # 遍历匹配，创建函数定义
    if any(matches):  # 如果有匹配的函数定义
        for match in matches:
            start_line_number = next(i for i, pos in line_starts.items() if pos > match.start()) - 1
            indent_level = len(lines[start_line_number]) - len(lines[start_line_number].lstrip())

            # 查找函数体的结束
            end_line_number = start_line_number + 1
            while end_line_number < len(lines):
                line = lines[end_line_number]
                if line.strip() and (len(line) - len(line.lstrip()) <= indent_level):
                    break
                end_line_number += 1
            end_line_number -= 1  # Adjust to include last valid line of the function

            # 构建函数体
            function_body = '\n'.join(lines[start_line_number:end_line_number+1])
            function_body_lines = function_body.count('\n') + 1

            functions.append({
                'type': 'FunctionDefinition',
                'name': "function"+match.group(1),  # 函数名
                'start_line': start_line_number + 1,
                'end_line': end_line_number + 1,
                'offset_start': 0,
                'offset_end': 0,
                'content': function_body,
                'contract_name': filename.replace('.py', '_python' + str(hash_value)),
                'contract_code': text.strip(),  # 整个代码
                'modifiers': [],
                'stateMutability': None,
                'returnParameters': None,
                'visibility': 'public',
                'node_count': function_body_lines
            })
    else:  # 如果没有找到函数定义
        function_body_lines = len(lines)
        functions.append({
            'type': 'FunctionDefinition',
            'name': "function"+filename.split('.')[0]+"all",  # 使用文件名作为函数名
            'start_line': 1,
            'end_line': function_body_lines,
            'offset_start': 0,
            'offset_end': 0,
            'content': text.strip(),
            'contract_name': filename.replace('.py', '_python' + str(hash_value)),
            'contract_code': text.strip(),
            'modifiers': [],
            'stateMutability': None,
            'returnParameters': None,
            'visibility': 'public',
            'node_count': function_body_lines
        })

    return functions
def find_cairo_functions(text, filename,hash):
    regex = r"((?:pub(?:\s*\([^)]*\))?\s+)?fn\s+\w+(?:<[^>]*>)?\s*\([^{]*\)(?:\s*->\s*[^{]*)?\s*\{)"
    matches = re.finditer(regex, text)

    # 函数列表
    functions = []

    # 将文本分割成行，用于更容易地计算行号
    lines = text.split('\n')
    line_starts = {i: sum(len(line) + 1 for line in lines[:i]) for i in range(len(lines))}

    # 先收集所有函数体，构建完整的函数代码
    function_bodies = []
    for match in matches:
        brace_count = 1
        function_body_start = match.start()
        inside_braces = True

        for i in range(match.end(), len(text)):
            if text[i] == '{':
                brace_count += 1
            elif text[i] == '}':
                brace_count -= 1

            if inside_braces and brace_count == 0:
                function_body_end = i + 1
                function_bodies.append(text[function_body_start:function_body_end])
                break

    # 完整的函数代码字符串
    contract_code = "\n".join(function_bodies).strip()

    # 再次遍历匹配，创建函数定义
    for match in re.finditer(regex, text):
        start_line_number = next(i for i, pos in line_starts.items() if pos > match.start()) - 1
        brace_count = 1
        function_body_start = match.start()
        inside_braces = True

        for i in range(match.end(), len(text)):
            if text[i] == '{':
                brace_count += 1
            elif text[i] == '}':
                brace_count -= 1

            if inside_braces and brace_count == 0:
                function_body_end = i + 1
                end_line_number = next(i for i, pos in line_starts.items() if pos > function_body_end) - 1
                function_body = text[function_body_start:function_body_end]
                function_body_lines = function_body.count('\n') + 1
                visibility = 'public'
                functions.append({
                    'type': 'FunctionDefinition',
                    'name': 'special_'+re.search(r'\bfn\s+(\w+)', match.group(1)).group(1),  # Extract function name from match
                    'start_line': start_line_number + 1,
                    'end_line': end_line_number,
                    'offset_start': 0,
                    'offset_end': 0,
                    'content': function_body,
                    'contract_name': filename.replace('.cairo','_cairo'+str(hash)),
                    'contract_code': "",
                    'modifiers': [],
                    'stateMutability': None,
                    'returnParameters': None,
                    'visibility': visibility,
                    'node_count': function_body_lines
                })
                break

    return functions

def get_antlr_parsing(path):
    with open(path, 'r', encoding='utf-8', errors="ignore") as file:
        code = file.read()
        hash_value=hash(code)
    filename = os.path.basename(path)
    if ".rs" in str(path):
        rust_functions = find_rust_functions(code, filename,hash_value)
        return rust_functions
    if ".py" in str(path):
        python_functions = find_python_functions(code, filename,hash_value)
        return python_functions
    if ".move" in str(path):
        move_functions = find_move_functions(code, filename,hash_value)
        return move_functions
    if ".cairo" in str(path):
        cairo_functions = find_cairo_functions(code, filename,hash_value)
        return cairo_functions
    else:
        input_stream = ANTLRInputStream(code)
        lexer = SolidityLexer(input_stream)
        token_stream = CommonTokenStream(lexer)
        parser = SolidityParser(token_stream)
        tree = parser.sourceUnit()

        visitor = SolidityInfoVisitor(code)
        visitor.visit(tree)

        return visitor.results



def get_antlr_ast(path):
    with open(path, 'r', encoding='utf-8', errors="ignore") as file:
        code = file.read()

    parse(code,dump_json=True,dump_path="./")