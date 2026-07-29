"""Where an artifact's bytes came from.

An artifact that nobody can trace is not evidence. A training input has to
name the import it came from, a checkpoint the attempt that wrote it, and a
thumbnail the artifact it was derived from -- otherwise a finished run cannot
be explained after the fact, and provenance cannot be reconstructed later
because the knowledge only exists at the moment of writing.

The three origins an artifact can have are different in kind, so each carries
a different reference:

* ``ingested`` -- the bytes came from outside the system, so there is no
  in-system identifier to point at, only a label describing the source;
* ``derived`` -- produced from another artifact, named by that artifact's id;
* ``run_output`` -- written by one execution, named by that run attempt's id.

A machine path anywhere in a label is refused, however it is introduced,
because ``copied from /mnt/nas/inbox/a.png`` and ``source=/mnt/...`` leak the
same mount root that a bare path would. Where a file happened to sit on one
machine is not what the source was, and a mount path must not reach the
domain or the database.

A remote URL is a legitimate source, and its own syntax looks like a path, so
a label's URLs are lifted out before the rest is scanned. That keeps the scan
strict without it having to know anything about URLs -- and a label mixing
both, such as ``from https://example.org/x, staged at /srv/import``, is still
refused for the part that is a path.

None of this makes the check a boundary: a caller determined to write a path
in prose can. It catches the mistake that actually happens, which is pasting
one in.

A URL carrying a credential is refused outright rather than scanned. A
presigned link or a basic-auth URL works for whoever reads it, and provenance
is durable, so storing one leaves a usable secret behind long after the import
it described. Provenance names where bytes came from, not a way back in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final
from urllib.parse import unquote, urlsplit
from uuid import UUID

from image_model_lab_domain.artifacts.errors import ArtifactProvenanceError
from image_model_lab_domain.lifecycle import require_state
from image_model_lab_domain.validation import require_id, require_instant, require_text

MAX_SOURCE_LABEL_LENGTH: Final = 500
"""Maximum length of an ingest source label, in characters."""

_REMOTE_URL: Final = re.compile(
    r"""
    (?<![A-Za-z0-9])       # the scheme starts a token
    (?!file://)            # a local path wearing a URL is not lifted
    [a-z][a-z0-9+.-]+      # a scheme, never the single letter of a drive
    ://
    (?>(?:[^\s/@]+@)?)     # userinfo, taken atomically so a host must follow it
    (?:[^\W_]|\[[0-9A-Fa-f:.]+\])   # a host: a name in any script, or a closed IPv6
    [^\s,;"'<>\\]*         # the rest, stopping where prose or a Windows path resumes
    """,
    re.VERBOSE | re.IGNORECASE,
)
"""One whole remote URL token, which a label may name a source by.

A URL's own syntax -- ``?next=/gallery``, ``#/gallery``, a port, a rooted path
-- reads like a machine path to any scan short of a URL parser, so a URL is
lifted out of the label before the scan rather than exempted case by case
inside it. ``file://`` is deliberately not lifted: that is a local path
wearing a URL, and the scan should see it.

Three things keep the lift from becoming a way to smuggle a path past the
scan. The scheme has to start a token, or ``file:///mnt/nas`` would be lifted
as the URL ``ile:///mnt/nas``. A host has to follow ``://``, or
``https:///mnt/nas`` would be lifted as a URL whose whole content is a machine
path. That host is a name or an IPv6 literal whose bracket actually closes, or
``https://[/mnt/nas`` would qualify on the bracket alone, and any userinfo is
taken atomically so a host still has to follow it -- otherwise
``https://user@/mnt/nas`` would match with ``u`` as its host. And the scheme
has to be at least two characters: no real scheme is one letter, every Windows
drive is, and ``C://Users/me/a.png`` is a pasted path.

The URL also ends where prose resumes rather than at the next space, or
``https://example.org/a,staged=/mnt/nas`` would leave as one token and take
the path with it. A comma or a quote is far likelier to be a writer's
punctuation than part of the address, and a raw backslash is never part of
one at all, so ``https://example.org/C:\\Users\\me\\a.png`` ends at the drive.

Together these hold the property the lift depends on: what leaves the label is
a whole remote URL, never something with a machine path inside it.
"""

_CREDENTIAL_PARAMETERS: Final = frozenset(
    {
        # Generic
        "access_token",
        "accesskey",
        "access_key",
        "accesskeyid",
        "access_key_id",
        "api_key",
        "apikey",
        "auth",
        "authorization",
        "bearer",
        "bearer_token",
        "credential",
        "credentials",
        "id_token",
        "jwt",
        "oauth_token",
        "oauth_token_secret",
        "password",
        "passwd",
        "personal_access_token",
        "private_token",
        "pwd",
        "refresh_token",
        "secret",
        "client_secret",
        "sig",
        "signature",
        "token",
        # AWS presigned
        "x_amz_signature",
        "x_amz_credential",
        "x_amz_security_token",
        # Google signed
        "x_goog_signature",
        "x_goog_credential",
    }
)
"""Query or fragment parameter names that carry a credential by themselves.

Matched as whole names, never as substrings, so an ordinary ``?series=`` or
``?key=`` is untouched -- an S3 object key names the object, not the way in.
Hyphens are read as underscores, so one entry covers ``bearer-token`` and
``bearer_token``, ``X-Amz-Signature`` and ``x_amz_signature``.

Every name here is a secret on its own. An Azure shared access signature is
covered by ``sig``, which each of its forms carries; its other fields --
``se``, ``sp``, ``st`` and the rest -- are expiry and permission metadata that
mean nothing without it, and they are short enough to be someone's ordinary
parameter. ``?st=article`` is a source, not a signature.
"""

_URL_LIKE: Final = re.compile(r"(?<![A-Za-z0-9])[a-z][a-z0-9+.-]*://\S+", re.IGNORECASE)
"""Anything shaped like a URL, for the credential scan to look inside.

Deliberately not :data:`_REMOTE_URL`, which answers the opposite question.
Lifting has to be conservative -- it removes text from the path scan, so it
must not swallow prose or a pasted path, and it stops at punctuation and
demands a real authority. A credential scan has to be liberal for exactly
those reasons reversed: ``?foo=1;token=...`` keeps its secret after the
semicolon that ends a lift, and ``https:///mnt/a?token=...`` carries one even
though no authority makes it a source worth lifting.
"""

_PARAMETER_SEPARATOR: Final = re.compile(r"[?&;]")

_URL_IGNORED_WHITESPACE: Final = str.maketrans("", "", "\t\r\n")
"""Characters a URL parser drops before it reads a URL.

:func:`urllib.parse.urlsplit` removes tabs and newlines wherever they appear,
so ``https://example.org/a?foo=1\\n&token=...`` is one working URL to whoever
follows it. The credential scan removes them too, or a pasted line break in
the middle of a URL would end the token just before its secret.
"""

_MACHINE_PATH: Final = re.compile(
    r"""
      (?<![^\W_])/        # a POSIX absolute path: a slash that starts something
    | \\                  # any backslash: a Windows separator or a UNC prefix
    | [A-Za-z]:[\\/]      # a Windows drive
    | file://             # a local path wearing a URL
    """,
    re.VERBOSE | re.IGNORECASE,
)
"""A machine path in what is left of a label once its URLs are lifted out.

``copied from /mnt/nas/inbox/a.png``, ``source=/mnt/...``,
``(/srv/import/a.png)`` and ``source:/mnt/...`` all leak the same mount root a
bare path would, so a slash starts a path unless it continues a word. That
still leaves ``2026/07`` and ``roll 4/12`` usable as labels.

A word here is a letter or digit in any script, not only ASCII, or a label
written in Japanese or Korean would have every slash read as a path.
"""


class ProvenanceKind(StrEnum):
    """How an artifact's bytes came to exist."""

    INGESTED = "ingested"
    DERIVED = "derived"
    RUN_OUTPUT = "run_output"


@dataclass(frozen=True, slots=True)
class ArtifactProvenance:
    """The origin recorded with an artifact when its bytes were written.

    ``source_id`` names the artifact or run attempt the bytes came from, and
    ``source_label`` describes an external origin that has no identifier here.
    Exactly one of them fits any given kind, so a record can never claim both
    an in-system parent and an outside source.
    """

    kind: ProvenanceKind
    recorded_at: datetime
    source_id: UUID | None = None
    source_label: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "kind",
            require_state(
                self.kind,
                states=ProvenanceKind,
                subject="artifact provenance kind",
                error=ArtifactProvenanceError,
            ),
        )
        object.__setattr__(
            self,
            "recorded_at",
            require_instant(
                self.recorded_at,
                field="artifact provenance recorded_at",
                error=ArtifactProvenanceError,
            ),
        )
        self._validate_source()

    def _validate_source(self) -> None:
        if self.kind is ProvenanceKind.INGESTED:
            if self.source_label is None:
                raise ArtifactProvenanceError(
                    "ingested artifact provenance needs a source label; bytes from outside "
                    "the system have no identifier here to name them by"
                )
            if self.source_id is not None:
                raise ArtifactProvenanceError(
                    "ingested artifact provenance must not have a source id; the bytes came "
                    "from outside the system"
                )
            self._validate_label(self.source_label)
            return

        if self.source_id is None:
            raise ArtifactProvenanceError(
                f"{self.kind.value} artifact provenance needs the source id of the "
                "artifact or run attempt the bytes came from"
            )
        require_id(
            self.source_id, field="artifact provenance source id", error=ArtifactProvenanceError
        )
        if self.source_label is not None:
            raise ArtifactProvenanceError(
                f"{self.kind.value} artifact provenance must not have a source label; its "
                "origin is inside the system and is named by the source id"
            )

    def _validate_label(self, label: object) -> None:
        # The credential scan runs before any other check, because every other
        # rejection quotes the label to explain itself. A pasted URL often
        # arrives with a stray newline, and that is enough to reach a message
        # carrying the secret into whatever reads the error.
        if type(label) is str:
            self._reject_credentials(label)
            if label != label.strip():
                # Said without the value, unlike require_text's own wording:
                # a label that reached here held no credential this code could
                # recognise, which is not the same as holding none.
                raise ArtifactProvenanceError(
                    "artifact provenance source label must not start or end with whitespace"
                )
        text = require_text(
            label,
            field="artifact provenance source label",
            error=ArtifactProvenanceError,
            max_length=MAX_SOURCE_LABEL_LENGTH,
        )
        if _MACHINE_PATH.search(_without_remote_urls(text)):
            # The label is not quoted back. A caller has what they typed, and
            # no message here is worth being the one that copies a secret out
            # of a label the credential scan did not recognise as a URL.
            raise ArtifactProvenanceError(
                "artifact provenance source label contains a machine path; record what "
                "the source was, not where one machine kept it"
            )

    @staticmethod
    def _reject_credentials(label: str) -> None:
        for url in _URL_LIKE.findall(label.translate(_URL_IGNORED_WHITESPACE)):
            if _carries_credentials(url):
                raise ArtifactProvenanceError(
                    "artifact provenance source label carries a credential in one of its "
                    "URLs; provenance records where bytes came from, not a way back in, "
                    "and a stored signature stays usable until it expires"
                )


def _without_remote_urls(label: str) -> str:
    """``label`` with its remote URLs removed, ready for the path scan.

    The pattern finds candidates and a URL parser decides. A token only leaves
    the label if it actually resolves to a host, so a malformed authority such
    as ``https://note@host@/mnt/nas/image.png`` -- which has no hostname after
    its last delimiter -- stays behind with its path for the scan to refuse.
    """

    def lift(match: re.Match[str]) -> str:
        token = match.group()
        try:
            hostname = urlsplit(token).hostname
        except ValueError:
            return token
        return " " if hostname else token

    return _REMOTE_URL.sub(lift, label)


def _carries_credentials(url: str) -> bool:
    """Whether ``url`` embeds a secret rather than only naming a source.

    A presigned URL and a basic-auth URL are both usable by whoever reads
    them, so neither belongs in a durable record. The rejected value is never
    echoed in the error: repeating a secret to report it is how it ends up in
    a log.

    The split is a real URL split, and each component is decoded only after
    it is separated out. Both halves of that matter. Decoding first would
    invent structure that is not there -- ``curator:hun%2Fter2@host`` would
    appear to end its authority at a slash inside the password. Splitting by
    hand got the delimiters wrong instead: an authority ends at ``?`` and
    ``#`` as well as ``/``, or the ``@`` in
    ``https://example.org?contact=mailto:curator@example.net`` reads as
    basic-auth in a URL that has no userinfo at all.

    A token this cannot parse carries no credential to find, so it is left to
    the checks around it rather than refused on suspicion.
    """

    try:
        parts = urlsplit(url)
    except ValueError:
        # Unparseable, but its text can still hold a secret, and something
        # further on would quote it while explaining a different complaint.
        return not _parameter_names(url).isdisjoint(_CREDENTIAL_PARAMETERS)

    if parts.password is not None or ":" in unquote(parts.username or ""):
        return True
    names = _parameter_names(parts.query) | _parameter_names(parts.fragment)
    return not names.isdisjoint(_CREDENTIAL_PARAMETERS)


def _parameter_names(component: str) -> set[str]:
    """The decoded parameter names in a query or fragment.

    The fragment is read the same way as the query because hash routing puts
    a whole query behind the ``#``, and a signature pasted there is as durable
    as one in front of it.
    """

    names: set[str] = set()
    for pair in _PARAMETER_SEPARATOR.split(component):
        name, assigned, _ = pair.partition("=")
        if assigned:
            names.add(unquote(name).strip().lower().replace("-", "_"))
    return names


__all__ = ["MAX_SOURCE_LABEL_LENGTH", "ArtifactProvenance", "ProvenanceKind"]
