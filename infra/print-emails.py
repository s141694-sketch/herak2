"""The emails Harak would have sent, decoded, from a worker's log on standard input (EMAIL_URL=consolemail://).

Django's console backend writes each message as raw MIME, its Arabic body in base64; this prints who it was for, its
subject and its text, links included. Standard library only: it runs in the backend container (try-local.sh and
codespace.sh pipe the worker's log into it)."""

import email
import sys
from email import policy

SEPARATOR = "-" * 79


def messages(lines):
    block = None
    for line in lines:
        line = line.rstrip("\n")
        if block is None:
            if line.startswith("Content-Type: "):
                block = [line]
            continue
        if line == SEPARATOR:
            yield "\n".join(block)
            block = None
        else:
            block.append(line)


def main() -> None:
    count = 0
    for raw in messages(sys.stdin):
        message = email.message_from_string(raw, policy=policy.default)
        count += 1
        print(f"=== {message['Date']}  to: {message['To']}")
        print(f"subject: {message['Subject']}")
        print(message.get_content().strip())
        print()
    if not count:
        print("no emails yet")


main()
