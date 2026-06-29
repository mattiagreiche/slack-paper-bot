# Domain Glossary

## Actors

**Slack Sharer**
A Slack workspace member who posts a supported link in a monitored Slack channel.
*Cannot:* manually alter archived metadata, approve generated curation, configure Zotero destinations, or access data from channels they cannot see in Slack.

**Archive Viewer**
A lab member or approved collaborator who can view the archived collection surface made available for the trial.
*Cannot:* change Slack monitoring settings, modify Zotero sync settings, or view private-channel provenance during the trial.

**Bot Operator**
The technical maintainer who configures Slack app settings, Zotero credentials, channel mappings, backfills, retries, and trial deployment settings.
*Cannot:* use the system to bypass Slack or Zotero access rules, expose private-channel activity to unauthorized viewers, or silently modify human-authored Zotero content.

**Zotero Group Member**
A person with access to the shared Zotero group library used for the trial.
*Cannot:* assume that bot-generated notes or tags are human-reviewed unless they are marked as reviewed.

**Slack Workspace Admin**
A person who can approve or install the Slack app and grant workspace permissions.
*Cannot:* define item curation behavior unless also acting as a Bot Operator or project stakeholder.

**Zotero Group Owner**
A person who owns or administers the Zotero group library and can grant bot write access.
*Cannot:* include private Slack channel provenance in the first trial.

**External Dependency**
Slack, Zotero, arXiv, DOI metadata providers, or any embedding/curation service used by the system.
*Cannot:* be assumed available, fast, correct, or stable at all times.

## Key Terms

**Supported Link**
A link that the system can recognize as a scholarly item worth adding to Zotero. During the trial, supported links include arXiv links, DOI links, journal article links, and Semantic Scholar paper links.

**Scholarly-Looking Link**
A link whose URL, domain, or page metadata suggests a scholarly item, including arXiv, DOI, Semantic Scholar, journal, publisher, repository, or academic profile pages.

**Known Vocabulary**
An optional curated list of lab, project, topic, method, or application terms that generated tags should reuse when possible. The first trial may start without a populated known vocabulary.

**Canonical Item**
The single internal representation of a Zotero item after duplicate URL variants and identifiers have been resolved.

**Slack Mention**
One occurrence of a Canonical Item being shared in a Slack channel, including channel, sharer, timestamp, and Slack permalink when available.

**Scholarly Item**
A Canonical Item representing a scholarly work, such as an arXiv preprint, DOI-backed article, Semantic Scholar paper, or journal article.

**Web Item**
A Canonical Item representing a non-scholarly or weakly structured webpage, such as a news article or a page without a stable scholarly identifier. Web Items are out of scope for the first trial unless the link resolves to a Scholarly Item.

**Opted-In Channel**
A public Slack channel that the bot has been invited to and that the trial policy treats as eligible for monitoring.

**Channel Collection**
A Zotero collection automatically created for one opted-in Slack channel.

**Topic Structure**
A generated cross-channel grouping or nearest-neighbor structure intended to surface items that are topically related beyond the Slack channel where they were shared.

**Related-Item Generation**
The generated curation task that finds scholarly items related to a given Canonical Item. This task may produce External Related Items from broader literature or, later, Internal Related Items from the trial library.

**Internal Related Item**
An existing Canonical Item already present in the trial library that is suggested as related to another Canonical Item.

**External Related Item**
A scholarly item outside the trial library that an external recommendation or discovery source suggests as related to a Canonical Item.

**Topic-Label Generation**
The generated curation task that produces human-readable topic labels or searchable tags for a Canonical Item or group of related Canonical Items.

**Generated Curation**
Any bot-created related-item suggestion, topic label, tag, cluster, explanation, or note that is inferred rather than imported from the item source or Slack.

**Bot-Owned Tag**
A generated Zotero tag whose name starts with `auto:` and clearly marks it as produced by the bot.

**Provenance Note**
A Zotero note attached to an item that records where it was shared in Slack and links back to the original Slack messages.

**Bot-Owned Note**
A Zotero note attached to an item that the system owns and may update. During the trial, this note contains Slack share history and generated curation.

**Rejected Generated Tag**
A Bot-Owned Tag that a Zotero Group Member removed from a specific item and that the bot must not re-add to that item.

**Sync State**
The system's record of whether a Canonical Item, Slack Mention, note, collection membership, or generated curation output has been successfully reflected in Zotero.

**Dry-Run Sync**
A preview of the Zotero item, collection membership, Bot-Owned Note, Bot-Owned Tags, generated curation, and provenance that would be written without changing Zotero.

**Real Sync**
A Zotero write operation that creates or updates items, collections, notes, tags, generated curation, or provenance in the configured Zotero group library.

**Secondary Archive Search**
A local search surface over stored Canonical Items and Slack Mentions that may support fallback discovery, debugging, or richer search than Zotero without replacing Zotero as the primary shared collection.

**Trial**
The initial limited deployment intended to test whether Slack-to-Zotero curation is useful for a small group before wider lab adoption.
