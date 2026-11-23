import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
LANDING = ROOT / "landing"
sys.path.insert(0, str(LANDING))

import server  # noqa: E402


class LandingPageTest(unittest.TestCase):
    def test_one_decorative_clown_moves_and_respects_reduced_motion(self):
        html = (LANDING / "index.html").read_text()
        css = (LANDING / "style.css").read_text()
        self.assertEqual(html.count('src="clown.webp"'), 1)
        self.assertIn('class="space" aria-hidden="true"', html)
        self.assertIn("@keyframes drift", css)
        self.assertIn("translate(calc(100vw - 80px), 20vh) rotate(180deg)", css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)
        self.assertIn(".clown { animation: none;", css)

    def test_compose_runs_localhost_only_landing_image(self):
        compose = (ROOT / "examples/compose.yaml").read_text()
        service = compose[compose.index("  landing:\n") : compose.index("  player:\n")]
        self.assertIn(
            "image: ${GATEWAY_LANDING_IMAGE:-"
            "ghcr.io/flashdim/tgstation-gateway-landing:latest}",
            service,
        )
        self.assertIn(
            "GATEWAY_PLAY_HOST: ${GATEWAY_PLAY_HOST:-localhost:8080}", service
        )
        self.assertIn("GATEWAY_SLOT_PATH: ${GATEWAY_SLOT_PATH:-/}", service)
        self.assertNotIn("volumes:", service)
        self.assertNotIn("slots.js", service)
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
                    "landing/style.css",
                    "landing/clown.webp",
                    "/srv/landing/",
                ],
                ["assets/ATTRIBUTION.md", "/srv/landing/ATTRIBUTION.md"],
                ["landing/server.py", "/opt/landing/server.py"],
            ],
        )
        served = {path.name for path in LANDING.iterdir() if path.suffix != ".pyc"} - {
            "Dockerfile",
            "server.py",
            "__pycache__",
        }
        self.assertEqual(served, {Path(path).name for path in copies[0][:-1]})
        self.assertIn("USER 65534:65534", dockerfile)
        self.assertIn('CMD ["python3", "/opt/landing/server.py"]', dockerfile)
        self.assertEqual(server.PAGE_ROOT, "/srv/landing")
        self.assertIn("HEALTHCHECK", dockerfile)

    def test_smoke_test_configures_slots_and_checks_attribution(self):
        smoke = (ROOT / "tests/smoke-landing.sh").read_text()
        self.assertIn("-e GATEWAY_PLAY_HOST=play.example.test", smoke)
        self.assertIn("https://play.example.test/LGplayer02/", smoke)
        self.assertIn("GATEWAY_PLAY_HOST='bad host'", smoke)
        self.assertNotIn("-v ", smoke)
        self.assertIn("--read-only --cap-drop ALL", smoke)
        self.assertIn("-p 127.0.0.1::8000", smoke)
        for path in ("slots.js", "page.js", "clown.webp", "ATTRIBUTION.md"):
            with self.subTest(path=path):
                self.assertIn(f'"$base/{path}"', smoke)
        self.assertNotRegex(smoke.lower(), r"password|secret|token")

    def render(self, slots=None, js=None):
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
if (process.argv[2] === "js") {
  vm.runInContext(process.argv[3], context);
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
                "js" if js is not None else "-",
                js if js is not None else json.dumps(slots),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        return json.loads(result.stdout)

    def test_default_slot(self):
        js = server.render_slots(server.build_slots({})).decode()
        result = self.render(js=js)
        card = result["list"]["children"][0]
        self.assertEqual(card["href"], "http://localhost:8080/")
        self.assertEqual(
            card["children"][1]["children"][1]["textContent"], "LGplayer01"
        )
        self.assertTrue(result["error"]["hidden"])

    def test_play_host_generates_slot_links(self):
        slots = server.build_slots(
            {
                "GATEWAY_PLAY_HOST": "play.lazorgator.party",
                "GATEWAY_SLOT_COUNT": "2",
                "GATEWAY_SLOT_PATH": "/{account}/",
                "GATEWAY_ACTIVE_SLOTS": "LGplayer02",
            }
        )
        self.assertEqual(
            slots,
            [
                {
                    "account": "LGplayer01",
                    "url": "https://play.lazorgator.party/LGplayer01/",
                    "active": False,
                },
                {
                    "account": "LGplayer02",
                    "url": "https://play.lazorgator.party/LGplayer02/",
                    "active": True,
                },
            ],
        )
        result = self.render(js=server.render_slots(slots).decode())
        hrefs = [card["href"] for card in result["list"]["children"]]
        self.assertEqual(
            hrefs,
            [
                "https://play.lazorgator.party/LGplayer01/",
                "https://play.lazorgator.party/LGplayer02/#shared",
            ],
        )

    def test_play_host_options(self):
        slots = server.build_slots(
            {
                "GATEWAY_PLAY_HOST": "play.example.test:8443",
                "GATEWAY_PLAY_SCHEME": "http",
                "GATEWAY_ACCOUNT_PREFIX": "Test",
                "GATEWAY_SLOT_COUNT": "3",
                "GATEWAY_SLOT_PATH": "/slot/{number}/",
            }
        )
        self.assertEqual(slots[2]["account"], "Test03")
        self.assertEqual(slots[2]["url"], "http://play.example.test:8443/slot/03/")

    def test_invalid_environment_is_rejected(self):
        for env in (
            {"GATEWAY_PLAY_HOST": "bad host"},
            {"GATEWAY_PLAY_HOST": "user@play.example"},
            {"GATEWAY_PLAY_HOST": "play.example/path"},
            {"GATEWAY_PLAY_HOST": "play.example:70000"},
            {"GATEWAY_PLAY_SCHEME": "javascript"},
            {"GATEWAY_SLOT_COUNT": "0"},
            {"GATEWAY_SLOT_COUNT": "100"},
            {"GATEWAY_SLOT_COUNT": "2"},
            {"GATEWAY_SLOT_PATH": "relative"},
            {"GATEWAY_SLOT_PATH": "/{password}/"},
            {"GATEWAY_SLOT_PATH": "/?x=1"},
            {"GATEWAY_ACCOUNT_PREFIX": "bad prefix"},
            {"GATEWAY_ACTIVE_SLOTS": "LGplayer09"},
        ):
            with self.subTest(env=env):
                with self.assertRaises(server.ConfigError):
                    server.build_slots(env)

    def test_generated_script_escapes_markup(self):
        js = server.render_slots(
            [{"account": "</script>", "url": "https://x/", "active": False}]
        ).decode()
        self.assertNotIn("</script>", js)

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
