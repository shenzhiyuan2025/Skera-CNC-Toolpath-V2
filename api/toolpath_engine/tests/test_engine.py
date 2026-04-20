import unittest

from api.toolpath_engine import evaluate_gcode


class ToolpathEngineTests(unittest.TestCase):
    def test_safe_gcode_green_or_yellow(self):
        gcode = "\n".join(
            [
                "G21",
                "G90",
                "G17",
                "G0 X0 Y0 Z25",
                "G1 Z-1 F200",
                "G1 X20 Y0 F600",
                "G0 Z25",
                "M30",
            ]
        )
        result = evaluate_gcode(gcode, file_name="demo.nc", software_source="AICAM", machine_model="Desk 5X CNC")
        self.assertIn(result.final_conclusion.value, {"green", "yellow"})
        self.assertTrue(result.allow_continue)
        self.assertIn("D1", result.dimension_scores)
        self.assertIn("D4", result.dimension_scores)
        self.assertIn("D6", result.dimension_scores)
        self.assertGreaterEqual(result.total_score, 0.0)

    def test_axis_limit_blocker(self):
        gcode = "\n".join(
            [
                "G21",
                "G90",
                "G0 X0 Y0 Z25",
                "G0 X9999 Y0 Z25",
                "M30",
            ]
        )
        result = evaluate_gcode(gcode)
        self.assertEqual(result.final_conclusion.value, "red")
        self.assertFalse(result.allow_continue)
        self.assertGreaterEqual(result.issue_counts.get("blocker", 0), 1)
        self.assertEqual(result.total_score, 0.0)

    def test_low_z_rapid_is_not_blocker_by_default(self):
        gcode = "\n".join(
            [
                "G21",
                "G90",
                "G0 X0 Y0 Z5",
                "G0 X20 Y0",
                "G1 Z-1 F200",
                "M30",
            ]
        )
        result = evaluate_gcode(gcode)
        self.assertNotEqual(result.final_conclusion.value, "red")
        self.assertEqual(result.issue_counts.get("blocker", 0), 0)
        self.assertTrue(any(i.code == "D1_RAP_001" for i in result.issues))


if __name__ == "__main__":
    unittest.main()
