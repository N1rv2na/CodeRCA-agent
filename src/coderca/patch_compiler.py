"""Deterministically compile exact replacement intents into candidate patches."""

from __future__ import annotations

import re
from collections.abc import Iterable
from difflib import unified_diff

from .contracts import CandidatePatch, PatchIntentDecision


class PatchIntentCompilationError(ValueError):
    """A Patch Intent cannot be deterministically applied to its source text."""

    def __init__(self, validation_errors: list[dict[str, object]]) -> None:
        super().__init__("Patch Intent cannot be compiled deterministically")
        self.validation_errors = validation_errors


_HUNK_HEADER = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?\n?$"
)


def compile_candidate_patch(
    source_text: str,
    intent: PatchIntentDecision,
) -> CandidatePatch:
    """Compile exact, unique, non-overlapping edits into a canonical diff."""

    errors: list[dict[str, object]] = []
    ranges: list[tuple[int, int, int]] = []
    for index, edit in enumerate(intent.edits):
        matches = _match_offsets(source_text, edit.old_text)
        if not matches:
            errors.append(
                _error(index, "missing_match", "old_text does not match the source", 0)
            )
            continue
        if len(matches) != 1:
            errors.append(
                _error(
                    index,
                    "ambiguous_match",
                    "old_text must match the source exactly once",
                    len(matches),
                )
            )
            continue
        start = matches[0]
        ranges.append((start, start + len(edit.old_text), index))

    for (_, previous_end, previous_index), (
        current_start,
        _,
        current_index,
    ) in zip(sorted(ranges), sorted(ranges)[1:]):
        if current_start < previous_end:
            errors.append(
                {
                    "loc": ["edits", current_index],
                    "type": "overlapping_edits",
                    "msg": "exact replacements must not overlap",
                    "overlaps_with": previous_index,
                }
            )

    if errors:
        raise PatchIntentCompilationError(errors)

    updated = source_text
    for start, end, index in sorted(ranges, reverse=True):
        updated = updated[:start] + intent.edits[index].new_text + updated[end:]
    if updated == source_text:
        raise PatchIntentCompilationError(
            [
                {
                    "loc": ["edits"],
                    "type": "no_op_edit",
                    "msg": "Patch Intent must change the source file",
                }
            ]
        )

    path = intent.target_path
    diff = _serialize_unified_diff(
        unified_diff(
            source_text.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="\n",
        )
    )
    if not diff.endswith("\n"):
        diff += "\n"
    return CandidatePatch(
        hypothesis_id=intent.hypothesis_id,
        target_path=path,
        mechanism=intent.mechanism,
        unified_diff=diff,
    )


def verify_compiled_candidate(
    intent: PatchIntentDecision,
    candidate: CandidatePatch,
) -> None:
    """Verify that one canonical single-file diff contains exactly the Intent edits."""

    if (
        candidate.hypothesis_id != intent.hypothesis_id
        or candidate.target_path != intent.target_path
    ):
        raise PatchIntentCompilationError(
            [{"loc": ["candidate_patch"], "type": "metadata_mismatch"}]
        )
    before, after = _changed_fragments(candidate.unified_diff, intent.target_path)
    try:
        updated = _apply_exact_edits(before, intent)
    except PatchIntentCompilationError:
        raise
    if updated != after:
        raise PatchIntentCompilationError(
            [
                {
                    "loc": ["candidate_patch", "unified_diff"],
                    "type": "compiled_patch_mismatch",
                    "msg": "Candidate Patch contains changes outside the Patch Intent",
                }
            ]
        )


def _match_offsets(source_text: str, old_text: str) -> list[int]:
    matches: list[int] = []
    offset = 0
    while True:
        match = source_text.find(old_text, offset)
        if match < 0:
            return matches
        matches.append(match)
        offset = match + 1


def _apply_exact_edits(source_text: str, intent: PatchIntentDecision) -> str:
    ranges: list[tuple[int, int, int]] = []
    errors: list[dict[str, object]] = []
    for index, edit in enumerate(intent.edits):
        matches = _match_offsets(source_text, edit.old_text)
        if len(matches) != 1:
            errors.append(
                _error(
                    index,
                    "fragment_match_count",
                    "old_text must occur once in Candidate Patch source fragments",
                    len(matches),
                )
            )
            continue
        ranges.append((matches[0], matches[0] + len(edit.old_text), index))
    for (_, previous_end, previous_index), (
        current_start,
        _,
        current_index,
    ) in zip(sorted(ranges), sorted(ranges)[1:]):
        if current_start < previous_end:
            errors.append(
                {
                    "loc": ["edits", current_index],
                    "type": "overlapping_edits",
                    "overlaps_with": previous_index,
                }
            )
    if errors:
        raise PatchIntentCompilationError(errors)
    updated = source_text
    for start, end, index in sorted(ranges, reverse=True):
        updated = updated[:start] + intent.edits[index].new_text + updated[end:]
    return updated


def _changed_fragments(unified_diff: str, target_path: str) -> tuple[str, str]:
    lines = unified_diff.splitlines(keepends=True)
    expected_headers = (f"--- a/{target_path}\n", f"+++ b/{target_path}\n")
    if len(lines) < 3 or tuple(lines[:2]) != expected_headers:
        raise PatchIntentCompilationError(
            [{"loc": ["candidate_patch", "unified_diff"], "type": "invalid_header"}]
        )
    before_chunks: list[str] = []
    after_chunks: list[str] = []
    index = 2
    hunk_count = 0
    separator = "\0CODERCA_HUNK_BOUNDARY\0"
    while index < len(lines):
        match = _HUNK_HEADER.match(lines[index])
        if match is None:
            raise PatchIntentCompilationError(
                [
                    {
                        "loc": ["candidate_patch", "unified_diff"],
                        "type": "invalid_hunk_header",
                    }
                ]
            )
        hunk_count += 1
        expected_before = int(match.group(2) or "1")
        expected_after = int(match.group(4) or "1")
        index += 1
        before: list[str] = []
        after: list[str] = []
        previous_prefix: str | None = None
        while index < len(lines) and not lines[index].startswith("@@ "):
            line = lines[index]
            if line.startswith(" "):
                before.append(line[1:])
                after.append(line[1:])
                previous_prefix = " "
            elif line.startswith("-"):
                before.append(line[1:])
                previous_prefix = "-"
            elif line.startswith("+"):
                after.append(line[1:])
                previous_prefix = "+"
            elif line.startswith("\\ No newline at end of file"):
                if previous_prefix in {" ", "-"} and before:
                    before[-1] = before[-1].removesuffix("\n")
                if previous_prefix in {" ", "+"} and after:
                    after[-1] = after[-1].removesuffix("\n")
            else:
                raise PatchIntentCompilationError(
                    [
                        {
                            "loc": ["candidate_patch", "unified_diff"],
                            "type": "invalid_hunk_line",
                        }
                    ]
                )
            index += 1
        if len(before) != expected_before or len(after) != expected_after:
            raise PatchIntentCompilationError(
                [
                    {
                        "loc": ["candidate_patch", "unified_diff"],
                        "type": "invalid_hunk_count",
                    }
                ]
            )
        before_chunks.append("".join(before))
        after_chunks.append("".join(after))
    if not hunk_count:
        raise PatchIntentCompilationError(
            [{"loc": ["candidate_patch", "unified_diff"], "type": "missing_hunk"}]
        )
    return separator.join(before_chunks), separator.join(after_chunks)


def _serialize_unified_diff(lines: Iterable[str]) -> str:
    serialized: list[str] = []
    for line in lines:
        if line.endswith("\n"):
            serialized.append(line)
        else:
            serialized.extend((line + "\n", "\\ No newline at end of file\n"))
    return "".join(serialized)


def _error(
    index: int,
    error_type: str,
    message: str,
    match_count: int,
) -> dict[str, object]:
    return {
        "loc": ["edits", index, "old_text"],
        "type": error_type,
        "msg": message,
        "match_count": match_count,
    }
