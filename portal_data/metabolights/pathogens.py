"""Pathogens per MetaboLights study, from the keywords that matched its papers.

``metabolights_search`` records which search keywords matched each paper's
title or abstract (the ``matched_keywords`` column of its papers CSV) and
which MetaboLights studies each paper links to. Most of those keywords are
generic ("host", "biofilm", "bacterial"), and one pathogen can match under
several names ("E. coli", "Escherichia coli", "ETEC"). PATHOGEN_KEYWORDS_CSV
maps just the keywords that identify a pathogen to one name for it, so a
study's pathogens are the mapped names of its papers' keywords.

Keywords left out of the map on purpose:
  - generic terms (infection, host, microbiome, vaccine, ...)
  - diseases with many possible causes (pneumonia, sepsis, meningitis,
    gastroenteritis, hepatitis on its own)
  - virus family and broad group names (Coronaviridae, coronavirus, herpes)
  - abbreviations with common other meanings in metabolomics papers: GAS
    (gas chromatography), MAC, PCP, CDI, GBS, VRE (e.g. "virtual research
    environment"), B19
A disease with a single cause maps to that pathogen (tuberculosis ->
Mycobacterium tuberculosis, malaria -> Plasmodium, COVID-19 -> SARS-CoV-2).

The result only covers studies the search found, and reflects what the paper
text mentions -- not necessarily what the dataset itself measured.
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Iterable
from pathlib import Path

logger = logging.getLogger(__name__)

PATHOGEN_KEYWORDS_CSV = Path(__file__).with_name("pathogen_keywords.csv")


def load_pathogen_map(path: Path = PATHOGEN_KEYWORDS_CSV) -> dict[str, str]:
    """Return {keyword (casefolded): pathogen} from a keyword,pathogen CSV."""
    mapping: dict[str, str] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            keyword = (row.get("keyword") or "").strip()
            pathogen = (row.get("pathogen") or "").strip()
            if keyword and pathogen:
                mapping[keyword.casefold()] = pathogen
    return mapping


def pathogens_for_keywords(keywords: Iterable[str], mapping: dict[str, str]) -> list[str]:
    """Return the distinct pathogens named by some matched keywords, sorted."""
    found = {mapping[k.strip().casefold()] for k in keywords if k.strip().casefold() in mapping}
    return sorted(found, key=str.casefold)


def pathogens_by_accession(papers_csv: Path, mapping: dict[str, str]) -> dict[str, list[str]]:
    """Return {MetaboLights accession: pathogens} from a metabolights_search papers CSV.

    A study linked from several papers gets the pathogens of all of them.
    Returns {} if the CSV doesn't exist (no search has been run) or can't
    be read, so the listing simply shows no pathogens.
    """
    keywords_by_accession: dict[str, set[str]] = {}
    try:
        with papers_csv.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                keywords = (row.get("matched_keywords") or "").split(";")
                for accession in (row.get("metabolights_accessions") or "").split(";"):
                    accession = accession.strip().upper()
                    if accession:
                        keywords_by_accession.setdefault(accession, set()).update(keywords)
    except FileNotFoundError:
        return {}
    except (OSError, csv.Error) as error:
        logger.warning("Could not read search results %s: %s", papers_csv, error)
        return {}

    result = {}
    for accession, keywords in keywords_by_accession.items():
        pathogens = pathogens_for_keywords(keywords, mapping)
        if pathogens:
            result[accession] = pathogens
    return result
