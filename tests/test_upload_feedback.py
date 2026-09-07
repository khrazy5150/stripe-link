"""How long an upload FEELS, which is not the same as how long it takes.

Measured 2026-09-07 when a tenant reported a short vertical video taking "a really long time":

  processor duration   ~2s, using 119MB of its 1024MB     -> memory was never the constraint
  SQS DelaySeconds     0                                  -> the queue adds nothing
  status poll          ~0.45s warm, ~2.8s cold
  client schedule      checks at 1.5s, 3.5s, 6.3s, 9.9s   -> a 2s job unnoticed until 3.5s

So the wait was the client's, not the server's -- and the button said "Uploading..." for the whole of it,
covering a byte transfer and a server-side job with one word and no percentage. Raising Lambda memory would
have cost money and changed nothing.
"""

import pathlib
import re
import unittest

UPLOADS = (pathlib.Path(__file__).resolve().parents[1] / "dashboard/src/api/uploads.js").read_text()
BUILDER = (pathlib.Path(__file__).resolve().parents[1]
           / "dashboard/src/components/LandingPages.vue").read_text()


def schedule(start, mult, cap, count=10):
    delay, elapsed, checks = start, 0, []
    for _ in range(count):
        elapsed += delay
        checks.append(elapsed / 1000)
        delay = min(cap, -(-delay * int(mult * 100) // 100))
    return checks


class PollingTests(unittest.TestCase):
    def _params(self, fn):
        body = UPLOADS[UPLOADS.index(f"async function {fn}("):]
        body = body[:body.index("\n}")]
        start = int(re.search(r"let delay = (\d+)", body).group(1))
        cap, mult = re.search(r"Math\.min\((\d+), Math\.ceil\(delay \* ([\d.]+)\)\)", body).groups()
        return start, float(mult), int(cap)

    def test_the_first_check_lands_before_a_typical_job_finishes(self):
        # The processor takes ~2s. Opening at 1500ms meant the first look was always too early and the
        # second did not arrive until 3.5s.
        for fn in ("pollVideoUrl", "pollImageUrl"):
            with self.subTest(fn=fn):
                start, _, _ = self._params(fn)
                self.assertLessEqual(start, 700, "the opening delay overshoots the work it waits for")

    def test_the_backoff_does_not_run_away(self):
        for fn in ("pollVideoUrl", "pollImageUrl"):
            with self.subTest(fn=fn):
                _, mult, cap = self._params(fn)
                self.assertLessEqual(mult, 1.3)
                self.assertLessEqual(cap, 3000, "an 8s ceiling adds most of a wait to a job already done")

    def test_a_finished_job_is_noticed_promptly(self):
        start, mult, cap = self._params("pollVideoUrl")
        checks = schedule(start, mult, cap)
        for job, limit in ((2, 3.5), (4, 5.0), (7, 9.0)):
            with self.subTest(job=job):
                noticed = next(c for c in checks if c >= job)
                self.assertLess(noticed, limit, f"a {job}s job is not noticed until {noticed}s")


class FeedbackTests(unittest.TestCase):
    """An opaque wait feels far longer than a visible one."""

    def test_the_transfer_reports_progress(self):
        # fetch() cannot report upload progress at all, which is why the whole transfer was silent.
        self.assertIn("XMLHttpRequest", UPLOADS)
        self.assertIn("xhr.upload.addEventListener", UPLOADS)
        self.assertNotIn('fetch(presigned.upload.url', UPLOADS.split("uploadVideo")[1][:1200])

    def test_the_two_phases_are_distinguished(self):
        # Bytes moving and a server working are different waits; only one can report a percentage, and
        # leaving "Uploading" on screen while nothing uploads is a lie the tenant can feel.
        self.assertIn('phase: "processing"', UPLOADS)
        self.assertIn('phase: "uploading"', UPLOADS)

    def test_the_builder_shows_it(self):
        self.assertIn("elementVideoStatus", BUILDER)
        self.assertIn("Processing...", BUILDER)
        self.assertRegex(BUILDER, r"Uploading \$\{percent\}%")

    def test_the_status_is_cleared_when_finished(self):
        # A stale "Processing..." on a button that is ready again is worse than no status.
        self.assertIn('elementVideoStatus[element.id] = "";', BUILDER)


if __name__ == "__main__":
    unittest.main()
