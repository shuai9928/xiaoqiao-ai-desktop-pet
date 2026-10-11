"""Frame-rate independent chance of occasional events (Fix A2).

Fix A keeps a napping pet in the 100 ms tier almost all the time. Two occasional
events used `random.random() < 0.006` once PER FRAME, so at 100 ms they would have
become three times rarer in real time (visible zzz duty ~32% -> ~11%, and the bored
self-kick of the swing). frame_prob() converts the per-frame chance into a per-time
chance; at the reference interval it equals the old value.
"""
import re
import unittest

import pet


class FrameProbTests(unittest.TestCase):
    def test_equals_the_old_value_at_the_reference_interval(self):
        self.assertAlmostEqual(pet.frame_prob(0.006, 1.0 / 30.0), 0.006, places=12)
        self.assertAlmostEqual(pet.frame_prob(0.006, 0.05, 0.05), 0.006, places=12)

    def test_slower_frames_get_proportionally_more_chance(self):
        p = 0.006
        self.assertAlmostEqual(pet.frame_prob(p, 0.1), 1 - (1 - p) ** 3, places=12)
        self.assertGreater(pet.frame_prob(p, 0.1), 2.9 * p)
        self.assertLess(pet.frame_prob(p, 0.1), 3.0 * p)
        self.assertLess(pet.frame_prob(p, 0.02), p)

    def test_no_event_probability_per_second_is_frame_rate_independent(self):
        p = 0.006
        for fps in (10, 20, 30, 60):
            q = pet.frame_prob(p, 1.0 / fps)
            self.assertAlmostEqual((1 - q) ** fps, (1 - p) ** 30, places=9, msg=fps)

    def test_bounds(self):
        self.assertEqual(pet.frame_prob(0.006, 0.0), 0.0)
        self.assertEqual(pet.frame_prob(0.006, -1.0), 0.0)
        self.assertEqual(pet.frame_prob(0.0, 0.1), 0.0)
        self.assertEqual(pet.frame_prob(1.0, 0.001), 1.0)
        for dt in (0.001, 0.016, 0.033, 0.05, 0.1, 0.25):
            self.assertTrue(0.0 < pet.frame_prob(0.006, dt) < 1.0)

    def test_the_two_nap_rolls_use_it(self):
        src = open(pet.__file__, encoding="utf-8").read()
        self.assertNotIn("random.random() < 0.006", src)
        self.assertEqual(len(re.findall(r"random\.random\(\) < frame_prob\(0\.006, dts", src)), 2)


if __name__ == "__main__":
    unittest.main()
