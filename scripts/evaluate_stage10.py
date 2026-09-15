#!/usr/bin/env python3
"""Compare saved Qwen/Gemini outputs on the same annotated stage-10 cases."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src")]

from kroika_contracts.contract_io import ContractValidationError, validate_document  # noqa: E402
from kroika_contracts.semantic import SemanticContractError, validate_ai_analysis  # noqa: E402


def _value(document: dict[str, Any], path: str) -> Any:
    value: Any = document
    for token in path.split("."):
        value = value[token]
    return value


def evaluate_provider(manifest: dict[str, Any], results_directory: Path) -> dict[str, Any]:
    total = len(manifest["cases"])
    present = schema_valid = semantic_valid = label_total = label_correct = 0
    latencies: list[float] = []
    costs: list[float] = []
    brier_terms: list[float] = []
    per_feature: dict[str, list[int]] = {}
    question_hits = question_total = 0
    for case in manifest["cases"]:
        path = results_directory / f"{case['case_id']}.json"
        if not path.is_file():
            continue
        present += 1
        record = json.loads(path.read_text(encoding="utf-8"))
        analysis = record.get("analysis", record)
        if "latency_ms" in record:
            latencies.append(float(record["latency_ms"]))
        if "cost_usd" in record:
            costs.append(float(record["cost_usd"]))
        try:
            validate_document("ai-style-analysis", analysis)
            schema_valid += 1
            validate_ai_analysis(analysis)
            semantic_valid += 1
        except (ContractValidationError, SemanticContractError):
            continue
        for feature, expected in case["labels"].items():
            actual = _value(analysis, feature)
            correct = int(actual == expected)
            label_total += 1
            label_correct += correct
            stats = per_feature.setdefault(feature, [0, 0])
            stats[0] += correct
            stats[1] += 1
            section = feature.split(".", 1)[0]
            section_value = analysis.get(section, {})
            confidence = section_value.get("confidence") if isinstance(section_value, dict) else None
            if isinstance(confidence, (int, float)):
                brier_terms.append((float(confidence) - correct) ** 2)
        if case.get("requires_question"):
            question_total += 1
            question_hits += int(bool(analysis.get("targeted_questions")))
    return {
        "expected_cases": total,
        "completed_cases": present,
        "schema_valid_rate": schema_valid / present if present else 0.0,
        "semantic_valid_rate": semantic_valid / present if present else 0.0,
        "label_accuracy": label_correct / label_total if label_total else 0.0,
        "question_recall": question_hits / question_total if question_total else 0.0,
        "confidence_brier": statistics.fmean(brier_terms) if brier_terms else None,
        "latency_p50_ms": statistics.median(latencies) if latencies else None,
        "mean_cost_usd": statistics.fmean(costs) if costs else None,
        "per_feature_accuracy": {
            feature: correct / count for feature, (correct, count) in sorted(per_feature.items())
        },
    }


def can_select_default(manifest: dict[str, Any], comparisons: dict[str, dict[str, Any]]) -> bool:
    expert_cases = sum(
        case.get("annotation_status") == "expert_verified" for case in manifest["cases"]
    )
    return (
        manifest.get("eligible_for_default_selection") is True
        and expert_cases >= 50
        and {"qwen", "gemini"}.issubset(comparisons)
        and all(item["completed_cases"] >= 50 for item in comparisons.values())
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=ROOT / "evaluation/stage10/manifest.json")
    parser.add_argument("--results", type=Path, default=ROOT / "evaluation/stage10/results")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    comparisons = {
        provider: evaluate_provider(manifest, args.results / provider)
        for provider in ("qwen", "gemini")
        if (args.results / provider).is_dir()
    }
    report = {
        "dataset_id": manifest["dataset_id"],
        "providers": comparisons,
        "default_selection_allowed": can_select_default(manifest, comparisons),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
