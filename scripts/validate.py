#!/usr/bin/env python3
"""Validate and generate the Czech blocklists in ``lists/``.

The validator is intentionally dependency-free: it only uses the Python
standard library, so it runs on a stock Raspberry Pi OS as well as in CI.

One curated domain list per scope is the source of truth; the other formats
are generated from it:

* ``basic.txt`` / ``aggressive.txt`` -- one plain hostname per line
* ``basic.hosts`` / ``aggressive.hosts`` -- hosts format, ``0.0.0.0 hostname``
* ``basic.abp`` / ``aggressive.abp`` -- Adblock/ABP format, ``||hostname^``

Run ``python3 scripts/validate.py --write`` after editing a ``.txt`` file to
regenerate the derived lists. Without ``--write`` the validator only checks,
and fails when a derived file is out of date.

Checks performed for the canonical ``.txt`` files:

* the file exists, is valid UTF-8, uses LF line endings and ends with a newline
* every non-blank line is a plain lowercase hostname: no comments, no URL
  schemes, no paths, no wildcard syntax, no whitespace
* every hostname has its ``www`` counterpart and every ``www`` hostname has
  its bare counterpart
* no duplicate entries and no out-of-order entries
* no entries that block public suffixes, shared hosting, URL shorteners,
  ad/tracker infrastructure or protected mainstream/infrastructure domains
* ``aggressive.txt`` contains every entry of ``basic.txt``

Checks performed for the derived ``.hosts`` and ``.abp`` files:

* the file exists, is valid UTF-8, uses LF line endings and ends with a newline
* its contents are exactly what the matching ``.txt`` file generates

Usage::

    python3 scripts/validate.py
    python3 scripts/validate.py --write
    python3 scripts/validate.py --root /path/to/repository

Exit status is ``0`` when everything is fine and ``1`` when at least one
problem was found.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent

BASIC_TXT_FILE = "basic.txt"
AGGRESSIVE_TXT_FILE = "aggressive.txt"

#: Derived formats: file suffix and the formatter used for each hostname.
HOSTS_SUFFIX = "hosts"
ABP_SUFFIX = "abp"
HOSTS_IP = "0.0.0.0"

#: The registrable label (the label directly in front of the public suffix) must
#: be at least this long. Shorter labels can wipe out a whole country TLD or a
#: very large provider, so they are rejected outright.
MIN_REGISTRABLE_LABEL_LENGTH = 3

#: Characters allowed in a hostname label.
ALLOWED_LABEL_CHARACTERS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-")

#: Wildcard-ish characters that must never appear in a hostname. ``?`` and
#: ``*`` are rejected as DNS label wildcards, the rest as regex, ABP or shell
#: glob leftovers.
FORBIDDEN_HOSTNAME_CHARACTERS = frozenset("*?[]{}()^$|\\")

#: Second-level public suffixes. Blocking them would block every site below a
#: whole country or category.
PUBLIC_SUFFIXES = frozenset(
    {
        "ac.uk",
        "co.at",
        "co.hu",
        "co.il",
        "co.jp",
        "co.kr",
        "co.nz",
        "co.rs",
        "co.uk",
        "co.za",
        "com.ar",
        "com.au",
        "com.br",
        "com.cn",
        "com.hk",
        "com.mx",
        "com.pl",
        "com.sg",
        "com.tr",
        "com.tw",
        "com.ua",
        "gov.uk",
        "net.au",
        "or.at",
        "org.au",
        "org.uk",
    }
)

#: Shared hosting and user-generated-content platforms. Blocking one tenant
#: there is pointless (new subdomains appear constantly) and blocks unrelated
#: content, so entries below these suffixes are rejected.
SHARED_HOSTING_SUFFIXES = frozenset(
    {
        "akamaized.net",
        "amazonaws.com",
        "azureedge.net",
        "azurewebsites.net",
        "blogger.com",
        "blogspot.com",
        "cloudapp.azure.com",
        "cloudfront.net",
        "cloudflare.net",
        "fastly.net",
        "fastlylb.net",
        "firebaseapp.com",
        "github.io",
        "gitlab.io",
        "googleusercontent.com",
        "herokuapp.com",
        "herokudns.com",
        "medium.com",
        "netlify.app",
        "notion.site",
        "pages.dev",
        "sharepoint.com",
        "substack.com",
        "tumblr.com",
        "vercel.app",
        "web.app",
        "weebly.com",
        "wixsite.com",
        "wordpress.com",
        "wordpress.org",
        "workers.dev",
    }
)

#: URL shorteners and redirectors: blocking them breaks far more than it helps.
SHORTENER_DOMAINS = frozenset(
    {
        "bit.ly",
        "cutt.ly",
        "goo.gl",
        "is.gd",
        "ow.ly",
        "t.co",
        "t.ly",
        "tinyurl.com",
    }
)

#: Ad, tracker and analytics infrastructure. Dedicated lists already cover this
#: topic; this repository blocks the content websites themselves.
AD_TRACKING_SUFFIXES = frozenset(
    {
        "adform.net",
        "adnxs.com",
        "casalemedia.com",
        "criteo.com",
        "criteo.net",
        "doubleclick.net",
        "google-analytics.com",
        "googleadservices.com",
        "googlesyndication.com",
        "googletagmanager.com",
        "googletagservices.com",
        "openx.net",
        "outbrain.com",
        "pubmatic.com",
        "rubiconproject.com",
        "scorecardresearch.com",
        "smartadserver.com",
        "taboola.com",
    }
)

#: Domains that must never appear in any list. These are mainstream Czech
#: publishers, public-service media, utilities and generic infrastructure whose
#: content is usually useful even when it contains a tabloid or lifestyle
#: section. Dedicated subdomains (for example ``zena.aktualne.cz``) may still be
#: blocked, but the parent domain must stay reachable.
PROTECTED_DOMAINS: Tuple[str, ...] = (
    # Mainstream Czech publishers and news
    "aktualne.cz",
    "www.aktualne.cz",
    "muz.aktualne.cz",
    "sport.aktualne.cz",
    "ekonom.aktualne.cz",
    "bleskove.cz",
    "ct24.cz",
    "czechcrunch.cz",
    "denik.cz",
    "www.denik.cz",
    "denikn.cz",
    "www.denikn.cz",
    "e15.cz",
    "www.e15.cz",
    "echo24.cz",
    "www.echo24.cz",
    "forum24.cz",
    "www.forum24.cz",
    "forbes.cz",
    "www.forbes.cz",
    "hn.cz",
    "ihned.cz",
    "www.ihned.cz",
    "info.cz",
    "www.info.cz",
    "irozhlas.cz",
    "www.irozhlas.cz",
    "lidovky.cz",
    "www.lidovky.cz",
    "novinky.cz",
    "www.novinky.cz",
    "pravo.cz",
    "www.pravo.cz",
    "radio.cz",
    "www.radio.cz",
    "respekt.cz",
    "www.respekt.cz",
    "reflex.cz",
    "www.reflex.cz",
    "rozhlas.cz",
    "www.rozhlas.cz",
    "seznamzpravy.cz",
    "www.seznamzpravy.cz",
    "zive.cz",
    "www.zive.cz",
    # Czech TV stations and streaming
    "ceskatelevize.cz",
    "www.ceskatelevize.cz",
    "iprima.cz",
    "www.iprima.cz",
    "play.iprima.cz",
    "zoom.iprima.cz",
    "nova.cz",
    "www.nova.cz",
    "tn.nova.cz",
    "voyo.nova.cz",
    # Czech portals, search, maps, e-mail
    "seznam.cz",
    "www.seznam.cz",
    "email.seznam.cz",
    "mapy.seznam.cz",
    "mapy.cz",
    "www.mapy.cz",
    "sport.seznam.cz",
    "idnes.cz",
    "www.idnes.cz",
    "ona.idnes.cz",
    "muz.idnes.cz",
    "recepty.idnes.cz",
    "sport.idnes.cz",
    "technet.idnes.cz",
    # Sports
    "isport.cz",
    "www.isport.cz",
    "livesport.cz",
    "www.livesport.cz",
    "sport.cz",
    "www.sport.cz",
    # Tech and community
    "diit.cz",
    "root.cz",
    "www.root.cz",
    "wikimedia.org",
    "wikipedia.org",
    "www.wikipedia.org",
    # Availability and infrastructure
    "alza.cz",
    "www.alza.cz",
    "czc.cz",
    "datart.cz",
    "mall.cz",
    "amazon.com",
    "amazon.de",
    "apple.com",
    "github.com",
    "gitlab.com",
    "cloudflare.com",
    "google.com",
    "www.google.com",
    "googleapis.com",
    "gstatic.com",
    "googlevideo.com",
    "microsoft.com",
    "mozilla.org",
    "netflix.com",
    "python.org",
    "youtube.com",
    # Reserved example domains used by the tests and documentation
    "example.com",
    "www.example.com",
    "foo.bar.example.com",
    "example.net",
    "example.org",
)


class HostEntry:
    """One validated canonical list entry."""

    __slots__ = ("hostname", "line")

    def __init__(self, hostname: str, line: int) -> None:
        self.hostname = hostname
        self.line = line

    @property
    def labels(self) -> List[str]:
        return self.hostname.split(".")

    @property
    def parent(self) -> str:
        """The hostname with its first label removed."""
        return self.hostname.split(".", 1)[1]


def format_hosts_entry(hostname: str) -> str:
    """Return the hosts-file line for *hostname*."""
    return f"{HOSTS_IP} {hostname}"


def format_abp_entry(hostname: str) -> str:
    """Return the Adblock/ABP line for *hostname*."""
    return f"||{hostname}^"


#: Derived formats as ``(suffix, formatter)`` pairs.
DERIVED_FORMATS: Tuple[Tuple[str, Callable[[str], str]], ...] = (
    (HOSTS_SUFFIX, format_hosts_entry),
    (ABP_SUFFIX, format_abp_entry),
)


def parse_hostname_line(line: str) -> Tuple[Optional[str], Optional[str]]:
    """Parse a single canonical ``.txt`` line.

    Returns ``(hostname, None)`` when the line is a valid entry and
    ``(None, message)`` when it is not.
    """
    if line.strip() == "":
        return None, "blank entry"
    if any(character.isspace() for character in line):
        return None, "entry contains whitespace; use one plain hostname per line"
    if line.startswith("#") or line.startswith(";"):
        return None, (
            "comments are not supported in .txt files; "
            "use one plain hostname per line"
        )
    if "://" in line or line.startswith(("http:", "https:")):
        return None, (
            "entry is a URL; use one plain hostname such as 'example.cz' "
            "without a scheme"
        )
    if "/" in line:
        return None, (
            "entry contains a path; use one plain hostname such as 'example.cz'"
        )

    for character in sorted(FORBIDDEN_HOSTNAME_CHARACTERS):
        if character in line:
            return None, (
                f"wildcard or pattern character {character!r} is not allowed; "
                "use one plain hostname per line"
            )

    if line.endswith("."):
        return None, "entry must not end with a trailing dot"

    labels = line.split(".")
    if len(labels) < 2:
        return None, "hostname must have at least two labels (for example 'example.cz')"
    if len(line) > 253:
        return None, "hostname is longer than 253 characters"
    for label in labels:
        if not label:
            return None, "hostname contains an empty label (consecutive dots)"
        if len(label) > 63:
            return None, f"label {label!r} is longer than 63 characters"
        if label.startswith("-") or label.endswith("-"):
            return None, f"label {label!r} must not start or end with a hyphen"
        unexpected = sorted(set(label) - ALLOWED_LABEL_CHARACTERS)
        if unexpected:
            return None, (
                f"label {label!r} contains {unexpected[0]!r}; "
                "use lowercase ASCII hostnames only"
            )

    top_level_domain = labels[-1]
    if len(top_level_domain) < 2 or not top_level_domain.isalpha():
        return None, (
            f"top-level label {top_level_domain!r} must be alphabetic "
            "and at least two characters long"
        )

    registrable_label = labels[-2]
    if len(registrable_label) < MIN_REGISTRABLE_LABEL_LENGTH:
        return None, (
            f"registrable label {registrable_label!r} is too short; "
            "blocking it could affect a whole TLD or a very large provider"
        )

    return line, None


def check_hostname_safety(hostname: str, where: str, errors: List[str]) -> None:
    """Reject hostnames that would block protected or shared domains."""
    if hostname in PROTECTED_DOMAINS:
        errors.append(
            f"{where}: {hostname!r} is a protected mainstream/infrastructure "
            "domain; block a dedicated subdomain instead of the parent domain"
        )
    if hostname in PUBLIC_SUFFIXES or any(
        hostname.endswith("." + suffix) for suffix in PUBLIC_SUFFIXES
    ):
        errors.append(
            f"{where}: {hostname!r} is a public suffix; blocking it would block "
            "an entire country or category"
        )
    for suffix in sorted(SHARED_HOSTING_SUFFIXES):
        if hostname == suffix or hostname.endswith("." + suffix):
            errors.append(
                f"{where}: {hostname!r} is hosted on shared infrastructure "
                f"({suffix}); blocking shared hosting breaks unrelated content"
            )
            break
    if hostname in SHORTENER_DOMAINS:
        errors.append(
            f"{where}: {hostname!r} is a URL shortener; blocking it would break "
            "unrelated links"
        )
    for suffix in sorted(AD_TRACKING_SUFFIXES):
        if hostname == suffix or hostname.endswith("." + suffix):
            errors.append(
                f"{where}: {hostname!r} is ad/tracker infrastructure ({suffix}); "
                "dedicated ad/tracker lists already cover this"
            )
            break


def check_www_counterparts(
    label: str, entries: Sequence[HostEntry], errors: List[str]
) -> None:
    """Every site is listed both with and without its ``www`` prefix."""
    hostnames = {entry.hostname for entry in entries}
    for entry in entries:
        hostname = entry.hostname
        if hostname.startswith("www."):
            counterpart = hostname[len("www.") :]
        else:
            counterpart = "www." + hostname
        if counterpart not in hostnames:
            errors.append(
                f"{label}:{entry.line}: missing {counterpart!r} for {hostname!r}; "
                "list every site with and without its 'www.' prefix"
            )


def read_list_text(path: Path, label: str, errors: List[str]) -> Optional[str]:
    """Read a list file and run the encoding/format checks on it."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        errors.append(
            f"{label}: list file is missing (looked at {path}); "
            "regenerate it with 'python3 scripts/validate.py --write'"
        )
        return None
    except OSError as exc:
        errors.append(f"{label}: cannot read list file: {exc}")
        return None

    if raw.startswith(b"\xef\xbb\xbf"):
        errors.append(f"{label}: file starts with a UTF-8 BOM; save it as plain UTF-8")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        errors.append(f"{label}: file is not valid UTF-8: {exc}")
        return None

    if "\r" in text:
        errors.append(f"{label}: file contains CR characters; use LF line endings only")
        text = text.replace("\r\n", "\n").replace("\r", "\n")

    if text and not text.endswith("\n"):
        errors.append(f"{label}: file must end with a newline")

    return text


def split_list_lines(text: str) -> List[str]:
    """Split file text into lines, dropping the trailing final newline."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def parse_host_list(
    path: Path, label: str, errors: List[str]
) -> Optional[List[HostEntry]]:
    """Parse, validate and return all entries of a canonical ``.txt`` file."""
    text = read_list_text(path, label, errors)
    if text is None:
        return None

    entries: List[HostEntry] = []
    seen: Dict[str, int] = {}
    previous_hostname: Optional[str] = None

    for number, line in enumerate(split_list_lines(text), start=1):
        where = f"{label}:{number}"

        if line == "":
            # Blank formatting lines are tolerated, but this repository keeps
            # the lists free of them so that Git diffs stay minimal.
            continue
        if line.strip() == "":
            errors.append(f"{where}: line contains only whitespace")
            continue

        hostname, message = parse_hostname_line(line)
        if message is not None:
            errors.append(f"{where}: {message}")
            continue
        assert hostname is not None

        if hostname in seen:
            errors.append(
                f"{where}: duplicate entry for {hostname!r} "
                f"(already on line {seen[hostname]})"
            )
        else:
            seen[hostname] = number

        if previous_hostname is not None and hostname < previous_hostname:
            errors.append(
                f"{where}: {hostname!r} is out of order; sort the list "
                f"alphabetically by hostname ({previous_hostname!r} comes before it)"
            )
        previous_hostname = hostname

        entries.append(HostEntry(hostname, number))

    for entry in entries:
        check_hostname_safety(entry.hostname, f"{label}:{entry.line}", errors)

    return entries


def check_superset(
    basic: Sequence[HostEntry],
    aggressive: Sequence[HostEntry],
    basic_label: str,
    aggressive_label: str,
    errors: List[str],
) -> None:
    """``aggressive.txt`` must contain every entry of ``basic.txt``."""
    aggressive_hostnames = {entry.hostname for entry in aggressive}
    for entry in basic:
        if entry.hostname not in aggressive_hostnames:
            errors.append(
                f"{aggressive_label}: missing {entry.hostname!r} from "
                f"{basic_label}; the aggressive list must be a complete "
                "superset of the basic list"
            )


def render_list(hostnames: Sequence[str], formatter: Callable[[str], str]) -> str:
    """Render derived file contents for the given hostnames."""
    return "".join(formatter(hostname) + "\n" for hostname in hostnames)


def derived_path(lists_directory: Path, txt_label: str, suffix: str) -> Path:
    """Return the path of the derived file for a canonical list."""
    stem = txt_label[: -len(".txt")]
    return lists_directory / f"{stem}.{suffix}"


def check_generated_list(
    path: Path,
    hostnames: Sequence[str],
    formatter: Callable[[str], str],
    errors: List[str],
) -> None:
    """A derived file must match exactly what the canonical list generates."""
    label = path.name
    text = read_list_text(path, label, errors)
    if text is None:
        return

    expected = render_list(hostnames, formatter)
    if text == expected:
        return

    message = (
        f"{label}: generated file is out of date; regenerate it with "
        "'python3 scripts/validate.py --write'"
    )
    expected_lines = split_list_lines(expected)
    actual_lines = split_list_lines(text)
    for number, (expected_line, actual_line) in enumerate(
        zip(expected_lines, actual_lines), start=1
    ):
        if expected_line != actual_line:
            message += (
                f" (first difference on line {number}: "
                f"expected {expected_line!r}, found {actual_line!r})"
            )
            break
    else:
        message += (
            f" (expected {len(expected_lines)} lines, "
            f"found {len(actual_lines)})"
        )
    errors.append(message)


def write_generated_list(
    path: Path,
    hostnames: Sequence[str],
    formatter: Callable[[str], str],
    errors: List[str],
) -> bool:
    """Write a derived file when its contents changed; returns True then."""
    content = render_list(hostnames, formatter)
    try:
        current = path.read_text(encoding="utf-8")
    except OSError:
        current = None
    if current == content:
        return False
    try:
        path.write_bytes(content.encode("utf-8"))
    except OSError as exc:
        errors.append(f"{path.name}: cannot write generated list: {exc}")
        return False
    return True


def print_errors(errors: Sequence[str]) -> None:
    print(f"FAILED: {len(errors)} problem(s) found", file=sys.stderr)
    for message in errors:
        print(f"  error: {message}", file=sys.stderr)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate and generate the Czech blocklists."
    )
    parser.add_argument(
        "--root",
        default=str(REPO_ROOT),
        help="repository root that contains the lists/ directory (default: %(default)s)",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="regenerate the derived .hosts and .abp lists from the .txt lists",
    )
    arguments = parser.parse_args(argv)

    root = Path(arguments.root).resolve()
    lists_directory = root / "lists"
    errors: List[str] = []

    basic_txt = parse_host_list(
        lists_directory / BASIC_TXT_FILE, BASIC_TXT_FILE, errors
    )
    aggressive_txt = parse_host_list(
        lists_directory / AGGRESSIVE_TXT_FILE, AGGRESSIVE_TXT_FILE, errors
    )

    if basic_txt is not None:
        check_www_counterparts(BASIC_TXT_FILE, basic_txt, errors)
    if aggressive_txt is not None:
        check_www_counterparts(AGGRESSIVE_TXT_FILE, aggressive_txt, errors)
    if basic_txt is not None and aggressive_txt is not None:
        check_superset(
            basic_txt,
            aggressive_txt,
            BASIC_TXT_FILE,
            AGGRESSIVE_TXT_FILE,
            errors,
        )

    canonical: List[Tuple[str, List[HostEntry]]] = []
    if basic_txt is not None:
        canonical.append((BASIC_TXT_FILE, basic_txt))
    if aggressive_txt is not None:
        canonical.append((AGGRESSIVE_TXT_FILE, aggressive_txt))

    if arguments.write:
        if errors:
            print_errors(errors)
            print("Nothing was written.", file=sys.stderr)
            return 1
        changed: List[str] = []
        for txt_label, entries in canonical:
            hostnames = [entry.hostname for entry in entries]
            for suffix, formatter in DERIVED_FORMATS:
                path = derived_path(lists_directory, txt_label, suffix)
                if write_generated_list(path, hostnames, formatter, errors):
                    changed.append(path.name)
        if errors:
            print_errors(errors)
            return 1
        if changed:
            print(f"Regenerated: {', '.join(changed)}")
        else:
            print("All generated lists are already up to date.")
        return 0

    for txt_label, entries in canonical:
        hostnames = [entry.hostname for entry in entries]
        for suffix, formatter in DERIVED_FORMATS:
            path = derived_path(lists_directory, txt_label, suffix)
            check_generated_list(path, hostnames, formatter, errors)

    if errors:
        print_errors(errors)
        return 1

    assert basic_txt is not None and aggressive_txt is not None
    print("Validation passed.")
    print(
        f"  {BASIC_TXT_FILE}: {len(basic_txt)} hostnames, "
        "unique, sorted, valid format"
    )
    print(
        f"  {AGGRESSIVE_TXT_FILE}: {len(aggressive_txt)} hostnames, "
        "unique, sorted, valid format"
    )
    print(f"  {AGGRESSIVE_TXT_FILE} is a superset of {BASIC_TXT_FILE}")
    for txt_label, _ in canonical:
        derived = ", ".join(
            derived_path(lists_directory, txt_label, suffix).name
            for suffix, _ in DERIVED_FORMATS
        )
        print(f"  {derived}: generated from {txt_label}")
    print(
        "  no public-suffix, shared-hosting, shortener or ad/tracker entries; "
        f"no matches against {len(PROTECTED_DOMAINS)} protected domains"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
