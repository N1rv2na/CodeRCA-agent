from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from coderca.contracts import CandidatePatch, ExactReplacement, PatchIntentDecision
from coderca.patch_compiler import PatchIntentCompilationError, compile_candidate_patch


def test_patch_intent_accepts_one_to_three_exact_replacements() -> None:
    one = PatchIntentDecision(
        hypothesis_id="H1",
        target_path="src/module.py",
        mechanism="Preserve an explicit false value.",
        edits=(ExactReplacement(old_text="value = True", new_text="value = False"),),
    )
    three = one.model_copy(
        update={
            "edits": (
                ExactReplacement(old_text="one", new_text="ONE"),
                ExactReplacement(old_text="two", new_text="TWO"),
                ExactReplacement(old_text="three", new_text="THREE"),
            )
        }
    )

    assert len(one.edits) == 1
    assert len(three.edits) == 3


@pytest.mark.parametrize("edit_count", [0, 4])
def test_patch_intent_rejects_edit_counts_outside_mvp_bounds(
    edit_count: int,
) -> None:
    edits = tuple(
        {"old_text": f"old-{index}", "new_text": f"new-{index}"}
        for index in range(edit_count)
    )

    with pytest.raises(ValidationError):
        PatchIntentDecision.model_validate(
            {
                "hypothesis_id": "H1",
                "target_path": "src/module.py",
                "mechanism": "Apply bounded exact replacements.",
                "edits": edits,
            }
        )


def test_exact_replacement_allows_deletion_but_rejects_empty_or_no_op_source() -> None:
    deletion = ExactReplacement(old_text="obsolete()\n", new_text="")

    assert deletion.new_text == ""
    with pytest.raises(ValidationError):
        ExactReplacement(old_text="", new_text="replacement")
    with pytest.raises(ValidationError):
        ExactReplacement(old_text="same", new_text="same")


def test_patch_contracts_forbid_unrecognized_fields() -> None:
    with pytest.raises(ValidationError):
        PatchIntentDecision.model_validate(
            {
                "hypothesis_id": "H1",
                "target_path": "src/module.py",
                "mechanism": "Replace a value.",
                "edits": [{"old_text": "old", "new_text": "new"}],
                "unified_diff": "model must not supply this",
            }
        )


@pytest.mark.parametrize("contract", ["intent", "candidate"])
def test_patch_contracts_reject_whitespace_only_mechanism(contract: str) -> None:
    payload: dict[str, object] = {
        "hypothesis_id": "H1",
        "target_path": "src/module.py",
        "mechanism": "   ",
    }
    if contract == "intent":
        payload["edits"] = [{"old_text": "old", "new_text": "new"}]
        model = PatchIntentDecision
    else:
        payload["unified_diff"] = "--- a/src/module.py\n+++ b/src/module.py\n"
        model = CandidatePatch

    with pytest.raises(ValidationError):
        model.model_validate(payload)

    with pytest.raises(ValidationError):
        CandidatePatch.model_validate(
            {
                "hypothesis_id": "H1",
                "target_path": "src/module.py",
                "mechanism": "Replace a value.",
                "unified_diff": "--- a/src/module.py\n+++ b/src/module.py\n",
                "edits": [],
            }
        )


def patch_intent(*edits: ExactReplacement) -> PatchIntentDecision:
    return PatchIntentDecision(
        hypothesis_id="H1",
        target_path="waffle/utils.py",
        mechanism="Preserve case-sensitive cache keys.",
        edits=edits,
    )


def test_compiler_generates_git_applicable_task_2_patch(tmp_path: Path) -> None:
    source = (
        "def keyfmt(k: str, v: str | None = None) -> str:\n"
        "    if v is None:\n"
        "        key = prefix + k\n"
        "    else:\n"
        "        key = prefix + hashlib.md5(\n"
        "            (k % v.lower()).encode('utf-8')\n"
        "        ).hexdigest()\n"
        "    return key\n"
    )
    candidate = compile_candidate_patch(
        source,
        patch_intent(
            ExactReplacement(
                old_text="k % v.lower()",
                new_text="k % v",
            )
        ),
    )
    target = tmp_path / "waffle" / "utils.py"
    target.parent.mkdir(parents=True)
    target.write_text(source)

    completed = subprocess.run(
        ["git", "apply", "--no-index", "--check", "-"],
        cwd=tmp_path,
        input=candidate.unified_diff,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert candidate.unified_diff.startswith(
        "--- a/waffle/utils.py\n+++ b/waffle/utils.py\n"
    )
    assert "v.lower()" in candidate.unified_diff
    assert "-            (k % v.lower()).encode" in candidate.unified_diff
    assert "+            (k % v).encode" in candidate.unified_diff


def test_compiler_generates_applicable_patch_without_final_source_newline(
    tmp_path: Path,
) -> None:
    source = "value = True"
    intent = PatchIntentDecision(
        hypothesis_id="H1",
        target_path="module.py",
        mechanism="Preserve false.",
        edits=(ExactReplacement(old_text="True", new_text="False"),),
    )
    target = tmp_path / "module.py"
    target.write_text(source)

    candidate = compile_candidate_patch(source, intent)
    completed = subprocess.run(
        ["git", "apply", "--no-index", "--check", "-"],
        cwd=tmp_path,
        input=candidate.unified_diff,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "\\ No newline at end of file" in candidate.unified_diff


def test_compiler_applies_three_non_overlapping_replacements_and_deletion() -> None:
    source = "one\ntwo\nobsolete\nthree\n"

    candidate = compile_candidate_patch(
        source,
        patch_intent(
            ExactReplacement(old_text="one", new_text="ONE"),
            ExactReplacement(old_text="two\n", new_text="TWO\n"),
            ExactReplacement(old_text="obsolete\n", new_text=""),
        ),
    )

    assert "-one" in candidate.unified_diff
    assert "+ONE" in candidate.unified_diff
    assert "-obsolete" in candidate.unified_diff


@pytest.mark.parametrize(
    ("source", "edits", "reason"),
    [
        (
            "present\n",
            (ExactReplacement(old_text="missing", new_text="replacement"),),
            "missing_match",
        ),
        (
            "same\nsame\n",
            (ExactReplacement(old_text="same", new_text="different"),),
            "ambiguous_match",
        ),
        (
            "abcdef\n",
            (
                ExactReplacement(old_text="abc", new_text="ABC"),
                ExactReplacement(old_text="bc", new_text="BC"),
            ),
            "overlapping_edits",
        ),
    ],
)
def test_compiler_rejects_non_deterministic_exact_edits(
    source: str,
    edits: tuple[ExactReplacement, ...],
    reason: str,
) -> None:
    with pytest.raises(PatchIntentCompilationError) as captured:
        compile_candidate_patch(source, patch_intent(*edits))

    assert captured.value.validation_errors[0]["type"] == reason
