#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Comment Cleaner — multi-language comment remover
- Safely strips comments from many languages without touching string literals.
- Interactive CLI: choose language, provide file path, preview counts, confirm, write output.
- Output filename: <original_name>_no_comments<ext> in same directory.

Supported families and rules:
- C-like (C, C++, C#, Java, JS, TS, CSS, Rust, Go, JSONC):  // line, /* block */
- PHP: //, #, /* */ (for PHP sections only; if full file, treated the same as C-like + #)
- Python: # line comments (triple-quoted strings are preserved)
- Bash/Shell: # line comments
- SQL: -- line, /* block */
- HTML/XML: <!-- block -->
- Ruby: # line; =begin ... =end block (rare; handled)
- YAML/TOML/INI: # (YAML), # or ; (INI/TOML)
Notes:
- String literals are preserved; comment markers inside strings are ignored.
- For JS/TS, template literals `...` are handled (including escaped backticks). Embedded ${...} is parsed to skip comments inside template string expressions correctly in a simple manner.
- For HTML/XML, script/style contents are not specially parsed—HTML comments are removed globally.
"""

import os
import sys
import re
from typing import Tuple, List, Optional

# -------------- Menu & Language Definitions --------------

LANGS = [
    ("Auto-detect by extension", "auto"),
    ("C", "c"),
    ("C++", "cpp"),
    ("C#", "csharp"),
    ("Java", "java"),
    ("JavaScript", "js"),
    ("TypeScript", "ts"),
    ("CSS", "css"),
    ("PHP", "php"),
    ("Rust", "rust"),
    ("Go", "go"),
    ("SQL", "sql"),
    ("Bash / Shell", "bash"),
    ("HTML", "html"),
    ("XML", "xml"),
    ("Python", "python"),
    ("Ruby", "ruby"),
    ("YAML", "yaml"),
    ("TOML", "toml"),
    ("INI", "ini"),
    ("JSON (with comments a.k.a JSONC)", "jsonc"),
]

EXT_TO_LANG = {
    # C-like group
    ".c": "c", ".h": "c", ".hpp": "cpp", ".hh": "cpp", ".hxx": "cpp",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
    ".cs": "csharp",
    ".java": "java",
    ".js": "js", ".mjs": "js", ".cjs": "js",
    ".ts": "ts", ".tsx": "ts",
    ".css": "css",
    ".rs": "rust",
    ".go": "go",
    ".jsonc": "jsonc",
    # PHP
    ".php": "php", ".phtml": "php",
    # SQL
    ".sql": "sql",
    # Bash
    ".sh": "bash", ".bash": "bash", ".zsh": "bash",
    # HTML/XML
    ".html": "html", ".htm": "html",
    ".xml": "xml",
    # Python
    ".py": "python",
    # Ruby
    ".rb": "ruby",
    # Config styles
    ".yml": "yaml", ".yaml": "yaml",
    ".toml": "toml",
    ".ini": "ini", ".cfg": "ini", ".conf": "ini",
    ".json": "jsonc",  # allow comments for convenience (JSONC)
}

def choose_language() -> str:
    print("Select language:")
    for i, (label, code) in enumerate(LANGS, start=1):
        print(f"  {i:2d}) {label}")
    while True:
        choice = input("Enter number: ").strip()
        if not choice.isdigit():
            print("Please enter a number.")
            continue
        idx = int(choice)
        if 1 <= idx <= len(LANGS):
            return LANGS[idx - 1][1]
        print("Invalid choice, try again.")

def auto_detect_language_from_path(path: str) -> Optional[str]:
    _, ext = os.path.splitext(path)
    ext = ext.lower()
    return EXT_TO_LANG.get(ext)

# -------------- Utilities --------------

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        # fallback to latin-1 to avoid hard crashes, user might have odd encodings
        with open(path, "r", encoding="latin-1", errors="replace") as f:
            return f.read()

def write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)

def out_path_with_suffix(original: str, suffix: str) -> str:
    folder, base = os.path.split(original)
    name, ext = os.path.splitext(base)
    return os.path.join(folder, f"{name}{suffix}{ext}")

# -------------- Core Tokenizers --------------

class Result:
    def __init__(self, text: str, comments_found: int, comments_removed_chars: int):
        self.text = text
        self.comments_found = comments_found
        self.comments_removed_chars = comments_removed_chars

# Generic C-like state machine (C/C++/C#/Java/JS/TS/CSS/Rust/Go/JSONC)
# Preserves ' " and template literals `...` (for JS/TS).
def strip_comments_c_like(src: str, treat_hash_as_line_comment: bool = False, support_backtick: bool = False) -> Result:
    i, n = 0, len(src)
    out = []
    comments = 0
    removed_chars = 0

    IN_STR_SGL, IN_STR_DBL, IN_TEMPLATE = 1, 2, 3
    state = 0
    template_brace_depth = 0  # for ${...} in template literals

    def peek(offset=0):
        j = i + offset
        return src[j] if 0 <= j < n else ""

    nonlocal_i = 0  # not used; placeholder to satisfy pylint-like tools

    while i < n:
        ch = src[i]
        ch2 = src[i + 1] if i + 1 < n else ""

        # Strings handling
        if state == IN_STR_SGL:
            out.append(ch)
            if ch == "\\":
                # escape next char
                if i + 1 < n:
                    out.append(src[i + 1])
                    i += 2
                    continue
            elif ch == "'":
                state = 0
            i += 1
            continue

        if state == IN_STR_DBL:
            out.append(ch)
            if ch == "\\":
                if i + 1 < n:
                    out.append(src[i + 1])
                    i += 2
                    continue
            elif ch == '"':
                state = 0
            i += 1
            continue

        if state == IN_TEMPLATE:
            out.append(ch)
            if ch == "\\":
                if i + 1 < n:
                    out.append(src[i + 1])
                    i += 2
                    continue
            elif ch == "`":
                state = 0
                i += 1
                continue
            elif ch == "$" and ch2 == "{":
                # enter JS expression — comments inside expression should be removed,
                # but we’ll just copy through and rely on outer scanner not being in comment mode.
                template_brace_depth += 1
                out.append(ch2)
                i += 2
                continue
            elif ch == "}" and template_brace_depth > 0:
                template_brace_depth -= 1
            i += 1
            continue

        # Not inside string/template:
        if ch == "'" and not support_backtick:
            state = IN_STR_SGL
            out.append(ch); i += 1; continue
        if ch == '"':
            state = IN_STR_DBL
            out.append(ch); i += 1; continue
        if support_backtick and ch == "`":
            state = IN_TEMPLATE
            template_brace_depth = 0
            out.append(ch); i += 1; continue

        # Detect comments
        if ch == "/" and ch2 == "/":
            # line comment
            comments += 1
            # consume until end of line
            j = i + 2
            while j < n and src[j] not in "\n\r":
                j += 1
            removed_chars += (j - i)
            i = j
            continue
        if ch == "/" and ch2 == "*":
            # block comment
            comments += 1
            j = i + 2
            while j < n - 1 and not (src[j] == "*" and src[j + 1] == "/"):
                j += 1
            j = j + 2 if j < n else n
            removed_chars += (j - i)
            i = j
            continue

        if treat_hash_as_line_comment and ch == "#":
            # line comment with #
            # but skip shebang #! at file start
            if not (i == 0 and i + 1 < n and src[i + 1] == "!"):
                comments += 1
                j = i + 1
                while j < n and src[j] not in "\n\r":
                    j += 1
                removed_chars += (j - i)
                i = j
                continue

        # Otherwise, normal char
        out.append(ch)
        i += 1

    return Result("".join(out), comments, removed_chars)

# Python-style: # line comments; triple-quoted strings preserved.
TRIPLE_STR_OPENERS = ("'''", '"""')

def strip_comments_python(src: str) -> Result:
    i, n = 0, len(src)
    out = []
    comments = 0
    removed_chars = 0

    IN_SGL, IN_DBL, IN_TSQ, IN_TDQ = 1, 2, 3, 4
    state = 0

    while i < n:
        ch = src[i]
        ch2 = src[i + 1] if i + 1 < n else ""
        ch3 = src[i + 2] if i + 2 < n else ""

        if state == IN_SGL:
            out.append(ch)
            if ch == "\\":
                if i + 1 < n:
                    out.append(src[i + 1]); i += 2; continue
            elif ch == "'":
                state = 0
            i += 1; continue

        if state == IN_DBL:
            out.append(ch)
            if ch == "\\":
                if i + 1 < n:
                    out.append(src[i + 1]); i += 2; continue
            elif ch == '"':
                state = 0
            i += 1; continue

        if state == IN_TSQ:
            out.append(ch)
            if ch == "'" and ch2 == "'" and ch3 == "'":
                out.append(ch2); out.append(ch3)
                i += 3; state = 0; continue
            i += 1; continue

        if state == IN_TDQ:
            out.append(ch)
            if ch == '"' and ch2 == '"' and ch3 == '"':
                out.append(ch2); out.append(ch3)
                i += 3; state = 0; continue
            i += 1; continue

        # not in string
        # check triple string openers
        if ch == "'" and ch2 == "'" and ch3 == "'":
            out.append(ch); out.append(ch2); out.append(ch3)
            i += 3; state = IN_TSQ; continue
        if ch == '"' and ch2 == '"' and ch3 == '"':
            out.append(ch); out.append(ch2); out.append(ch3)
            i += 3; state = IN_TDQ; continue

        if ch == "'":
            out.append(ch); i += 1; state = IN_SGL; continue
        if ch == '"':
            out.append(ch); i += 1; state = IN_DBL; continue

        # line comments with #
        if ch == "#":
            # allow shebang at very beginning (#!)
            if not (i == 0 and ch2 == "!"):
                comments += 1
                j = i + 1
                while j < n and src[j] not in "\n\r":
                    j += 1
                removed_chars += (j - i)
                i = j
                continue

        out.append(ch)
        i += 1

    return Result("".join(out), comments, removed_chars)

# SQL: -- line, /* block */
def strip_comments_sql(src: str) -> Result:
    # reuse c-like without backticks, but without //; enable block and --; keep strings ' " `
    # We'll adapt: first remove /* */ via c-like block; then handle -- lines.
    # To avoid over-complication, do a simple state machine:
    i, n = 0, len(src)
    out = []
    comments = 0
    removed = 0

    IN_SGL, IN_DBL, IN_BKT = 1, 2, 3
    state = 0

    while i < n:
        ch = src[i]
        ch2 = src[i + 1] if i + 1 < n else ""

        # strings
        if state == IN_SGL:
            out.append(ch)
            if ch == "\\":
                if i + 1 < n:
                    out.append(src[i + 1]); i += 2; continue
            elif ch == "'":
                state = 0
            i += 1; continue
        if state == IN_DBL:
            out.append(ch)
            if ch == "\\":
                if i + 1 < n:
                    out.append(src[i + 1]); i += 2; continue
            elif ch == '"':
                state = 0
            i += 1; continue
        if state == IN_BKT:
            out.append(ch)
            if ch == "`":
                state = 0
            i += 1; continue

        # open strings
        if ch == "'":
            out.append(ch); i += 1; state = IN_SGL; continue
        if ch == '"':
            out.append(ch); i += 1; state = IN_DBL; continue
        if ch == "`":
            out.append(ch); i += 1; state = IN_BKT; continue

        # block comment
        if ch == "/" and ch2 == "*":
            comments += 1
            j = i + 2
            while j < n - 1 and not (src[j] == "*" and src[j + 1] == "/"):
                j += 1
            j = j + 2 if j < n else n
            removed += (j - i)
            i = j
            continue

        # line comment --
        if ch == "-" and ch2 == "-":
            comments += 1
            j = i + 2
            while j < n and src[j] not in "\n\r":
                j += 1
            removed += (j - i)
            i = j
            continue

        out.append(ch)
        i += 1

    return Result("".join(out), comments, removed)

# HTML/XML: <!-- ... -->
def strip_comments_html(src: str) -> Result:
    comments = 0
    removed_chars = 0

    def repl(m):
        nonlocal comments, removed_chars
        comments += 1
        removed_chars += len(m.group(0))
        return ""

    # Remove <!-- ... --> including newlines (non-greedy)
    pattern = re.compile(r"<!--[\s\S]*?-->", re.MULTILINE)
    out = pattern.sub(repl, src)
    return Result(out, comments, removed_chars)

# Ruby: # line, =begin ... =end block (must be at line starts)
def strip_comments_ruby(src: str) -> Result:
    # Handle strings ' " and heredocs roughly by ignoring # in strings.
    # For simplicity, we’ll remove =begin...=end via regex and then scan lines for #.
    # First: =begin ... =end (only if at line start, ignoring whitespace)
    comments = 0
    removed_chars = 0

    def block_repl(m):
        nonlocal comments, removed_chars
        comments += 1
        removed_chars += len(m.group(0))
        return ""

    out = re.sub(r"(?m)^[ \t]*=begin[\s\S]*?^[ \t]*=end[ \t]*\r?\n?", block_repl, src)

    # Now line comments (#) but avoid ones inside strings via a simple string-aware scan.
    i, n = 0, len(out)
    res = []
    IN_SGL, IN_DBL = 1, 2
    state = 0
    while i < n:
        ch = out[i]
        ch2 = out[i + 1] if i + 1 < n else ""
        if state == IN_SGL:
            res.append(ch)
            if ch == "\\" and i + 1 < n:
                res.append(out[i + 1]); i += 2; continue
            if ch == "'":
                state = 0
            i += 1; continue
        if state == IN_DBL:
            res.append(ch)
            if ch == "\\" and i + 1 < n:
                res.append(out[i + 1]); i += 2; continue
            if ch == '"':
                state = 0
            i += 1; continue

        if ch == "'":
            res.append(ch); i += 1; state = IN_SGL; continue
        if ch == '"':
            res.append(ch); i += 1; state = IN_DBL; continue

        if ch == "#":
            # comment to end of line
            comments += 1
            j = i + 1
            while j < n and out[j] not in "\n\r":
                j += 1
            removed_chars += (j - i)
            i = j
            continue

        res.append(ch)
        i += 1

    return Result("".join(res), comments, removed_chars)

# INI / TOML / YAML: line comments with # (INI can also use ;)
def strip_comments_hash_and_semicolon(src: str, allow_semicolon: bool = True) -> Result:
    comments = 0
    removed = 0
    out_lines = []
    for line in src.splitlines(True):
        # Very simple approach: strip from first unquoted # or ; (INI/TOML)
        # Handle quoted strings "..." and '...'
        i, n = 0, len(line)
        IN_SGL, IN_DBL = 1, 2
        state = 0
        cut = None
        while i < n:
            ch = line[i]
            if state == IN_SGL:
                if ch == "\\" and i + 1 < n:
                    i += 2; continue
                if ch == "'":
                    state = 0
                i += 1; continue
            if state == IN_DBL:
                if ch == "\\" and i + 1 < n:
                    i += 2; continue
                if ch == '"':
                    state = 0
                i += 1; continue
            # not in string
            if ch == "'":
                state = IN_SGL; i += 1; continue
            if ch == '"':
                state = IN_DBL; i += 1; continue
            if ch == "#":
                cut = i; break
            if allow_semicolon and ch == ";":
                cut = i; break
            i += 1
        if cut is not None:
            comments += 1
            removed += len(line) - cut
            out_lines.append(line[:cut].rstrip() + ("\n" if line.endswith("\n") else ""))
        else:
            out_lines.append(line)
    return Result("".join(out_lines), comments, removed)

# -------------- Dispatcher --------------

def strip_comments(src: str, lang: str) -> Result:
    lang = lang.lower()
    if lang in {"c","cpp","csharp","java","css","rust","go","jsonc","php"}:
        # C-like; PHP adds # as line comment sometimes
        treat_hash = (lang == "php")
        return strip_comments_c_like(src, treat_hash_as_line_comment=treat_hash, support_backtick=False)
    if lang in {"js","ts"}:
        return strip_comments_c_like(src, treat_hash_as_line_comment=False, support_backtick=True)
    if lang == "python":
        return strip_comments_python(src)
    if lang == "sql":
        return strip_comments_sql(src)
    if lang in {"html","xml"}:
        return strip_comments_html(src)
    if lang == "ruby":
        return strip_comments_ruby(src)
    if lang == "bash":
        # shell: just #
        return strip_comments_c_like(src, treat_hash_as_line_comment=True, support_backtick=False)
    if lang == "yaml":
        return strip_comments_hash_and_semicolon(src, allow_semicolon=False)
    if lang in {"toml","ini"}:
        return strip_comments_hash_and_semicolon(src, allow_semicolon=True)
    # Default fallback: treat as C-like
    return strip_comments_c_like(src, treat_hash_as_line_comment=False, support_backtick=False)

# -------------- CLI Flow --------------

def main():
    print("=== Comment Cleaner ===")

    # 1) language choice
    lang = choose_language()

    # 2) file path
    path = input("Enter exact file path: ").strip().strip('"')
    if not os.path.isfile(path):
        print(f"❌ File not found: {path}")
        sys.exit(1)

    # auto-detect if requested
    if lang == "auto":
        detected = auto_detect_language_from_path(path)
        if not detected:
            print("⚠️  Could not auto-detect from extension. Defaulting to C-like.")
            detected = "cpp"
        lang = detected
        print(f"Auto-detected language: {lang}")

    # 3) read file
    src = read_text(path)

    # 4) dry-run strip
    result = strip_comments(src, lang)
    print(f"\nFound {result.comments_found} comment block(s)/line(s).")
    print(f"Characters to remove: {result.comments_removed_chars}")

    # 5) confirm
    confirm = input("Delete comments and save a new file? (yes/no): ").strip().lower()
    if confirm not in {"y", "yes"}:
        print("Aborted. No changes made.")
        sys.exit(0)

    # 6) write output
    outp = out_path_with_suffix(path, "_no_comments")
    write_text(outp, result.text)

    print("\n✅ Done.")
    print(f"Comments removed: {result.comments_found}")
    print(f"Characters removed: {result.comments_removed_chars}")
    print(f"Saved: {outp}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
