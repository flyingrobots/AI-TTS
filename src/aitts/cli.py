# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The command-line client, and the daemon runner.

Exit status tells the truth, narrowly (features.md §8): 0 means the daemon
accepted the operation — for ``say``, that the utterance was queued, not that
it was heard. ``say --wait`` and ``wait`` exist for callers that need the
stronger guarantee, and they exit 0 only for Played.

Playback pause is not backpressure. Callers should continue using ``say``;
accepted speech is spooled until the user resumes playback.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import signal
import sys
from pathlib import Path
from typing import Any

from aitts import __version__
from aitts.client import Client, DaemonError, DaemonUnreachableError
from aitts.model import ContentFormat, State
from aitts.paths import default_home, default_socket

EXIT_OK = 0
EXIT_DAEMON_ERROR = 1
EXIT_UNREACHABLE = 2
EXIT_NOT_PLAYED = 3

_TRANSPORT_OPS = ("pause", "resume", "skip", "status", "voices", "metrics", "engines")


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, indent=2) + "\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-tts",
        description="Send text to the AI-TTS daemon and control playback.",
    )
    parser.add_argument("--version", action="version", version=f"ai-tts {__version__}")
    parser.add_argument(
        "--socket",
        type=Path,
        default=None,
        help="daemon socket path (default: AI_TTS_SOCKET or the daemon home)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("tui", help="open the interactive terminal dashboard (requires ai-tts[tui])")

    say = sub.add_parser("say", help="queue text to be spoken, even while playback is paused")
    say.add_argument("text")
    say.add_argument(
        "--format",
        dest="content_format",
        choices=[content_format.value for content_format in ContentFormat],
        default=ContentFormat.PLAIN_TEXT.value,
        help="interpret input as literal plain text or Markdown (default: plain_text)",
    )
    say.add_argument("--voice")
    say.add_argument("--engine", help="backend for this clip; defaults to the live setting")
    say.add_argument("--speed", type=float)
    say.add_argument(
        "--sensitivity",
        choices=["public", "internal", "confidential"],
        help="who may speak this text (omitted = confidential; fail closed)",
    )
    say.add_argument("--priority", choices=["normal", "urgent", "preempt"])
    say.add_argument(
        "--preempt", action="store_true", help="interrupt and later resume current speech"
    )
    say.add_argument("--source", help="client identity recorded with the utterance")
    say.add_argument(
        "--wait",
        action="store_true",
        help="block until the utterance reaches a terminal state; exit 0 only for Played",
    )
    say.add_argument("--timeout", type=float, help="seconds to wait with --wait")

    wait = sub.add_parser("wait", help="block until an utterance finishes")
    wait.add_argument("id")
    wait.add_argument("--timeout", type=float)

    listing = sub.add_parser("list", help="show a queue")
    listing.add_argument("queue", choices=["input", "playback"])

    history = sub.add_parser("history", help="show what has been said")
    history.add_argument("--limit", type=int, default=20)
    history.add_argument("--before", help="paginate: only items before this id")

    sub.add_parser(
        "purge-cache",
        help="remove cached audio not needed by current or queued speech",
    )

    for name in _TRANSPORT_OPS:
        sub.add_parser(name, help=f"send '{name}' to the daemon")

    rewind = sub.add_parser("rewind", help="restart the current utterance, or replay one")
    rewind.add_argument("--to", help="utterance id to bring to the head of the plan")

    cancel = sub.add_parser("cancel", help="cancel an utterance that is not playing")
    cancel.add_argument("id")

    clear = sub.add_parser("clear", help="drain a named queue")
    clear.add_argument("queue", choices=["input", "playback"])

    sub.add_parser(
        "next-chunk",
        help="give up the current chunk of a document and play the next one",
    )
    sub.add_parser(
        "prev-chunk",
        help="replay the previous chunk of the current document",
    )
    sub.add_parser(
        "resume-when-idle",
        help="release the playback hold once nothing is using the microphone",
    )
    sub.add_parser("voice-map", help="show which voice each speaking client holds")

    assign = sub.add_parser(
        "assign-voice",
        help="assign a voice to one client, outranking whatever it asks for",
    )
    assign.add_argument("source", help="the client's --source value")
    assign.add_argument(
        "voice",
        nargs="?",
        help="voice id to assign; omit with --release to forget the assignment",
    )
    assign.add_argument(
        "--release",
        action="store_true",
        help="forget the assignment, so the client claims a voice again",
    )

    _settings_parser(sub.add_parser("settings", help="read or change settings"))

    daemon = sub.add_parser("daemon", help="run the daemon in the foreground")
    daemon.add_argument("--home", type=Path, default=None)
    daemon.add_argument(
        "--engine",
        choices=["kokoro", "kokoro-mlx", "openai-audio", "chatterbox", "fake"],
        default=None,
    )
    daemon.add_argument("--workers", type=int, default=2)
    daemon.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="write bounded owner-only diagnostics to this file instead of stderr",
    )

    return parser


def _settings_parser(settings: argparse.ArgumentParser) -> None:
    """Describe the compatible flag and positional settings forms."""
    settings.add_argument("action", nargs="?", choices=["set"])
    settings.add_argument("key", nargs="?")
    settings.add_argument("value", nargs="?")
    settings.add_argument("--engine", help="change the backend for the next clip")
    settings.add_argument("--earcon", choices=["on", "off"], help="pre-speech chime")
    settings.add_argument("--ducking", choices=["on", "off"], help="lower other apps during speech")
    settings.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", dest="updates")


def _say_payload(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "op": "submit",
        "origin": "CLI",
        "text": args.text,
        "content_format": args.content_format,
    }
    if args.preempt:
        payload["preempt"] = True
    for key in ("voice", "engine", "speed", "sensitivity", "priority", "source"):
        value = getattr(args, key)
        if value is not None:
            payload[key] = value
    return payload


def _history_payload(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {"op": "history", "limit": args.limit}
    if args.before:
        payload["before"] = args.before
    return payload


def _assign_voice_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.release:
        if args.voice is not None:
            msg = "--release does not take a voice"
            raise SystemExit(msg)
        return {"op": "assign_voice", "source": args.source, "release": True}
    if args.voice is None:
        msg = "assign-voice needs a voice, or --release to forget the assignment"
        raise SystemExit(msg)
    return {"op": "assign_voice", "source": args.source, "voice": args.voice}


def _settings_payload(args: argparse.Namespace) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    pairs = list(args.updates)
    if args.action is not None:
        if args.key is None or args.value is None:
            msg = "settings set requires KEY VALUE"
            raise SystemExit(msg)
        pairs.append(f"{args.key}={args.value}")
    if args.engine is not None:
        pairs.append(f"engine={args.engine}")
    pairs.extend(
        f"{key}={getattr(args, key)}"
        for key in ("earcon", "ducking")
        if getattr(args, key) is not None
    )
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep:
            msg = f"--set expects KEY=VALUE, got {pair!r}"
            raise SystemExit(msg)
        key = {"earcon": "earcon_enabled", "ducking": "ducking_enabled"}.get(key, key)
        if key in {"earcon_enabled", "ducking_enabled"}:
            value = {"on": "true", "off": "false"}.get(value, value)
        if key in {"speed", "playback_rate"}:
            updates[key] = float(value)
        elif key in {
            "captions_enabled",
            "input_interrupt_enabled",
            "earcon_enabled",
            "ducking_enabled",
        }:
            if value not in {"true", "false"}:
                msg = f"{key} must be true or false"
                raise SystemExit(msg)
            updates[key] = value == "true"
        else:
            updates[key] = value
    return {"op": "settings", "set": updates} if updates else {"op": "settings"}


_PAYLOAD_BUILDERS: dict[str, Any] = {
    "say": _say_payload,
    "history": _history_payload,
    "settings": _settings_payload,
    "list": lambda args: {"op": "list", "queue": args.queue},
    "rewind": lambda args: {"op": "rewind", "to": args.to} if args.to else {"op": "rewind"},
    "cancel": lambda args: {"op": "cancel", "id": args.id},
    "clear": lambda args: {"op": "clear", "queue": args.queue},
    "purge-cache": lambda _args: {"op": "purge_cache"},
    "next-chunk": lambda _args: {"op": "next_segment"},
    "prev-chunk": lambda _args: {"op": "previous_segment"},
    "resume-when-idle": lambda _args: {"op": "resume_when_input_idle"},
    "voice-map": lambda _args: {"op": "voice_assignments"},
    "assign-voice": _assign_voice_payload,
}


def _payload_for(args: argparse.Namespace) -> dict[str, Any]:
    builder = _PAYLOAD_BUILDERS.get(args.command)
    if builder is None:
        return {"op": args.command}
    result: dict[str, Any] = builder(args)
    return result


def _run_client_command(args: argparse.Namespace) -> int:
    client = Client(args.socket or default_socket())
    try:
        if args.command == "wait":
            final = client.wait_for_terminal(args.id, timeout=args.timeout)
            _emit({"ok": True, "id": args.id, "final_state": final})
            return EXIT_OK if final == State.PLAYED.value else EXIT_NOT_PLAYED
        response = client.request(_payload_for(args))
        if args.command == "say" and args.wait:
            final = client.wait_for_terminal(response["id"], timeout=args.timeout)
            response["final_state"] = final
            _emit(response)
            return EXIT_OK if final == State.PLAYED.value else EXIT_NOT_PLAYED
        _emit(response)
    except DaemonError as exc:
        _emit({"ok": False, "error": {"type": exc.error_type, "message": str(exc)}})
        return EXIT_DAEMON_ERROR
    except DaemonUnreachableError as exc:
        _emit({"ok": False, "error": {"type": "unreachable", "message": str(exc)}})
        return EXIT_UNREACHABLE
    return EXIT_OK


def _run_daemon(args: argparse.Namespace) -> int:
    if args.log_file is None:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    else:
        from aitts.adapters.diagnostic_logging import (  # noqa: PLC0415 - daemon-only adapter
            configure_daemon_logging,
        )

        log_path = args.log_file.expanduser()
        if not log_path.is_absolute():
            log_path = Path.cwd() / log_path
        configure_daemon_logging(log_path)
    from aitts.adapters.process_lifecycle import (  # noqa: PLC0415 - daemon-only adapter
        ImmediateProcessTerminator,
    )
    from aitts.daemon import Daemon  # noqa: PLC0415 - heavy import only for the daemon
    from aitts.playback import SoundDeviceSink  # noqa: PLC0415

    home = args.home or default_home()
    from aitts.engines.selection import configured_engines  # noqa: PLC0415

    engine, engines = configured_engines(home, override=args.engine)
    terminator = ImmediateProcessTerminator()

    async def serve() -> None:
        daemon = Daemon(
            home=home,
            engine=engine,
            engines=engines,
            sink=SoundDeviceSink(),
            workers=args.workers,
            socket_path=args.socket,
        )
        await daemon.start()
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        logging.getLogger("aitts").info(
            "event=daemon_ready version=%s engine=%s",
            __version__,
            engine.name,
        )
        await stop.wait()
        await daemon.stop()
        terminator.terminate(EXIT_OK)

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(serve())
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    """Run the CLI; return the process exit code."""
    args = _build_parser().parse_args(argv)
    if args.command == "daemon":
        return _run_daemon(args)
    if args.command == "tui":
        try:
            from aitts.tui.app import SpeechTUI  # noqa: PLC0415 - optional terminal dependency
        except ModuleNotFoundError as exc:
            if exc.name not in {"textual", "rich"}:
                raise
            sys.stderr.write("Install the terminal UI with: uv tool install 'ai-tts[tui]'\n")
            return EXIT_DAEMON_ERROR
        SpeechTUI(args.socket or default_socket()).run()
        return EXIT_OK
    return _run_client_command(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
