"""Check reproducible README assets against the frozen fourteen-model aggregates."""

import hashlib
import json
import math
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET

from src.utils import render_results as renderer


REPO = Path(__file__).resolve().parents[2]
ASSETS = REPO / "assets/benchmark"
DATA = REPO / "data/results"


class ReadmeAssetsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((DATA / "summary.json").read_text())

    def test_generated_files_match_and_svgs_are_self_contained(self):
        generated = renderer.build(self.data)
        self.assertEqual(len(generated), 5)
        self.assertEqual(set(generated), {
            ASSETS / "overview.svg", ASSETS / "structural-queries.svg",
            ASSETS / "graph-text-decisions.svg", ASSETS / "optimization-trajectories.svg",
            REPO / "docs/results.md",
        })
        for path, content in generated.items():
            with self.subTest(path=path.name):
                self.assertEqual(path.read_text(), content)
                if path.suffix != ".svg":
                    continue
                root = ET.fromstring(content)
                ns = {"s": "http://www.w3.org/2000/svg"}
                self.assertTrue(root.find("s:title", ns).text)
                self.assertTrue(root.find("s:desc", ns).text)
                self.assertFalse(root.findall(".//s:script", ns))
                self.assertFalse(root.findall(".//s:foreignObject", ns))
                self.assertFalse(root.findall(".//s:image", ns))
                self.assertNotIn("http", content.split(">", 1)[1])

    def test_all_model_aggregates_match_frozen_publication_snapshot(self):
        # This is a preservation check, not independent raw-output recomputation.
        values = [{key: value for key, value in model.items() if key != "label"}
                  for model in self.data["models"]]
        encoded = json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
        self.assertEqual(hashlib.sha256(encoded).hexdigest(),
                         "ceff4a3b97f9a8669d3c65c8ac0869d6cb28f12e62cab0f96757df006aacf2b6")

    def test_aggregate_shapes_ranges_and_completion_semantics(self):
        models = self.data["models"]
        self.assertEqual(len({model["id"] for model in models}), 14)
        self.assertEqual(len(self.data["rq1_tasks"]), 6)
        self.assertEqual(self.data["rq2_conditions"], ["T", "G", "TG", "BAG", "A"])
        self.assertEqual(len(self.data["rq3_tasks"]), 4)
        for model in models:
            with self.subTest(model=model["id"]):
                for field, count in (("rq1", 6), ("arxiv", 5), ("prime", 5)):
                    self.assertEqual(len(model[field]), count)
                    for value in model[field]:
                        if value is None:
                            self.assertNotEqual(field, "rq1")
                        else:
                            self.assertTrue(math.isfinite(value) and 0 <= value <= 100)
                self.assertEqual(len(model["rq3"]), 4)
                for row in model["rq3"]:
                    self.assertEqual(len(row), 4)
                    for gap, completed in zip(row[:2], row[2:]):
                        self.assertIs(type(completed), int)
                        self.assertTrue(0 <= completed <= 10)
                        if completed == 0:
                            self.assertIsNone(gap)
                        else:
                            self.assertIsNotNone(gap)
                            self.assertTrue(math.isfinite(gap))

    def test_public_bundle_documents_aggregate_only_scope(self):
        self.assertEqual({path.name for path in DATA.iterdir()}, {"README.md", "summary.json"})
        for relative in ("README.md", "data/README.md", "data/results/README.md",
                         "docs/reproduction.md", "docs/results.md"):
            text = (REPO / relative).read_text()
            with self.subTest(document=relative):
                self.assertNotIn("src.utils.public_results", text)
                self.assertNotIn("tests.publication.test_public_results", text)
                for name in ("structural-queries.csv", "graph-text-decisions.csv",
                             "optimization-trajectories.csv"):
                    self.assertNotIn(name, text)
        self.assertNotIn("distributed final rows", self.data["sources"]["note"])

    def test_all_models_coverage_and_missing_values_are_preserved(self):
        models = self.data["models"]
        self.assertEqual(len(models), 14)
        self.assertEqual(sum(row[2] + row[3] for m in models for row in m["rq3"]), 951)
        self.assertEqual([m["id"] for m in models if m["arxiv"][0] is None], ["laya", "qwen4score"])
        jev = next(m for m in models if m["id"] == "jev")
        self.assertEqual(jev["rq3"][2][2:], [8, 8])
        laya = next(m for m in models if m["id"] == "laya")
        self.assertEqual(laya["rq3"][2], [None, 0, 0, 1])
        chart = (ASSETS / "optimization-trajectories.svg").read_text()
        self.assertIn("stroke-dasharray", chart)
        self.assertIn("0.00 [1]", chart)

    def test_relative_gap_definition_and_modularity_units_are_explicit(self):
        for relative in ("README.md", "data/results/README.md", "docs/results.md"):
            text = (REPO / relative).read_text()
            with self.subTest(document=relative):
                self.assertIn("|f_i-R_i|", text)
                self.assertIn(r"\times100", text)
                self.assertIn("Q_i^*-Q_i", text)
                self.assertNotIn("Signed gaps are not clamped", text)
        for model in self.data["models"]:
            for row in model["rq3"][:3]:
                for gap in row[:2]:
                    if gap is not None:
                        self.assertGreaterEqual(gap, 0)

    def test_document_links(self):
        for relative in ("README.md", "data/README.md", "docs/results.md", "docs/reproduction.md",
                 "data/results/README.md", "configs/README.md", "tests/README.md"):
            path = REPO / relative
            content = path.read_text()
            links = re.findall(r'\]\(([^)]+)\)|(?:href|src)="([^"]+)"', content)
            for pair in links:
                link = next(v for v in pair if v)
                if link.startswith(("https://", "http://")):
                    continue
                target, _, anchor = link.partition("#")
                target_path = path.parent / target if target else path
                self.assertTrue(target_path.exists(), (relative, link))
                if anchor:
                    headings = re.findall(r"^#+ (.+)$", target_path.read_text(), re.M)
                    slugs = [re.sub(r"[^\w -]", "", heading.lower()).replace(" ", "-")
                             for heading in headings]
                    self.assertIn(anchor, slugs, (relative, link))

    def test_model_labels_do_not_encode_or_highlight_reasoning_settings(self):
        models = {model["id"]: model for model in self.data["models"]}
        self.assertEqual(models["gpt54"]["label"], "GPT-5.4")
        self.assertEqual(models["astra"]["label"], "GPT-6-Astra")
        for model_id in ("qwen27", "gpt54", "astra"):
            svg = renderer.SVG(100, "Labels", "Model labels use the same baseline style.")
            renderer.label(svg, models[model_id], 30, 40)
            root = ET.fromstring(svg.finish())
            ns = {"s": "http://www.w3.org/2000/svg"}
            label = root.find(".//s:text", ns)
            self.assertEqual(label.attrib["font-weight"], "400")
            self.assertEqual(root.findall(".//s:rect", ns)[-1].attrib["fill"], renderer.BLUE)
        for path, content in renderer.build(self.data).items():
            if path.suffix == ".svg":
                self.assertNotIn("(none)", content)
                self.assertNotIn("explicit none", content)
                root = ET.fromstring(content)
                for label in root.findall(".//{http://www.w3.org/2000/svg}text"):
                    if label.text in ("GPT-5.4", "GPT-6-Astra"):
                        self.assertEqual(label.attrib["font-weight"], "400")
        settings = (REPO / "docs/reproduction.md").read_text()
        self.assertIn('reasoning_effort="none"', settings)
        self.assertIn("medium observed", settings)

    def test_readme_uses_current_task_focused_figures(self):
        readme = (REPO / "README.md").read_text()
        generated = renderer.build(self.data)
        images = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", readme)
        self.assertEqual(len(images), 3)
        for link in images:
            self.assertIn(REPO / link, generated)
            self.assertNotIn("(none)", (REPO / link).read_text())
        structural = generated[ASSETS / "structural-queries.svg"]
        for text in ("simple cycle", "path between", "at most two edges",
                     "component count", "including isolates"):
            self.assertIn(text, structural)
        graph_text = generated[ASSETS / "graph-text-decisions.svg"]
        for text in ("Target / candidate text", "Relational evidence", "Entity + context text",
                     "Same nodes + text as TG", "Only explicit edges removed",
                     "A / A*", "TG - BAG", "G - A/A*", "names and types"):
            self.assertIn(text, graph_text)
        optimization = generated[ASSETS / "optimization-trajectories.svg"]
        for text in ("closed-tour length", "signed crossing-edge weight", "two seeds",
                     "at most two groups", "all legal next actions", "four fixed rules"):
            self.assertIn(text, optimization)
        for text in ("Exact degree", "Pairwise connectivity", "Distance threshold",
                     "Articulation point", "training-label anchors",
                     "not** an edge-only", "unrelated to RQ2"):
            self.assertIn(text, readme)


if __name__ == "__main__":
    unittest.main()
