# Read with AI-TTS in Zed

Change-kind: feature.

Run **Read with AI-TTS** from Zed's task picker to save and queue the active
UTF-8 text document. Run **Read Selection with AI-TTS** to queue just the current
selection without saving. Both use the existing daemon and playback controls.

## Install

Install a version of AI-TTS containing the `ai-tts-zed-read` entry point.
For development, run `uv sync --frozen` in this checkout. The helper then lives
at `.venv/bin/ai-tts-zed-read`; it needs no speech-model extras because the
already-running daemon owns synthesis.

Use **zed: open tasks** from the command palette to open your global tasks file,
usually `~/.config/zed/tasks.json`. Append the objects from [tasks.json](tasks.json)
to its existing array. For a development install, change each `command` to the
absolute path of `.venv/bin/ai-tts-zed-read` in this checkout. An absolute path
also avoids differences between your shell's PATH and Zed's environment.

These global tasks work across projects. Each task explicitly maps its required
Zed variable into the environment, which also filters it out when that context
is unavailable. You can instead put the definitions
in one project's `.zed/tasks.json` if you only want them there.

Optionally append the object in [keymap.json](keymap.json) to your Zed keymap.
It proposes **Command+Option+R** for the document and
**Command+Option+Shift+R** for the selection. Choose other keys if these conflict
with your existing bindings. The task picker works without keymap changes.

## Use and recovery

1. Start AI-TTS normally.
2. Open a text document in Zed, then use **task: spawn** from the command palette.
3. Choose **Read with AI-TTS**, or highlight a passage and choose
   **Read Selection with AI-TTS**.
4. Use the AI-TTS menu-bar controls to pause, resume, skip, or change playback rate.

Successful submission hides the task terminal. Errors leave it visible without
moving focus away from the editor. Fix the reported problem, then invoke the
named task again. Exit zero means queued, not heard. Existing playback holds
remain in effect; invoking a read task never resumes playback automatically.

**Read with AI-TTS saves the active buffer before it reads the file.** This is
necessary because tasks cannot directly obtain the whole unsaved editor buffer.
Give untitled documents a filename inside an open project first. If the
selection task is available, it can read highlighted text without a filename.
In the tested Zed 1.23.3 host, buffers outside an open worktree did not supply
task context. Open the document's parent folder as a project if the tasks are
missing. Do not use a cached task rerun after changing documents or
selections: spawn the named task again, or bind `task::Rerun` with
`reevaluate_context: true`.

## Admission and failure contracts

- File input comes from `ZED_FILE`. `.md` and `.markdown` extensions, ignoring
  case, use Markdown interpretation. Other UTF-8 text files remain literal.
  A UTF-8 BOM is removed; line endings and remaining characters are preserved.
- Selection input comes from `ZED_SELECTED_TEXT` and stays literal, including
  Markdown punctuation, Unicode, quotes, and shell-looking text.
- Both inputs are confidential, Normal priority, and attributed to `zed:file`
  or `zed:selection`. They use the daemon's configured voice, engine, and speed.
- The helper reads Zed's environment directly and sends text over the existing
  Unix-socket client. Document text is never interpolated into a shell command
  or passed as a process argument. Its success output contains only the queued
  utterance ID. Zed still carries selections in the process environment, which
  imposes the operating system's process-launch size limit on selections.
- Empty input, missing files, directories, invalid UTF-8, NUL-containing binary
  input, and text over 512 KiB fail before admission. Reads are bounded rather
  than loading an arbitrary file into memory. PDFs and other rich documents
  require the native AI-TTS file entry point rather than this text task.
- Requests exceeding the daemon's 1 MiB encoded JSONL limit are refused locally.
  Some Unicode or control-heavy documents hit this limit below 512 KiB.
- Exit 1 means a local refusal or a daemon refusal. Exit 2 means the daemon is
  unreachable. Failure never prints a document preview. A transport failure
  can leave admission uncertain; check AI-TTS's queue before retrying to avoid
  submitting the same text twice.

## Verification

The daemon tests in `tests/test_zed.py` use an owned paused daemon, a fake speech
engine, and a silent sink. They verify exact literal selection admission,
Markdown interpretation, attribution, confidentiality, preserved holds,
inclusive byte limits, and refusal without queue admission.

Installed Zed 1.23.3 acceptance verified a dirty file saved before admission,
literal selection submission, a changed unsaved selection without saving, and
visible daemon-unavailable failure followed by successful recovery. It also
established the missing-context limitation for buffers outside an open
worktree. These checks used a separate paused test daemon and produced no
audible output. Optional keyboard bindings and process-environment size limits
were not exercised. See the [testing receipt](../../docs/testing-evidence/2026-10-14-zed-tasks.md).

See [Zed's task documentation](https://zed.dev/docs/tasks) for global task
installation, save behavior, environment variables, and custom keybindings.
