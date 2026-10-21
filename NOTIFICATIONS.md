# Telegram event delivery

Source version 3.3.4 adds a durable queue for application events: receiver and rover connections, receiver errors and service events sent through `app.notify.send`. Open **System settings → Notifications** to inspect delivery. Only administrators can read these counters or send a test message. Browser language and Telegram language remain independent.

## Delivery policy

- At most 200 pending or in-flight events. A full queue rejects new events and increments the overflow counter; it does not create more workers or replace an older important alert silently.
- One background worker per application, with a persistent SQLite lease for each attempt. No HTTP call holds a database transaction. Producers wait for a local write, not Telegram; SQLite contention times out after 50 ms. Write failures are logged and counted without raising into the caster.
- At most 8 HTTP attempts per event, within 30 minutes of queue time. Temporary network/server errors use delays of 5, 10, 20, 40, 80, 160 and 300 seconds. A Telegram `retry_after` can extend the delay and also holds subsequent events. Events expire instead of being delivered after their lifetime.
- A minimum of 3.1 seconds between event attempts accommodates a group destination. Other senders sharing the bot can still exhaust its limit; the queue then honors the returned delay. See Telegram's [limits](https://core.telegram.org/bots/faq#my-bot-is-hitting-limits-how-do-i-avoid-this) and [ResponseParameters](https://core.telegram.org/bots/api#responseparameters).
- Pending events with the same event key and destination are deduplicated. Successful delivery starts the caller's cooldown, preserved across restarts. Online and offline events keep separate keys. A delayed event cannot pass an older pending event, avoiding a late offline alert arriving after its recovery alert.
- Turning notifications or a category off cancels matching waiting events. Changing the token or chat cancels events for the previous destination instead of redirecting them. An HTTP request already in flight can finish using its previous settings. A temporary settings-database error pauses processing rather than treating all alerts as disabled.
- The worker uses the latest saved Telegram language. Events delayed at least one minute include their recorded UTC time. Event names are plain text and messages are bounded to Telegram's size limit.

A timeout or termination after Telegram accepts a message but before SQLite records success can cause a duplicate. A saved message is not proof of delivery, and an exhausted retry limit does not prove Telegram never received an earlier attempt. The interface shows pending, successful, failed, expired, cancelled and overflow totals separately.

## Storage and restart

The file is `/opt/gnss-caster/instance/notifications.sqlite`, accessible to the service account/group and root. It stores event text, hashes of the destination and deduplication key, attempt state and counters; it does not store the bot token or chat ID. API status excludes text, destination hashes and raw Telegram errors. Completed event text is removed; only the latest 200 terminal records are retained, plus up to 1,000 cooldown keys for up to a day. SQLite file growth is capped at 2,048 pages (normally 8 MiB).

An unfinished attempt becomes eligible after its 90-second lease. If the worker cannot start, the already-saved events stay queued; the next event or service startup retries worker creation. Storage or settings failures cause the worker to back off. Do not delete the database as a routine restart remedy: that would lose pending events and cooldown history.

Retry, expiry and cooldown timing uses a monotonic clock within the process and a saved high-water mark across restarts. A backward wall-clock correction cannot freeze delivery. If wall time moves backwards while the service is stopped, that stopped interval is conservatively not counted toward expiry; messages still expire within 30 minutes of processing time. Forward time changes across restarts can expire older events. Displayed event timestamps use wall time and therefore depend on the machine's clock.

The queue is operational state and is deliberately excluded from configuration backup archives and installation rollback snapshots. Restoring an old configuration does not import its old queue. The local queue remains subject to expiry and destination checks; a changed restored token/chat cancels mismatched pending events. Counters persist with this file. Local-write-failure counts are held in memory for the current service process because a failed storage device cannot reliably save its own failure counter.

## Separate channels and verification

Test messages and command replies remain synchronous with their existing result handling. The standalone backup script's notifications and archive uploads are also separate; this screen does not claim to track their delivery. Unifying those channels and persistent maintenance/audit jobs is further R11 work.

Automated tests use real temporary SQLite files, concurrent producers, simulated process interruption and mocked HTTP responses. Browser tests use local sample data in English and Russian. Real Telegram delivery, systemd startup, power loss and Raspberry Pi storage behavior require a separate authorized validation window; no live deployment is implied by merging this code.
