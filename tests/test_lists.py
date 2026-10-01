#!/usr/bin/env python3
"""Unit tests for the Czech blocklists."""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import validate as validator  # noqa: E402  (imported after the sys.path tweak)

BASIC_TXT_PATH = ROOT / "lists" / "basic.txt"
AGGRESSIVE_TXT_PATH = ROOT / "lists" / "aggressive.txt"
BASIC_HOSTS_PATH = ROOT / "lists" / "basic.hosts"
AGGRESSIVE_HOSTS_PATH = ROOT / "lists" / "aggressive.hosts"
BASIC_ABP_PATH = ROOT / "lists" / "basic.abp"
AGGRESSIVE_ABP_PATH = ROOT / "lists" / "aggressive.abp"

TXT_PATHS = (BASIC_TXT_PATH, AGGRESSIVE_TXT_PATH)
GENERATED_PATHS = (
    BASIC_HOSTS_PATH,
    AGGRESSIVE_HOSTS_PATH,
    BASIC_ABP_PATH,
    AGGRESSIVE_ABP_PATH,
)

# The lists this repository is expected to ship. Keeping the expectations
# hard-coded makes accidental removals a test failure instead of a silent
# change, and doubles as a check for typos.
EXPECTED_BASIC = [
    "ahaonline.cz",
    "aplausin.cz",
    "blesk.cz",
    "expres.cz",
    "extra.cz",
    "nasehvezdy.cz",
    "stars24.cz",
    "super.cz",
    "vipshow.cz",
    "zena.aktualne.cz",
]

EXPECTED_AGGRESSIVE = EXPECTED_BASIC + [
    "dama.cz",
    "electropiknik.cz",
    "elle.cz",
    "extralife.cz",
    "extrasimo.cz",
    "fajntip.cz",
    "femina.cz",
    "iglanc.cz",
    "jenproholky.cz",
    "jenprozeny.cz",
    "jenzeny.cz",
    "kafe.cz",
    "kondice.cz",
    "lifee.cz",
    "lp-life.cz",
    "marianne.cz",
    "mezizenami.cz",
    "mymuzi.cz",
    "onlyu.cz",
    "predminutou.cz",
    "prozeny.cz",
    "tojesenzace.cz",
    "viposobnosti.cz",
    "vlasta.cz",
    "zadnyspeky.cz",
    "zena-in.cz",
    "zeny.cz",
]

# Parent domains that must stay reachable: only a dedicated subdomain may be
# blocked (for example zena.aktualne.cz).
MAINSTREAM_PARENTS = (
    "aktualne.cz",
    "idnes.cz",
    "iprima.cz",
    "nova.cz",
    "seznam.cz",
)

# Domains that must never appear in any list, in any format.
UNRELATED_DOMAINS = (
    "aktualne.cz",
    "www.aktualne.cz",
    "idnes.cz",
    "seznam.cz",
)

# A minimal, fully consistent set of all six list files. Individual tests
# override exactly one file to provoke a specific validation error.
MINIMAL_TXT = "super.cz\nwww.super.cz\n"
MINIMAL_HOSTS = "0.0.0.0 super.cz\n0.0.0.0 www.super.cz\n"
MINIMAL_ABP = "||super.cz^\n||www.super.cz^\n"
MINIMAL_FILES = {
    "basic.txt": MINIMAL_TXT,
    "aggressive.txt": MINIMAL_TXT,
    "basic.hosts": MINIMAL_HOSTS,
    "aggressive.hosts": MINIMAL_HOSTS,
    "basic.abp": MINIMAL_ABP,
    "aggressive.abp": MINIMAL_ABP,
}

# Two sites in consistent canonical/derived form.
TWO_SITE_TXT = "ahaonline.cz\nsuper.cz\nwww.ahaonline.cz\nwww.super.cz\n"
TWO_SITE_HOSTS = (
    "0.0.0.0 ahaonline.cz\n"
    "0.0.0.0 super.cz\n"
    "0.0.0.0 www.ahaonline.cz\n"
    "0.0.0.0 www.super.cz\n"
)
TWO_SITE_ABP = "||ahaonline.cz^\n||super.cz^\n||www.ahaonline.cz^\n||www.super.cz^\n"


def expected_hostnames(sites):
    """Return the canonical hostnames (site plus ``www``) of the given sites."""
    hostnames = set()
    for site in sites:
        hostnames.add(site)
        hostnames.add("www." + site)
    return sorted(hostnames)


def read_lines(path):
    """Return the raw lines of a list file, preserving everything as-is."""
    return path.read_bytes().decode("utf-8").split("\n")


def read_hostnames(test_case, path):
    """Parse a canonical list file and fail the test on the first invalid line."""
    hostnames = []
    for number, line in enumerate(read_lines(path), start=1):
        if not line:
            continue
        hostname, error = validator.parse_hostname_line(line)
        test_case.assertIsNone(error, f"{path.name}:{number}: {error}")
        hostnames.append(hostname)
    return hostnames


def unwrap_hosts_line(test_case, line, where):
    prefix = validator.HOSTS_IP + " "
    test_case.assertTrue(
        line.startswith(prefix), f"{where}: {line!r} must start with {prefix!r}"
    )
    hostname, error = validator.parse_hostname_line(line[len(prefix) :])
    test_case.assertIsNone(error, f"{where}: {error}")
    return hostname


def unwrap_abp_line(test_case, line, where):
    test_case.assertTrue(
        line.startswith("||") and line.endswith("^"),
        f"{where}: {line!r} must look like '||example.cz^'",
    )
    hostname, error = validator.parse_hostname_line(line[2:-1])
    test_case.assertIsNone(error, f"{where}: {error}")
    return hostname


def read_generated(test_case, path):
    """Parse a generated list file and fail the test on the first invalid line."""
    unwrap = unwrap_hosts_line if path.suffix == ".hosts" else unwrap_abp_line
    hostnames = []
    for number, line in enumerate(read_lines(path), start=1):
        if not line:
            continue
        hostnames.append(unwrap(test_case, line, f"{path.name}:{number}"))
    return hostnames


def file_hostnames(test_case, path):
    """Return the hostnames of a list file, canonical or generated."""
    if path.suffix == ".txt":
        return read_hostnames(test_case, path)
    return read_generated(test_case, path)


def write_lists(directory, **overrides):
    """Write a minimal valid repository, overriding the requested files."""
    lists = Path(directory) / "lists"
    lists.mkdir()
    contents = dict(MINIMAL_FILES)
    contents.update(overrides)
    for name, text in contents.items():
        (lists / name).write_text(text, encoding="utf-8")


def run_validator(directory, *extra_arguments):
    """Run the validator and return (exit code, stderr, stdout)."""
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exit_code = validator.main(
            ["--root", str(directory), *extra_arguments]
        )
    return exit_code, stderr.getvalue(), stdout.getvalue()


class TestCanonicalTxtFiles(unittest.TestCase):
    """Formatting, ordering and encoding of the canonical domain lists."""

    def test_files_exist_and_are_not_empty(self):
        for path in TXT_PATHS:
            with self.subTest(path=path.name):
                self.assertTrue(path.is_file(), f"{path} is missing")
                self.assertTrue(path.stat().st_size > 0)

    def test_files_are_valid_utf8_without_bom_and_use_lf(self):
        for path in TXT_PATHS:
            with self.subTest(path=path.name):
                raw = path.read_bytes()
                self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), "unexpected BOM")
                raw.decode("utf-8")  # raises on invalid UTF-8
                self.assertNotIn(b"\r", raw, "use LF line endings only")

    def test_files_end_with_a_newline(self):
        for path in TXT_PATHS:
            with self.subTest(path=path.name):
                self.assertTrue(path.read_bytes().endswith(b"\n"))

    def test_lines_are_plain_hostnames_without_comments(self):
        for path in TXT_PATHS:
            with self.subTest(path=path.name):
                for number, line in enumerate(read_lines(path), start=1):
                    if not line:
                        continue
                    self.assertEqual(line, line.strip(), f"{path.name}:{number}")
                    self.assertFalse(
                        line.startswith("#") or line.startswith(";"),
                        f"{path.name}:{number}: comments are not supported",
                    )

    def test_entries_are_valid_hostnames(self):
        for path in TXT_PATHS:
            for number, line in enumerate(read_lines(path), start=1):
                if not line:
                    continue
                with self.subTest(path=path.name, line=number):
                    hostname, error = validator.parse_hostname_line(line)
                    self.assertIsNone(error, f"{path.name}:{number}: {error}")
                    self.assertEqual(hostname, line)

    def test_entries_have_no_schemes_paths_or_wildcards(self):
        for path in TXT_PATHS:
            for number, line in enumerate(read_lines(path), start=1):
                if not line:
                    continue
                with self.subTest(path=path.name, line=number):
                    self.assertNotIn("://", line)
                    self.assertNotIn("/", line)
                    for character in "*?[]{}()^$|\\":
                        self.assertNotIn(character, line)

    def test_entries_are_unique_and_sorted(self):
        for path in TXT_PATHS:
            with self.subTest(path=path.name):
                hostnames = read_hostnames(self, path)
                self.assertEqual(
                    len(hostnames),
                    len(set(hostnames)),
                    f"{path.name} contains duplicates",
                )
                self.assertEqual(
                    hostnames, sorted(hostnames), f"{path.name} is not sorted"
                )

    def test_every_site_has_its_www_hostname(self):
        for path in TXT_PATHS:
            hostnames = set(read_hostnames(self, path))
            for hostname in sorted(hostnames):
                counterpart = (
                    hostname[len("www.") :]
                    if hostname.startswith("www.")
                    else "www." + hostname
                )
                with self.subTest(path=path.name, hostname=hostname):
                    self.assertIn(counterpart, hostnames)

    def test_no_entry_is_a_protected_domain(self):
        for path in TXT_PATHS:
            for hostname in read_hostnames(self, path):
                with self.subTest(path=path.name, hostname=hostname):
                    self.assertNotIn(hostname, validator.PROTECTED_DOMAINS)


class TestGeneratedFiles(unittest.TestCase):
    """The hosts and ABP files are generated from the canonical lists."""

    def test_files_exist_and_are_not_empty(self):
        for path in GENERATED_PATHS:
            with self.subTest(path=path.name):
                self.assertTrue(path.is_file(), f"{path} is missing")
                self.assertTrue(path.stat().st_size > 0)

    def test_files_are_valid_utf8_without_bom_and_use_lf(self):
        for path in GENERATED_PATHS:
            with self.subTest(path=path.name):
                raw = path.read_bytes()
                self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), "unexpected BOM")
                raw.decode("utf-8")  # raises on invalid UTF-8
                self.assertNotIn(b"\r", raw, "use LF line endings only")

    def test_files_end_with_a_newline(self):
        for path in GENERATED_PATHS:
            with self.subTest(path=path.name):
                self.assertTrue(path.read_bytes().endswith(b"\n"))

    def test_hosts_files_match_the_txt_lists(self):
        self.assertEqual(
            read_generated(self, BASIC_HOSTS_PATH), read_hostnames(self, BASIC_TXT_PATH)
        )
        self.assertEqual(
            read_generated(self, AGGRESSIVE_HOSTS_PATH),
            read_hostnames(self, AGGRESSIVE_TXT_PATH),
        )

    def test_abp_files_match_the_txt_lists(self):
        self.assertEqual(
            read_generated(self, BASIC_ABP_PATH), read_hostnames(self, BASIC_TXT_PATH)
        )
        self.assertEqual(
            read_generated(self, AGGRESSIVE_ABP_PATH),
            read_hostnames(self, AGGRESSIVE_TXT_PATH),
        )

    def test_entries_are_unique_and_sorted(self):
        for path in GENERATED_PATHS:
            hostnames = read_generated(self, path)
            with self.subTest(path=path.name):
                self.assertEqual(
                    len(hostnames),
                    len(set(hostnames)),
                    f"{path.name} contains duplicates",
                )
                self.assertEqual(
                    hostnames, sorted(hostnames), f"{path.name} is not sorted"
                )

    def test_files_are_exactly_rendered_from_the_txt_lists(self):
        pairs = (
            (BASIC_TXT_PATH, BASIC_HOSTS_PATH),
            (AGGRESSIVE_TXT_PATH, AGGRESSIVE_HOSTS_PATH),
            (BASIC_TXT_PATH, BASIC_ABP_PATH),
            (AGGRESSIVE_TXT_PATH, AGGRESSIVE_ABP_PATH),
        )
        for txt_path, generated in pairs:
            formatter = (
                validator.format_hosts_entry
                if generated.suffix == ".hosts"
                else validator.format_abp_entry
            )
            with self.subTest(generated=generated.name):
                self.assertEqual(
                    generated.read_text(encoding="utf-8"),
                    validator.render_list(read_hostnames(self, txt_path), formatter),
                )


class TestBasicList(unittest.TestCase):
    def test_txt_hostnames_match_the_expected_set(self):
        self.assertEqual(
            read_hostnames(self, BASIC_TXT_PATH),
            expected_hostnames(EXPECTED_BASIC),
        )

    def test_generated_hostnames_match_the_expected_set(self):
        expected = expected_hostnames(EXPECTED_BASIC)
        self.assertEqual(read_generated(self, BASIC_HOSTS_PATH), expected)
        self.assertEqual(read_generated(self, BASIC_ABP_PATH), expected)

    def test_expected_hostnames_are_present(self):
        hostnames = set(read_hostnames(self, BASIC_TXT_PATH))
        for hostname in ("super.cz", "www.super.cz", "zena.aktualne.cz"):
            with self.subTest(hostname=hostname):
                self.assertIn(hostname, hostnames)


class TestAggressiveList(unittest.TestCase):
    def test_txt_hostnames_match_the_expected_set(self):
        self.assertEqual(
            read_hostnames(self, AGGRESSIVE_TXT_PATH),
            expected_hostnames(EXPECTED_AGGRESSIVE),
        )

    def test_generated_hostnames_match_the_expected_set(self):
        expected = expected_hostnames(EXPECTED_AGGRESSIVE)
        self.assertEqual(read_generated(self, AGGRESSIVE_HOSTS_PATH), expected)
        self.assertEqual(read_generated(self, AGGRESSIVE_ABP_PATH), expected)

    def test_txt_is_a_complete_superset_of_basic(self):
        basic = set(read_hostnames(self, BASIC_TXT_PATH))
        aggressive = set(read_hostnames(self, AGGRESSIVE_TXT_PATH))
        self.assertTrue(
            basic.issubset(aggressive),
            f"missing from aggressive.txt: {sorted(basic - aggressive)}",
        )

    def test_generated_formats_are_supersets_of_basic(self):
        for basic_path, aggressive_path in (
            (BASIC_HOSTS_PATH, AGGRESSIVE_HOSTS_PATH),
            (BASIC_ABP_PATH, AGGRESSIVE_ABP_PATH),
        ):
            basic = set(read_generated(self, basic_path))
            aggressive = set(read_generated(self, aggressive_path))
            with self.subTest(format=basic_path.suffix):
                self.assertTrue(
                    basic.issubset(aggressive),
                    "missing from "
                    f"{aggressive_path.name}: {sorted(basic - aggressive)}",
                )


class TestDedicatedSubdomainHandling(unittest.TestCase):
    """zena.aktualne.cz is blocked without blocking aktualne.cz."""

    def test_subdomain_and_its_www_are_listed_in_every_format(self):
        for path in TXT_PATHS + GENERATED_PATHS:
            hostnames = file_hostnames(self, path)
            with self.subTest(path=path.name):
                self.assertIn("zena.aktualne.cz", hostnames)
                self.assertIn("www.zena.aktualne.cz", hostnames)

    def test_parent_domain_is_listed_nowhere(self):
        for path in TXT_PATHS + GENERATED_PATHS:
            hostnames = file_hostnames(self, path)
            with self.subTest(path=path.name):
                self.assertNotIn("aktualne.cz", hostnames)
                self.assertNotIn("www.aktualne.cz", hostnames)


class TestMainstreamParentsStayReachable(unittest.TestCase):
    def test_parent_domains_are_not_listed(self):
        listed = set()
        for path in TXT_PATHS + GENERATED_PATHS:
            listed |= set(file_hostnames(self, path))
        for parent in MAINSTREAM_PARENTS:
            with self.subTest(parent=parent):
                self.assertNotIn(parent, listed)
                self.assertNotIn("www." + parent, listed)

    def test_unrelated_domains_are_absent_from_every_list(self):
        listed = set()
        for path in TXT_PATHS + GENERATED_PATHS:
            listed |= set(file_hostnames(self, path))
        for domain in UNRELATED_DOMAINS:
            with self.subTest(domain=domain):
                self.assertNotIn(domain, listed)


class TestValidatorScript(unittest.TestCase):
    def test_accepts_this_repository(self):
        exit_code, stderr, _ = run_validator(ROOT)
        self.assertEqual(exit_code, 0, stderr)

    def test_accepts_a_minimal_valid_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            write_lists(directory)
            exit_code, stderr, _ = run_validator(directory)
            self.assertEqual(exit_code, 0, stderr)

    def test_rejects_an_out_of_order_txt_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            write_lists(
                directory,
                **{"basic.txt": "super.cz\nahaonline.cz\nwww.super.cz\n"},
            )
            exit_code, stderr, _ = run_validator(directory)
            self.assertEqual(exit_code, 1)
            self.assertIn("out of order", stderr)

    def test_rejects_a_url_in_a_canonical_list(self):
        with tempfile.TemporaryDirectory() as directory:
            write_lists(
                directory,
                **{"basic.txt": "https://super.cz\nwww.super.cz\n"},
            )
            exit_code, stderr, _ = run_validator(directory)
            self.assertEqual(exit_code, 1)
            self.assertIn("URL", stderr)

    def test_rejects_a_path_in_a_canonical_list(self):
        with tempfile.TemporaryDirectory() as directory:
            write_lists(
                directory,
                **{"basic.txt": "super.cz/foo/bar\nwww.super.cz\n"},
            )
            exit_code, stderr, _ = run_validator(directory)
            self.assertEqual(exit_code, 1)
            self.assertIn("path", stderr)

    def test_rejects_a_wildcard_in_a_canonical_list(self):
        with tempfile.TemporaryDirectory() as directory:
            write_lists(
                directory,
                **{"basic.txt": "*.super.cz\nwww.super.cz\n"},
            )
            exit_code, stderr, _ = run_validator(directory)
            self.assertEqual(exit_code, 1)
            self.assertIn("wildcard", stderr)

    def test_rejects_a_protected_parent_domain(self):
        with tempfile.TemporaryDirectory() as directory:
            write_lists(
                directory,
                **{
                    "basic.txt": "aktualne.cz\nwww.aktualne.cz\n",
                    "basic.hosts": (
                        "0.0.0.0 aktualne.cz\n0.0.0.0 www.aktualne.cz\n"
                    ),
                    "basic.abp": "||aktualne.cz^\n||www.aktualne.cz^\n",
                },
            )
            exit_code, stderr, _ = run_validator(directory)
            self.assertEqual(exit_code, 1)
            self.assertIn("protected", stderr)

    def test_rejects_a_missing_www_counterpart(self):
        with tempfile.TemporaryDirectory() as directory:
            write_lists(
                directory,
                **{
                    "basic.txt": "super.cz\n",
                    "basic.hosts": "0.0.0.0 super.cz\n",
                    "basic.abp": "||super.cz^\n",
                },
            )
            exit_code, stderr, _ = run_validator(directory)
            self.assertEqual(exit_code, 1)
            self.assertIn("missing 'www.super.cz'", stderr)

    def test_rejects_a_missing_basic_entry_in_aggressive(self):
        with tempfile.TemporaryDirectory() as directory:
            write_lists(
                directory,
                **{
                    "basic.txt": TWO_SITE_TXT,
                    "basic.hosts": TWO_SITE_HOSTS,
                    "basic.abp": TWO_SITE_ABP,
                },
            )
            exit_code, stderr, _ = run_validator(directory)
            self.assertEqual(exit_code, 1)
            self.assertIn("superset", stderr)

    def test_rejects_a_stale_generated_file(self):
        with tempfile.TemporaryDirectory() as directory:
            write_lists(
                directory,
                **{"aggressive.hosts": "0.0.0.0 super.cz\n"},
            )
            exit_code, stderr, _ = run_validator(directory)
            self.assertEqual(exit_code, 1)
            self.assertIn("out of date", stderr)

    def test_rejects_a_missing_generated_file(self):
        with tempfile.TemporaryDirectory() as directory:
            write_lists(directory)
            (Path(directory) / "lists" / "basic.abp").unlink()
            exit_code, stderr, _ = run_validator(directory)
            self.assertEqual(exit_code, 1)
            self.assertIn("missing", stderr)

    def test_write_regenerates_stale_lists(self):
        updated_txt = "dobre.cz\nsuper.cz\nwww.dobre.cz\nwww.super.cz\n"
        with tempfile.TemporaryDirectory() as directory:
            write_lists(directory)
            for name in ("basic.txt", "aggressive.txt"):
                (Path(directory) / "lists" / name).write_text(
                    updated_txt, encoding="utf-8"
                )
            exit_code, _, _ = run_validator(directory)
            self.assertEqual(exit_code, 1, "stale generated files must fail")

            exit_code, stderr, _ = run_validator(directory, "--write")
            self.assertEqual(exit_code, 0, stderr)

            exit_code, stderr, _ = run_validator(directory)
            self.assertEqual(exit_code, 0, stderr)
            hosts_text = (Path(directory) / "lists" / "basic.hosts").read_text(
                encoding="utf-8"
            )
            abp_text = (Path(directory) / "lists" / "basic.abp").read_text(
                encoding="utf-8"
            )
            self.assertIn("0.0.0.0 dobre.cz\n", hosts_text)
            self.assertIn("||dobre.cz^\n", abp_text)

    def test_write_is_a_no_op_when_files_are_current(self):
        with tempfile.TemporaryDirectory() as directory:
            write_lists(directory)
            lists = Path(directory) / "lists"
            before = {path.name: path.read_bytes() for path in lists.iterdir()}
            exit_code, stderr, _ = run_validator(directory, "--write")
            self.assertEqual(exit_code, 0, stderr)
            after = {path.name: path.read_bytes() for path in lists.iterdir()}
            self.assertEqual(before, after)

    def test_write_does_nothing_when_a_canonical_list_is_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            write_lists(
                directory,
                **{"basic.txt": "https://super.cz\nwww.super.cz\n"},
            )
            hosts = Path(directory) / "lists" / "basic.hosts"
            before = hosts.read_bytes()
            exit_code, stderr, _ = run_validator(directory, "--write")
            self.assertEqual(exit_code, 1)
            self.assertIn("URL", stderr)
            self.assertEqual(before, hosts.read_bytes())


if __name__ == "__main__":
    unittest.main()
