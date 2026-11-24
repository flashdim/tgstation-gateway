from functools import partial
import json
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
LANDING = ROOT / "landing"
sys.path.insert(0, str(LANDING))

import server  # noqa: E402


class LandingPageTest(unittest.TestCase):
    def test_static_page_and_slots_work_without_status_endpoints(self):
        slots = server.render_slots(
            server.build_slots(
                {
                    "GATEWAY_SLOT_COUNT": "2",
                    "GATEWAY_SLOT_PATH": "/{account}/",
                    "GATEWAY_ACTIVE_SLOTS": "LGplayer02",
                }
            )
        )
        handler = partial(server.LandingHandler, directory=str(LANDING))
        with (
            mock.patch.object(server.LandingHandler, "slots_js", slots),
            mock.patch.object(server.LandingHandler, "log_message"),
            server.ThreadingHTTPServer(("127.0.0.1", 0), handler) as httpd,
        ):
            thread = threading.Thread(target=httpd.serve_forever)
            thread.start()
            base = f"http://127.0.0.1:{httpd.server_port}"
            try:
                for path in ("status.json", "status.json?refresh=1", "status.js"):
                    for method in ("GET", "HEAD"):
                        with self.subTest(path=path, method=method):
                            with self.assertRaises(HTTPError) as error:
                                urlopen(
                                    Request(f"{base}/{path}", method=method), timeout=5
                                )
                            self.assertEqual(error.exception.code, 404)
                            error.exception.close()
                with urlopen(f"{base}/slots.js", timeout=5) as response:
                    self.assertEqual(response.read(), slots)
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                for path in (
                    "index.html",
                    "page.js",
                    "wizard.js",
                    "narsie.js",
                    "style.css",
                    "assets/layer1.webp",
                    "assets/banners/alert.svg",
                    "assets/sprites/clown.webp",
                ):
                    with self.subTest(path=path):
                        with urlopen(f"{base}/{path}", timeout=5) as response:
                            self.assertEqual(
                                response.read(), (LANDING / path).read_bytes()
                            )
            finally:
                httpd.shutdown()
                thread.join(timeout=5)
        html = (LANDING / "index.html").read_text()
        self.assertNotIn("status.js", html)
        self.assertNotIn("server-status", html)

    def test_wiki_sprites_are_attributed_and_displayed(self):
        html = (LANDING / "index.html").read_text()
        css = (LANDING / "style.css").read_text()
        attribution = (LANDING / "assets/ATTRIBUTION.md").read_text()
        self.assertIn('href="assets/ATTRIBUTION.md"', html)
        self.assertNotIn("PotatoMasher", html)
        self.assertNotIn("WJohnston", html)
        self.assertNotIn("scriptis", html)
        self.assertNotIn("CC BY-SA 3.0", html)
        self.assertNotIn("CC BY-NC-SA 4.0", html)
        self.assertNotIn("GNU AGPL v3.0", html)
        sources = {
            "narsie": (
                "narsie.gif",
                "c84eccc9-775b-4f0a-996d-f62a18193f43",
            ),
            "alien": ("alien.png", "c3955ad9-14d8-4d13-a967-ab7e95af6f03"),
            "operative": (
                "operative.png",
                "89ee354c-4b68-4661-944b-0c88a11a8411",
            ),
            "wizard": ("wizard.png", "fd8813b9-0dac-47b9-ab8f-40c0070f6bbc"),
            "singularity": (
                "singularity.gif",
                "3858a45e-ce06-463f-a429-f5ad967531d0",
            ),
        }
        for name, (filename, asset_id) in sources.items():
            with self.subTest(sprite=name):
                self.assertRegex(html, rf'class="[^"]*\b{name}\b')
                self.assertIn(f'src="assets/sprites/{filename}"', html)
                self.assertTrue((LANDING / "assets/sprites" / filename).is_file())
                self.assertIn(asset_id, attribution)
        self.assertNotRegex(html, r'src="https://github\.com/user-attachments/')
        self.assertIn("PotatoMasher", attribution)
        self.assertIn("WJohnston", attribution)
        self.assertIn("https://wiki.tgstation13.org/User:Kingfish", attribution)
        self.assertIn("CC BY-NC-SA 4.0", attribution)
        self.assertIn("Repository copies:", attribution)
        self.assertIn("Narsie GIF retains its animation", attribution)
        self.assertIn(".character {", css)
        self.assertIn("animation: drift 96s linear infinite", css)
        self.assertIn(".alien { animation-delay: -24s; }", css)
        self.assertIn(".operative { animation-delay: -48s; }", css)
        self.assertIn("animation: wizard-drift 96s linear -72s infinite", css)
        self.assertIn("animation: wizard-spin 96s linear -72s infinite", css)
        self.assertIn(".narsie-anchor { position: fixed; bottom: 0; left: 50%", css)
        self.assertIn(".singularity { position: absolute; top: 50%; left: 50%", css)
        self.assertIn('background-image: url("assets/layer1.webp")', css)
        self.assertIn("background-repeat: repeat", css)
        self.assertIn("@keyframes background-drift", css)
        self.assertIn("animation: background-drift 180s linear infinite", css)
        self.assertIn("scriptis", attribution)
        self.assertIn("GNU AGPL v3.0", attribution)

    def test_station_alert_banner_is_used_and_has_gator_features(self):
        html = (LANDING / "index.html").read_text()
        banner = (LANDING / "assets/banners/alert.svg").read_text()
        self.assertIn(
            '<img class="landing-banner" src="assets/banners/alert.svg" alt="LazorGator Party 13">',
            html,
        )
        self.assertIn(
            ".landing-banner { position: relative; z-index: 2;",
            (LANDING / "style.css").read_text(),
        )
        self.assertIn("red eye lasers", banner)
        self.assertIn('filter id="laser-glow"', banner)
        self.assertIn('stroke="#f8f2d5"', banner)
        self.assertIn('fill="#ff263e"', banner)

    def test_one_decorative_clown_moves_and_respects_reduced_motion(self):
        html = (LANDING / "index.html").read_text()
        css = (LANDING / "style.css").read_text()
        self.assertEqual(html.count('src="assets/sprites/clown.webp"'), 1)
        self.assertIn('class="space" aria-hidden="true"', html)
        self.assertIn("@keyframes drift", css)
        self.assertIn("animation: drift 96s linear infinite", css)
        self.assertIn("translate(calc(100vw - 80px), 20vh)", css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)
        self.assertIn(".character { animation: none;", css)

    def test_floating_sprites_share_a_height_and_preserve_aspect_ratio(self):
        css = (LANDING / "style.css").read_text()
        self.assertRegex(
            css,
            r"\.character-button img \{[^}]*height: clamp\([^;]+\); width: auto;",
        )

    def test_clown_alien_operative_and_wizard_sprites_share_dimensions(self):
        sprites = LANDING / "assets/sprites"
        dimensions = {}
        for name in ("clown.webp", "alien.png", "operative.png", "wizard.png"):
            data = (sprites / name).read_bytes()
            if name.endswith(".png"):
                self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
                self.assertEqual(data[12:16], b"IHDR")
                dimensions[name] = (
                    int.from_bytes(data[16:20], "big"),
                    int.from_bytes(data[20:24], "big"),
                )
            else:
                self.assertEqual(data[12:16], b"VP8L")
                self.assertEqual(data[20], 0x2F)
                b0, b1, b2, b3 = data[21:25]
                dimensions[name] = (
                    1 + b0 + ((b1 & 0x3F) << 8),
                    1 + (b1 >> 6) + (b2 << 2) + ((b3 & 0x0F) << 10),
                )
        self.assertEqual(set(dimensions.values()), {(32, 32)})

    def test_compose_runs_localhost_only_landing_image(self):
        compose = (ROOT / "examples/compose.yaml").read_text()
        service = compose[compose.index("  landing:\n") : compose.index("  player:\n")]
        self.assertIn(
            "image: ${GATEWAY_LANDING_IMAGE:-"
            "ghcr.io/flashdim/tgstation-gateway-landing:latest}",
            service,
        )
        self.assertIn(
            "GATEWAY_PLAY_HOST: ${GATEWAY_PLAY_HOST:-localhost:${GATEWAY_PORT:-8080}}",
            service,
        )
        self.assertIn("profiles:\n      - landing\n", service)
        self.assertIn("GATEWAY_SLOT_PATH: ${GATEWAY_SLOT_PATH:-/}", service)
        self.assertNotIn("volumes:", service)
        self.assertNotIn("slots.js", service)
        self.assertIn('"127.0.0.1:${GATEWAY_LANDING_PORT:-8000}:8000"', service)
        self.assertIn("read_only: true", service)
        self.assertIn("      - ALL\n", service)
        self.assertNotIn("python:3.12-alpine", service)

    def test_smoke_test_fetches_the_tiled_background_asset(self):
        smoke = (ROOT / "tests/smoke-landing.sh").read_text()
        self.assertIn('curl -fsS "$base/assets/layer1.webp"', smoke)
        self.assertIn(
            "for asset in clown.webp alien.png operative.png wizard.png narsie.gif singularity.gif;",
            smoke,
        )
        self.assertIn("Web/P image", smoke)

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
                    "landing/wizard.js",
                    "landing/narsie.js",
                    "landing/style.css",
                    "/srv/landing/",
                ],
                ["landing/assets/sprites/", "/srv/landing/assets/sprites/"],
                [
                    "landing/assets/ATTRIBUTION.md",
                    "landing/assets/layer1.webp",
                    "/srv/landing/assets/",
                ],
                [
                    "landing/assets/banners/alert.svg",
                    "/srv/landing/assets/banners/alert.svg",
                ],
                ["landing/server.py", "/opt/landing/server.py"],
            ],
        )
        served = {path.name for path in LANDING.iterdir() if path.suffix != ".pyc"} - {
            "Dockerfile",
            "server.py",
            "__pycache__",
            "assets",
        }
        self.assertEqual(served, {Path(path).name for path in copies[0][:-1]})
        self.assertEqual(
            {path.name for path in (LANDING / "assets/sprites").iterdir()},
            {
                "clown.webp",
                "alien.png",
                "operative.png",
                "wizard.png",
                "narsie.gif",
                "singularity.gif",
            },
        )
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
        for path in (
            "slots.js",
            "page.js",
            "wizard.js",
            "narsie.js",
            "clown.webp",
            "alien.png",
            "operative.png",
            "wizard.png",
            "narsie.gif",
            "singularity.gif",
            "$base/assets/sprites/$asset",
            "assets/layer1.webp",
            "assets/ATTRIBUTION.md",
        ):
            with self.subTest(path=path):
                self.assertIn(path, smoke)
        self.assertNotRegex(smoke.lower(), r"password|secret|token")

    def test_character_bubbles_restart_and_expire(self):
        script = """
const fs = require("fs");
const vm = require("vm");
const assert = require("assert");
let nextTimer = 0;
const timers = new Map();
const speakers = ["*honk*", "*hiss*", "Guys? Where are you?", "I CAST REGULAR MISSILE"]
  .map(message => {
    const bubble = { hidden: true, textContent: "" };
    const button = {
      dataset: { message },
      nextElementSibling: bubble,
      addEventListener: (type, callback) => {
        assert.strictEqual(type, "click");
        button.click = callback;
      },
    };
    return { button, bubble, message };
  });
const context = {
  document: { querySelectorAll: selector => {
    assert.strictEqual(selector, ".character-button");
    return speakers.map(speaker => speaker.button);
  }},
  setTimeout: (callback, delay) => {
    assert.strictEqual(delay, 4000);
    timers.set(++nextTimer, callback);
    return nextTimer;
  },
  clearTimeout: id => timers.delete(id),
};
vm.runInNewContext(fs.readFileSync(process.argv[1], "utf8"), context);
for (const { button, bubble, message } of speakers) {
  assert.strictEqual(bubble.hidden, true);
  button.click();
  assert.strictEqual(bubble.hidden, false);
  assert.strictEqual(bubble.textContent, message);
  assert.strictEqual(timers.size, 1);
  const firstTimer = nextTimer;
  button.click();
  assert.strictEqual(timers.size, 1);
  assert.strictEqual(timers.has(firstTimer), false);
  const activeTimer = nextTimer;
  timers.get(activeTimer)();
  timers.delete(activeTimer);
  assert.strictEqual(bubble.hidden, true);
  assert.strictEqual(bubble.textContent, "");
}
"""
        subprocess.run(
            ["node", "-e", script, str(LANDING / "wizard.js")],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        html = (LANDING / "index.html").read_text()
        self.assertIn('type="button" aria-label="Activate wizard"', html)
        self.assertIn('aria-label="Clown" data-message="*honk*"', html)
        self.assertIn('aria-label="Alien" data-message="*hiss*"', html)
        self.assertIn('aria-label="Operator" data-message="Guys? Where are you?"', html)
        self.assertEqual(html.count('class="speech-bubble"'), 4)
        self.assertIn(
            'id="wizard-bubble" class="speech-bubble" role="status" hidden', html
        )

    def test_narsie_summons_a_singularity_then_restores_the_orbits(self):
        html = (LANDING / "index.html").read_text()
        self.assertIn('<script defer src="narsie.js"></script>', html)
        self.assertIn('<button class="narsie" type="button" aria-label=', html)
        self.assertIn('class="singularity" aria-hidden="true" hidden', html)
        script = """
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const style = () => ({removeProperty(key) { delete this[key]; }});
const attributes = new Map();
const button = {
  getBoundingClientRect: () => ({left: 300, top: 400, width: 200, height: 200}),
  getAttribute: name => attributes.get(name),
  setAttribute: (name, value) => attributes.set(name, value),
  removeAttribute: name => attributes.delete(name),
  addEventListener: (event, callback) => { button[event] = callback; },
};
const singularity = {hidden: true, style: style()};
const image = {style: style()};
const sprite = {
  style: style(),
  getBoundingClientRect: () => ({left: 130, top: 130, width: 40, height: 40}),
  querySelector: () => image,
};
const layer = {
  clientWidth: 800, clientHeight: 600, querySelectorAll: () => [sprite],
  classList: new Set(),
};
layer.classList.remove = name => layer.classList.delete(name);
const motion = {matches: false};
const callbacks = [];
vm.runInNewContext(fs.readFileSync(process.argv[1], "utf8"), {
  document: {querySelector: name => ({
    ".narsie": button, ".singularity": singularity, ".character-layer": layer,
  })[name]},
  matchMedia: () => motion,
  requestAnimationFrame: callback => callbacks.push(callback),
});
const tick = now => callbacks.shift()(now);
const center = () => sprite.style.translate.split(" ").map(value => 150 + parseFloat(value));

button.click();
button.click();
assert.equal(callbacks.length, 1);
assert.ok(layer.classList.has("in-vortex"));
tick(0);
assert.equal(singularity.hidden, false);
assert.equal(singularity.style.opacity, 0);
assert.ok(Math.hypot(center()[0] - 150, center()[1] - 150) < 0.001);
tick(600);
assert.equal(singularity.style.opacity, 1);
tick(2900);
assert.ok(Math.hypot(center()[0] - 400, center()[1] - 500) < 25);
assert.ok(parseFloat(image.style.rotate) > 10);
tick(3000);
const ejectionY = center()[1];
tick(3050);
assert.ok(ejectionY - center()[1] > 25);
tick(3400);
assert.ok(singularity.style.opacity > 0 && singularity.style.opacity < 1);
let prevX = center()[0];
let bounced = false;
for (let time = 3450; time <= 8000; time += 50) {
  tick(time);
  const [x, y] = center();
  assert.ok(x >= 20 && x <= 780 && y >= 20 && y <= 580);
  bounced ||= x > prevX;
  prevX = x;
}
assert.ok(bounced);
assert.equal(singularity.hidden, true);
assert.equal(singularity.style.opacity, 0);
assert.ok(layer.classList.has("in-vortex"));
tick(9990);
assert.ok(Math.hypot(center()[0] - 150, center()[1] - 150) < 1);
tick(10000);
assert.equal(callbacks.length, 0);
assert.equal(singularity.hidden, true);
assert.equal(attributes.has("aria-disabled"), false);
assert.equal(layer.classList.size, 0);
assert.equal(sprite.style.translate, undefined);
assert.equal(image.style.rotate, undefined);

motion.matches = true;
button.click();
tick(11000);
assert.equal(singularity.hidden, false);
assert.equal(singularity.style.opacity, 1);
assert.equal(layer.classList.size, 0);
assert.equal(sprite.style.translate, undefined);
tick(14000);
assert.equal(singularity.hidden, true);
"""
        subprocess.run(
            ["node", "-e", script, str(LANDING / "narsie.js")],
            check=True,
            timeout=30,
        )

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
            {"GATEWAY_SLOT_COUNT": "2", "GATEWAY_SLOT_PATH": "/{account}/../"},
            {"GATEWAY_SLOT_PATH": "/./{account}/"},
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
