# Source audit

Audit date: 2026-09-07 (America/Los_Angeles). The imported research was used only for candidate discovery. Its prices, availability counts, addresses, observation dates, commute estimates, and citations were not imported as observations.

## Enabled and live-validated sources

| Community | Official page | Public inventory source | Result | Notes |
|---|---|---|---|---|
| Sevens | https://sevensmv.com/floorplans/ | Jonah embedded JSON | Complete exact units | Base rent and fee-inclusive monthly total are stored separately. Public inventory may include restricted units; verify eligibility before applying. |
| Loft House | https://livelofthouse.com/floorplans/ | Jonah embedded JSON | Complete exact units | Same provider contract as Sevens. |
| AIRE | https://aireliving.com/floorplans/ | Jonah embedded JSON | Complete exact units | Same provider contract as Sevens. |
| eaves Mountain View at Middlefield | official Avalon community page | Avalon Fusion embedded state | Complete exact units | Requested move-in and lease-specific pricing basis retained when exposed. |
| Avalon Mountain View | official Avalon community page | Avalon Fusion embedded state | Complete exact units | Requested move-in and lease-specific pricing basis retained when exposed. |
| The Martin | https://livethemartin.com/floorplans/ | Public WordPress/Yardi inventory actions | Complete exact units | Nonces are read from the page on every run rather than stored. |
| Rowe at Pear Village | https://rowepearvillage.com/floor-plans/ | Public SightMap API linked by official page | Complete exact units | Base and total monthly prices, lease term, availability, and affordable-housing metadata retained when exposed. |
| The Flats at CityLine | https://citylineflats.com/apartments/ | Public SightMap API linked by official page | Complete exact units | Floorplans include BMR labels; unit affordability metadata is retained when exposed. |
| Avelle | https://liveavelle.com/floorplans/ | Public WordPress/Yardi inventory actions | Complete exact units | Official address is 1170 Spruce St; this corrects the research candidate's address. |
| Villa Del Sol | https://www.villadelsolsunnyvale.com/apartments/ca/sunnyvale/floor-plans | Public G5 GraphQL endpoint configured by official page | Complete response, no matching units | Only a two-bedroom floorplan was exposed during validation. This is explicit no studio/one-bedroom availability, not collection failure. |

Each adapter rejects malformed or incomplete payloads. A zero becomes `explicit_no_availability` only after the expected complete provider structure parses successfully.

## Audited blockers and unsupported sources

| Candidate/provider | Finding | Current treatment |
|---|---|---|
| 1250 Lakeside / Essex | Direct collection returned HTTP 429 security checkpoint. | `blocked`; never interpreted as zero availability. |
| Maxwell and Epic / Essex | Same provider family; implementation remains pending. | Unsupported. |
| Redwood Place and Santa Clara Square / Irvine Company | Direct collection was challenged. Current Irvine terms also prohibit automated scraping. | Unsupported. |
| Prometheus communities | Direct checks returned HTTP 403 from this machine. | Unsupported; seek a stable public feed. |
| Catalyst Mountain View | Official search rendering shows exact units, while raw collector access receives a challenge. | Unsupported; no result stored from research/search snippets. |
| ILARA and Montrose | Official sites advertise interactive SightMap inventory, but stable public map API identifiers were not validated in this audit. | Candidate for the next SightMap expansion. |
| Kensington Place / Anton 1101 and other weak candidates | Research names or URLs may be stale or ambiguous. | Revalidate identity and official address before implementation. |

Robots directives and site terms are recorded as source-policy evidence when found. The monitor uses a clear user agent, bounded retries, sequential requests, and a once-daily schedule. It does not solve CAPTCHAs, authenticate, rotate identities, or evade access controls.
