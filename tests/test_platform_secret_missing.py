import unittest
from unittest import mock
from stripe_link import stripe_platform_secrets as sps


class AMissingSecretIsUnconfiguredNotACrashTests(unittest.TestCase):
    """The prod ARN pointed at a stripe-cart secret deleted with that stack. boto3's
    ResourceNotFoundException escaped as an unhandled 502, which API Gateway answers WITHOUT CORS, so the
    dashboard showed the bare "Failed to fetch" and could never name the problem."""

    def setUp(self):
        sps._CACHE.clear()
        self.env = mock.patch.dict("os.environ", {
            "STRIPE_PLATFORM_SECRET_ARN": "arn:aws:secretsmanager:us-west-2:1:secret:gone-Ab12Cd"}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(sps._CACHE.clear)

    def _boto(self, exc):
        client = mock.Mock()
        client.get_secret_value.side_effect = exc
        boto3 = mock.Mock()
        boto3.client.return_value = client
        return mock.patch.dict("sys.modules", {"boto3": boto3}), client

    def test_a_deleted_secret_yields_no_key_instead_of_raising(self):
        patch, _ = self._boto(Exception("ResourceNotFoundException: can't find the specified secret"))
        with patch:
            self.assertEqual(sps._load_secret_payload(), {})
            self.assertIsNone(sps.get_platform_secret_key("live"))

    def test_the_failure_is_NOT_cached_so_creating_the_secret_needs_no_redeploy(self):
        """A warm container would otherwise answer 'not configured' long after the secret existed --
        and the sweeps that share these containers keep them warm indefinitely."""
        patch, client = self._boto(Exception("ResourceNotFoundException"))
        with patch:
            sps._load_secret_payload()
        self.assertNotIn("payload", sps._CACHE)
        ok = mock.Mock()
        ok.get_secret_value.return_value = {"SecretString": '{"sk_live": "sk_live_restored"}'}
        boto3 = mock.Mock(); boto3.client.return_value = ok
        with mock.patch.dict("sys.modules", {"boto3": boto3}):
            self.assertEqual(sps.get_platform_secret_key("live"), "sk_live_restored")

    def test_an_absent_ARN_is_still_cached(self):
        """That cannot change without a redeploy, so caching it is correct -- the distinction the fix
        turns on."""
        sps._CACHE.clear()
        with mock.patch.dict("os.environ", {"STRIPE_PLATFORM_SECRET_ARN": "",
                                            "PLATFORM_STRIPE_SECRET_ARN": ""}, clear=False):
            self.assertEqual(sps._load_secret_payload(), {})
            self.assertIn("payload", sps._CACHE)


if __name__ == "__main__":
    unittest.main()
