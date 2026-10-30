import unittest

from scripts import run_fast_context_grounding_experiment as grounding


class FastContextGroundingExperimentTests(unittest.TestCase):
    def test_fixed_context_contains_no_retrieval_results(self):
        bundle = grounding._context_bundle(
            ("Пользователь предпочитает кофе эспрессо.",)
        )
        self.assertEqual(bundle["consumer"], "FAST")
        self.assertEqual(bundle["selection_stats"]["retrieval_candidates"], 0)
        self.assertEqual(bundle["selection_stats"]["retrieval_returned"], 0)
        self.assertEqual(
            bundle["memories"][0]["record"]["content"],
            "Пользователь предпочитает кофе эспрессо.",
        )

    def test_a0_uses_current_fast_renderer(self):
        case = grounding.GROUNDING_CASES[0]
        system_prompt, user_prompt = grounding._render_a0(case)
        self.assertIn("FAST", system_prompt)
        self.assertIn("КОНТЕКСТ ИЗ ПАМЯТИ ANIMA", user_prompt)
        self.assertIn("эспрессо", user_prompt)
        self.assertIn(case["query"], user_prompt)

    def test_a1_and_a2_preserve_fixed_facts(self):
        case = grounding.GROUNDING_CASES[0]
        _, a1 = grounding._render_a1(case)
        _, a2 = grounding._render_a2(case)
        self.assertIn("FACTS:", a1)
        self.assertIn("эспрессо", a1)
        self.assertNotIn("EXAMPLE:", a1)
        self.assertIn("EXAMPLE:", a2)
        self.assertIn("эспрессо", a2)
        self.assertIn(case["query"], a2)

    def test_evaluator_accepts_grounded_and_unknown_answers(self):
        direct = grounding.GROUNDING_CASES[0]
        missing = grounding.GROUNDING_CASES[1]
        self.assertTrue(
            grounding._evaluate("Ты предпочитаешь эспрессо.", direct)["passed"]
        )
        self.assertTrue(
            grounding._evaluate("У меня нет информации об имени собаки.", missing)[
                "passed"
            ]
        )
        self.assertFalse(
            grounding._evaluate("Собаку зовут Барсик.", missing)["passed"]
        )


if __name__ == "__main__":
    unittest.main()
