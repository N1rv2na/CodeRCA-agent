"""Deterministically compile exact replacement intents into candidate patches."""

from __future__ import annotations

from collections.abc import Iterable
from difflib import unified_diff

from .contracts import CandidatePatch, PatchIntentDecision


class PatchIntentCompilationError(ValueError):
    """A Patch Intent cannot be deterministically applied to its source text."""

    def __init__(self, validation_errors: list[dict[str, object]]) -> None:
        super().__init__("Patch Intent cannot be compiled deterministically")
        self.validation_errors = validation_errors


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


def _match_offsets(source_text: str, old_text: str) -> list[int]:
    matches: list[int] = []
    offset = 0
    while True:
        match = source_text.find(old_text, offset)
        if match < 0:
            return matches
        matches.append(match)
        offset = match + 1


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
