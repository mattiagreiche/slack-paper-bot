# Spec: Zotero-Integrated Paper Archive — Trial
**Source:** User request on 2026-06-29, existing Slack paper archive project memory, and Slack OAuth trial request on 2026-07-23
**Epic:** N/A — single trial spec
**Glossary:** specs/glossary.md
**Generated:** 2026-06-29
**Status:** DRAFT — requires operator review

## System Constraints

- **SC-01**: The trial MUST treat Zotero as the visible shared library destination for synced items. Any local web surface MUST support operation, debugging, configuration, or curation review rather than replacing Zotero as the primary collection interface.
- **SC-02**: The system MUST NOT post replies, summaries, or notifications into Slack during the trial unless explicitly enabled later.
- **SC-03**: The system MUST monitor only opted-in public Slack channels during the trial.
- **SC-04**: The system MUST NOT store full Slack message text. It MAY store supported links, channel metadata, sharer metadata, timestamps, and Slack permalinks.
- **SC-05**: The system MUST distinguish imported factual metadata from generated curation.
- **SC-06**: Generated curation MUST be labeled as bot-generated wherever it appears in Zotero.
- **SC-07**: A failed external dependency MUST NOT cause loss of already-ingested Slack mentions.
- **SC-08**: The trial MUST support arXiv links, DOI links, journal article links, and Semantic Scholar paper links. General web/news links and ResearchGate links MUST be synced only when they resolve to a stable scholarly identifier; otherwise they are out of scope for the first trial.
- **SC-09**: Private Slack channels MUST be excluded from the first trial.
- **SC-10**: Human-authored Zotero notes, tags, collections, and item metadata MUST NOT be overwritten by bot sync. The bot MAY fill or refresh factual Zotero item metadata from the item source and MUST own any Bot-Owned Tags it creates.
- **SC-11**: The system MUST provide enough status information for a Bot Operator to identify pending sync work, failed sync work, and external dependency failures.
- **SC-12**: Semble sync and zemble-based workflows are out of scope for this trial. The trial MAY preserve enough conceptual separation to add Semble later. [ASSUMPTION]
- **SC-13**: The trial does not require importing pre-existing Zotero items into the similarity index because there is no existing lab Zotero library at the start of the trial.
- **SC-14**: For journal, publisher, repository, and Semantic Scholar pages, the system MUST attempt Zotero translator-based metadata first and then fall back to external scholarly metadata sources when translator-based metadata is unavailable or incomplete.
- **SC-15**: Normal operation SHOULD NOT repeatedly resync stable Zotero items. Resync and refresh SHOULD occur only when there is a new Slack Mention, a failed job retry, a metadata correction, or an explicit Bot Operator action.
- **SC-16**: The first working milestone MUST prove the path from a Slack arXiv link in an opted-in public channel to a Zotero item in the channel's collection with Slack provenance in `Bot notes`. This milestone does not remove DOI, journal, Semantic Scholar, generated curation, or review-surface behavior from the full trial spec.
- **SC-17**: The local web surface SHOULD retain archive search as a secondary or fallback view when it can run alongside Zotero sync without adding meaningful operational complexity. The trial SHOULD NOT make local archive search the primary homepage unless Zotero search proves insufficient for lab use.
- **SC-18**: Generated related items and generated topic tags MUST NOT be required for the first working Slack-to-Zotero implementation. They SHOULD be added after plain Slack-to-Zotero item sync, channel collection membership, and Slack provenance notes work reliably.
- **SC-19**: Bot-Owned Notes SHOULD contain human-useful content only and SHOULD NOT include machine-readable sync identifiers, stack traces, retry metadata, or debug details.
- **SC-20**: External Related Items SHOULD be the first related-paper feature after plain Slack-to-Zotero sync. Internal Related Items MAY be added later, but are not required for the trial.
- **SC-21**: External Related Items MUST NOT be automatically added to Zotero as library items unless a Zotero Group Member or Bot Operator explicitly chooses to add them later.
- **SC-22**: Installation into a Slack workspace other than the app's development workspace MUST use Slack's supported OAuth installation flow.
- **SC-23**: Slack installation credentials MUST be protected at rest and MUST NOT appear in browser responses, operator pages, logs, errors, Zotero content, or generated exports.
- **SC-24**: Slack events, user and channel enrichment, backfill, and catch-up MUST use the credential belonging to the single Active Slack Installation. Events from any other workspace MUST NOT be processed with that credential.
- **SC-25**: Completing Slack authorization MUST NOT expand the trial beyond opted-in public channels or grant the system permission to post into Slack.
- **SC-26**: A newly authorized Slack Installation MUST NOT begin ingestion or Zotero sync until the Trial Zotero Destination has been configured and a Bot Operator activates the installation.
- **SC-27**: A failed, cancelled, duplicated, expired, or forged OAuth attempt MUST NOT replace a valid Slack Installation or expose installation credentials.
- **SC-28**: The trial MUST permit exactly one Active Slack Installation and one Trial Zotero Destination at a time. Concurrent multi-workspace processing is out of scope.
- **SC-29**: An ordinary archive-data reset MUST preserve the Slack Installation and Trial Zotero Destination. Removing installation credentials MUST require a separate explicit full-reset action.

## Feature Specs

### F-01: Opted-In Slack Channel Capture | MUST

**F-01.1: Capture supported link from an opted-in channel**
- **GIVEN** the bot has access to an opted-in Slack channel
- **WHEN** a Slack Sharer posts a supported link in that channel
- **THEN** the system records a Slack Mention for the Canonical Item and queues Zotero sync work for that item

**F-01.2: Ignore channels that are not opted in**
- **GIVEN** the bot is not present in a Slack channel or the channel is not treated as opted in
- **WHEN** a Slack Sharer posts a supported link in that channel
- **THEN** the system does not record the item from that message

**F-01.3: Ignore unsupported Slack surfaces**
- **GIVEN** a supported link appears in a Slack direct message, private channel, bot message, deleted message, or unsupported channel type
- **WHEN** the system receives or discovers that message
- **THEN** the system does not record a Slack Mention for it

**F-01.4: External Slack delivery failure**
- **GIVEN** Slack delivery of a live event fails or is interrupted
- **WHEN** the channel is later processed by catch-up or backfill
- **THEN** the system records any missing supported links without creating duplicate Slack Mentions

### F-02: Historical Backfill and Catch-Up | MUST

**Requires:** F-01 (Opted-In Slack Channel Capture)

**F-02.1: Backfill opted-in channel history**
- **GIVEN** a Bot Operator requests backfill for an opted-in channel
- **WHEN** Slack history is available
- **THEN** the system processes historical messages and records Slack Mentions for supported links

**F-02.2: Respect date bounds**
- **GIVEN** a Bot Operator provides a start date, end date, or message limit for backfill
- **WHEN** backfill runs
- **THEN** the system processes only messages inside the requested bounds and reports the number of mentions created

**F-02.3: Backfill cannot read channel history**
- **GIVEN** Slack denies history access, the bot is not in the channel, or the channel no longer exists
- **WHEN** backfill runs
- **THEN** the system reports the channel failure and continues processing other eligible channels

**F-02.4: Scheduled catch-up after downtime**
- **GIVEN** the system has previously processed an opted-in channel
- **WHEN** the worker resumes after downtime
- **THEN** the system checks for messages since the last successful catch-up and records any missing supported links

### F-03: Canonical Item Metadata | MUST

**Requires:** F-01 (Opted-In Slack Channel Capture)

**F-03.1: Create canonical item**
- **GIVEN** the system sees a supported link for an item not yet recorded
- **WHEN** the link is processed
- **THEN** the system creates one Canonical Item record and marks factual metadata as pending

**F-03.2: Deduplicate URL variants**
- **GIVEN** multiple supported links refer to the same item
- **WHEN** those links are processed from any opted-in channel
- **THEN** the system attaches all Slack Mentions to one Canonical Item

**F-03.3: Fetch factual item metadata**
- **GIVEN** a Canonical Item has pending metadata
- **WHEN** the metadata source is available
- **THEN** the system records available factual metadata appropriate to the item type, including title, creators, abstract or description, source identifier, canonical URL, PDF URL when available, categories or subjects when available, publication date when available, and updated date when available
- **AND** for arXiv items, the arXiv API remains primary while the official arXiv abstract page MAY provide factual citation metadata when the API is rate-limited, unavailable, or times out

**F-03.4: Metadata fetch fails**
- **GIVEN** a metadata source is unavailable, returns malformed data, or does not contain the item
- **WHEN** the system attempts to fetch metadata
- **THEN** the system records the failure, keeps the Canonical Item and Slack Mention, and schedules or allows a retry
- **AND** the Bot Operator can distinguish a timeout, rate limit, provider response, and other safe failure category even when the underlying exception has no message

**F-03.5: Resolve identifier-backed scholarly links**
- **GIVEN** a supported link contains or resolves to a stable scholarly identifier such as an arXiv ID, DOI, Semantic Scholar paper ID, PMID, or OpenAlex work ID
- **WHEN** metadata enrichment runs
- **THEN** the system uses that identifier as the primary deduplication key and attempts to create a Scholarly Item

**F-03.6: Resolve journal and publisher pages**
- **GIVEN** a supported link points to a journal, publisher, Semantic Scholar, or repository page
- **WHEN** metadata enrichment runs
- **THEN** the system first attempts Zotero translator-based metadata, then falls back to external scholarly metadata sources, and treats the item as a Scholarly Item when enough metadata is available

**F-03.7: Create minimal item for unresolved scholarly-looking link**
- **GIVEN** a Scholarly-Looking Link cannot be fully resolved by translator-based metadata or external scholarly metadata sources
- **WHEN** the system can still identify a title or canonical URL
- **THEN** the system creates a minimal Canonical Item for Zotero sync using the available title and URL

**F-03.10: Choose minimal unresolved Zotero item type**
- **GIVEN** the system creates a minimal Canonical Item for an unresolved Scholarly-Looking Link
- **WHEN** the link looks like a paper, preprint, article, journal page, publisher page, repository paper page, or Semantic Scholar page
- **THEN** the system represents it as a Zotero journal article

**F-03.11: Fallback minimal unresolved Zotero item type**
- **GIVEN** the system creates a minimal Canonical Item for an unresolved Scholarly-Looking Link
- **WHEN** the link does not look like a paper, preprint, article, journal page, publisher page, repository paper page, or Semantic Scholar page
- **THEN** the system represents it as a Zotero webpage

**F-03.8: Resolve web and news links**
- **GIVEN** a web, news, or ResearchGate link does not resolve to a stable scholarly identifier
- **WHEN** metadata enrichment runs
- **THEN** the system marks the link unsupported for Zotero sync during the first trial

**F-03.9: Unsupported or blocked webpage**
- **GIVEN** a link cannot be resolved to a scholarly identifier and webpage metadata cannot be extracted
- **WHEN** metadata enrichment runs
- **THEN** the system records the link as unsupported for Zotero sync and exposes the failure in the local surface without blocking other items

**F-03.12: Viewer visibility for unsupported links**
- **GIVEN** an unsupported link has been recorded from an opted-in public channel
- **WHEN** an Archive Viewer or Bot Operator opens the local surface
- **THEN** the system may show the unsupported link, source channel, sharer, timestamp, and unsupported reason without creating a Zotero item for it

### F-04: Zotero Group Library Item Sync | MUST

**Requires:** F-03 (Canonical Item Metadata)

**F-04.1: Create Zotero item**
- **GIVEN** a Canonical Item has enough factual metadata to represent it in Zotero
- **WHEN** Zotero sync runs
- **THEN** the system creates a corresponding item in the configured Zotero group library

**F-04.2: Avoid duplicate Zotero items**
- **GIVEN** the Zotero group library already contains an item for the Canonical Item
- **WHEN** Zotero sync runs
- **THEN** the system links the Canonical Item to the existing Zotero item rather than creating a duplicate

**F-04.3: Preserve human edits in Zotero**
- **GIVEN** a Zotero item has been edited by a Zotero Group Member
- **WHEN** Zotero sync runs again
- **THEN** the system does not overwrite human-authored notes, non-bot tags, or collection choices unless the field is explicitly owned by the bot

**F-04.4: Refresh factual Zotero metadata**
- **GIVEN** a Zotero item corresponds to a Canonical Item
- **WHEN** the item source provides new or corrected factual metadata
- **THEN** the system may refresh Zotero item fields derived from the item source while preserving human-authored notes, non-bot tags, and collection choices

**F-04.5: Zotero sync failure**
- **GIVEN** Zotero rejects a request, credentials expire, rate limits apply, or the group library is unavailable
- **WHEN** Zotero sync runs
- **THEN** the system records the failure, keeps local sync state pending or failed, and retries or exposes the failure to a Bot Operator

**F-04.6: Immediate Zotero sync**
- **GIVEN** a Canonical Item has enough metadata for Zotero sync
- **WHEN** sync work is queued during normal operation
- **THEN** the system attempts real Zotero sync without requiring prior dry-run approval

**F-04.7: Retry after temporary Zotero failure**
- **GIVEN** Zotero sync fails because of rate limits, temporary external failure, or interrupted processing
- **WHEN** the failure is recorded
- **THEN** the system retries later without losing the Canonical Item, Slack Mentions, or pending collection and note updates

### F-05: Channel-Based Zotero Collection Membership | MUST

**Requires:** F-04 (Zotero Group Library Item Sync)

**F-05.1: Add item to channel collection**
- **GIVEN** a Canonical Item has a Slack Mention in an opted-in channel
- **WHEN** Zotero sync runs
- **THEN** the Zotero item is a member of the collection mapped to that channel

**F-05.2: Create or map missing channel collection**
- **GIVEN** an opted-in channel has no mapped Zotero collection
- **WHEN** Zotero sync first needs to place an item from that channel
- **THEN** the system automatically creates a Zotero collection using the raw Slack channel name and records the mapping

**F-05.3: Item shared across channels**
- **GIVEN** the same Canonical Item is shared in multiple opted-in channels
- **WHEN** Zotero sync runs
- **THEN** the Zotero item belongs to each corresponding channel collection without being duplicated

**F-05.4: Private channel collection safety**
- **GIVEN** a Slack Mention comes from a private channel
- **WHEN** Zotero sync runs
- **THEN** the system skips Zotero collection membership and provenance sync for that mention during the trial

### F-06: Zotero Provenance Notes | MUST

**Requires:** F-04 (Zotero Group Library Item Sync)

**F-06.1: Create provenance note**
- **GIVEN** a Zotero item corresponds to a Canonical Item with at least one Slack Mention
- **WHEN** Zotero sync runs
- **THEN** the system creates or updates one Bot-Owned Note titled `Bot notes` containing human-useful bot-generated curation when available and Slack share history

**F-06.2: Include Slack source details**
- **GIVEN** a Slack Mention has channel, sharer, timestamp, and permalink data
- **WHEN** the provenance note is updated
- **THEN** the note includes those available details without including full Slack message text

**F-06.3: Append repeat shares**
- **GIVEN** a Canonical Item already has a Zotero provenance note
- **WHEN** the item receives a new Slack Mention
- **THEN** the provenance note reflects the additional share without removing prior share entries

**F-06.4: Avoid editing human notes**
- **GIVEN** the Zotero item has notes created by Zotero Group Members
- **WHEN** provenance note sync runs
- **THEN** the system updates only the bot-owned provenance note

**F-06.5: Exclude debug details from Zotero note**
- **GIVEN** sync state, source IDs, retry state, or error details exist for a Canonical Item
- **WHEN** the Bot-Owned Note is created or updated
- **THEN** the note excludes those debug details and leaves troubleshooting information in the local surface

### F-07: BibTeX and Citation Data | SHOULD

**Requires:** F-03 (Canonical Item Metadata), F-04 (Zotero Group Library Item Sync)

**F-07.1: Store citation data when available**
- **GIVEN** citation data is available for a Canonical Item
- **WHEN** metadata enrichment runs
- **THEN** the system stores citation data and makes it available for Zotero sync or local inspection

**F-07.2: Citation source unavailable**
- **GIVEN** the citation source is unavailable or returns incomplete data
- **WHEN** citation enrichment runs
- **THEN** the system falls back to available factual metadata and does not block Zotero item creation

### F-08: Generated Similarity Structure | SHOULD

**Requires:** F-03 (Canonical Item Metadata), F-04 (Zotero Group Library Item Sync)

**Implementation detail:** Build External Related Items before internal related items, embeddings, or LLM-generated explanations. The first implementation uses Semantic Scholar's Recommendations API, stores suggestions locally, and renders them into Zotero `Bot notes` as clearly labeled bot-generated suggestions.

**F-08.1: Generate internal related items**
- **GIVEN** a Canonical Item has title and abstract or description metadata and the library contains other comparable items
- **WHEN** internal related-item generation has been explicitly enabled
- **THEN** the system identifies up to three Internal Related Items across the full library, independent of Slack channel

**F-08.2: Store internal related-item output**
- **GIVEN** Internal Related Items have been generated for a Canonical Item
- **WHEN** Zotero sync runs
- **THEN** the system writes the suggestions directly to the item's Bot-Owned Note

**F-08.9: Generate external related items**
- **GIVEN** a Canonical Item has enough metadata or a stable scholarly identifier for external recommendation
- **WHEN** external related-item generation runs
- **THEN** the system may identify up to five External Related Items from broader scholarly literature and mark them separately from Internal Related Items

**F-08.12: Store external related-item output in Zotero**
- **GIVEN** External Related Items have been generated for a Canonical Item
- **WHEN** Zotero sync updates the item's Bot-Owned Note
- **THEN** the note includes the External Related Items as human-useful suggestions separate from Slack provenance and generated tags

**F-08.13: External related-item manual import**
- **GIVEN** an External Related Item is suggested but is not yet in the Zotero group library
- **WHEN** a Zotero Group Member or Bot Operator chooses to add it later
- **THEN** the system may create a Zotero item for that suggestion, add it to the same Channel Collection as the Canonical Item it was suggested from, and record that it was manually accepted rather than automatically imported

**F-08.10: External recommendation source unavailable**
- **GIVEN** an external recommendation source is unavailable, rate-limited, returns no results, or cannot recognize the Canonical Item
- **WHEN** external related-item generation runs
- **THEN** the system records the failure or absence of suggestions, includes a brief related-papers-unavailable message in the Bot-Owned Note, and does not block Zotero sync or topic-label generation

**F-08.11: External related item not automatically imported**
- **GIVEN** an External Related Item has been suggested
- **WHEN** Zotero sync runs
- **THEN** the system does not create a Zotero library item for that external suggestion unless a Zotero Group Member or Bot Operator explicitly chooses to add it later

**F-08.6: Run generated similarity after sync**
- **GIVEN** a Canonical Item has synced to Zotero
- **WHEN** generated curation has been enabled after the first working Slack-to-Zotero implementation
- **THEN** the system immediately runs generated similarity for that item when enough metadata exists

**F-08.7: Minimal unresolved item similarity**
- **GIVEN** a minimal unresolved Canonical Item has title or description metadata
- **WHEN** generated curation has been enabled after the first working Slack-to-Zotero implementation
- **THEN** the system may immediately run generated similarity using the available title or description

**F-08.8: Plain sync before similarity**
- **GIVEN** generated similarity is not yet enabled
- **WHEN** a Canonical Item syncs to Zotero
- **THEN** the system syncs the item, collection membership, and Slack provenance without related-item suggestions

**F-08.14: Internal related items deferred**
- **GIVEN** plain Zotero sync and External Related Items are available
- **WHEN** internal related-item generation is not enabled
- **THEN** the system does not need to compute or show similar papers from the existing trial library

**F-08.3: Insufficient library size**
- **GIVEN** the library has too few comparable items
- **WHEN** generated curation runs
- **THEN** the system records that similarity output is unavailable rather than creating low-confidence suggestions

**F-08.4: Fewer than three comparable items**
- **GIVEN** a Canonical Item has comparable metadata and enough other items exist in the library
- **WHEN** fewer than three comparable items are available
- **THEN** the system writes only the comparable items that exist and records that fewer than three related items were available

**F-08.5: Similarity output becomes stale**
- **GIVEN** new items have been added since similarity output was last generated
- **WHEN** a Bot Operator explicitly refreshes generated curation
- **THEN** the system can refresh bot-generated similarity output without modifying human-authored Zotero content

#### F-08 External Related Papers: Semantic Scholar Implementation

Use Semantic Scholar Recommendations API as the first External Related Items source:

```text
GET https://api.semanticscholar.org/recommendations/v1/papers/forpaper/{paper_id}
```

Request at most five suggestions per source paper. Request useful display fields:

```text
title,url,authors,year,abstract,venue,externalIds,citationCount,fieldsOfStudy,publicationTypes,publicationDate,openAccessPdf
```

Use an optional Semantic Scholar API key when configured. Treat Semantic Scholar as unreliable: unavailable, rate-limited, missing IDs, empty responses, and malformed responses are expected operational states.

External related-paper generation constraints:

- **F-08.SC-01:** Related papers MUST be generated only after a Canonical Item has enough metadata or a stable identifier to query Semantic Scholar.
- **F-08.SC-02:** Related papers MUST be stored separately from factual item metadata and Slack provenance.
- **F-08.SC-03:** Related papers MUST be labeled as bot-generated external suggestions in every user-visible and Zotero-visible surface.
- **F-08.SC-04:** Related papers MUST NOT be automatically imported into Zotero as library items.
- **F-08.SC-05:** Related-paper failure MUST NOT block Slack ingestion, factual metadata enrichment, Zotero item creation, channel collection membership, or Slack provenance note updates.
- **F-08.SC-06:** The worker MUST NOT call Semantic Scholar on every page view or every worker loop for already-fresh suggestions.
- **F-08.SC-07:** The system MUST NOT store full Slack message text while generating or displaying related papers.
- **F-08.SC-08:** Bot-Owned Notes MUST contain human-useful suggestion details only. They MUST NOT contain Semantic Scholar raw payloads, stack traces, retry metadata, local database IDs, or secret-bearing errors.
- **F-08.SC-09:** Suggested papers MAY include abstracts locally for operator review, but Zotero `Bot notes` SHOULD keep suggestions compact: title, authors, year, venue if available, Semantic Scholar URL, and stable identifiers if available.
- **F-08.SC-10:** The first implementation SHOULD prefer a simple deterministic worker flow over LLM ranking or explanation.

Identifier strategy:

- **F-08.ID-01:** For a Semantic Scholar source item, query recommendations using the stored Semantic Scholar paper ID.
- **F-08.ID-02:** For an arXiv source item, query recommendations using `ArXiv:<arxiv-id>`.
- **F-08.ID-03:** For a DOI source item, query recommendations using `DOI:<doi>`.
- **F-08.ID-04:** If Semantic Scholar rejects the identifier, the system records related-paper generation as unavailable for that Canonical Item.
- **F-08.ID-05:** The system MAY later add a metadata lookup step to discover a Semantic Scholar paper ID for items that only have title, URL, PMID, OpenAlex ID, or publisher metadata.

Data model requirements:

- source Canonical Item ID
- recommendation source, initially `semantic_scholar`
- recommendation status: `pending`, `ready`, `unavailable`, or `failed`
- recommendation error, redacted before display
- fetch attempt count
- next retry timestamp
- last fetched timestamp
- source query identifier used with Semantic Scholar
- suggested paper identifier from Semantic Scholar
- suggested title
- suggested authors
- suggested year or publication date
- suggested venue
- suggested URL
- suggested abstract when available
- suggested external IDs, such as DOI or arXiv
- suggested citation count when available
- suggested fields of study or publication types when available
- suggestion rank

Uniqueness requirements:

- **F-08.DM-01:** A source Canonical Item MUST NOT store duplicate related suggestions for the same Semantic Scholar paper ID.
- **F-08.DM-02:** Re-running generation for the same source item SHOULD update existing suggestion rows rather than append duplicate rows.
- **F-08.DM-03:** If a suggestion later becomes a Canonical Item through normal Slack ingestion, the suggestion record MAY link to that Canonical Item, but the first implementation does not need to do this.

Queueing related-paper generation:

**F-08.15: Queue after successful Zotero sync**
- **GIVEN** a Canonical Item has synced to Zotero
- **AND** related-paper generation is enabled
- **AND** the item has a Semantic Scholar-recognized identifier
- **WHEN** worker processing completes the Zotero sync
- **THEN** the system marks related-paper generation pending for that item

**F-08.16: Do not queue when disabled**
- **GIVEN** related-paper generation is disabled
- **WHEN** a Canonical Item syncs to Zotero
- **THEN** the system does not call Semantic Scholar and does not add related-paper content to `Bot notes`

**F-08.17: Do not queue private-only items**
- **GIVEN** a Canonical Item has only private-channel Slack Mentions
- **WHEN** related-paper generation is considered
- **THEN** the system does not generate or sync related-paper suggestions for that item during the trial

**F-08.18: Explicit operator refresh**
- **GIVEN** related-paper suggestions already exist for an item
- **WHEN** a Bot Operator explicitly refreshes related papers
- **THEN** the system may mark generation pending again even if suggestions are otherwise fresh

Fetching related papers:

**F-08.19: Fetch recommendations**
- **GIVEN** an item has pending related-paper generation
- **AND** the item has a Semantic Scholar-recognized query identifier
- **WHEN** the worker calls Semantic Scholar
- **THEN** the system stores up to five recommendations with rank and display metadata

**F-08.20: Filter self-recommendations**
- **GIVEN** Semantic Scholar returns the source paper as a recommendation
- **WHEN** suggestions are stored
- **THEN** the source paper is excluded from the suggestion list

**F-08.21: Fewer than five suggestions**
- **GIVEN** Semantic Scholar returns fewer than five recommendations
- **WHEN** suggestions are stored
- **THEN** the system stores the available suggestions and records the generation status as `ready`

**F-08.22: Empty recommendations**
- **GIVEN** Semantic Scholar recognizes the source paper but returns no recommendations
- **WHEN** generation runs
- **THEN** the system records the status as `unavailable` with a human-safe reason

**F-08.23: Source paper not found**
- **GIVEN** Semantic Scholar cannot find the source paper
- **WHEN** generation runs
- **THEN** the system records the status as `unavailable` and does not retry aggressively

**F-08.24: Temporary failure**
- **GIVEN** Semantic Scholar is down, rate-limited, times out, or returns malformed data
- **WHEN** generation runs
- **THEN** the system records the status as `failed`, increments attempts, stores a redacted error, and schedules retry with backoff

Syncing related papers into Zotero `Bot notes`:

**F-08.25: Include ready suggestions**
- **GIVEN** a Canonical Item has ready related-paper suggestions
- **WHEN** Zotero `Bot notes` are rendered
- **THEN** the note includes a separate section titled `Related papers (bot-generated via Semantic Scholar)`

**F-08.26: Suggestion display format**
- **GIVEN** a related-paper suggestion has title, authors, year, venue, URL, and stable identifiers
- **WHEN** the note is rendered
- **THEN** the suggestion includes title, compact author list, year, venue if available, a link, and DOI/arXiv ID if available

**F-08.27: Mark suggestions as generated**
- **GIVEN** related-paper suggestions appear in Zotero
- **WHEN** a Zotero Group Member reads the note
- **THEN** the note makes clear that the suggestions are bot-generated and sourced from Semantic Scholar

**F-08.28: Unavailable message**
- **GIVEN** related-paper generation is unavailable or failed
- **WHEN** Zotero `Bot notes` are rendered
- **THEN** the note may include a short human-safe message such as `Related papers unavailable from Semantic Scholar.`

**F-08.29: Do not expose debug details**
- **GIVEN** related-paper generation has failed
- **WHEN** Zotero `Bot notes` are rendered
- **THEN** the note does not include stack traces, raw API errors, retry details, local sync IDs, or credentials

**F-08.30: Preserve Slack provenance**
- **GIVEN** related-paper suggestions exist
- **WHEN** Zotero `Bot notes` are updated
- **THEN** the note still includes all public Slack share history and does not remove previous provenance entries

Local operator visibility:

**F-08.31: Status counts**
- **GIVEN** related-paper generation work exists
- **WHEN** a Bot Operator opens `/status`
- **THEN** the operator can see counts for pending, ready, unavailable, and failed related-paper generation

**F-08.32: Failed work list**
- **GIVEN** related-paper generation has failed for one or more items
- **WHEN** a Bot Operator opens `/status`
- **THEN** the operator can see affected item titles, redacted failure summaries, and next retry times

**F-08.33: Retry failed related papers**
- **GIVEN** related-paper generation failed for an item
- **WHEN** a Bot Operator clicks retry
- **THEN** the system marks related-paper generation pending and eligible for worker pickup

**F-08.34: Detail page review**
- **GIVEN** related-paper suggestions exist for an item
- **WHEN** an authenticated viewer opens the local paper detail page
- **THEN** the page may show suggestions separately from factual metadata and Slack mentions

Manual import is deferred:

**F-08.35: Do not auto-import suggestions**
- **GIVEN** a related-paper suggestion is stored
- **WHEN** Zotero sync runs
- **THEN** the system does not create a Zotero item for that suggestion automatically

**F-08.36: Future explicit import**
- **GIVEN** a Bot Operator later chooses to import a suggestion
- **WHEN** manual import is implemented
- **THEN** the imported item should enter the same channel collection as the source paper and be marked as manually accepted

Manual import is not required for the first related-paper implementation.

Recommended first worker sequence:

1. Metadata refresh.
2. Zotero item/collection/provenance sync.
3. Related-paper generation for eligible synced items.
4. Zotero note refresh for items whose related-paper output changed.
5. Slack catch-up.

The implementation may use a different sequence if it preserves these guarantees:

- related-paper failure does not block Zotero item creation
- new related-paper output eventually appears in `Bot notes`
- stable items are not refreshed forever without new work or an explicit operator action

Suggested configuration:

- `RELATED_PAPERS_ENABLED=false` by default unless the operator enables the feature
- `RELATED_PAPERS_LIMIT=5`
- `RELATED_PAPERS_RETRY_LIMIT` optional
- `SEMANTIC_SCHOLAR_API_KEY` optional
- `SEMANTIC_SCHOLAR_RECOMMENDATION_POOL=recent` by default, with `all-cs` as an optional alternative for computer-science-only trials

Related-paper test scenarios:

- Unit test Semantic Scholar query ID selection for arXiv, DOI, and Semantic Scholar source items.
- Unit test parsing recommendation responses with full metadata, missing authors, missing venue, missing URL, and external IDs.
- Unit test filtering out a self-recommendation.
- Unit test retry/backoff behavior for temporary Semantic Scholar failures.
- Unit test `unavailable` behavior for not-found and empty recommendation responses.
- Integration test worker path: synced item -> related suggestions stored -> Zotero note refreshed.
- Integration test that related-paper failure does not block Zotero item sync.
- Web test status counts and retry route for failed related-paper generation.
- Web/detail test related suggestions are shown separately from factual metadata.
- Zotero note rendering test includes ready suggestions, labels them bot-generated, and excludes debug details.
- Regression test suggestions are not auto-created as Zotero items.

### F-09: Generated Topic Labels and Tags | SHOULD

**Requires:** F-08 (Generated Similarity Structure)

**F-09.1: Suggest topic labels**
- **GIVEN** a group of related items has enough metadata for generated curation
- **WHEN** topic labeling runs
- **THEN** the system suggests human-readable topic labels and marks them as bot-generated

**F-09.2: Suggest searchable tags**
- **GIVEN** a Canonical Item has enough metadata for generated curation
- **WHEN** tag suggestion runs
- **THEN** the system writes up to eight topic, method, or application tags to Zotero as Bot-Owned Tags using the `auto:` prefix, reusing Known Vocabulary terms when a suitable match exists and otherwise generating tags from factual metadata and external scholarly metadata

**F-09.3: Generated label uncertainty**
- **GIVEN** the system cannot produce a confident label or tag
- **WHEN** topic labeling or tag suggestion runs
- **THEN** the system leaves the item unlabeled or marks the output as low-confidence rather than presenting it as canonical

**F-09.4: Human correction**
- **GIVEN** a Zotero Group Member edits or removes a generated tag or label
- **WHEN** sync or refresh runs again for that item because of a new Slack Mention, failed job retry, metadata correction, or explicit Bot Operator action
- **THEN** the system treats removal as a rejection for that item and does not re-add the exact same Bot-Owned Tag to that item

**F-09.5: Too many generated tags**
- **GIVEN** generated curation produces more than eight candidate tags for an item
- **WHEN** Zotero sync writes Bot-Owned Tags
- **THEN** the system writes only the eight highest-ranked tags and does not write the rest

**F-09.6: Run generated tags after sync**
- **GIVEN** a Canonical Item has synced to Zotero
- **WHEN** generated tags have been enabled after external related-item generation works
- **THEN** the system immediately runs generated tag suggestion for that item when enough metadata exists

**F-09.7: Empty known vocabulary**
- **GIVEN** the trial has no Known Vocabulary configured
- **WHEN** tag suggestion runs
- **THEN** the system generates free-form Bot-Owned Tags without failing or requiring a vocabulary

**F-09.8: Minimal unresolved item tags**
- **GIVEN** a minimal unresolved Canonical Item has title or description metadata
- **WHEN** generated tags have been enabled after external related-item generation works
- **THEN** the system may immediately generate Bot-Owned Tags using the available title or description

**F-09.9: External related items before generated tags**
- **GIVEN** generated tags are not yet enabled
- **WHEN** a Canonical Item syncs to Zotero
- **THEN** the system syncs the item, collection membership, and Slack provenance without Bot-Owned Tags

**F-09.10: Rule-based generated tags**
- **GIVEN** factual metadata or external scholarly metadata includes categories, fields of study, venue, paper type, or other structured descriptors
- **WHEN** tag suggestion runs without an LLM
- **THEN** the system may create Bot-Owned Tags from those structured descriptors using deterministic rules

### F-10: Local Operator and Review Surface | SHOULD

**Requires:** F-01 (Opted-In Slack Channel Capture), F-04 (Zotero Group Library Item Sync)

**F-10.1: View sync status**
- **GIVEN** a Bot Operator opens the local status surface
- **WHEN** sync work exists
- **THEN** the operator can see counts for pending, successful, and failed Slack ingestion, metadata enrichment, Zotero sync, and generated curation work

**F-10.2: Retry failed work**
- **GIVEN** a sync, metadata, or generated curation job has failed
- **WHEN** a Bot Operator retries it
- **THEN** the system attempts the work again and records the new outcome

**F-10.3: Review generated curation**
- **GIVEN** generated curation has been created
- **WHEN** the operator reviews the item
- **THEN** the system shows generated outputs separately from factual metadata and Slack provenance

**F-10.4: Unauthorized local access**
- **GIVEN** a person without trial access opens the local operator or review surface
- **WHEN** they attempt to view archive data
- **THEN** the system denies access

**F-10.5: Shared-password operator access**
- **GIVEN** a person has the shared trial password
- **WHEN** they open the local operator or review surface
- **THEN** the system grants access to status, retry, and review information for the trial

**F-10.6: Optional item-level dry-run sync**
- **GIVEN** a Bot Operator selects a Canonical Item for preview
- **WHEN** they run dry-run sync
- **THEN** the system may show the Zotero item metadata, collection membership, Bot-Owned Note content, Bot-Owned Tags, generated curation, and provenance that would be written without changing Zotero

**F-10.7: Execute real Zotero sync**
- **GIVEN** Zotero credentials are configured and a Canonical Item has syncable metadata
- **WHEN** real sync runs
- **THEN** the system writes the item, channel collection membership, Bot-Owned Note, Bot-Owned Tags, generated curation, and provenance to Zotero and records the sync outcome

**F-10.8: Secondary local archive search**
- **GIVEN** the local app has stored Canonical Items and Slack Mentions
- **WHEN** an Archive Viewer or Bot Operator opens the secondary archive search view
- **THEN** the system may provide search, date filtering, source filtering, and semantic title or abstract search across the local archive without replacing Zotero as the primary shared collection

### F-11: Trial Privacy and Access Boundaries | MUST

**F-11.1: Public-channel eligibility check**
- **GIVEN** a Slack channel is private
- **WHEN** the bot considers the channel for event ingestion, backfill, catch-up, or Zotero sync
- **THEN** the system excludes that channel from the first trial

**F-11.2: Public-channel Zotero visibility check**
- **GIVEN** the configured Zotero group library is accessible to a defined set of Zotero Group Members
- **WHEN** the bot is configured for sync
- **THEN** the Bot Operator can confirm that public-channel items, collection membership, and provenance notes may sync to that library

**F-11.3: Credential secrecy**
- **GIVEN** Slack and Zotero credentials are configured
- **WHEN** status pages, logs, errors, or sync notes are generated
- **THEN** credentials and secrets are never displayed

**F-11.4: Permission revocation**
- **GIVEN** the Slack app, Zotero credentials, or Zotero group access is revoked
- **WHEN** the system attempts future ingestion or sync
- **THEN** it stops the affected operation, records the failure, and does not delete previously synced Zotero content unless explicitly instructed

### F-12: Explicit Non-Goals for Trial | WON'T (this milestone)

**F-12.1: No Slack chatbot**
- **GIVEN** a Slack user asks the bot a question in Slack
- **WHEN** the message is received
- **THEN** the system does not answer as a chatbot

**F-12.2: No PDF full-text processing**
- **GIVEN** an item has a PDF URL
- **WHEN** metadata or curation runs
- **THEN** the system does not download or process the full PDF during this trial

**F-12.3: No automatic Slack posting**
- **GIVEN** an item is ingested, synced, clustered, tagged, or fails processing
- **WHEN** the event occurs
- **THEN** the system does not post into Slack

**F-12.4: No Semble sync**
- **GIVEN** an item is ingested or synced to Zotero
- **WHEN** downstream sync runs
- **THEN** the system does not create or update Semble cards or collections during this trial

**F-12.5: No pre-existing Zotero import**
- **GIVEN** the configured Zotero group library starts empty or has no lab-wide existing collection to import
- **WHEN** the trial begins
- **THEN** the system does not require a one-time import of existing Zotero items for the trial to function

**F-12.6: No general webpage collection**
- **GIVEN** a Slack message contains a news article, blog post, ResearchGate page without a stable scholarly identifier, or unrelated webpage
- **WHEN** the link is processed
- **THEN** the system does not create a Zotero Web Item during the first trial

**F-12.7: No concurrent multi-workspace operation**
- **GIVEN** the Slack app can be authorized by more than one workspace
- **WHEN** the trial application runs
- **THEN** it does not concurrently ingest, backfill, catch up, or sync content for more than one Slack workspace

### F-13: Slack OAuth Workspace Installation | MUST

**Requires:** F-01 (Opted-In Slack Channel Capture), F-02 (Historical Backfill and Catch-Up), F-11 (Trial Privacy and Access Boundaries)

**F-13.1: Begin workspace authorization**
- **GIVEN** a prospective installer opens the app's Slack installation entry point
- **WHEN** the installation request is valid
- **THEN** the installer is sent to Slack to approve only the bot permissions required for opted-in public-channel capture, channel lookup, and user lookup

**F-13.2: Approve workspace installation**
- **GIVEN** Slack has approved the requested permissions for a workspace
- **WHEN** Slack returns a valid, unexpired authorization response
- **THEN** the system records that workspace as the single Slack Installation, leaves it inactive pending operator activation, and shows the installer a clear completion result without exposing credentials
- **AND** authorization remains valid when Slack grants additional bot permissions beyond the required set, while any missing required permission is reported by name

**F-13.3: Cancel or deny authorization**
- **GIVEN** an installer cancels authorization, denies permissions, or Slack rejects the request
- **WHEN** the installer returns to the application
- **THEN** the system shows a human-safe failure result and does not create, activate, or replace a Slack Installation

**F-13.4: Reject invalid authorization state**
- **GIVEN** an authorization response has missing, mismatched, reused, or expired request state
- **WHEN** the system receives the response
- **THEN** the system rejects it without exchanging credentials or changing any existing Slack Installation

**F-13.5: Authorization exchange unavailable**
- **GIVEN** Slack is unavailable, times out, or rejects an otherwise valid authorization exchange
- **WHEN** installation completion is attempted
- **THEN** the system reports that installation did not complete, records a credential-free diagnostic outcome, and leaves existing installations unchanged

**F-13.6: Reinstall an existing workspace**
- **GIVEN** the currently recorded Slack workspace successfully authorizes the app again
- **WHEN** authorization completes
- **THEN** the system updates that installation's current credentials, granted permissions, and bot identity without creating a duplicate installation
- **AND** it preserves the prior active status only when all required permissions and Trial Zotero Destination access remain valid; otherwise it becomes inactive

**F-13.7: Duplicate or concurrent authorization callbacks**
- **GIVEN** Slack delivers the same successful authorization response more than once or completion attempts overlap
- **WHEN** the responses are processed
- **THEN** at most one Slack Installation exists and a valid newer installation is not overwritten by an older response

**F-13.8: Installation awaits activation**
- **GIVEN** a workspace has completed authorization
- **WHEN** the Trial Zotero Destination has not been configured or a Bot Operator has not activated the installation
- **THEN** the installation remains inactive and the system does not ingest events, run backfill or catch-up, or sync that workspace's content to Zotero

**F-13.9: Activate an authorized workspace**
- **GIVEN** an authorized workspace exists and the Trial Zotero Destination is configured
- **WHEN** a Bot Operator activates the Slack Installation
- **THEN** the installation becomes eligible for opted-in public-channel ingestion, enrichment, backfill, catch-up, and Zotero sync

**F-13.10: Receive event from active installation**
- **GIVEN** Slack sends a valid event for an active Slack Installation
- **WHEN** the event belongs to an opted-in public channel
- **THEN** the system processes it using that workspace's installation context and preserves the workspace identity on resulting channel, user, mention, and sync records

**F-13.11: Receive event from unknown or inactive workspace**
- **GIVEN** Slack sends a correctly signed event for a workspace with no active Slack Installation
- **WHEN** the event is received
- **THEN** the system performs no ingestion or enrichment, does not fall back to another workspace's credentials, and records a credential-free operator diagnostic

**F-13.12: Run workspace-specific catch-up and backfill**
- **GIVEN** one Active Slack Installation exists
- **WHEN** catch-up or operator-requested backfill runs
- **THEN** only eligible channels belonging to that active workspace are read using its credential

**F-13.13: Preserve public-channel scope**
- **GIVEN** a Slack Installation is active
- **WHEN** the system discovers events or channels outside the trial's public-channel boundary
- **THEN** it excludes private channels, direct messages, group direct messages, and channels where the bot is not opted in

**F-13.14: Installation credential revoked**
- **GIVEN** Slack revokes or invalidates an installation credential or the app is uninstalled from a workspace
- **WHEN** the system next receives revocation information or attempts Slack access
- **THEN** it marks the installation inactive, stops future Slack reads for that workspace, preserves previously ingested records and Zotero content, and exposes a credential-free operator status

**F-13.15: Deactivate installation manually**
- **GIVEN** a Slack Installation is active
- **WHEN** a Bot Operator deactivates it
- **THEN** new event ingestion, enrichment, catch-up, and backfill stop for that workspace without deleting prior records or previously synced Zotero content

**F-13.16: Review installation status**
- **GIVEN** a Slack Installation has been attempted
- **WHEN** an authenticated Bot Operator reviews installation status
- **THEN** the system shows workspace identity, active or inactive status, granted permission names, bot identity, installation time, and human-safe failures without exposing credentials

**F-13.17: Existing development-workspace credential**
- **GIVEN** the development workspace currently uses a manually configured bot credential
- **WHEN** OAuth workspace installation becomes the supported trial path
- **THEN** the development workspace is reauthorized through the same OAuth flow and verified before the manually configured credential path is removed

**F-13.18: Use one trial Zotero destination**
- **GIVEN** the Active Slack Installation is eligible for processing
- **WHEN** a Canonical Item, Channel Collection, Bot-Owned Note, or generated curation output is synced
- **THEN** the system writes it only to the configured Trial Zotero Destination

**F-13.19: Missing or invalid Zotero destination**
- **GIVEN** the Trial Zotero Destination is missing or its Zotero access has been revoked
- **WHEN** activation or Zotero sync is attempted
- **THEN** the installation cannot become newly active, or its Zotero sync pauses if already active, and no alternative Zotero destination is used as a fallback

**F-13.20: Reject an unexpected second workspace**
- **GIVEN** a Slack Installation is already recorded
- **WHEN** a different Slack workspace attempts authorization without an explicit operator-approved replacement
- **THEN** the system rejects the replacement, preserves the current installation and credentials, and shows a human-safe explanation

**F-13.21: Replace the installed workspace**
- **GIVEN** a Bot Operator intends to move the trial from the test workspace to Mila
- **WHEN** the operator explicitly approves replacement and Mila successfully completes authorization
- **THEN** Mila becomes the single inactive Slack Installation, the former workspace credential is no longer used, prior archive records are preserved, and Mila still requires activation before processing begins

**F-13.22: Ordinary archive reset**
- **GIVEN** a Bot Operator resets papers, mentions, channels, metadata, or sync state during development
- **WHEN** the ordinary archive reset completes
- **THEN** the Slack Installation, its active or inactive status, and the Trial Zotero Destination remain available

**F-13.23: Explicit full reset**
- **GIVEN** a Bot Operator intentionally requests a full reset that includes credentials
- **WHEN** the operator confirms and completes that reset
- **THEN** the Slack Installation and Trial Zotero Destination are removed, archive data is handled according to the reset request, and the system clearly reports that Slack must be authorized again

**F-13.24: Preserve replaced-workspace records as history**
- **GIVEN** the test workspace has been replaced by Mila
- **WHEN** normal ingestion, backfill, catch-up, metadata, or Zotero sync work runs
- **THEN** prior test-workspace records may remain available as historical local data but are not treated as Mila records or made eligible for new Mila processing

## Open Questions

- **OQ-01**: No blocking OAuth scope questions remain for the single-workspace trial.

## Assumptions

- **A-01**: Zotero is the primary visible library destination for the trial; the local web surface becomes operational/review tooling rather than the main archive.
- **A-02**: The trial supports arXiv links, DOI links, journal article links, and Semantic Scholar paper links. Web/news links are excluded unless they resolve to a stable scholarly identifier.
- **A-03**: Slack channel names are provenance, not a sufficient topic taxonomy.
- **A-04**: Generated curation is useful only if visibly marked as generated and kept separate from factual metadata.
- **A-05**: Semble and zemble are not part of the first Zotero-integrated trial.
- **A-06**: Private Slack channels are excluded from the first Zotero-integrated trial.
- **A-07**: The bot creates one Zotero collection per opted-in public Slack channel.
- **A-08**: Generated curation remains in the full trial spec but should be implemented after plain Slack-to-Zotero sync works.
- **A-09**: Generated curation may eventually be written to Zotero during the trial, but it is not part of the first working Slack-to-Zotero implementation.
- **A-10**: The bot may refresh factual Zotero item fields from source metadata.
- **A-11**: Generated topic tags are written as real Zotero tags with a bot-owned naming convention.
- **A-12**: Internal Related Items are deferred; the first related-paper feature should suggest External Related Items from broader literature.
- **A-13**: Bot-Owned Tags use the `auto:` prefix.
- **A-14**: The Bot-Owned Note contains human-useful content only: generated related items when available, generated tags when available, and Slack shares. Debug details stay local.
- **A-15**: Anyone with the shared trial password can access the local operator and review surface.
- **A-16**: If a Zotero Group Member removes a Bot-Owned Tag from an item, the bot treats that exact tag as rejected for that item and does not re-add it.
- **A-17**: The bot writes up to eight generated `auto:` tags per item.
- **A-18**: Zotero channel collections use raw Slack channel names.
- **A-19**: No pre-existing Zotero import is required for the first lab trial because there is no existing lab Zotero library.
- **A-20**: ResearchGate links become Scholarly Items only when a stable scholarly identifier can be extracted; otherwise they are unsupported during the first trial.
- **A-21**: The Bot-Owned Note title is `Bot notes`.
- **A-22**: For journal, publisher, repository, and Semantic Scholar pages, the system tries Zotero translators first and falls back to external scholarly metadata APIs.
- **A-23**: If a Scholarly-Looking Link cannot fully resolve but has at least a title or URL, the system creates a minimal Zotero item.
- **A-24**: Generated tags use a rule-based strategy first: reuse Known Vocabulary terms when possible and otherwise derive `auto:` tags from factual metadata or external scholarly metadata.
- **A-25**: After generated curation is enabled, it runs after each item syncs to Zotero when enough metadata exists, but later refreshes are triggered only by explicit Bot Operator action.
- **A-26**: Minimal unresolved Scholarly-Looking Links use Zotero journal article type when they look paper-like and Zotero webpage type otherwise.
- **A-27**: Minimal unresolved items receive generated curation immediately when title or description metadata exists.
- **A-28**: Bot-Owned Tag removal is detected only when sync or refresh runs for a concrete reason; stable items are not repeatedly resynced in normal operation.
- **A-29**: The trial starts with an empty Known Vocabulary.
- **A-30**: The first working milestone is a Slack arXiv link syncing into Zotero with channel collection membership and Slack provenance in `Bot notes`.
- **A-31**: Real Zotero sync is more important than dry-run sync because the Bot Operator can test against a personal or trial Zotero library. If dry-run exists, item-level preview is sufficient for the trial.
- **A-32**: Existing Slack ingestion, backfill, authentication, status, and local persistence behavior may be reused where it helps, while the local archive UI is repositioned as secondary/fallback rather than the primary product surface.
- **A-33**: Zotero writes should happen immediately during normal sync and rely on recorded failures plus retry behavior rather than operator approval or batch approval.
- **A-34**: Secondary local archive search should remain available to trial viewers when it can run on the same deployment without complicating operations.
- **A-35**: Zotero channel collections are created lazily, when the first supported item from that opted-in channel syncs.
- **A-36**: Unsupported links from opted-in public channels should be visible to Archive Viewers and Bot Operators in the local surface, without creating Zotero items for them.
- **A-37**: External Related Items are useful because they can surface broader literature beyond what lab members have already shared, but they should be visually distinct from Internal Related Items.
- **A-38**: External Related Items should be suggestions only and should not create Zotero items automatically during the trial.
- **A-39**: External Related Items should appear in Zotero `Bot notes`.
- **A-40**: A later manual "add to Zotero" action for External Related Items is useful, but automatic import is not desired.
- **A-41**: Each item should show up to five External Related Items in Zotero `Bot notes`.
- **A-42**: External Related Items should be implemented before rule-based generated tags.
- **A-43**: A manually imported External Related Item should be added to the same Channel Collection as the item it was suggested from.
- **A-44**: If external related papers are unavailable, the Bot-Owned Note should say that related papers are unavailable rather than silently omitting the section.
- **A-45**: The trial supports exactly one Slack Installation and one Active Slack Installation at a time.
- **A-46**: A newly authorized workspace remains inactive until a Bot Operator configures the Trial Zotero Destination and activates it.
- **A-47**: Events and background reads from an unknown, replaced, or inactive workspace are ignored without falling back to another credential.
- **A-48**: Reauthorization of the currently recorded workspace updates its installation idempotently and does not create duplicate records.
- **A-49**: Previously ingested records and Zotero content are preserved when a Slack Installation is deactivated, revoked, or uninstalled.
- **A-50**: The existing manually configured development-workspace credential remains available only until the test workspace is successfully reauthorized and verified through OAuth, after which the manual credential path is removed.
- **A-51**: The test workspace is explicitly replaced by Mila after OAuth verification rather than remaining concurrently active.
- **A-52**: The trial uses one configured Trial Zotero Destination because no pre-existing Mila Zotero library needs isolation during the initial local trial.
- **A-53**: Ordinary archive resets preserve Slack authorization and the Trial Zotero Destination; only an explicit full reset removes them.
