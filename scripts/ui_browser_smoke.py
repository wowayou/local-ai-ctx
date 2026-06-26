from __future__ import annotations

import argparse
import shutil
import sys
import threading
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter

from ctx.doctor import run_doctor
from ctx.models import Priority, ProjectStatus
from ctx.store import add_project, ensure_providers, init_store, load_store
from ctx.ui import create_ui_server, server_url


ROOT_DIR = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = ROOT_DIR / "tests" / "ui_snapshots"
OUTPUT_DIR = Path("/tmp/local-ai-ctx-ui-visual")
DIFF_PIXEL_THRESHOLD = 24
MAX_DIFF_RATIO = 0.08


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run real Chromium UI smoke checks.")
    parser.add_argument("--update", action="store_true", help="update screenshot baselines")
    args = parser.parse_args(argv)

    _prepare_output_dir()
    ledger = OUTPUT_DIR / "ledger"
    _seed_ledger(ledger)
    server = create_ui_server(ledger, port=0, language="zh", ledger_source="runtime")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _run_browser_checks(server_url(server), ledger, update=args.update)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    print("ok ui browser smoke")
    return 0


def _seed_ledger(ledger: Path) -> None:
    init_store(ledger)
    ensure_providers(ledger, ["official", "browser-provider"])
    add_project(
        ledger,
        "browser-demo",
        name="Browser Demo",
        status=ProjectStatus.TODO,
        priority=Priority.MEDIUM,
        next_action="Use the pill menu to commit the next local slice",
        surfaces={"wsl": {"path": "/tmp/browser-demo"}},
        agents=["codex-cli"],
        providers=["browser-provider"],
        repo={
            "remote": "git@example.com:ctx/browser-demo.git",
            "default_branch": "main",
            "branch": "feature/browser-smoke",
            "known_risk": "watch the fetch path",
        },
        blockers=["none"],
        risks=["keep fields"],
        rules=["no framework"],
    )
    add_project(
        ledger,
        "blocked-risk",
        name="Blocked Risk",
        status=ProjectStatus.BLOCKED,
        priority=Priority.HIGH,
        next_action="Wait for local review",
        providers=["official"],
        blockers=["waiting on review"],
        risks=["manual verification pending"],
    )
    add_project(
        ledger,
        "context-gap",
        name="Context Gap",
        status=ProjectStatus.ACTION_REQUIRED,
        priority=Priority.LOW,
        next_action="Fill surface and provider before continuing",
    )


def _run_browser_checks(url: str, ledger: Path, *, update: bool) -> None:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SystemExit(
            "Playwright is not installed. Run: UV_CACHE_DIR=/tmp/local-ai-ctx-uv-cache uv run --extra dev playwright install chromium"
        ) from exc

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 820}, device_scale_factor=1)
                page.goto(url, wait_until="networkidle")
                _assert_layout(page, "desktop action")
                _capture_and_compare(page, "desktop_action.png", update=update)

                _choose_row_option(page, "browser-demo", "status", "doing")
                _choose_row_option(page, "browser-demo", "priority", "high")
                _edit_next_action(page, "browser-demo", "Commit the refreshed Notion table slice")
                page.locator('[data-project-id="browser-demo"][data-quick-field="status"] [data-current-detail]').first.wait_for(
                    state="visible"
                )
                _assert_project_updated(
                    ledger,
                    status=ProjectStatus.DOING,
                    priority=Priority.HIGH,
                    next_action="Commit the refreshed Notion table slice",
                )

                page.locator('[data-panel-target="panel-browser-demo"]').first.click()
                page.locator("#panel-browser-demo").wait_for(state="visible")
                page.locator("#panel-browser-demo [data-panel-close]").click()
                page.locator("#panel-browser-demo").wait_for(state="hidden")
                _choose_view(page, "doctor")
                page.locator("#doctor-panel").wait_for(state="visible")
                _open_filter_menu(page, "status")
                _assert_layout(page, "desktop interaction")
                _assert_menu_visible(page)
                _capture_and_compare(page, "desktop_interaction.png", update=update)

                _choose_view(page, "table")
                page.locator('[data-view-panel="table"]').wait_for(state="visible")
                _assert_layout(page, "desktop table")
                _capture_and_compare(page, "desktop_table.png", update=update)

                _choose_view(page, "board")
                page.locator('[data-view-panel="board"]').wait_for(state="visible")
                _assert_layout(page, "desktop board")
                _assert_board_scrollable(page)
                _capture_and_compare(page, "desktop_board.png", update=update)
                _install_quick_update_counter(page)
                _drag_card_to_status(page, "browser-demo", "doing")
                _drag_card_to_point(page, "browser-demo", 20, 20)
                _assert_quick_update_count(page, 0)
                _assert_card_in_status(page, "browser-demo", "doing")
                _assert_project_updated(
                    ledger,
                    status=ProjectStatus.DOING,
                    priority=Priority.HIGH,
                    next_action="Commit the refreshed Notion table slice",
                )
                _drag_card_to_status(page, "browser-demo", "action_required")
                _assert_quick_update_count(page, 1)
                _assert_project_updated(
                    ledger,
                    status=ProjectStatus.ACTION_REQUIRED,
                    priority=Priority.HIGH,
                    next_action="Commit the refreshed Notion table slice",
                )
                _drag_card_to_status_with_autoscroll(page, "browser-demo", "archived")
                _assert_quick_update_count(page, 2)
                _assert_project_updated(
                    ledger,
                    status=ProjectStatus.ARCHIVED,
                    priority=Priority.HIGH,
                    next_action="Commit the refreshed Notion table slice",
                )

                mobile = browser.new_page(viewport={"width": 390, "height": 760}, device_scale_factor=1)
                mobile.goto(url, wait_until="networkidle")
                _assert_layout(mobile, "mobile action")
                _capture_and_compare(mobile, "mobile_action.png", update=update)
                _choose_view(mobile, "table")
                mobile.locator('[data-view-panel="table"]').wait_for(state="visible")
                _assert_layout(mobile, "mobile table")
                _capture_and_compare(mobile, "mobile_table.png", update=update)
                _choose_view(mobile, "board")
                _assert_layout(mobile, "mobile board")
                if mobile.locator("[data-drag-handle]").first.is_visible():
                    raise AssertionError("mobile board should use status menus instead of drag handles")
                _choose_row_option(mobile, "browser-demo", "status", "blocked", scope='[data-project-card]')
                _assert_project_updated(
                    ledger,
                    status=ProjectStatus.BLOCKED,
                    priority=Priority.HIGH,
                    next_action="Commit the refreshed Notion table slice",
                )
                mobile.close()
            finally:
                browser.close()
    except PlaywrightError as exc:
        message = str(exc)
        if "Executable doesn't exist" in message or "playwright install" in message:
            raise SystemExit("Chromium is missing. Run: uv run --extra dev playwright install chromium") from exc
        if "error while loading shared libraries" in message:
            raise SystemExit(
                "Chromium system dependencies are missing. Run: sudo apt-get install -y libasound2t64 "
                "or: uv run --extra dev playwright install-deps chromium"
            ) from exc
        raise
    except PlaywrightTimeoutError:
        raise


def _choose_row_option(page, project_id: str, field: str, value: str, *, scope: str = "") -> None:
    if scope:
        selector = f'{scope}[data-project-id="{project_id}"] [data-quick-field="{field}"]'
    else:
        selector = f'[data-project-id="{project_id}"][data-quick-field="{field}"]'
    root = page.locator(selector).first
    root.locator("[data-menu-trigger]").click()
    root.locator(f'[data-menu-option][data-value="{value}"]').click()
    root.locator(f'[data-menu-trigger][data-value="{value}"]').wait_for(
        state="visible"
    )
    page.wait_for_function(
        """([projectId, field, value]) => {
          const root = document.querySelector(`[data-project-id="${projectId}"][data-quick-field="${field}"]`);
          const group = root && root.closest("[data-project-record]");
          return group && group.dataset[field] === value;
        }""",
        arg=[project_id, field, value],
    )


def _choose_view(page, view: str) -> None:
    menu = page.locator("[data-more-menu]").first
    if not menu.evaluate("node => node.open"):
        page.locator("[data-more-menu] > summary").click()
    menu.locator(f'[data-nav-item="{view}"]').click()
    page.locator(f'[data-view-panel="{view}"]').wait_for(state="visible")


def _edit_next_action(page, project_id: str, value: str) -> None:
    button = page.locator(f'[data-next-action-display][data-project-id="{project_id}"]').first
    button.click()
    editor = page.locator(".next-action-input")
    editor.fill(value)
    editor.press("Enter")
    page.locator(f'[data-next-action-display][data-project-id="{project_id}"]').filter(has_text=value).wait_for(
        state="visible"
    )


def _drag_card_to_status(page, project_id: str, status: str) -> None:
    card = page.locator(f'[data-project-card][data-project-id="{project_id}"]').first
    handle = card.locator("[data-drag-handle]").first
    zone = page.locator(f'[data-dropzone="{status}"]').first
    handle.scroll_into_view_if_needed()
    handle_box = handle.bounding_box()
    zone_box = zone.bounding_box()
    if handle_box is None or zone_box is None:
        raise AssertionError("drag source or target is not visible")
    page.mouse.move(handle_box["x"] + handle_box["width"] / 2, handle_box["y"] + handle_box["height"] / 2)
    page.mouse.down()
    page.mouse.move(zone_box["x"] + zone_box["width"] / 2, zone_box["y"] + zone_box["height"] / 2, steps=12)
    page.mouse.up()
    _assert_card_in_status(page, project_id, status)


def _drag_card_to_point(page, project_id: str, x: int, y: int) -> None:
    card = page.locator(f'[data-project-card][data-project-id="{project_id}"]').first
    handle = card.locator("[data-drag-handle]").first
    handle.scroll_into_view_if_needed()
    handle_box = handle.bounding_box()
    if handle_box is None:
        raise AssertionError("drag source is not visible")
    page.mouse.move(handle_box["x"] + handle_box["width"] / 2, handle_box["y"] + handle_box["height"] / 2)
    page.mouse.down()
    page.mouse.move(x, y, steps=10)
    page.mouse.up()
    page.wait_for_timeout(150)


def _drag_card_to_status_with_autoscroll(page, project_id: str, status: str) -> None:
    card = page.locator(f'[data-project-card][data-project-id="{project_id}"]').first
    handle = card.locator("[data-drag-handle]").first
    board = page.locator("[data-board]").first
    handle.scroll_into_view_if_needed()
    handle_box = handle.bounding_box()
    board_box = board.bounding_box()
    if handle_box is None or board_box is None:
        raise AssertionError("drag source or board is not visible")

    start_x = handle_box["x"] + handle_box["width"] / 2
    start_y = handle_box["y"] + handle_box["height"] / 2
    edge_x = board_box["x"] + board_box["width"] - 10
    edge_y = board_box["y"] + min(max(start_y - board_box["y"], 80), board_box["height"] - 20)
    starts_on_handle = page.evaluate(
        """([x, y]) => Boolean(document.elementFromPoint(x, y)?.closest("[data-drag-handle]"))""",
        [start_x, start_y],
    )
    if not starts_on_handle:
        hit = page.evaluate(
            """([x, y]) => {
              const element = document.elementFromPoint(x, y);
              return element ? element.outerHTML : "";
            }""",
            [start_x, start_y],
        )
        raise AssertionError(f"auto-scroll drag did not start on handle: {hit[:200]}")

    page.mouse.move(start_x, start_y)
    page.mouse.down()
    page.mouse.move(start_x + 18, start_y, steps=3)

    drop_point = None
    for index in range(90):
        page.mouse.move(edge_x - (index % 2), edge_y, steps=2)
        page.wait_for_timeout(25)
        drop_point = page.evaluate(
            """(status) => {
              const board = document.querySelector("[data-board]");
              const zone = document.querySelector(`[data-dropzone="${status}"]`);
              if (!board || !zone) return null;
              const boardRect = board.getBoundingClientRect();
              const rect = zone.getBoundingClientRect();
              const visibleLeft = Math.max(rect.left, boardRect.left + 14, 24);
              const visibleRight = Math.min(rect.right, boardRect.right - 14, window.innerWidth - 24);
              if (visibleRight <= visibleLeft) return null;
              return {
                x: (visibleLeft + visibleRight) / 2,
                y: Math.min(Math.max(rect.top + Math.min(60, rect.height / 2), 24), window.innerHeight - 24)
              };
            }""",
            status,
        )
        if drop_point:
            break

    if not drop_point:
        diagnostic = page.evaluate(
            """(status) => {
              const board = document.querySelector("[data-board]");
              const zone = document.querySelector(`[data-dropzone="${status}"]`);
              const boardRect = board ? board.getBoundingClientRect() : null;
              const zoneRect = zone ? zone.getBoundingClientRect() : null;
              return {
                boardScrollLeft: board ? board.scrollLeft : null,
                boardClientWidth: board ? board.clientWidth : null,
                boardScrollWidth: board ? board.scrollWidth : null,
                hasGhost: Boolean(document.querySelector(".drag-ghost")),
                draggingCards: document.querySelectorAll("[data-project-card].is-dragging").length,
                targetClasses: Array.from(document.querySelectorAll("[data-dropzone].is-drop-target")).map((item) => item.dataset.dropzone),
                boardRect: boardRect ? {left: boardRect.left, right: boardRect.right, top: boardRect.top, bottom: boardRect.bottom} : null,
                zoneRect: zoneRect ? {left: zoneRect.left, right: zoneRect.right, top: zoneRect.top, bottom: zoneRect.bottom} : null
              };
            }""",
            status,
        )
        page.mouse.up()
        raise AssertionError(f"target status did not become visible after auto-scroll: {status} {diagnostic}")

    page.mouse.move(drop_point["x"], drop_point["y"], steps=10)
    page.wait_for_timeout(100)
    drop_hit = page.evaluate(
        """([x, y]) => {
          const element = document.elementFromPoint(x, y);
          const zone = element ? element.closest("[data-dropzone]") : null;
          return {
            element: element ? element.outerHTML.slice(0, 180) : null,
            zone: zone ? zone.dataset.dropzone : null,
            point: {x, y}
          };
        }""",
        [drop_point["x"], drop_point["y"]],
    )
    page.mouse.up()
    for _ in range(20):
        state = _card_status_state(page, project_id)
        if state["status"] == status and state["zone"] == status:
            return
        page.wait_for_timeout(250)
    raise AssertionError(f"card did not move to {status}: {_card_status_state(page, project_id)} drop hit: {drop_hit}")


def _assert_card_in_status(page, project_id: str, status: str) -> None:
    page.wait_for_function(
        """([projectId, status]) => {
          const card = document.querySelector(`[data-project-card][data-project-id="${projectId}"]`);
          return card && card.dataset.status === status && card.closest(`[data-dropzone="${status}"]`);
        }""",
        arg=[project_id, status],
    )


def _card_status_state(page, project_id: str) -> dict:
    return page.evaluate(
        """(projectId) => {
          const card = document.querySelector(`[data-project-card][data-project-id="${projectId}"]`);
          const zone = card ? card.closest("[data-dropzone]") : null;
          const state = card ? card.querySelector(".row-save-state") : null;
          const board = document.querySelector("[data-board]");
          return {
            status: card ? card.dataset.status : null,
            zone: zone ? zone.dataset.dropzone : null,
            quickCalls: window.__quickUpdateCalls || 0,
            saveState: state ? state.textContent : null,
            boardScrollLeft: board ? board.scrollLeft : null,
            hasGhost: Boolean(document.querySelector(".drag-ghost")),
            draggingCards: document.querySelectorAll("[data-project-card].is-dragging").length,
            targetClasses: Array.from(document.querySelectorAll("[data-dropzone].is-drop-target")).map((item) => item.dataset.dropzone)
          };
        }""",
        project_id,
    )


def _install_quick_update_counter(page) -> None:
    page.evaluate(
        """() => {
          window.__quickUpdateCalls = 0;
          if (window.__quickUpdateFetchWrapped) return;
          window.__quickUpdateFetchWrapped = true;
          const originalFetch = window.fetch.bind(window);
          window.fetch = (...args) => {
            const target = args[0] && (args[0].url || String(args[0]));
            if (String(target).includes("/projects/") && String(target).endsWith("/quick")) {
              window.__quickUpdateCalls += 1;
            }
            return originalFetch(...args);
          };
        }"""
    )


def _assert_quick_update_count(page, expected: int) -> None:
    page.wait_for_timeout(150)
    actual = page.evaluate("() => window.__quickUpdateCalls || 0")
    if actual != expected:
        raise AssertionError(f"expected {expected} quick updates, got {actual}")


def _open_filter_menu(page, field: str) -> None:
    drawer = page.locator("[data-filter-menu]").first
    if not drawer.evaluate("node => node.open"):
        page.locator("[data-filter-menu] > summary").click()
    page.locator(f'[data-filter-field="{field}"] [data-menu-trigger]').click()
    page.locator(f'[data-filter-field="{field}"] .menu-popover').wait_for(state="visible")


def _assert_project_updated(
    ledger: Path,
    *,
    status: ProjectStatus,
    priority: Priority,
    next_action: str,
) -> None:
    project = load_store(ledger).projects["browser-demo"]
    report = run_doctor(ledger)

    assert project.status is status
    assert project.priority is priority
    assert project.next_action == next_action
    assert project.surfaces
    assert project.agents[0].value == "codex-cli"
    assert project.providers == ["browser-provider"]
    assert project.repo is not None
    assert project.repo.remote == "git@example.com:ctx/browser-demo.git"
    assert project.repo.default_branch == "main"
    assert project.repo.branch == "feature/browser-smoke"
    assert project.repo.known_risk == "watch the fetch path"
    assert project.blockers == ["none"]
    assert project.risks == ["keep fields"]
    assert project.rules == ["no framework"]
    assert report.error_count == 0


def _assert_layout(page, label: str) -> None:
    overflow = page.evaluate(
        """() => ({
          docWidth: document.documentElement.scrollWidth,
          viewportWidth: document.documentElement.clientWidth,
          bodyWidth: document.body.scrollWidth
        })"""
    )
    if overflow["docWidth"] > overflow["viewportWidth"] + 1:
        raise AssertionError(f"{label}: horizontal overflow {overflow}")

    clipped = page.evaluate(
        """() => Array.from(document.querySelectorAll(".pill, .menu-trigger, .filter-toggle, .row-toggle"))
          .filter((el) => {
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && (el.scrollWidth > el.clientWidth + 2 || el.scrollHeight > el.clientHeight + 3);
          })
          .map((el) => el.outerText || el.textContent || el.className)"""
    )
    if clipped:
        raise AssertionError(f"{label}: clipped controls: {clipped[:5]}")

    selectors = [
        ".search-field input",
        '[data-filter-field="status"] [data-menu-trigger]',
        '[data-filter-field="priority"] [data-menu-trigger]',
        ".filter-toggle",
        "#reset-filters",
    ]
    overlaps = page.evaluate(
        """(selectors) => {
          const items = selectors.flatMap((selector) => Array.from(document.querySelectorAll(selector)).map((el) => ({
            selector,
            rect: el.getBoundingClientRect()
          }))).filter((item) => item.rect.width > 0 && item.rect.height > 0);
          const hits = [];
          for (let i = 0; i < items.length; i += 1) {
            for (let j = i + 1; j < items.length; j += 1) {
              const a = items[i].rect;
              const b = items[j].rect;
              const separated = a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top;
              if (!separated) hits.push(`${items[i].selector} overlaps ${items[j].selector}`);
            }
          }
          return hits;
        }""",
        selectors,
    )
    if overlaps:
        raise AssertionError(f"{label}: toolbar overlap: {overlaps}")


def _assert_board_scrollable(page) -> None:
    scrollable = page.evaluate(
        """() => {
          const board = document.querySelector("[data-board]");
          return Boolean(board && board.scrollWidth > board.clientWidth + 20 && getComputedStyle(board).overflowX !== "visible");
        }"""
    )
    if not scrollable:
        raise AssertionError("desktop board should remain horizontally scrollable")


def _assert_menu_visible(page) -> None:
    rect = page.locator('[data-filter-field="status"] .menu-popover').bounding_box()
    viewport = page.viewport_size
    if rect is None or viewport is None:
        raise AssertionError("status menu is not visible")
    if rect["x"] < -1 or rect["y"] < -1 or rect["x"] + rect["width"] > viewport["width"] + 1:
        raise AssertionError(f"status menu outside viewport: {rect} in {viewport}")
    if rect["height"] < 120:
        raise AssertionError(f"status menu unexpectedly short: {rect}")


def _capture_and_compare(page, filename: str, *, update: bool) -> None:
    actual = OUTPUT_DIR / filename
    expected = SNAPSHOT_DIR / filename
    page.screenshot(path=actual, full_page=False)
    _assert_nonblank(actual)

    if update:
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(actual, expected)
        print(f"updated {expected.relative_to(ROOT_DIR)}")
        return

    if not expected.exists():
        raise AssertionError(f"missing UI snapshot baseline {expected}; run scripts/ui_browser_smoke.sh --update")
    _compare_images(expected, actual)
    print(f"ok snapshot {filename}")


def _assert_nonblank(path: Path) -> None:
    with Image.open(path) as image:
        if image.width < 300 or image.height < 300:
            raise AssertionError(f"screenshot too small: {path} {image.size}")
        grayscale = image.convert("L")
        low, high = grayscale.getextrema()
        if high - low < 10:
            raise AssertionError(f"screenshot appears blank: {path}")
        colors = image.convert("RGB").getcolors(maxcolors=1_000_000)
        if colors is not None and len(colors) < 20:
            raise AssertionError(f"screenshot has too few colors: {path}")


def _compare_images(expected: Path, actual: Path) -> None:
    with Image.open(expected).convert("RGB") as expected_raw:
        with Image.open(actual).convert("RGB") as actual_raw:
            expected_image = _normalize_for_diff(expected_raw)
            actual_image = _normalize_for_diff(actual_raw)
            if expected_image.size != actual_image.size:
                raise AssertionError(
                    f"{actual.name}: dimensions changed from {expected_image.size} to {actual_image.size}; "
                    f"actual saved at {actual}"
                )
            diff = ImageChops.difference(expected_image, actual_image)
            diff_pixels = _count_changed_pixels(diff)
            total_pixels = expected_image.width * expected_image.height
            ratio = diff_pixels / total_pixels
            if ratio > MAX_DIFF_RATIO:
                diff_path = OUTPUT_DIR / actual.name.replace(".png", ".diff.png")
                diff.point(lambda value: 255 if value > DIFF_PIXEL_THRESHOLD else 0).save(diff_path)
                raise AssertionError(
                    f"{actual.name}: visual diff {ratio:.3%} exceeds {MAX_DIFF_RATIO:.3%}; "
                    f"actual {actual}; diff {diff_path}"
                )


def _count_changed_pixels(diff: Image.Image) -> int:
    thresholded = diff.convert("L").point(lambda value: 255 if value > DIFF_PIXEL_THRESHOLD else 0)
    histogram = thresholded.histogram()
    return histogram[255]


def _normalize_for_diff(image: Image.Image) -> Image.Image:
    return image.convert("L").filter(ImageFilter.GaussianBlur(radius=0.8)).convert("RGB")


def _prepare_output_dir() -> None:
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
