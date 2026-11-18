# AI-TTS client crate

`aitts-client` talks to the AI-TTS daemon over its Unix socket with the
`aitts-protocol` wire types. It has two parts. It parses no command line.

## One request

`Client::new(socket, limit).request(&request)` opens a connection, sends one
request line, reads one reply line, and decodes it as the reply to that
operation. Each socket read and write waits at most `limit`. A daemon error
reply (`ok: false`) is returned as `Reply::Error`; it is not a `ClientError`.

## Subscription

`Client::subscribe(policy)` sends `{"op":"subscribe"}` and returns only after
the daemon acknowledges it. `Subscription::next_delivery` returns the next
event. When the connection closes or fails, the next call connects and
subscribes again, up to `policy.attempts` times with `policy.delay` between
attempts, and returns `Delivery::Resubscribed`. Events sent while the client was
disconnected are lost, so a caller reads current state again after that item.
A quiet daemon gives `ClientError::TimedOut` and keeps the connection.
`Client::subscribe_to_progress` also asks for `playback_progress` events, as
the dashboard does.

## Errors

| `ClientError` | Cause | `exit_status()` |
|---|---|---|
| `Unreachable` | The socket is absent, or nothing accepts on it. | 2 |
| `TimedOut` | No complete line within the time limit. | 2 |
| `Closed` | The daemon closed the connection before a complete line. | 2 |
| `Io` | A read or write on the connected socket failed. | 2 |
| `Wire` | The line is larger than `MAX_RESPONSE_BYTES` or is not valid for the operation. | 1 |
| `Refused` | The daemon answered `subscribe` with an error reply. | 1 |

Exit status 2 is the Python CLI's `EXIT_UNREACHABLE`. A reply that is not valid
JSON is never a success.

## Tests

`cargo test -p aitts-client`. The tests and their oracles are in
[the verification record](../../docs/testing-evidence/2026-11-16-socket-client.md).
