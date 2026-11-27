"""LHDiff stage 1: normalize both file versions and find the unchanged lines."""

from __future__ import annotations

import difflib
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field

#: Lines taken above and below a line to form its context (paper and slides use 4).
CONTEXT_WINDOW = 4

_WHITESPACE_RUN = re.compile(r"\s+")


@dataclass
class FileVersion:
    """One version of a file, raw and normalized.

    `original[i]` and `normalized[i]` are the same physical line, so the two
    lists always have equal length and an index is valid in both.
    """

    path: str
    original: list[str] = field(default_factory=list)
    normalized: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.original)


@dataclass
class DiffResult:
    """Stage 1 output, consumed by every later stage."""

    old: FileVersion
    new: FileVersion
    mapping: dict[int, list[int]] = field(default_factory=dict)
    left_list: list[int] = field(default_factory=list)
    right_list: list[int] = field(default_factory=list)
    backend: str = "gnu"

    def old_context(self, index: int, window: int = CONTEXT_WINDOW) -> str:
        return get_context(self.old.normalized, index, window)

    def new_context(self, index: int, window: int = CONTEXT_WINDOW) -> str:
        return get_context(self.new.normalized, index, window)


def normalize(line: str) -> str:
    """Lowercase, collapse whitespace runs to one space, strip the ends.

    A blank or whitespace-only line becomes "". It stays in the list rather
    than being dropped, or every index after it would shift.

    >>> normalize("      String line  =              null;")
    'string line = null;'
    >>> normalize("\\t\\tFileReader fr = new FileReader(path);")
    'filereader fr = new filereader(path);'
    >>> normalize("   ")
    ''
    """
    return _WHITESPACE_RUN.sub(" ", line.lower()).strip()


def read_lines(path: str) -> list[str]:
    """Read a file into lines, handling LF, CRLF and CR, tolerating bad UTF-8.

    Not str.splitlines(), which also breaks on form feed, vertical tab,
    \\x1c-\\x1e, \\x85 and \\u2028. A file with a ^L page break would then get
    line numbers disagreeing with the editor, git and diff, which is fatal
    for a tool whose output is line numbers.

    >>> import tempfile, os
    >>> tmp = tempfile.TemporaryDirectory()
    >>> path = os.path.join(tmp.name, "f")
    >>> _ = open(path, "w", newline="").write("one\\x0ctwo\\r\\nthree")
    >>> read_lines(path)
    ['one\\x0ctwo', 'three']
    >>> tmp.cleanup()
    """
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as handle:
        text = handle.read()

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()  # a trailing newline ends the last line, it doesn't start one
    return lines


def preprocess_file(path: str) -> FileVersion:
    """Read a file and build its FileVersion."""
    original = read_lines(path)
    return FileVersion(path, original, [normalize(line) for line in original])


def get_context(lines: list[str], index: int, window: int = CONTEXT_WINDOW) -> str:
    """Return the lines around `lines[index]`, space-joined into one string.

    Pass normalized lines. The target line itself is excluded, since content
    and context are scored separately and then weighted. At the file edges
    the window is clamped rather than padded, and blank lines are skipped,
    because empty tokens would skew the context similarity score.

    >>> get_context(["a", "b", "c", "d"], 1, window=1)
    'a c'
    >>> get_context(["a", "b", "c"], 0, window=2)
    'b c'
    >>> get_context(["a", "", "c"], 1, window=1)
    'a c'
    """
    if not 0 <= index < len(lines):
        raise IndexError(f"line index {index} out of range for {len(lines)} lines")

    above = lines[max(0, index - window):index]
    below = lines[index + 1:index + 1 + window]
    return " ".join(part for part in (above + below) if part)


def gnu_diff_available() -> bool:
    """True if GNU diff is on PATH."""
    return shutil.which("diff") is not None


def _unchanged_difflib(old_norm: list[str], new_norm: list[str]) -> list[tuple[int, int]]:
    """Unchanged (old, new) index pairs according to difflib."""
    pairs: list[tuple[int, int]] = []
    matcher = difflib.SequenceMatcher(a=old_norm, b=new_norm, autojunk=False)
    for tag, old_start, old_end, new_start, _ in matcher.get_opcodes():
        if tag == "equal":
            pairs.extend((old_start + k, new_start + k) for k in range(old_end - old_start))
    return pairs


def _unchanged_gnu(old_norm: list[str], new_norm: list[str]) -> list[tuple[int, int]]:
    """Unchanged (old, new) index pairs according to GNU diff.

    diff emits one tag character per line ('=' unchanged, '-' old only,
    '+' new only) and we walk that stream with two pointers.

    The format strings contain no newline on purpose. Using "=\\n" works on
    Linux and macOS but silently yields zero pairs under Git for Windows,
    where the newline doesn't survive into diff.exe's arguments.
    """
    with tempfile.TemporaryDirectory() as workdir:
        old_path = os.path.join(workdir, "old")
        new_path = os.path.join(workdir, "new")
        for path, lines in ((old_path, old_norm), (new_path, new_norm)):
            with open(path, "w", encoding="utf-8") as handle:
                handle.writelines(line + "\n" for line in lines)

        completed = subprocess.run(
            ["diff",
             "--unchanged-line-format==",
             "--old-line-format=-",
             "--new-line-format=+",
             old_path, new_path],
            capture_output=True, text=True,
        )

    # diff exits 0 (same) or 1 (differences); 2 or more means it failed.
    if completed.returncode > 1:
        raise RuntimeError(f"diff failed: {completed.stderr.strip()}")

    pairs: list[tuple[int, int]] = []
    old_index = new_index = 0
    for tag in completed.stdout:
        if tag == "=":
            pairs.append((old_index, new_index))
            old_index += 1
            new_index += 1
        elif tag == "-":
            old_index += 1
        elif tag == "+":
            new_index += 1
        else:
            raise RuntimeError(f"unexpected tag {tag!r} from diff; expected '=', '-' or '+'")

    # One tag per line means both pointers must land on the end of their file.
    # If they don't we misread the output, so fail loudly instead of returning
    # a plausible-looking partial answer.
    if old_index != len(old_norm) or new_index != len(new_norm):
        raise RuntimeError(
            f"diff output accounted for {old_index}/{len(old_norm)} old lines and "
            f"{new_index}/{len(new_norm)} new lines; the diff backend is misbehaving"
        )

    return pairs


def detect_unchanged(
    old: FileVersion,
    new: FileVersion,
    backend: str = "auto",
) -> DiffResult:
    """Diff the normalized lines and split them into mapped, left and right.

    Diffing the normalized lines is what makes a pure indentation or casing
    change count as unchanged.

    GNU diff and difflib disagree on roughly 1.5-2.8% of unchanged pairs in
    real churn (measured on requests, jinja2 and click), always on lines that
    are identical after normalization. The paper specifies Unix diff, so
    "auto" prefers GNU diff and falls back to difflib only when it's missing.
    Force a backend when results must be comparable across machines.
    """
    if backend not in {"auto", "gnu", "difflib"}:
        raise ValueError(f"unknown backend {backend!r}")

    if backend == "auto":
        backend = "gnu" if gnu_diff_available() else "difflib"
    if backend == "gnu" and not gnu_diff_available():
        raise RuntimeError("backend='gnu' requested but diff is not on PATH")

    finder = _unchanged_gnu if backend == "gnu" else _unchanged_difflib
    pairs = finder(old.normalized, new.normalized)

    result = DiffResult(old=old, new=new, backend=backend)
    matched_old, matched_new = set(), set()
    for old_index, new_index in pairs:
        result.mapping[old_index] = [new_index]
        matched_old.add(old_index)
        matched_new.add(new_index)

    result.left_list = [i for i in range(len(old)) if i not in matched_old]
    result.right_list = [j for j in range(len(new)) if j not in matched_new]
    return result


def preprocess(old_path: str, new_path: str, backend: str = "auto") -> DiffResult:
    """Run stage 1 on a pair of files."""
    return detect_unchanged(
        preprocess_file(old_path),
        preprocess_file(new_path),
        backend=backend,
    )


def describe(result: DiffResult) -> str:
    """Readable dump of a DiffResult, 1-indexed, for eyeballing during dev."""
    out = [
        f"old: {result.old.path} ({len(result.old)} lines)",
        f"new: {result.new.path} ({len(result.new)} lines)",
        f"backend: {result.backend}",
        f"unchanged pairs: {len(result.mapping)}",
        "",
        "mapping (1-indexed for reading):",
    ]
    for old_index in sorted(result.mapping):
        targets = ",".join(str(i + 1) for i in result.mapping[old_index])
        out.append(f"  {old_index + 1}-{targets}")

    out += ["", "left list (unmatched old lines):"]
    out += [f"  {i + 1}: {result.old.original[i]!r}" for i in result.left_list]
    out += ["", "right list (unmatched new lines):"]
    out += [f"  {j + 1}: {result.new.original[j]!r}" for j in result.right_list]
    return "\n".join(out)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LHDiff stage 1: preprocess and diff")
    parser.add_argument("old_file")
    parser.add_argument("new_file")
    parser.add_argument("--backend", choices=["auto", "gnu", "difflib"], default="auto")
    args = parser.parse_args()

    print(describe(preprocess(args.old_file, args.new_file, backend=args.backend)))
