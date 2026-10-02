# Install the terminal dashboard with the CLI

Change-kind: bug fix.

`make install` exported constraints for the `kokoro` extra only and installed the bare checkout, so the installed CLI had no Textual and `ai-tts tui` could not run. The README's suggested fix, `uv tool install --force '.[tui]'`, replaced the entire uv tool environment without `kokoro`, the spaCy English model, or the lock constraints, which left the daemon unable to speak.

The installer now exports the frozen lock with `--extra kokoro --extra tui` and installs `<checkout>[tui]` with the same constraints, `--reinstall-package ai-tts`, Kokoro, and the English model. The README's manual and MLX commands do the same. The README now warns against the bare `.[tui]` reinstall and suggests `uv run --extra tui ai-tts tui` for trying the dashboard from a checkout.

- `test_install_includes_the_terminal_dashboard_at_its_locked_versions` (medium, `tests/test_make_installation.py`) runs the real Make entry point through the owned uv and launchctl fakes, whose `export` delegates to the real uv against the real lockfile. It requires that the tool-install package argument requests the `tui` extra and that the constraints file pins `textual` to the locked version. Oracle: README "Terminal dashboard", which says `ai-tts tui` works after `make install`. It was red on parent `f7c2524` with `the tool install omits the tui extra: /Users/james/git/ai-tts`, and it passes after the fix. The rest of `tests/test_make_installation.py` and `tests/test_launch_agent_activation.py` (39 tests) pass unchanged.
- Real host, 2026-10-02: `make install` resolved 111 packages, added Textual and four of its dependencies, and kept Kokoro 0.9.4, transformers 5.16.1, and `en_core_web_sm` 3.8.0. The installed Textual is 8.2.8, which equals the lock. The daemon came back `ok` on engine kokoro, `~/.local/bin/ai-tts tui --help` succeeded, and the menu-bar app was relaunched by its login agent.

Limits: the automated test checks installation intent and the exported pins. The real install is the evidence that uv accepts the `<path>[tui]` package specification.
