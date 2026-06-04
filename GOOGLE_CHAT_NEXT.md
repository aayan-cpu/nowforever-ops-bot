# Google Chat Live Integration Plan

## V1 local brain
Already built here:
- ingest Vault messages
- classify messages
- create tasks
- summarize rooms

## V2 Google Chat app
Add endpoints:

```text
POST /google-chat/events
POST /google-chat/command
```

Events to support:

```text
MESSAGE
ADDED_TO_SPACE
CARD_CLICKED
```

Bot commands:

```text
/ops dashboard
/ops tasks
/ops tasks 4 Channelview
/ops alerts
/ops report today
/ops close <task_id>
/ops assign <task_id> @person
```

## V3 Auto watchers
Scheduled jobs:

```text
8:00 AM  morning dashboard
12:00 PM unresolved urgent reminder
8:30 PM missing reports reminder
9:15 PM CEO daily summary
instant high priority alerts
```

## V4 Image/OCR math verifier
Pipeline:

```text
Google Chat attachment
  -> download image
  -> AI vision/OCR extracts structured values
  -> Python recomputes totals/differences
  -> confidence score
  -> if mismatch or low confidence, create high-priority review task
```

Example BOL/Veeder check:

```json
{
  "room": "4 Channelview",
  "bol_gallons": 8666,
  "veeder_gallons": 6166,
  "difference": 2500,
  "status": "needs_review"
}
```
