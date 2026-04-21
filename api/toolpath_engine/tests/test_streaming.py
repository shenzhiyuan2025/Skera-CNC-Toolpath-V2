import io
import unittest

from api.toolpath_engine import evaluate_fileobj


class ToolpathStreamingTests(unittest.TestCase):
    def test_sampling_sets_meta_and_truncated(self):
        gcode = "\n".join(
            [
                "G21",
                "G90",
                "G0 X0 Y0 Z25",
                "G1 Z-1 F200",
                "G1 X20 Y0 F600",
                "G0 Z25",
                "M30",
            ]
        )
        res = evaluate_fileobj(io.BytesIO(gcode.encode("utf-8")), max_lines=3)
        sampling = (res.task_meta or {}).get("sampling") or {}
        self.assertTrue(bool(sampling.get("sampled")))
        self.assertEqual(int(sampling.get("max_lines") or 0), 3)
        self.assertTrue(bool(sampling.get("truncated")))

    def test_stop_on_first_blocker(self):
        tail = "\n".join([f"G0 X0 Y0 Z25 ; {i}" for i in range(20000)])
        gcode = "\n".join(
            [
                "G21",
                "G90",
                "G0 X0 Y0 Z25",
                "G0 X9999 Y0 Z25",
                tail,
            ]
        )
        res = evaluate_fileobj(io.BytesIO(gcode.encode("utf-8")))
        self.assertEqual(res.final_conclusion.value, "red")
        self.assertEqual(res.total_score, 0.0)
        self.assertGreaterEqual(int(res.issue_counts.get("blocker", 0)), 1)
        self.assertLess(int(res.metrics.get("total_lines", 0)), 200)


if __name__ == "__main__":
    unittest.main()

