import unittest

from agent.events import assignment_event, error_event, report_event, review_event, tool_call_event


class EventSchemaTests(unittest.TestCase):
    def test_tool_call_event_carries_type_data_and_timestamp(self):
        event = tool_call_event("read_file", {"path": "README.md"}, agent="Worker_1", primary=False)
        self.assertEqual(event["type"], "tool_call")
        self.assertEqual(event["agent"], "Worker_1")
        self.assertEqual(event["data"]["name"], "read_file")
        self.assertEqual(event["data"]["args"]["path"], "README.md")
        self.assertIn("ts", event)
        self.assertFalse(event["meta"]["primary"])

    def test_report_and_review_events_include_structured_fields(self):
        report = report_event(
            "Worker_1",
            "short summary",
            full_report="full report body",
            findings=["a"],
            completed_actions=["b"],
            evidence=["c"],
            open_questions=["d"],
            round_index=2,
        )
        review = review_event("Supervisor", "Looks good", "complete", final_answer="done", round_index=2)
        self.assertEqual(report["data"]["summary"], "short summary")
        self.assertEqual(report["data"]["full_report"], "full report body")
        self.assertEqual(report["data"]["findings"], ["a"])
        self.assertEqual(report["data"]["completed_actions"], ["b"])
        self.assertEqual(report["meta"]["round"], 2)
        self.assertEqual(review["data"]["status"], "complete")
        self.assertEqual(review["data"]["final_answer"], "done")

    def test_assignment_and_error_events_are_ui_friendly(self):
        assignment = assignment_event("Worker_2", "Tester", "Verify the flow", round_index=1)
        failure = error_event("HTTP Error 500", agent="Supervisor", code="backend_http_error")
        self.assertEqual(assignment["data"]["role"], "Tester")
        self.assertEqual(assignment["data"]["task"], "Verify the flow")
        self.assertEqual(failure["data"], "HTTP Error 500")
        self.assertEqual(failure["meta"]["code"], "backend_http_error")
