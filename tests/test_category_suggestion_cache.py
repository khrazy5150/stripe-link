"""Category suggestions: the whole scoped set, filtered locally.

The autocomplete called the API on every focus AND every 180ms typing pause, each one a Lambda invoke plus
a full DynamoDB scan of contributed categories. plans/PRODUCT_CATEGORY_AUTOCOMPLETE.md line 90 asked for
fetch-once-and-filter-locally; the word "may" enforced nothing and it was never built.

Filtering locally is only CORRECT over a complete set, which is why the endpoint had to learn `limit`:
its default of 20 is a typeahead page, and 28 curated categories already exceed it. A cached page of 20
filtered locally is fast and silently wrong — the failure this codebase keeps producing.
"""

import json
import shutil
import subprocess
import pathlib
import unittest

from handlers.product_categories import DEFAULT_SUGGESTION_LIMIT, MAX_SUGGESTION_LIMIT, handler
from stripe_link.domain.categories import CURATED_CATEGORIES

ROOT = pathlib.Path(__file__).resolve().parents[1]
UTIL = ROOT / "dashboard" / "src" / "utils" / "categories.js"


class FakeCategoriesRepo:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.scans = 0

    def list_all(self):
        self.scans += 1
        return list(self.rows)


def get(params, repo=None):
    event = {"httpMethod": "GET", "queryStringParameters": params}
    response = handler(event, None, repository=repo or FakeCategoriesRepo())
    return json.loads(response["body"])["categories"]


class SuggestionLimitTests(unittest.TestCase):
    def test_the_default_is_a_typeahead_page_and_truncates_the_catalog(self):
        # Establishes WHY limit had to exist: the default cannot represent the whole set.
        self.assertGreater(len(CURATED_CATEGORIES), DEFAULT_SUGGESTION_LIMIT)
        self.assertEqual(len(get({})), DEFAULT_SUGGESTION_LIMIT)

    def test_a_client_can_ask_for_the_whole_scoped_set(self):
        rows = get({"limit": "500"})
        self.assertEqual(len(rows), len(CURATED_CATEGORIES))

    def test_limit_is_capped(self):
        self.assertLessEqual(len(get({"limit": "999999"})), MAX_SUGGESTION_LIMIT)

    def test_a_nonsense_limit_falls_back_to_the_default(self):
        for bad in ("abc", "-1", "0"):
            with self.subTest(limit=bad):
                self.assertEqual(len(get({"limit": bad})), DEFAULT_SUGGESTION_LIMIT)

    def test_every_request_still_scans_once_which_is_what_caching_reduces(self):
        # Not a defect — it is the cost the client-side cache exists to stop paying per keystroke.
        repo = FakeCategoriesRepo()
        get({}, repo)
        get({"q": "supp"}, repo)
        self.assertEqual(repo.scans, 2)


class LocalFilterMatchesServerTests(unittest.TestCase):
    """The client filters the cached set; it must match what the server would have returned."""

    def setUp(self):
        if not shutil.which("node"):
            self.skipTest("node not available")
        self.all_rows = get({"limit": "500"})

    def _js_filter(self, query):
        script = f"""
        import {{ filterCategories }} from {json.dumps(str(UTIL))};
        const rows = {json.dumps(self.all_rows)};
        console.log(JSON.stringify(filterCategories(rows, {json.dumps(query)}).map(r => r.key)));
        """
        proc = subprocess.run(["node", "--input-type=module", "-e", script],
                              capture_output=True, text=True, cwd=str(ROOT), timeout=60)
        if proc.returncode != 0:
            raise AssertionError(proc.stderr)
        return json.loads(proc.stdout)

    def test_local_filter_equals_a_server_query_for_the_same_term(self):
        for term in ("supp", "Dietary Supplement", "app", "z", "", "  ", "SUPP", "dietary supp"):
            with self.subTest(term=term):
                server = [row["key"] for row in get({"q": term, "limit": "500"})]
                self.assertEqual(self._js_filter(term), server)


class CachedSuggestionsBehaviourTests(unittest.TestCase):
    """The composable itself: one fetch per open, none per keystroke, and no cross-scope bleed."""

    def _run(self, script_body):
        if not shutil.which("node"):
            self.skipTest("node not available")
        module = ROOT / "dashboard" / "src" / "composables" / "useCachedSuggestions.js"
        script = f"""
        import {{ useCachedSuggestions }} from {json.dumps(str(module))};
        {script_body}
        """
        proc = subprocess.run(["node", "--input-type=module", "-e", script],
                              capture_output=True, text=True, cwd=str(ROOT / "dashboard"), timeout=60)
        if proc.returncode != 0:
            raise AssertionError(proc.stderr)
        return json.loads(proc.stdout)

    def test_typing_does_not_fetch_and_opening_does(self):
        out = self._run("""
        let calls = 0;
        const rows = [{key:'dietary_supplement',label:'Dietary Supplement'},{key:'apparel',label:'Apparel'}];
        const s = useCachedSuggestions({
          fetchAll: async () => { calls += 1; return rows; },
          filter: (items, q) => items.filter(i => i.key.includes(q)),
          scope: () => 'physical',
        });
        await s.open();
        s.search('supp'); s.search('suppl'); s.search('supplem');   // keystrokes: no network
        console.log(JSON.stringify({calls, shown: s.suggestions.value.map(r => r.key)}));
        """)
        self.assertEqual(out["calls"], 1, "typing must not hit the API")
        self.assertEqual(out["shown"], ["dietary_supplement"])

    def test_reopening_refreshes_so_a_new_category_reappears(self):
        out = self._run("""
        let calls = 0;
        const s = useCachedSuggestions({
          fetchAll: async () => { calls += 1; return calls === 1 ? [{key:'a',label:'A'}]
                                                                : [{key:'a',label:'A'},{key:'brand_new',label:'Brand New'}]; },
          filter: (items) => items,
          scope: () => 'physical',
        });
        await s.open();
        await s.open();
        console.log(JSON.stringify({calls, shown: s.suggestions.value.map(r => r.key)}));
        """)
        self.assertEqual(out["calls"], 2, "opening the field must refresh")
        self.assertIn("brand_new", out["shown"])

    def test_switching_scope_never_shows_the_previous_scopes_list(self):
        # A digital product must not be offered a physical product's categories, even for a frame.
        out = self._run("""
        let scope = 'physical';
        const bySc = {physical: [{key:'apparel',label:'Apparel'}], digital: [{key:'ebook',label:'Ebook'}]};
        const s = useCachedSuggestions({
          fetchAll: async (k) => bySc[k],
          filter: (items) => items,
          scope: () => scope,
        });
        await s.open();
        const first = s.suggestions.value.map(r => r.key);
        scope = 'digital';
        const p = s.open();
        const during = s.suggestions.value.map(r => r.key);   // BEFORE the fetch resolves
        await p;
        console.log(JSON.stringify({first, during, after: s.suggestions.value.map(r => r.key)}));
        """)
        self.assertEqual(out["first"], ["apparel"])
        self.assertEqual(out["during"], [], "the old scope's list must be dropped, not shown while loading")
        self.assertEqual(out["after"], ["ebook"])

    def test_a_late_response_for_an_abandoned_scope_is_discarded(self):
        out = self._run("""
        let scope = 'slow';
        const s = useCachedSuggestions({
          fetchAll: (k) => new Promise((res) =>
            setTimeout(() => res([{key: k, label: k}]), k === 'slow' ? 40 : 1)),
          filter: (items) => items,
          scope: () => scope,
        });
        const slow = s.open();          // starts a slow request
        scope = 'fast';
        await s.open();                 // a newer open for a different scope resolves first
        await slow;                     // the stale one lands afterwards
        console.log(JSON.stringify({shown: s.suggestions.value.map(r => r.key)}));
        """)
        self.assertEqual(out["shown"], ["fast"], "a stale response overwrote the current scope")


if __name__ == "__main__":
    unittest.main()
