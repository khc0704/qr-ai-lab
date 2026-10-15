#!/usr/bin/env python3
"""design_lint.py — QR AI Lab design-system linter for the Next.js frontend.

Catches UI code that bypasses the design tokens defined in DESIGN.md / globals.css.

Usage
  python3 scripts/design_lint.py [--strict] [PATH ...]   CLI: lint files or dirs (default: frontend/src)
  python3 scripts/design_lint.py --hook                   Claude Code PostToolUse hook (reads hook JSON on stdin)

Exit codes
  CLI : 0 clean, 1 errors (or warnings with --strict)
  hook: 0 clean / out of scope, 2 violations (stderr is fed back to Claude)

Rules
  E001 hex color literal            E002 rgb()/hsl()/oklch() literal
  E003 Tailwind default palette     E004 raw brand-* scale outside globals.css / components/ui
  E005 inline style color           W001 dark: variant outside components/ui or components/layout
Suppress one line with a trailing comment containing:  design-lint: allow
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCOPE_ROOT = REPO_ROOT / "frontend" / "src"
EXTS = {".tsx", ".ts", ".jsx", ".js", ".css", ".mdx"}
# Token source + vendored shadcn base layer: fully exempt (they define the tokens).
EXEMPT_PREFIXES = ("app/globals.css", "components/ui/")
# The only layers allowed to use the `dark:` variant.
DARK_ALLOWED_PREFIXES = ("components/ui/", "components/layout/")
ALLOW_MARK = "design-lint: allow"

PALETTE = (
    r"(?:red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|"
    r"fuchsia|pink|rose|slate|gray|zinc|neutral|stone)-\d{2,3}"
)
PREFIX = (
    r"(?:bg|text|border|ring|ring-offset|fill|stroke|from|to|via|outline|decoration|divide|"
    r"placeholder|caret|accent|shadow|inset-ring)"
)
OPACITY = r"(?:/\d{1,3})?"


@dataclass(frozen=True)
class Rule:
    code: str
    pattern: re.Pattern[str]
    message: str
    warning: bool = False


RULES: list[Rule] = [
    Rule(
        "E001",
        re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b"),
        "hex 色碼 — 改用語意 token（bg-card / text-muted-foreground / border-border …），見 DESIGN.md §2",
    ),
    Rule(
        "E002",
        re.compile(r"\b(?:rgba?|hsla?|oklch|oklab)\("),
        "rgb()/hsl()/oklch() 色值 — 改用語意 token，見 DESIGN.md §2",
    ),
    Rule(
        "E003",
        re.compile(rf"(?<![\w/-]){PREFIX}-(?:{PALETTE}|black|white){OPACITY}(?![\w-])"),
        "Tailwind 預設色盤 / black / white — 改用語意 token（例：text-white → text-primary-foreground，"
        "bg-black/50 → bg-background/80，text-gray-500 → text-muted-foreground）",
    ),
    Rule(
        "E005",
        re.compile(
            r"style=\{\{[^}]*\b(?:color|background(?:Color)?|borderColor|fill|stroke|outlineColor)\s*:"
        ),
        "inline style 顏色 — 改用 className + token",
    ),
]
BRAND_RULE = Rule(
    "E004",
    re.compile(rf"(?<![\w-])(?:[\w-]+:)*{PREFIX}-brand-\d{{2,3}}{OPACITY}(?![\w-])"),
    "brand-* 原始色階只能用在 globals.css 與 components/ui — 頁面請用 bg-primary / text-brand-ink",
)
DARK_RULE = Rule(
    "W001",
    re.compile(r"(?<![\w-])dark:"),
    "`dark:` 變體只允許在 components/ui 與 components/layout — token 已依模式切換，頁面不需要",
    warning=True,
)


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    col: int
    code: str
    snippet: str
    message: str
    warning: bool


def rel_to_scope(path: Path) -> str | None:
    try:
        return path.resolve().relative_to(SCOPE_ROOT).as_posix()
    except ValueError:
        return None


def in_scope(path: Path) -> bool:
    return path.suffix in EXTS and rel_to_scope(path) is not None


def lint_file(path: Path) -> list[Finding]:
    rel = rel_to_scope(path) or path.as_posix()
    if rel.startswith(EXEMPT_PREFIXES):
        return []
    rules = [*RULES, BRAND_RULE]
    if not rel.startswith(DARK_ALLOWED_PREFIXES):
        rules.append(DARK_RULE)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    findings: list[Finding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if ALLOW_MARK in line:
            continue
        for rule in rules:
            for m in rule.pattern.finditer(line):
                findings.append(
                    Finding(path, lineno, m.start() + 1, rule.code, m.group(0), rule.message, rule.warning)
                )
    return findings


def iter_targets(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if not p.is_absolute():
            p = Path.cwd() / p
        if p.is_dir():
            out.extend(f for f in sorted(p.rglob("*")) if f.is_file() and f.suffix in EXTS and "node_modules" not in f.parts)
        elif p.is_file() and p.suffix in EXTS:
            out.append(p)
    return out


def display(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def format_findings(findings: list[Finding]) -> str:
    lines = [
        f"{display(f.path)}:{f.line}:{f.col} {f.code} `{f.snippet}` — {f.message}" for f in findings
    ]
    return "\n".join(lines)


def cli_main(argv: list[str]) -> int:
    strict = "--strict" in argv
    paths = [a for a in argv if not a.startswith("--")] or [str(SCOPE_ROOT)]
    targets = iter_targets(paths)
    findings = [f for t in targets for f in lint_file(t)]
    errors = [f for f in findings if not f.warning]
    warnings = [f for f in findings if f.warning]
    if findings:
        print(format_findings(findings))
    print(f"design-lint: {len(targets)} file(s), {len(errors)} error(s), {len(warnings)} warning(s)")
    if errors or (strict and warnings):
        return 1
    return 0


def hook_main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0
    tool_input = payload.get("tool_input") or {}
    tool_response = payload.get("tool_response") or {}
    raw = tool_input.get("file_path") or tool_response.get("filePath") or ""
    if not raw:
        return 0
    path = Path(raw)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.exists() or not in_scope(path):
        return 0
    findings = lint_file(path)
    if not findings:
        return 0
    header = (
        f"[design-lint] {len(findings)} design-system violation(s) in {display(path)}. "
        "Fix them now using the semantic tokens in DESIGN.md §2 / .claude/rules/frontend.md. "
        "Only if a literal is genuinely required, add a trailing comment `design-lint: allow` and say why."
    )
    print(header + "\n" + format_findings(findings), file=sys.stderr)
    return 2


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--hook" in args:
        sys.exit(hook_main())
    sys.exit(cli_main(args))
