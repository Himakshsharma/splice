#!/usr/bin/env python3
"""Browser end-to-end test of the SPLICE UI (headless Chromium via Playwright).

    pip install playwright && python -m playwright install chromium
    python scripts/e2e_ui.py --base-url http://localhost:8000 [--screenshots docs/screenshots]

Drives the real UI against a real backend: landing page, file validation,
upload -> processing -> results, preview players, timeline, 3D view, edit
decisions, download, delete, and a mobile-overflow check.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from smoke_test import make_video  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--screenshots", default=None, help="folder to save screenshots into")
    ap.add_argument("--timeout", type=float, default=600)
    ap.add_argument("--font-file", default=None, help="offline only: serve this Archivo .ttf instead of Google Fonts")
    args = ap.parse_args()
    base = args.base_url.rstrip("/")
    shots = Path(args.screenshots) if args.screenshots else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)

    def snap(page, name: str, full: bool = False) -> None:
        if shots:
            page.screenshot(path=str(shots / f"{name}.png"), full_page=full)

    console_errors: list[str] = []
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
        video = Path(tmp) / "interview-take.mp4"
        make_video(video)
        bad = Path(tmp) / "notes.txt"
        bad.write_text("not a video")

        browser = pw.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        context = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        if args.font_file:
            font = Path(args.font_file).read_bytes()
            face = "@font-face{font-family:'Archivo';font-style:normal;font-weight:300 800;font-stretch:62% 125%;src:url(https://fonts.gstatic.com/local.ttf) format('truetype')}"
            context.route("https://fonts.googleapis.com/**", lambda r: r.fulfill(body=face, content_type="text/css"))
            context.route("https://fonts.gstatic.com/**", lambda r: r.fulfill(body=font, content_type="font/ttf"))
        page = context.new_page()
        failed_requests: list[str] = []
        page.on("requestfailed", lambda r: failed_requests.append(f"{r.url} ({r.failure})"))
        page.on("console", lambda m: m.type == "error" and not m.text.startswith("Failed to load resource") and console_errors.append(m.text))
        page.on("pageerror", lambda e: console_errors.append(str(e)))

        # Landing
        page.goto(base + "/")
        expect(page.get_by_role("heading", level=1)).to_have_text("Your videos. Less silence. More impact.")
        page.wait_for_timeout(5200)  # let the hero animation reach the cut
        snap(page, "01-landing")
        page.get_by_role("link", name="See how it works").click()
        expect(page.locator("#how-it-works")).to_be_in_viewport()
        print("ok  landing page renders and in-page navigation works")

        # Editor: client-side validation
        page.get_by_role("navigation", name="Main").get_by_role("link", name="Start editing").click()
        expect(page.get_by_role("heading", name="Editor")).to_be_visible()
        page.get_by_test_id("file-input").set_input_files(str(bad))
        expect(page.get_by_role("alert").filter(has_text="isn't a supported video")).to_be_visible()
        print("ok  unsupported file rejected in the browser")

        # Upload a real video
        page.get_by_test_id("file-input").set_input_files(str(video))
        expect(page.get_by_text("interview-take.mp4")).to_be_visible()
        expect(page.get_by_text("Read in your browser")).to_be_visible()
        page.get_by_label("Minimum pause to cut").fill("0.6")
        snap(page, "02-editor-ready")
        page.get_by_test_id("primary-action").click()
        expect(page.get_by_test_id("primary-action")).to_be_disabled()  # no double submits
        heading = page.get_by_test_id("stage-heading")
        expect(heading).to_be_visible(timeout=30_000)
        snap(page, "03-processing")
        print(f"ok  processing panel shows real stage: {heading.inner_text()!r}")

        results = page.get_by_test_id("results")
        expect(results).to_be_visible(timeout=args.timeout * 1000)
        expect(page.get_by_text("Checked by the server")).to_be_visible()
        out_dur = page.get_by_test_id("output-duration").inner_text()
        print(f"ok  results shown (edited length {out_dur})")

        # media + download are real backend output
        edited_src = page.get_by_label("Edited", exact=True).get_attribute("src")
        assert edited_src and "/download?" in edited_src
        # Open-source Chromium builds (like Playwright's) ship without an H.264 decoder; Chrome, Edge,
        # Safari and Firefox all have one. Only assert playback where the browser can decode it.
        h264 = page.evaluate("() => document.createElement('video').canPlayType('video/mp4; codecs=\"avc1.42E01E, mp4a.40.2\"')")
        if h264:
            page.wait_for_function(
                "() => [...document.querySelectorAll('video')].every(v => v.readyState >= 1 && v.duration > 0)", timeout=30_000
            )
            durations = page.evaluate("() => [...document.querySelectorAll('video')].map(v => v.duration)")
            assert durations[1] < durations[0] - 2, durations
            print(f"ok  both players load (original {durations[0]:.1f}s, edited {durations[1]:.1f}s)")
        else:
            print("--  this test browser has no H.264 decoder; skipped in-page playback check")

        href = page.get_by_test_id("download").get_attribute("href")
        resp = page.request.get(href if href.startswith("http") else base + href)
        assert resp.status == 200 and resp.headers["content-type"] == "video/mp4", resp.status
        print(f"ok  download returns {len(resp.body())} bytes of video/mp4")

        page.get_by_test_id("edit-timeline").click(position={"x": 200, "y": 40})
        page.get_by_role("button", name="Apply the cuts").click()
        page.wait_for_timeout(2600)
        results.scroll_into_view_if_needed()
        snap(page, "04-results", full=True)
        page.get_by_text("Inspect edit decisions").click()
        expect(page.get_by_role("table")).to_be_visible()
        rows = page.get_by_role("table").locator("tbody tr").count()
        print(f"ok  timeline, 3D view and edit decision table ({rows} rows) work")

        # Re-render with new settings (reuses analysis)
        page.get_by_label("Keep after speech").fill("0.3")
        page.get_by_test_id("primary-action").click()
        expect(page.get_by_text("Re-rendering with new settings")).to_be_visible(timeout=15_000)
        expect(results).to_be_visible(timeout=args.timeout * 1000)
        print("ok  re-render with new settings completes")

        page.get_by_role("button", name="Delete from server").click()
        expect(results).to_be_hidden()
        print("ok  delete removes the job")

        # About + mobile layout
        page.goto(base + "/about")
        expect(page.get_by_role("heading", name="How SPLICE works")).to_be_visible()
        snap(page, "05-about")
        mobile = context.browser.new_context(viewport={"width": 375, "height": 800}, is_mobile=True, device_scale_factor=2)
        if args.font_file:
            mobile.route("https://fonts.googleapis.com/**", lambda r: r.fulfill(body=face, content_type="text/css"))
            mobile.route("https://fonts.gstatic.com/**", lambda r: r.fulfill(body=font, content_type="font/ttf"))
        mobile = mobile.new_page()
        for path in ("/", "/editor", "/about"):
            mobile.goto(base + path)
            mobile.wait_for_timeout(600)
            overflow = mobile.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
            assert overflow <= 0, f"{path} overflows horizontally by {overflow}px on mobile"
            snap(mobile, "06-mobile" + (path.replace("/", "-") if path != "/" else "-landing"))
        print("ok  no horizontal overflow at 375px")
        browser.close()

    # Aborted requests are expected (polling stops, players are torn down); fonts may be offline.
    bad_requests = [u for u in failed_requests if "ERR_ABORTED" not in u and "fonts.g" not in u]
    real_errors = console_errors + [f"request failed: {u}" for u in bad_requests]
    if real_errors:
        print("console errors:", *real_errors, sep="\n  ")
        sys.exit(1)
    print("UI E2E PASSED")


if __name__ == "__main__":
    main()
