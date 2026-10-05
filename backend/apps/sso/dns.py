"""DNS lookups for domain verification (D63); tests replace ``txt_records``."""

import dns.exception
import dns.resolver


class LookupFailed(Exception):
    pass


def txt_records(name: str) -> list[str]:
    """The TXT strings published at ``name`` (each record's parts joined, as RFC 7208 reads them)."""
    try:
        answer = dns.resolver.resolve(name, "TXT", lifetime=10)
    except (dns.exception.DNSException, OSError) as exc:
        raise LookupFailed(type(exc).__name__) from exc
    return [b"".join(rdata.strings).decode("utf-8", "replace") for rdata in answer]
