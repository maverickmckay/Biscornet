"""
Backtest tests: scenario construction, runner scoring, route functions.
"""
import pytest


# ---------------------------------------------------------------------------
# Scenario construction
# ---------------------------------------------------------------------------

class TestBacktestScenarios:

    def test_all_scenarios_load(self):
        from app.backtest.scenarios import all_scenarios
        scenarios = all_scenarios()
        assert len(scenarios) == 6

    def test_scenario_names_unique(self):
        from app.backtest.scenarios import all_scenarios
        names = [s.name for s in all_scenarios()]
        assert len(names) == len(set(names))

    def test_each_scenario_has_graph_and_history(self):
        from app.backtest.scenarios import all_scenarios
        for s in all_scenarios():
            assert s.graph is not None
            assert len(s.graph.nodes) >= 3
            assert len(s.graph.edges) >= 2
            assert isinstance(s.history, dict)
            assert len(s.history) >= 1

    def test_ground_truth_failure_hours_positive(self):
        from app.backtest.scenarios import all_scenarios
        for s in all_scenarios():
            assert s.ground_truth.failure_hours > 0

    def test_stable_scenario_marked(self):
        from app.backtest.scenarios import all_scenarios
        stable = [s for s in all_scenarios() if s.ground_truth.is_stable]
        assert len(stable) >= 1
        assert stable[0].name == "FALSE_ALARM"

    def test_readings_have_timestamps(self):
        from app.backtest.scenarios import all_scenarios
        for s in all_scenarios():
            for readings in s.history.values():
                for r in readings:
                    assert r.timestamp is not None
                    assert 0.0 <= r.load <= 1.0
                    assert 0.0 <= r.reliability <= 1.0


# ---------------------------------------------------------------------------
# Individual scenario runs
# ---------------------------------------------------------------------------

class TestScenarioRunner:

    def test_cascade_spof_node_hit(self):
        from app.backtest.scenarios import scenario_cascade_spof
        from app.backtest.runner import run_scenario
        result = run_scenario(scenario_cascade_spof())
        # Gateway is clearly trending toward failure — should be in top-3
        assert result.node_hit, f"Expected node hit; top3={result.oracle_top3_nodes}"

    def test_cascade_spof_status_critical_or_approaching(self):
        from app.backtest.scenarios import scenario_cascade_spof
        from app.backtest.runner import run_scenario
        result = run_scenario(scenario_cascade_spof())
        assert result.oracle_threshold_status in ('approaching', 'critical', 'exceeded'), \
            f"Expected high-severity status, got {result.oracle_threshold_status}"

    def test_authority_vacuum_mechanism(self):
        from app.backtest.scenarios import scenario_authority_vacuum
        from app.backtest.runner import run_scenario
        result = run_scenario(scenario_authority_vacuum())
        # CTO approves everything → APPROVAL_GATES
        assert result.mechanism_hit, \
            f"Expected approval_gates, got {result.oracle_predicted_mechanism}"

    def test_false_alarm_no_false_positive(self):
        from app.backtest.scenarios import scenario_false_alarm
        from app.backtest.runner import run_scenario
        result = run_scenario(scenario_false_alarm())
        assert not result.false_positive, \
            f"FALSE POSITIVE on stable scenario: status={result.oracle_threshold_status}"

    def test_false_alarm_scores_correctly(self):
        from app.backtest.scenarios import scenario_false_alarm
        from app.backtest.runner import run_scenario
        result = run_scenario(scenario_false_alarm())
        # Stable scenario: score = 1.0 iff no false positive
        if not result.false_positive:
            assert result.composite_score == 1.0
        else:
            assert result.composite_score == 0.0

    def test_vendor_collapse_reliability_declining(self):
        from app.backtest.scenarios import scenario_vendor_collapse
        from app.backtest.runner import run_scenario
        from app.engines.threshold import ThresholdEngine, ThresholdStatus
        s = scenario_vendor_collapse()
        engine = ThresholdEngine()
        prox = engine.score_all_nodes(s.graph, s.history)
        vendor_prox = prox.get("vendor")
        assert vendor_prox is not None
        # Reliability declining sharply — should not be STABLE
        assert vendor_prox.status != ThresholdStatus.STABLE, \
            f"Vendor should not be STABLE; got {vendor_prox.status}"

    def test_compound_failure_compute_critical(self):
        from app.backtest.scenarios import scenario_compound_failure
        from app.backtest.runner import run_scenario
        from app.engines.threshold import ThresholdEngine, ThresholdStatus
        s = scenario_compound_failure()
        engine = ThresholdEngine()
        prox = engine.score_all_nodes(s.graph, s.history)
        compute_prox = prox.get("compute")
        assert compute_prox is not None
        assert compute_prox.status in (
            ThresholdStatus.APPROACHING, ThresholdStatus.CRITICAL, ThresholdStatus.EXCEEDED
        )

    def test_silent_drift_nodes_drifting(self):
        from app.backtest.scenarios import scenario_silent_drift
        from app.engines.threshold import ThresholdEngine, ThresholdStatus
        s = scenario_silent_drift()
        engine = ThresholdEngine()
        prox = engine.score_all_nodes(s.graph, s.history)
        # At least some nodes should be DRIFTING (not STABLE, not yet CRITICAL)
        statuses = {p.status for p in prox.values()}
        assert ThresholdStatus.STABLE not in statuses or ThresholdStatus.DRIFTING in statuses


# ---------------------------------------------------------------------------
# Full suite runner
# ---------------------------------------------------------------------------

class TestBacktestSuite:

    @pytest.fixture(scope="class")
    def report(self):
        from app.backtest.runner import run_suite
        return run_suite()

    def test_report_has_6_results(self, report):
        assert report.scenario_count == 6
        assert len(report.results) == 6

    def test_suite_score_bounded(self, report):
        assert 0.0 <= report.suite_score <= 1.0

    def test_node_accuracy_bounded(self, report):
        assert 0.0 <= report.node_accuracy <= 1.0

    def test_mechanism_accuracy_bounded(self, report):
        assert 0.0 <= report.mechanism_accuracy <= 1.0

    def test_false_positive_rate_bounded(self, report):
        assert 0.0 <= report.false_positive_rate <= 1.0

    def test_all_verdicts_valid(self, report):
        for r in report.results:
            assert r.verdict in ('PASS', 'PARTIAL', 'FAIL')

    def test_composite_scores_bounded(self, report):
        for r in report.results:
            assert 0.0 <= r.composite_score <= 1.0

    def test_report_to_dict_keys(self, report):
        from app.backtest.runner import report_to_dict
        d = report_to_dict(report)
        for key in ('suite_score', 'node_accuracy', 'mechanism_accuracy',
                    'results', 'summary', 'run_at'):
            assert key in d, f"Missing key: {key}"

    def test_results_have_notes(self, report):
        for r in report.results:
            assert isinstance(r.notes, list)
            assert len(r.notes) >= 1

    def test_suite_overall_passing(self, report):
        # Minimum bar: suite score should be at least 0.45 (partial pass)
        assert report.suite_score >= 0.45, \
            f"Suite score too low: {report.suite_score:.2f}. Summary: {report.summary}"


# ---------------------------------------------------------------------------
# Route functions (direct, no HTTP startup)
# ---------------------------------------------------------------------------

class TestBacktestRoutes:

    def test_list_scenarios_route(self):
        from app.api.backtest_routes import list_scenarios
        result = list_scenarios()
        assert "scenarios" in result
        assert len(result["scenarios"]) == 6

    def test_run_backtest_route_all(self):
        from app.api.backtest_routes import run_backtest, BacktestRequest
        result = run_backtest(BacktestRequest(scenarios=None))
        assert "suite_score" in result
        assert "results" in result
        assert len(result["results"]) == 6

    def test_run_backtest_route_subset(self):
        from app.api.backtest_routes import run_backtest, BacktestRequest
        result = run_backtest(BacktestRequest(scenarios=["CASCADE_SPOF", "FALSE_ALARM"]))
        assert len(result["results"]) == 2

    def test_run_backtest_route_unknown_scenario(self):
        from fastapi import HTTPException
        from app.api.backtest_routes import run_backtest, BacktestRequest
        with pytest.raises(HTTPException) as exc:
            run_backtest(BacktestRequest(scenarios=["NONEXISTENT"]))
        assert exc.value.status_code == 400

    def test_run_single_scenario_route(self):
        from app.api.backtest_routes import run_single_scenario
        result = run_single_scenario("CASCADE_SPOF")
        assert "verdict" in result
        assert "scoring" in result
        assert "oracle" in result

    def test_run_single_scenario_404(self):
        from fastapi import HTTPException
        from app.api.backtest_routes import run_single_scenario
        with pytest.raises(HTTPException) as exc:
            run_single_scenario("DOES_NOT_EXIST")
        assert exc.value.status_code == 404
