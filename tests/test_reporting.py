import unittest

from agent.reporting import EnhancedWorkerReport, WorkerReport, normalize_worker_report


class WorkerReportTests(unittest.TestCase):
    def test_normalize_worker_report_uses_payload_when_present(self):
        report = normalize_worker_report(
            "Worker_1",
            '{"summary":"Done","findings":["f1"],"completed_actions":["a1"],"evidence":["e1"],"open_questions":["q1"]}',
            {
                "summary": "Done",
                "findings": ["f1"],
                "completed_actions": ["a1"],
                "evidence": ["e1"],
                "open_questions": ["q1"],
            },
        )
        self.assertEqual(report.worker, "Worker_1")
        self.assertEqual(report.summary, "Done")
        self.assertEqual(report.findings, ["f1"])
        self.assertEqual(report.completed_actions, ["a1"])
        self.assertEqual(report.evidence, ["e1"])
        self.assertEqual(report.open_questions, ["q1"])

    def test_normalize_worker_report_falls_back_to_raw_output_summary(self):
        text = "Worker found two issues and verified the fix."
        report = normalize_worker_report("Worker_2", text, None)
        self.assertEqual(report.summary, text)
        self.assertEqual(report.raw_output, text)


class EnhancedWorkerReportTests(unittest.TestCase):
    def test_quality_score_zero_for_empty_report(self):
        report = EnhancedWorkerReport(worker="Worker_1", summary="")
        self.assertEqual(report.quality_score(), 0.0)

    def test_quality_score_increases_with_findings(self):
        report = EnhancedWorkerReport(
            worker="Worker_1",
            summary="Found issues",
            findings=["issue1", "issue2", "issue3"],
        )
        score = report.quality_score()
        self.assertGreater(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_quality_score_tool_calls_add_bonus(self):
        base = EnhancedWorkerReport(worker="W", summary="x", findings=["f1"])
        with_tools = EnhancedWorkerReport(worker="W", summary="x", findings=["f1"], tool_calls_made=3)
        self.assertGreater(with_tools.quality_score(), base.quality_score())

    def test_quality_score_capped_at_one(self):
        report = EnhancedWorkerReport(
            worker="Worker_1",
            summary="Rich output",
            findings=["f"] * 10,
            completed_actions=["a"] * 10,
            evidence=["e"] * 10,
            tool_calls_made=5,
        )
        self.assertEqual(report.quality_score(), 1.0)

    def test_enhanced_report_inherits_worker_report(self):
        report = EnhancedWorkerReport(worker="Worker_1", summary="s", duration_seconds=1.5, confidence=0.8)
        self.assertIsInstance(report, WorkerReport)
        self.assertEqual(report.duration_seconds, 1.5)
        self.assertEqual(report.confidence, 0.8)

    def test_as_dict_includes_enhanced_fields(self):
        report = EnhancedWorkerReport(worker="W", summary="s", tool_calls_made=2, duration_seconds=3.0)
        d = report.as_dict()
        self.assertIn("tool_calls_made", d)
        self.assertIn("duration_seconds", d)
        self.assertEqual(d["tool_calls_made"], 2)
