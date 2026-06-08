import unittest

from stripe_link.ids import generate_id, generate_local_id


class IdGenerationTests(unittest.TestCase):
    def test_generate_id_returns_padded_base62_snowflake(self):
        value = generate_id()

        self.assertEqual(len(value), 11)
        self.assertRegex(value, r"^[0-9A-Za-z]{11}$")

    def test_generate_local_id_uses_local_prefix(self):
        value = generate_local_id()

        self.assertRegex(value, r"^local_[0-9A-Za-z]{11}$")

    def test_generate_id_is_unique_and_time_ordered(self):
        values = [generate_id() for _ in range(50)]

        self.assertEqual(len(values), len(set(values)))
        self.assertEqual(values, sorted(values))


if __name__ == "__main__":
    unittest.main()
