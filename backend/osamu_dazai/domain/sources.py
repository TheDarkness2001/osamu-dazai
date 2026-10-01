"""Sources and their verification state (spec §44: never fabricate sources)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import model_validator

from osamu_dazai.domain.common import Entity, id_field


class SourceKind(StrEnum):
    DOI = "doi"
    URL = "url"
    BOOK = "book"
    USER_FILE = "user_file"
    STANDARD = "standard"  # curriculum standard / exam specification


class VerificationMethod(StrEnum):
    NONE = "none"
    CROSSREF = "crossref"
    SEMANTIC_SCHOLAR = "semantic_scholar"
    URL_FETCH = "url_fetch"
    USER_FILE = "user_file"  # the user uploaded it — exists by construction
    MANUAL = "manual"  # an editor confirmed it


class Source(Entity):
    ID_PREFIX = "src"
    id: str = id_field(ID_PREFIX)
    project_id: str
    kind: SourceKind
    citation: str  # human-readable reference
    title: str = ""
    authors: str = ""
    year: str = ""
    doi: str | None = None
    url: str | None = None
    verified: bool = False
    verified_via: VerificationMethod = VerificationMethod.NONE
    verified_at: datetime | None = None
    note: str = ""

    @model_validator(mode="after")
    def _verification_consistent(self) -> Source:
        if self.verified and self.verified_via is VerificationMethod.NONE:
            raise ValueError("a verified source must record how it was verified")
        if not self.verified and self.verified_via is not VerificationMethod.NONE:
            raise ValueError("verified_via set but source is not marked verified")
        return self
