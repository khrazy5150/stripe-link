import unittest

from stripe_link.domain.funnels import FunnelError, resolve_funnel_transition


def post_checkout(**overrides):
    base = {
        "thank_you_page": {"page_id": "page_thank_you"},
        "funnel_steps": [
            {"step_id": "upsell_1", "page_id": "page_upsell_1", "on_accept": "thank_you", "on_decline": "downsell_1"},
            {"step_id": "downsell_1", "page_id": "page_downsell_1", "on_accept": "thank_you", "on_decline": "thank_you"},
        ],
    }
    base.update(overrides)
    return base


class ResolveFunnelTransitionTests(unittest.TestCase):
    def test_first_hop_resolves_to_first_step(self):
        destination = resolve_funnel_transition(post_checkout(), current_step_id=None, outcome="accept")
        self.assertEqual(destination, {"kind": "page", "page_id": "page_upsell_1", "step_id": "upsell_1"})

    def test_first_hop_with_no_steps_resolves_to_thank_you_page(self):
        destination = resolve_funnel_transition(post_checkout(funnel_steps=[]), current_step_id=None, outcome="accept")
        self.assertEqual(destination, {"kind": "page", "page_id": "page_thank_you", "step_id": "thank_you"})

    def test_first_hop_with_no_steps_resolves_to_external_thank_you_url(self):
        destination = resolve_funnel_transition(
            post_checkout(funnel_steps=[], thank_you_page={"url": "https://example.com/thanks"}),
            current_step_id=None,
            outcome="accept",
        )
        self.assertEqual(destination, {"kind": "url", "url": "https://example.com/thanks"})

    def test_declining_upsell_routes_to_downsell(self):
        destination = resolve_funnel_transition(post_checkout(), current_step_id="upsell_1", outcome="decline")
        self.assertEqual(destination, {"kind": "page", "page_id": "page_downsell_1", "step_id": "downsell_1"})

    def test_accepting_upsell_routes_to_thank_you(self):
        destination = resolve_funnel_transition(post_checkout(), current_step_id="upsell_1", outcome="accept")
        self.assertEqual(destination, {"kind": "page", "page_id": "page_thank_you", "step_id": "thank_you"})

    def test_declining_downsell_terminates_at_thank_you(self):
        destination = resolve_funnel_transition(post_checkout(), current_step_id="downsell_1", outcome="decline")
        self.assertEqual(destination, {"kind": "page", "page_id": "page_thank_you", "step_id": "thank_you"})

    def test_unknown_current_step_raises(self):
        with self.assertRaises(FunnelError):
            resolve_funnel_transition(post_checkout(), current_step_id="not_a_step", outcome="accept")

    def test_unknown_target_step_raises(self):
        broken = post_checkout(funnel_steps=[
            {"step_id": "upsell_1", "page_id": "page_upsell_1", "on_accept": "missing_step", "on_decline": "thank_you"},
        ])
        with self.assertRaises(FunnelError):
            resolve_funnel_transition(broken, current_step_id="upsell_1", outcome="accept")

    def test_detached_funnel_id_is_rejected_as_unsupported(self):
        with self.assertRaises(FunnelError):
            resolve_funnel_transition({"funnel_id": "funnel_123"}, current_step_id=None, outcome="accept")

    def test_invalid_outcome_raises(self):
        with self.assertRaises(FunnelError):
            resolve_funnel_transition(post_checkout(), current_step_id="upsell_1", outcome="maybe")

    def test_missing_thank_you_configuration_raises(self):
        with self.assertRaises(FunnelError):
            resolve_funnel_transition({}, current_step_id=None, outcome="accept")


if __name__ == "__main__":
    unittest.main()
