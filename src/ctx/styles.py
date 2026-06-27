from __future__ import annotations

# CSS for the local action workbench UI.
# Imported by ui.py and embedded directly into each HTML response (single-file
# distribution — no separate static files).  Use normal CSS braces here; the
# f-string in ui.py inserts STYLES as a value so its braces are never
# interpreted as Python interpolation markers.

STYLES = """\
    :root {
      color-scheme: light;

      /* ── surface & text ── */
      --bg: #f7f7f5;
      --bg-subtle: #f0f0ee;
      --ink: #202428;
      --muted: #767672;
      --line: #e0e0dc;
      --line-soft: #ebebea;
      --panel: #ffffff;
      --panel-soft: #fafaf8;

      /* ── accent (teal) — use sparingly: primary button + active indicator ── */
      --accent: #25635f;
      --accent-fg: #ffffff;
      --accent-soft: #e8f3f0;
      --accent-line: #aecdc9;

      /* ── status semantic tokens (fg / bg / border) ── */
      --s-action-fg: #8a6d3b; --s-action-bg: #faf3e8; --s-action-line: #dfc99a;
      --s-doing-fg:  #4a6b8a; --s-doing-bg:  #edf2f8; --s-doing-line:  #c4d4e4;
      --s-block-fg:  #924040; --s-block-bg:  #fdf0f0; --s-block-line:  #e0b4b4;
      --s-todo-fg:   #5a5a58; --s-todo-bg:   #f3f3f1; --s-todo-line:   #ddddd8;
      --s-done-fg:   #4a7a5a; --s-done-bg:   #edf4f0; --s-done-line:   #b8d4c4;

      /* ── space scale (4 px base) ── */
      --space-1: 4px;  --space-2: 8px;  --space-3: 12px; --space-4: 16px;
      --space-5: 20px; --space-6: 24px; --space-7: 32px; --space-8: 40px;

      /* ── radii ── */
      --radius-sm: 6px;
      --radius-md: 8px;
      --radius-pill: 999px;

      /* ── control height baseline ── */
      --height-btn: 30px;

      /* ── shadows ── */
      --shadow-sm: 0 1px 2px rgba(15,15,15,.05);
      --shadow-md: 0 4px 14px rgba(15,15,15,.08);
      --shadow-lg: 0 12px 30px rgba(15,15,15,.11);
      --shadow-panel: -16px 0 36px rgba(15,15,15,.12);

      /* ── type scale ── */
      --fw-regular: 400;
      --fw-medium:  500;
      --fw-strong:  600;
      --fs-xs:   12px; --fs-sm: 13px; --fs-base: 14px;
      --fs-lg:   16px; --fs-xl: 21px;
      --lh: 1.55;

      /* ── legacy semantic vars (kept for JS / compat) ── */
      --blue: #315f91;
      --green: #2d6a4f;
      --amber: #946200;
      --red: #b42318;
      --violet: #6d5a96;
      --ok: #0f766e;
      --warn: #9a6700;
      --err: #b42318;
    }

    /* ── resets ── */
    * { box-sizing: border-box; }
    [hidden] { display: none !important; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: var(--fs-base);
      line-height: var(--lh);
      letter-spacing: 0;
    }
    button, input, textarea, select { letter-spacing: 0; }

    /* ── shell ── */
    .app-shell {
      min-height: 100vh;
      display: grid;
      grid-template-columns: minmax(0, 1fr);
    }
    .nav-icon { width: 21px; height: 21px; }
    .workbench { min-width: 0; }

    /* ── header ── */
    .app-header {
      display: flex;
      justify-content: space-between;
      gap: var(--space-5);
      align-items: center;
      padding: var(--space-2) clamp(var(--space-3), 3vw, var(--space-6));
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }
    h1, h2, h3, p { margin: 0; }
    h1 { font-size: var(--fs-xl); line-height: 1.2; }
    h2 { font-size: var(--fs-lg); }
    h3 { font-size: var(--fs-lg); }
    .app-header h1 { font-size: var(--fs-lg); }
    .header-copy p, .help, .muted, .setting-readout span, .project-name span { color: var(--muted); }
    .header-actions {
      position: relative;
      display: flex;
      align-items: center;
      gap: var(--space-2);
    }

    /* ── .popover — shared base for all floating menus ──
       z-index layers: context-menu 30 | filter 35 | header-menu 40 | peek-layer 80  */
    .popover {
      position: absolute;
      z-index: 30;
      border: 1px solid var(--line);
      border-radius: var(--radius-md);
      background: var(--panel);
      box-shadow: var(--shadow-lg);
      padding: var(--space-2);
    }

    /* ── more menu ── */
    .more-menu {
      position: relative;
      border: 1px solid var(--line);
      border-radius: var(--radius-md);
      background: var(--panel);
    }
    .more-menu > summary {
      list-style: none;
      padding: 7px var(--space-3);
      color: var(--ink);
      font-weight: var(--fw-strong);
      cursor: pointer;
      border-radius: var(--radius-md);
      transition: background-color 110ms;
    }
    .more-menu > summary:hover { background: var(--bg-subtle); }
    .more-menu > summary::-webkit-details-marker { display: none; }
    .more-popover {
      right: 0;
      top: calc(100% + var(--space-1));
      z-index: 40;
      display: grid;
      gap: var(--space-1);
      width: min(420px, calc(100vw - 32px));
    }
    .more-item {
      width: 100%;
      justify-self: stretch;
      border: 0;
      border-radius: var(--radius-sm);
      background: transparent;
      color: var(--ink);
      padding: var(--space-2) 10px;
      text-align: left;
    }
    .more-item:hover, .more-item.is-active {
      background: var(--accent-soft);
      color: var(--accent);
    }
    .more-item:active { background: var(--accent-line); }

    /* ── settings menu ── */
    .settings-menu {
      position: relative;
      border: 1px solid var(--line);
      border-radius: var(--radius-md);
      background: var(--panel);
    }
    .settings-menu summary {
      list-style: none;
      padding: 7px var(--space-2);
      color: var(--ink);
      font-weight: var(--fw-strong);
      cursor: pointer;
      border-radius: var(--radius-md);
      transition: background-color 110ms;
    }
    .settings-menu summary:hover { background: var(--bg-subtle); }
    .settings-menu summary::-webkit-details-marker { display: none; }
    .settings-menu form {
      position: absolute;
      right: 0;
      top: calc(100% + var(--space-1));
      z-index: 40;
      width: min(420px, calc(100vw - 32px));
      border: 1px solid var(--line);
      border-radius: var(--radius-md);
      background: var(--panel);
      box-shadow: var(--shadow-lg);
      padding: var(--space-3);
    }
    .more-popover .settings-menu form {
      position: static;
      width: 100%;
      margin-top: var(--space-1);
      box-shadow: none;
    }

    /* ── dashboard layout ── */
    .dashboard {
      display: grid;
      gap: var(--space-4);
      padding: var(--space-4) clamp(var(--space-4), 4vw, var(--space-8)) var(--space-8);
    }

    /* ── doctor drawer ── */
    .doctor-drawer {
      display: grid;
      gap: var(--space-2);
      border: 1px solid var(--line);
      border-radius: var(--radius-md);
      background: var(--panel);
      padding: var(--space-3);
    }
    .doctor-drawer > div { display: flex; gap: var(--space-2); align-items: center; }
    .doctor-drawer.ok { border-color: var(--s-done-line); }
    .doctor-drawer.warning { border-color: var(--s-action-line); }
    .doctor-drawer.error { border-color: var(--s-block-line); }

    /* ── action view ── */
    .section-label {
      font-size: var(--fs-xs);
      font-weight: var(--fw-strong);
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .action-view { display: grid; gap: var(--space-3); min-width: 0; }
    .action-queue { display: grid; gap: var(--space-2); }
    .action-item {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      grid-template-rows: auto auto;
      grid-template-areas: "name  controls" "body  controls";
      gap: var(--space-1) var(--space-3);
      align-items: end;
      border: 1px solid var(--line);
      border-radius: var(--radius-md);
      background: var(--panel);
      padding: var(--space-3);
    }
    .action-name { grid-area: name; min-width: 0; }
    .action-body { grid-area: body; display: grid; gap: var(--space-1); min-width: 0; }
    .action-controls {
      grid-area: controls;
      display: flex;
      flex-wrap: wrap;
      justify-content: end;
      align-items: center;
      gap: var(--space-2);
    }
    .flag-count {
      display: none;
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--warn);
      flex-shrink: 0;
    }
    .flag-count[data-count]:not([data-count="0"]) { display: inline-block; }
    .action-empty {
      border: 1px dashed var(--line);
      border-radius: var(--radius-md);
      background: var(--panel);
      color: var(--muted);
      padding: var(--space-6);
      text-align: center;
      font-weight: var(--fw-strong);
    }
    .action-item[data-status="action_required"] { box-shadow: inset 3px 0 0 var(--s-action-fg); }
    .action-item[data-status="now"],
    .action-item[data-status="doing"] { box-shadow: inset 3px 0 0 var(--s-doing-fg); }
    .action-item[data-status="blocked"],
    .action-item[data-status="sync_risk"] { box-shadow: inset 3px 0 0 var(--s-block-fg); }
    .action-item[data-status="todo"],
    .action-item[data-status="parked"] { box-shadow: inset 3px 0 0 var(--s-todo-fg); }

    .view-panel { min-width: 0; }

    /* ── alert ── */
    .alert {
      margin: var(--space-4) clamp(var(--space-4), 4vw, 44px) 0;
      padding: 10px var(--space-3);
      border-radius: var(--radius-md);
      background: var(--accent-soft);
      border: 1px solid var(--accent-line);
    }
    .alert.error { background: var(--s-block-bg); border-color: var(--s-block-line); }

    /* ── action-row shared controls (next-action editor + row save state) ── */
    .cell-open {
      display: block;
      width: 100%;
      border: 0;
      border-radius: var(--radius-sm);
      background: transparent;
      color: inherit;
      padding: 0;
      text-align: left;
      font: inherit;
      cursor: pointer;
    }
    .cell-open:hover strong, .cell-open:hover { color: var(--accent); background: transparent; }
    .next-action-edit {
      width: 100%;
      border: 0;
      border-radius: var(--radius-sm);
      background: transparent;
      color: var(--muted);
      padding: 2px 0;
      text-align: left;
      font: inherit;
      font-size: var(--fs-sm);
      font-weight: var(--fw-regular);
      overflow-wrap: anywhere;
    }
    .next-action-edit:hover { background: var(--bg-subtle); }
    .next-action-input { min-height: 34px; resize: vertical; }
    .row-save-state {
      display: block;
      min-height: 20px;
      color: var(--muted);
      font-size: var(--fs-xs);
      font-weight: var(--fw-strong);
      transition: color 200ms;
    }
    .row-save-state.saving { color: var(--blue); }
    .row-save-state.saved { color: var(--ok); }
    .row-save-state.error { color: var(--err); }
    .undo-link {
      margin-left: 5px;
      border: 0;
      background: transparent;
      color: var(--accent);
      padding: 0;
      font-size: var(--fs-xs);
      font-weight: var(--fw-strong);
    }
    .undo-link:hover { text-decoration: underline; }

    /* ── choice menus / pills ── */
    .choice-menu { position: relative; min-width: 0; }
    .menu-trigger, .pill {
      display: inline-grid;
      grid-template-columns: minmax(0, auto);
      gap: 1px;
      align-items: center;
      min-height: var(--height-btn);
      border: 1px solid var(--line);
      border-radius: var(--radius-sm);
      background: var(--panel-soft);
      color: var(--ink);
      padding: 5px 10px;
      font: inherit;
      font-weight: var(--fw-strong);
      cursor: pointer;
      text-align: left;
      max-width: 100%;
    }
    .filter-trigger { width: 100%; background: var(--panel-soft); }
    .menu-trigger small, .pill small {
      color: var(--muted);
      font-size: 11px;
      font-weight: var(--fw-medium);
      line-height: 1.1;
    }
    .pill[disabled] { opacity: 0.62; cursor: wait; }
    .pill { transition: filter 100ms; }
    .pill:hover:not([disabled]) { filter: brightness(0.95); }

    /* ── tone classes: status & priority chips ── */
    .tone-action { color: var(--s-action-fg); background: var(--s-action-bg); border-color: var(--s-action-line); }
    .tone-now, .tone-doing { color: var(--s-doing-fg); background: var(--s-doing-bg); border-color: var(--s-doing-line); }
    .tone-risk, .tone-blocked { color: var(--s-block-fg); background: var(--s-block-bg); border-color: var(--s-block-line); }
    .tone-todo, .tone-parked { color: var(--s-todo-fg); background: var(--s-todo-bg); border-color: var(--s-todo-line); }
    .tone-done, .tone-archived { color: var(--s-done-fg); background: var(--s-done-bg); border-color: var(--s-done-line); }
    .tone-high { color: var(--s-block-fg); background: var(--s-block-bg); border-color: var(--s-block-line); }
    .tone-medium { color: var(--s-action-fg); background: var(--s-action-bg); border-color: var(--s-action-line); }
    .tone-low { color: var(--s-done-fg); background: var(--s-done-bg); border-color: var(--s-done-line); }
    .tone-neutral { color: var(--s-todo-fg); background: var(--s-todo-bg); border-color: var(--s-todo-line); }

    /* ── menu popover ── */
    .menu-popover {
      top: calc(100% + var(--space-1));
      left: 0;
      min-width: 220px;
      max-width: min(300px, calc(100vw - 24px));
      max-height: min(430px, calc(100vh - 120px));
      overflow: auto;
    }
    [data-menu-root].opens-up .menu-popover {
      top: auto;
      bottom: calc(100% + var(--space-1));
    }
    .filter-menu .menu-popover { min-width: 100%; }
    .menu-section-title {
      padding: var(--space-2) var(--space-2) var(--space-1);
      color: var(--muted);
      font-size: 11px;
      font-weight: var(--fw-strong);
    }
    .menu-option {
      position: relative;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: var(--space-2);
      align-items: center;
      width: 100%;
      border: 0;
      border-radius: var(--radius-sm);
      background: transparent;
      color: var(--ink);
      padding: 7px var(--space-2);
      text-align: left;
      font: inherit;
      cursor: pointer;
    }
    .menu-option:hover, .menu-option.is-selected { background: var(--bg-subtle); }
    .menu-option:active { background: var(--accent-soft); color: var(--accent); }
    .menu-option.is-selected::before {
      content: "";
      width: 3px;
      height: 18px;
      border-radius: var(--radius-pill);
      background: var(--accent);
      position: absolute;
      margin-left: -5px;
    }
    .menu-option span { font-weight: var(--fw-strong); }
    .menu-option small { color: var(--muted); font-size: 11px; }

    /* ── flags / tags ── */
    .flag {
      display: inline-flex;
      align-items: center;
      margin: 0 var(--space-1) var(--space-1) 0;
      border: 1px solid var(--line);
      border-radius: var(--radius-sm);
      padding: 2px var(--space-1);
      font-size: var(--fs-xs);
      font-weight: var(--fw-strong);
      white-space: nowrap;
    }

    /* ── flag variants ── */
    .flag.warning { color: var(--s-action-fg); background: var(--s-action-bg); border-color: var(--s-action-line); }
    .flag.error { color: var(--s-block-fg); background: var(--s-block-bg); border-color: var(--s-block-line); }

    /* ── peek panel ── */
    .peek-layer {
      position: fixed;
      inset: 0;
      z-index: 80;
      display: grid;
      justify-content: end;
      background: rgba(15, 18, 20, 0.22);
    }
    .peek-backdrop {
      position: fixed;
      inset: 0;
      z-index: 0;
      border: 0;
      border-radius: 0;
      background: transparent;
      padding: 0;
      cursor: pointer;
    }
    .peek-panel {
      position: relative;
      z-index: 1;
      width: min(560px, 100vw);
      height: 100vh;
      overflow: auto;
      background: var(--panel);
      border-left: 1px solid var(--line);
      box-shadow: var(--shadow-panel);
      padding: var(--space-5);
    }
    .peek-head {
      display: flex;
      align-items: start;
      justify-content: space-between;
      gap: var(--space-3);
      margin-bottom: var(--space-3);
    }
    .peek-head p { color: var(--muted); margin-top: 3px; }

    /* ── property list ── */
    .property-list {
      display: grid;
      gap: 1px;
      margin: 0 0 var(--space-4);
      border: 1px solid var(--line-soft);
      border-radius: var(--radius-sm);
      overflow: hidden;
    }
    .property-list div {
      display: grid;
      grid-template-columns: 118px minmax(0, 1fr);
      gap: var(--space-2);
      padding: 7px 9px;
      background: var(--panel-soft);
    }
    .property-list dt { color: var(--muted); font-size: var(--fs-xs); font-weight: var(--fw-strong); }
    .property-list dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }

    /* ── forms ── */
    form { display: grid; gap: var(--space-3); }
    .create-form {
      grid-template-columns: minmax(180px, 0.7fr) minmax(260px, 1.3fr) auto;
      align-items: end;
    }
    label { display: grid; gap: var(--space-1); font-weight: var(--fw-strong); }
    input, select, textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: var(--radius-sm);
      padding: var(--space-2) 9px;
      font: inherit;
      background: var(--panel);
      color: var(--ink);
    }
    textarea { min-height: 68px; resize: vertical; }
    [aria-invalid="true"] { border-color: var(--err); }
    .field-error { color: var(--err); font-weight: var(--fw-strong); font-size: var(--fs-sm); }
    .help { font-size: var(--fs-xs); font-weight: var(--fw-medium); }

    /* ── btn component system ── */
    /* Base: minimal shared token — focus ring + disabled state */
    .btn {
      font: inherit;
      font-weight: var(--fw-strong);
      cursor: pointer;
      transition: background-color 110ms, color 110ms, border-color 110ms;
    }
    .btn:focus-visible {
      outline: 2px solid var(--accent);
      outline-offset: 2px;
    }
    .btn:disabled, .btn[disabled] {
      opacity: 0.48;
      cursor: not-allowed;
    }
    /* primary — accent fill */
    .btn--primary {
      justify-self: start;
      border: 0;
      border-radius: var(--radius-sm);
      min-height: var(--height-btn);
      padding: 6px var(--space-3);
      background: var(--accent);
      color: var(--accent-fg);
      font-weight: var(--fw-strong);
    }
    .btn--primary:hover { background: #1f5250; }
    .btn--primary:active { background: #174340; }
    /* secondary — neutral fill */
    .btn--secondary {
      justify-self: start;
      border: 1px solid var(--line);
      border-radius: var(--radius-sm);
      min-height: var(--height-btn);
      padding: 6px var(--space-3);
      background: var(--bg-subtle);
      color: var(--ink);
      font-weight: var(--fw-strong);
    }
    .btn--secondary:hover { background: var(--line-soft); }
    /* icon — square, height-btn */
    .btn--icon, .icon-button {
      width: var(--height-btn);
      height: var(--height-btn);
      display: inline-grid;
      place-items: center;
      border: 1px solid var(--line);
      border-radius: var(--radius-sm);
      background: var(--bg-subtle);
      color: var(--ink);
      padding: 0;
    }
    .btn--icon:hover, .icon-button:hover { background: var(--line-soft); border-color: var(--muted); }
    /* ── legacy bare button defaults (submit buttons, unclassed elements) ── */
    button {
      justify-self: start;
      border: 0;
      border-radius: var(--radius-sm);
      padding: var(--space-2) var(--space-3);
      background: var(--accent);
      color: var(--accent-fg);
      font: inherit;
      font-weight: var(--fw-strong);
      cursor: pointer;
      transition: background-color 110ms;
    }
    button:hover { background: #1f5250; }
    button:active { background: #174340; }
    button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
    button:disabled, button[disabled] { opacity: 0.48; cursor: not-allowed; }
    button.secondary {
      background: var(--bg-subtle);
      color: var(--ink);
      border: 1px solid var(--line);
    }
    button.secondary:hover { background: var(--line-soft); }

    /* ── advanced form sections ── */
    .more-fields { border-top: 1px solid var(--line); padding-top: var(--space-3); display: grid; gap: var(--space-4); }
    .advanced-group { display: grid; gap: var(--space-3); border: 1px solid var(--line-soft); border-radius: var(--radius-md); padding: var(--space-3); }
    .advanced-group-title { font-weight: var(--fw-strong); font-size: var(--fs-sm); color: var(--muted); margin: 0; }
    summary { cursor: pointer; font-weight: var(--fw-strong); color: var(--accent); }
    fieldset { border: 1px solid var(--line); border-radius: var(--radius-md); padding: 10px; }
    legend { font-weight: var(--fw-strong); }
    .checks, .radio-row { display: flex; flex-wrap: wrap; gap: var(--space-2); }
    .checks label, .radio-row label {
      display: flex;
      align-items: center;
      gap: var(--space-1);
      font-weight: var(--fw-strong);
      border: 1px solid var(--line);
      border-radius: var(--radius-sm);
      padding: var(--space-1) var(--space-2);
      background: var(--panel);
    }
    .checks input, .radio-row input { width: auto; }
    .grid-two { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-3); }
    .detail-summary {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: var(--space-2) var(--space-3);
      margin: var(--space-3) 0 0;
    }
    .detail-summary div { min-width: 0; }
    .detail-summary dt { color: var(--muted); font-size: var(--fs-xs); font-weight: var(--fw-strong); }
    .detail-summary dd { margin: 2px 0 0; overflow-wrap: anywhere; }
    .diagnostics { padding-left: 18px; margin: 0; }
    .diagnostics li { margin-bottom: 7px; }
    .muted, .setting-readout span { color: var(--muted); }
    .setting-readout { display: grid; gap: 3px; overflow-wrap: anywhere; }
    .checkline { display: flex; align-items: center; gap: var(--space-2); font-weight: var(--fw-strong); }
    .checkline input { width: auto; }

    /* ── responsive ── */
    @media (max-width: 760px) {
      .app-shell { display: block; }
      .app-header { align-items: stretch; flex-direction: column; gap: 10px; }
      .header-actions { justify-content: space-between; }
      .more-popover { position: static; width: 100%; margin-top: var(--space-1); box-shadow: none; }
      .more-menu { justify-self: stretch; }
      .settings-menu form { position: static; width: 100%; margin-top: var(--space-1); box-shadow: none; }
      .dashboard { padding-inline: var(--space-3); }
      .action-item { grid-template-columns: 1fr; grid-template-areas: "name" "body" "controls"; }
      .action-controls { justify-content: start; }
      .create-form, .grid-two, .detail-summary { grid-template-columns: 1fr; }
      .menu-popover { position: fixed; left: 12px; right: 12px; top: auto; bottom: 12px; max-width: none; width: auto; }
      .peek-layer { justify-content: stretch; }
      .peek-panel { width: 100vw; border-left: 0; box-shadow: none; }
      .property-list div { grid-template-columns: 92px minmax(0, 1fr); }
      /* touch targets ≥44px on mobile */
      .pill, .menu-trigger, .btn--primary, .btn--secondary { min-height: 44px; }
      .btn--icon { width: 44px; height: 44px; }
    }
"""
