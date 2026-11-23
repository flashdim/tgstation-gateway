import json
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
LANDING = ROOT / "landing"


class LandingPageTest(unittest.TestCase):
    def test_compose_runs_localhost_only_landing_image(self):
        compose = (ROOT / "examples/compose.yaml").read_text()
        service = compose[compose.index("  landing:\n") : compose.index("  player:\n")]
        self.assertIn(
            "image: ${GATEWAY_LANDING_IMAGE:-"
            "ghcr.io/flashdim/tgstation-gateway-landing:latest}",
            service,
        )
        self.assertIn(
            '"${GATEWAY_LANDING_SLOTS:-../landing/slots.js}:/srv/landing/slots.js:ro"',
            service,
        )
        self.assertIn('"127.0.0.1:${GATEWAY_LANDING_PORT:-8000}:8000"', service)
        self.assertIn("read_only: true", service)
        self.assertIn("      - ALL\n", service)
        self.assertNotIn("python:3.12-alpine", service)

    def test_image_serves_only_page_files_and_attribution(self):
        dockerfile = (LANDING / "Dockerfile").read_text()
        self.assertRegex(
            dockerfile, r"(?m)^FROM python:3\.12-alpine@sha256:[0-9a-f]{64}$"
        )
        copies = [
            line.split()[1:]
            for line in dockerfile.splitlines()
            if line.startswith("COPY ")
        ]
        self.assertEqual(
            copies,
            [
                [
                    "landing/index.html",
                    "landing/page.js",
                    "landing/slots.js",
                    "landing/style.css",
                    "landing/clown.webp",
                    "/srv/landing/",
                ],
                ["assets/ATTRIBUTION.md", "/srv/landing/ATTRIBUTION.md"],
            ],
        )
        served = {path.name for path in LANDING.iterdir()} - {"Dockerfile"}
        self.assertEqual(served, {Path(path).name for path in copies[0][:-1]})
        self.assertIn("USER 65534:65534", dockerfile)
        self.assertIn('"--directory", "/srv/landing"', dockerfile)
        self.assertIn("HEALTHCHECK", dockerfile)

    def test_smoke_test_overrides_slots_and_checks_attribution(self):
        smoke = (ROOT / "tests/smoke-landing.sh").read_text()
        self.assertIn(":/srv/landing/slots.js:ro", smoke)
        self.assertIn("--read-only --cap-drop ALL", smoke)
        self.assertIn("-p 127.0.0.1::8000", smoke)
        for path in ("slots.js", "page.js", "clown.webp", "ATTRIBUTION.md"):
            with self.subTest(path=path):
                self.assertIn(f'"$base/{path}"', smoke)
        self.assertNotRegex(smoke.lower(), r"password|secret|token")

    def render(self, slots=None, default=False):
        script = """
const fs = require("fs");
const vm = require("vm");
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.hidden = true; }
  append(...children) { this.children.push(...children); }
  setAttribute(name, value) { this[name] = value; }
}
const list = new Element("div");
const error = new Element("p");
const context = {
  URL,
  window: {},
  document: {
    baseURI: "https://gateway.example/landing/",
    getElementById: id => id === "slots" ? list : error,
    createElement: tag => new Element(tag),
  },
};
vm.createContext(context);
if (process.argv[3] === "default") {
  vm.runInContext(fs.readFileSync(process.argv[1] + "/slots.js", "utf8"), context);
} else {
  context.window.GATEWAY_SLOTS = JSON.parse(process.argv[3]);
}
vm.runInContext(fs.readFileSync(process.argv[1] + "/page.js", "utf8"), context);
process.stdout.write(JSON.stringify({list, error}));
"""
        result = subprocess.run(
            [
                "node",
                "-e",
                script,
                str(LANDING),
                "-",
                "default" if default else json.dumps(slots),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return json.loads(result.stdout)

    def test_default_slot(self):
        result = self.render(default=True)
        card = result["list"]["children"][0]
        self.assertEqual(card["href"], "http://localhost:8080/")
        self.assertEqual(
            card["children"][1]["children"][1]["textContent"], "LGplayer01"
        )
        self.assertTrue(result["error"]["hidden"])

    def test_statuses_and_urls(self):
        result = self.render(
            [
                {"account": "LGplayer01", "url": "/player/1?x=1", "active": False},
                {
                    "account": "LGplayer02",
                    "url": "https://player.example/2?x=1#old",
                    "active": True,
                },
            ]
        )
        available, active = result["list"]["children"]
        self.assertEqual(available["href"], "https://gateway.example/player/1?x=1")
        self.assertEqual(active["href"], "https://player.example/2?x=1#shared")
        self.assertEqual(
            available["children"][1]["children"][0]["textContent"], "AVAILABLE SLOT"
        )
        self.assertEqual(
            active["children"][1]["children"][0]["textContent"], "ACTIVE SESSION"
        )
        self.assertEqual(
            active["children"][1]["children"][2]["textContent"], "Watch session"
        )
        self.assertTrue(result["error"]["hidden"])

    def test_invalid_configuration_is_not_linked(self):
        result = self.render(
            [
                {"account": "invalid", "url": "javascript:alert(1)", "active": False},
                {
                    "account": "invalid",
                    "url": "https://user@example.com/",
                    "active": True,
                },
                {"account": "invalid", "url": "/", "active": "false"},
                {"account": "<img src=x>", "url": "/", "active": False},
            ]
        )
        self.assertFalse(result["error"]["hidden"])
        self.assertEqual(len(result["list"]["children"]), 1)
        self.assertEqual(
            result["list"]["children"][0]["children"][1]["children"][1]["textContent"],
            "<img src=x>",
        )
        for slots in ([], None):
            with self.subTest(slots=slots):
                self.assertFalse(self.render(slots)["error"]["hidden"])


if __name__ == "__main__":
    unittest.main()
