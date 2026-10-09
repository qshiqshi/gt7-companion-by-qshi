"""Every positive radio variant formats in either language and gets heard once."""
import random
import unittest
from gt7companion.engineer.texts import Texts


class RadioVariants(unittest.TestCase):
    def test_incident_and_best_lap_bags_play_every_variant_before_repeating(self):
        for language in ("de", "en"):
            for kind in ("best_lap", "spin", "crash"):
                with self.subTest(language=language, kind=kind):
                    texts = Texts(language, "Driver", rng=random.Random(7))
                    self.assertEqual(len(texts._lines[kind]), 50)
                    first = [texts.line(kind, time="1:39.9") for _ in range(50)]
                    second = [texts.line(kind, time="1:39.9") for _ in range(50)]
                    self.assertEqual(len(set(first)), 50)
                    self.assertEqual(set(first), set(second))
                    self.assertNotEqual(first[-1], second[0])
                    for line in first:
                        self.assertNotIn("{", line)
                        self.assertNotIn("A-Rank", line)


if __name__ == "__main__":
    unittest.main()
