# Data attribution and terms

All interaction data in this repository is derived from **DDInter 2.0**, an
open-access drug-drug interaction database from the Computational Biology &
Drug Design Group.

- Source: https://ddinter2.scbdd.com/
- Citation: Xiong G, et al. DDInter 2.0: an enhanced drug interaction resource
  with expanded data coverage, new interaction types, and improved user
  interface. *Nucleic Acids Research.* 2025;53(D1):D1356-D1364.

The bundled JSON is a reformatting of DDInter's published data; it is not a new
database and adds no interaction claims of its own. DDInter's published terms of
use (https://ddinter2.scbdd.com/terms/) were reviewed and permit this
open redistribution with attribution. If you reuse this data, cite DDInter as
above and confirm the terms still fit your own context. DDInter is an academic
database rather than a government-agency product; that provenance is a
governance consideration for clinical deployment, noted openly here and in the
project README.

## CIEL concept dictionary

The CIEL bridge (`out/ciel_rxnorm_crosswalk.json` and the coverage files) is
derived from the **CIEL** concept dictionary (Columbia International eHealth
Laboratory), an OpenMRS community terminology published via the Open Concept
Lab.

- Source: https://app.openconceptlab.org/#/orgs/CIEL/sources/CIEL/
- Version used: CIEL v2026-07-20 (OCL export)

CIEL is an OpenMRS community resource. It is included here with the permission
of its maintainer for this OpenMRS-supporting work. The crosswalk reproduces
only CIEL concept codes and names alongside their existing CIEL-authored RxNorm
mappings; it adds no clinical claims of its own. If you reuse it, attribute
CIEL and confirm your own use fits CIEL's terms.

## Licensing

The **code and data files** in this repository are released under the Mozilla
Public License 2.0 with the OpenMRS Healthcare Disclaimer (see LICENSE and
HEALTHCARE_DISCLAIMER.md), matching OpenMRS's own licensing. This licensing
covers this project's packaging and tooling; the underlying facts remain those
of DDInter and CIEL respectively and must be cited and used per their terms.
