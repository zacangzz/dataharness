# PyInstaller + Textual TUI: Blank Screen Debug Log

**Date:** 2026-04-13  
**Status:** Resolved — packaged app renders; root cause was app CSS layout, not PyInstaller  
**Binary:** `dist/hragent` (PyInstaller onefile, macOS)

---

## The Problem

The original symptom was "blank screen": `./dist/hragent` appeared to hang with no visible UI.

What made this confusing was that multiple things were true at once:

- PyInstaller onefile **can** attach stdio in a way that breaks Textual unless `/dev/tty` is used.
- The app **was** entering Textual application mode and drawing a frame.
- The app still looked blank because its own CSS caused one widget to paint over the rest of the layout.

So the final issue was not a single packaging bug. The packaging/tty diagnosis was useful, but it was not the last-mile root cause of the blank screen seen in this repo.

---

## Architecture Overview

```
src/main.py          — entrypoint: resolves model path, loads LlmModel, patches tty, runs ChatApp
src/cli/app.py       — Textual TUI (ChatApp): input box, message log, streaming replies
src/core/model.py    — LlmModel: wraps llama-cpp-python, exposes stream(history) generator
hragent.spec         — PyInstaller spec: bundles textual + llama_cpp, excludes libmtmd
```

The binary is a **PyInstaller onefile** (`--onefile`): a self-extracting archive that unpacks to a temp dir and re-executes itself as a child process.

---

## Root Cause: PyInstaller Onefile stdio Pipes

### What PyInstaller onefile does to stdio

When a PyInstaller onefile binary runs:

1. The **bootloader** (outer process) starts and extracts the archive to a temp dir
2. It re-executes the **Python process** (inner process) as a child
3. The inner process's stdio file descriptors **are not inherited from the terminal** — they are pipes connecting to the bootloader

This means inside the frozen binary:
- `sys.__stdin__` (fd 0) = a pipe, not the keyboard
- `sys.__stdout__` (fd 1) = a pipe, not the terminal
- `sys.__stderr__` (fd 2) = a pipe, not the terminal

All three `isatty()` checks return `False`.

### Why this breaks Textual

Textual's `LinuxDriver` (`textual/drivers/linux_driver.py`) uses two fds:

```python
self._file = sys.__stderr__        # fd 2: writes all terminal escape sequences here
self.fileno = sys.__stdin__.fileno()  # fd 0: reads keyboard events from here
```

In `start_application_mode()`:
```python
if os.isatty(self.fileno):         # if False → tcsetattr NEVER called
    termios.tcsetattr(...)         # this sets raw mode — required for keyboard input
```

With piped fds:
- **fd 2 is a pipe** → all ANSI escape sequences (rendering, cursor, colour) go to a pipe that nobody reads → blank screen
- **fd 0 is a pipe** → `os.isatty(0)` is False → `tcsetattr` skipped → terminal stays in cooked mode → no raw keyboard input reaches Textual → app hangs
- **fd 1 is a pipe** → `print("Loading model…")` in `main.py` goes to the pipe → invisible

### The baseline tty fix

Open `/dev/tty` (the controlling terminal, bypasses the pipe redirection) and use `os.dup2` to replace all three standard fds before `app.run()`:

```python
import os
if not sys.__stderr__.isatty():
    try:
        tty_fd = os.open("/dev/tty", os.O_RDWR)
        os.dup2(tty_fd, 0)   # stdin  → /dev/tty  (Textual reads keys from fd 0)
        os.dup2(tty_fd, 1)   # stdout → /dev/tty  (print() output)
        os.dup2(tty_fd, 2)   # stderr → /dev/tty  (Textual writes output to fd 2)
        os.close(tty_fd)
    except OSError as exc:
        log.warning("could not open /dev/tty: %s", exc)
```

`os.dup2` replaces the underlying fd in-place, so existing Python file objects (`sys.__stdin__`, `sys.__stderr__`) automatically point to `/dev/tty` without needing to be replaced.

**Why `os.dup2` instead of replacing `sys.__stderr__`:**  
Textual captures `sys.__stderr__` by reference at `LinuxDriver.__init__` time, but then calls `.fileno()` on it. The fileno (2) must itself be a tty. Replacing the Python object doesn't change fd 2 — `os.dup2` does.

---

## Updated findings

- `llama_cpp` does temporarily redirect stdout/stderr during model init when `verbose=False`, but its context manager restores the fds when model init exits.
- A direct run of `./dist/hragent` from a real terminal now shows:
  - `Loading model…`
  - `Model loaded, starting UI…`
  - a rendered Textual frame
- That means the remaining problem is not "Textual never renders" in all cases. It is a combination of launch-context sensitivity and an initial UI state that can look blank.

## Final root cause

The actual root cause of the "blank screen" in `hragent` was a **Textual CSS layout bug** in the app itself.

The app originally used this broad selector:

```python
ScrollableContainer {
    height: 1fr;
    border: solid $primary;
    padding: 1 2;
}
```

That looked harmless because it was intended for the message log. But in Textual, `Footer` is itself implemented as a `ScrollableContainer`.

So this selector unintentionally affected:

- `#message-log`
- `Footer`

The result was that `Footer` no longer kept its normal `height: 1`; it inherited `height: 1fr` and expanded to fill the screen, painting over the app. The UI was running, but the message log and welcome text were visually hidden behind the oversized footer/input area.

### Evidence from the debug run

Using `textual-dev` plus an instrumented debug launcher showed:

- `#message-log` existed
- the welcome `Static("HR Agent ...")` widget was mounted
- `Input` and `Footer` were both occupying full-screen regions

Captured layout:

- `message_log region: Region(x=0, y=0, width=78, height=4)`
- `input region: Region(x=0, y=0, width=78, height=24)`
- `footer region: Region(x=0, y=0, width=78, height=24)`
- `footer styles dock=bottom height=1fr`

That proved the app was not blank because it failed to compose or mount. It was blank because the wrong widget was covering the screen.

### The fix

Narrow the CSS so it targets only the message log:

```python
#message-log {
    height: 1fr;
    border: solid $primary;
    padding: 1 2;
    border-title-align: left;
}
```

Then explicitly size the bottom widgets:

```python
#chat-input {
    dock: bottom;
    height: 3;
    width: 100%;
}

Footer {
    dock: bottom;
    height: 1;
}
```

There was also a secondary cleanup:

- guard the welcome/system message so it mounts once only

This avoided duplicate startup messages during debugging runs.

## Troubleshooting Timeline

### Attempt 1 — Wrong `@work` import (earlier session)
**Hypothesis:** `from textual._work_decorator import work` uses a private module that PyInstaller may not bundle.  
**Fix:** Changed to `from textual import work` (public API).  
**Result:** No change. Blank screen persisted.

### Attempt 2 — os.dup2 in worker thread (earlier session)
**Hypothesis:** llama.cpp C++ init spams stderr before TUI starts, corrupting rendering.  
**Fix:** Redirected fd 2 to `/dev/null` inside the model-loading worker thread using `os.dup2`.  
**Result:** Made things worse — fd 2 was redirected to `/dev/null` while Textual's render loop was already running, sending all TUI output to `/dev/null`.

### Attempt 3 — Load model before app.run() (earlier session)
**Hypothesis:** llama_cpp's `verbose=False` internally does `os.dup2(devnull, 2)` during C++ init. If this runs while Textual is active it kills rendering.  
**Fix:** Moved model loading to before `app.run()`. Removed the worker thread for model loading entirely.  
**Result:** Eliminated the dup2 race condition. Still blank screen due to the pipe issue.

### Attempt 4 — Patch sys.__stderr__ only (earlier session)
**Hypothesis:** Textual writes to `sys.__stderr__`; redirect it to `/dev/tty`.  
**Fix:**
```python
tty_fd = os.open("/dev/tty", os.O_RDWR)
tty_file = io.TextIOWrapper(io.FileIO(tty_fd, closefd=True))
sys.__stderr__ = tty_file
```
**Result:** Still blank. This replaced the Python object but did not replace fd 2. Textual's `WriterThread` holds the old `sys.__stderr__` reference; even if it updated, fd 0 (stdin) was still a pipe so `tcsetattr` was skipped.

### Attempt 5 — os.dup2 on fds 0 and 2 (this session)
**Hypothesis:** Both fd 0 (stdin) and fd 2 (stderr) must be a tty for Textual to work.  
**Fix:**
```python
tty_fd = os.open("/dev/tty", os.O_RDWR)
os.dup2(tty_fd, 0)
os.dup2(tty_fd, 2)
os.close(tty_fd)
```
**Verification:** Built a minimal clock app (`tests/clock_tty_test.py`) with only this fix and no model loading. **Clock rendered correctly as a frozen binary.** Confirmed fix is sound for pure Textual apps.  
**Result for hragent:** Still blank. `print("Loading model…")` also invisible — revealed fd 1 (stdout) was still a pipe.

### Attempt 6 — os.dup2 on fds 0, 1, and 2
**Fix:** Added `os.dup2(tty_fd, 1)` for stdout.  
**Result:** Direct terminal reproduction shows visible loading output and a rendered Textual frame.

### Attempt 7 — Improve startup diagnostics and first-frame visibility (current state)
**Hypothesis:** Some "blank screen" reports are successful renders with too little visible content, not total render failure.  
**Fix:** Move tty diagnostics into a reusable startup helper, log pre/post model-init stdio state, and make the first Textual frame visibly non-empty.  
**Goal:** Distinguish real tty/render failures from an empty initial UI.

### Attempt 8 — Use `textual-dev` to inspect live layout (resolved)
**Hypothesis:** The app may be composing successfully, but a layout rule is hiding the real content.  
**Fix:** Added `textual-dev` as a dev dependency and used an instrumented launcher to inspect mounted widgets and computed regions.  
**Result:** Confirmed `Footer` was inheriting `ScrollableContainer { height: 1fr; }` and painting over the screen. This was the real root cause.

---

## Smoke Test: clock_tty_test

To isolate the TUI fix from model loading complexity, a minimal frozen binary was created:

- **Source:** `tests/clock_tty_test.py` — Textual clock app + tty fix, no dependencies
- **Spec:** `clock_test.spec` — textual only, no llama_cpp
- **Build:** `uv run pyinstaller clock_test.spec --distpath dist_clock`
- **Run:** `./dist_clock/clock_test`

**Result: Clock rendered correctly.** This confirms:
- The `/dev/tty` approach is correct
- Textual bundles correctly with PyInstaller
- The tty fix resolves the blank screen for pure Textual apps

The remaining question is not whether Textual can render, but whether specific launch contexts still bypass the repaired tty path.

---

## Textual Driver Internals (Reference)

From `textual/drivers/linux_driver.py`:

| What | fd | Used for |
|------|----|----------|
| `self._file = sys.__stderr__` | 2 | `WriterThread` writes all ANSI escape sequences here |
| `self.fileno = sys.__stdin__.fileno()` | 0 | Input selector reads keyboard events; `tcsetattr` raw mode |
| `self.input_tty = sys.__stdin__.isatty()` | 0 | Guards `_request_terminal_sync_mode_support` |

From `textual/drivers/_writer_thread.py`:

```python
def run(self) -> None:
    write = self._file.write   # self._file captured from sys.__stderr__ at init
    flush = self._file.flush
    while True:
        text = get()
        if text is None: break
        write(text)
        if qsize() == 0: flush()
```

`WriterThread` holds a direct reference to the file object captured at `LinuxDriver.__init__`. The `_file.write()` call goes to whatever fd the file object wraps — so `os.dup2` on fd 2 affects this correctly.

---

## Files Modified

| File | Change |
|------|--------|
| `src/main.py` | Repairs tty before visible output, logs fd diagnostics around model init, then starts the UI |
| `src/core/terminal.py` | Shared stdio diagnostics and `/dev/tty` repair helper |
| `src/cli/app.py` | Fixed the layout bug by narrowing the container CSS; shows a visible ready state on first frame |
| `hragent.spec` | Refactored with `optional_*` helpers; excludes `libmtmd`, `tkinter`, `pytest` |
| `tests/clock_tty_test.py` | New: minimal Textual smoke test for frozen binary tty fix |
| `clock_test.spec` | New: PyInstaller spec for clock smoke test |

## Lessons Learned

### 1. Separate packaging bugs from app layout bugs

If a packaged Textual app looks blank, do not assume PyInstaller is the only cause.

Check these separately:

- Did the app enter Textual alt-screen mode?
- Did startup/mount logs run?
- Did a frame border or footer paint?
- Are the actual child widgets present and sized correctly?

If the frame exists but the content does not, the next step should be layout inspection, not more PyInstaller speculation.

### 2. Avoid broad widget-class selectors in Textual CSS

Rules like:

```css
ScrollableContainer { ... }
```

are dangerous unless you genuinely want to affect **every** subclass in the app, including framework widgets such as `Footer`.

Prefer:

- `#message-log`
- `.chat-panel`
- other app-specific selectors

This is the single most important lesson from this incident.

### 3. `compose()` existing is not enough

The app did have a valid `compose()` and it yielded widgets correctly. The screen still looked blank because a different widget overpainted the content.

So:

- "blank screen" does **not** imply missing widgets
- "compose works" does **not** imply layout works

Always inspect computed regions when behavior contradicts mounted widgets.

### 4. `textual-dev` is the fastest truth source for Textual rendering issues

For future agents: use `textual-dev` early.

Helpful workflow:

1. `uv add --dev textual-dev`
2. create a tiny debug launcher around the real app
3. log widget regions, mounted children, and computed styles
4. only after that, change CSS/layout

This was what exposed the real bug.

### 5. Keep tty diagnostics, but don’t stop there

The `/dev/tty` repair work was still valid and should stay:

- PyInstaller onefile can still produce pipe-backed stdio
- Textual still depends on real tty-backed input/output

But once tty diagnostics show healthy `isatty()` values, shift attention to the app layout itself.

## Practical future checklist

If another packaged Textual app in this repo looks blank:

1. Check the log for startup, mount, and tty diagnostics.
2. Confirm whether Textual entered alt-screen mode at all.
3. If borders/footer paint but content does not, suspect layout/CSS overdraw.
4. Search for broad selectors like `ScrollableContainer`, `Widget`, `Container`, `Static`, etc.
5. Use `textual-dev` to inspect computed regions before changing packaging.
6. Prefer app-specific selectors over framework-class selectors.

---

## Next Steps

1. Check `dist/local/hragent.log` after running `./dist/hragent` and review the before/after stdio diagnostics
2. If a user still reports a blank screen, capture the exact launch context and whether `Model loaded, starting UI…` was visible
3. If diagnostics show `/dev/tty` cannot be opened in a specific environment, treat that as a separate launch-context bug rather than a general Textual failure

---

## Key References

- Textual `LinuxDriver`: `.venv/lib/python3.12/site-packages/textual/drivers/linux_driver.py`
- Textual `WriterThread`: `.venv/lib/python3.12/site-packages/textual/drivers/_writer_thread.py`
- PyInstaller onefile behaviour: bootloader spawns child process with piped stdio
- `/dev/tty`: the controlling terminal device, always accessible regardless of stdio redirection
