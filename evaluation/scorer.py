import logging
import sys

from evaluation.golden_incidents import GOLDEN_INCIDENTS
from backend.orchestrator import AgentGraph
from backend.session import SessionManager

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (TypeError, ValueError):
        pass

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("evaluator")


def normalize_source(s):
    return s.lower().replace("_", "")


async def run_evaluation():
    session_manager = SessionManager()
    agent_graph = AgentGraph(session_manager)

    results = []
    total_score = 0
    max_score = 0

    print("=" * 70)
    print("PAGERPILOT - EVALUATION SUITE")
    print(f"Running {len(GOLDEN_INCIDENTS)} golden incident evaluations")
    print("=" * 70)

    for golden in GOLDEN_INCIDENTS:
        print(f"\n--- Evaluating: {golden['id']} ({golden['title']}) ---")

        result = await agent_graph.run(golden["id"])
        brief = result.get("brief")

        scores = {}
        score = 0
        max_possible = 0

        if brief:
            sources_used = len(brief.evidence_sources)
            expected_coverage = golden["scoring"]["evidence_coverage"]
            coverage_score = min(sources_used, expected_coverage)
            scores["evidence_coverage"] = {
                "score": coverage_score,
                "max": expected_coverage,
                "detail": f"Sources used: {sources_used}/{expected_coverage}",
            }
            score += coverage_score
            max_possible += expected_coverage

            expected_verdict = golden["expected_verdict"]
            hypotheses = brief.root_cause_hypotheses
            if hypotheses:
                top_title = hypotheses[0].title
                correct = expected_verdict.lower() in top_title.lower() or \
                         any(kw in top_title.lower() for kw in golden["expected_verdict"].lower().split())
                scores["correct_root_cause"] = {
                    "score": 1 if correct else 0,
                    "max": 1,
                    "detail": f"Top hypothesis: '{top_title}' | Expected: '{expected_verdict}' | {'PASS' if correct else 'FAIL'}",
                }
                score += 1 if correct else 0
                max_possible += 1
            else:
                scores["correct_root_cause"] = {
                    "score": 0,
                    "max": 1,
                    "detail": "No hypotheses generated",
                }
                max_possible += 1

            summary_len = len(brief.summary)
            has_recommendation = bool(brief.recommended_action)
            usefulness = 1 if summary_len > 50 and has_recommendation else 0
            scores["summary_usefulness"] = {
                "score": usefulness,
                "max": 1,
                "detail": f"Summary length: {summary_len} chars | Has recommendation: {has_recommendation} | {'PASS' if usefulness else 'FAIL'}",
            }
            score += usefulness
            max_possible += 1

            stages_run = len([l for l in result.get("logs", []) if l["action"] == "Agent completed"])
            expected_stages = 4
            scores["stages_completed"] = {
                "score": 1 if stages_run == expected_stages else 0,
                "max": 1,
                "detail": f"Stages completed: {stages_run}/{expected_stages}",
            }
            score += 1 if stages_run == expected_stages else 0
            max_possible += 1

            expected_sources = set(normalize_source(s) for s in golden["expected_sources"])
            actual_sources = set(normalize_source(s.value) for s in brief.evidence_sources)
            overlap = len(expected_sources & actual_sources)
            source_score = overlap / len(expected_sources) if expected_sources else 0
            scores["source_signal_accuracy"] = {
                "score": source_score,
                "max": 1,
                "detail": f"Expected: {golden['expected_sources']} | Got: {[s.value for s in brief.evidence_sources]}",
            }
            score += source_score
            max_possible += 1

        else:
            scores["error"] = {"score": 0, "max": 0, "detail": "No brief generated"}

        pct = round((score / max_possible) * 100, 1) if max_possible else 0
        total_score += score
        max_score += max_possible

        results.append({
            "incident_id": golden["id"],
            "type": golden["type"],
            "status": result["status"],
            "scores": scores,
            "total": score,
            "max": max_possible,
            "percentage": pct,
        })

        print(f"  Status: {result['status']}")
        for metric, data in scores.items():
            icon = "✓" if data["score"] >= data["max"] else "✗"
            print(f"  {icon} {metric}: {data['score']}/{data['max']} - {data['detail']}")
        print(f"  TOTAL: {score}/{max_possible} ({pct}%)")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    overall_pct = round((total_score / max_score) * 100, 1) if max_score else 0
    passed = sum(1 for r in results if r["percentage"] >= 70)
    total = len(results)
    print(f"Overall Score: {total_score}/{max_score} ({overall_pct}%)")
    print(f"Passed: {passed}/{total}")
    print(f"Failed: {total - passed}/{total}")
    print()

    for r in results:
        icon = "✓" if r["percentage"] >= 70 else "✗"
        print(f"  {icon} {r['incident_id']}: {r['percentage']}%")

    print()
    return results


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_evaluation())
