# Review a Kinocut cut on a Hermes Gadget TV

Pair the TV in Hermes and confirm that `gadget_devices` reports `ui.show_media`.
No TV app change, listener, discovery, or upload is performed by Kinocut.

1. Prepare the review with `kinocut.tv_preview.prepare_tv_review_payload`.
   Give it the cut path and, optionally, an existing QC sheet from the review
   workflow. Otherwise it writes a JPEG contact sheet with six samples. It
   reuses square-pixel video that fits within 1920×1080 (or copies it to a
   requested output path). Otherwise it writes a square-pixel H.264/AAC MP4
   proxy that fits within those bounds while preserving the display aspect ratio.
2. Publish **only those exact artifacts** through an authorized media host the
   TV can reach. Bind their HTTP(S) URLs with `tv_review_messages`. The helper
   does not infer URLs from filesystem paths; do not send the drafts with null
   URLs or substitute the original high-resolution cut. Use immutable hosted
   URLs for each review so an old TV request cannot play a newer revision.
3. Send the resulting `ui.show_media` requests with `gadget_action` to the
   paired TV, one at a time. Let the reviewer see both the QC image and video
   before asking for a decision. If the TV declares choice support, pass
   `decision_card` (`title` and `options`) to `gadget_ask`. On a TV that instead
   returns chat replies, require `APPROVE <review_id>` or `REJECT <review_id>`
   from the paired TV. Both the card title and chat caption include the unique
   ID and the cut's SHA-256 prefix. Bind a choice response to its originating
   card's ID; never substitute the newest review ID for a missing or old ID.
   If the TV cannot open the URLs or return a decision, use the Hermes Desktop
   review card instead.
4. Normalize the paired-TV decision to `APPROVE` or `REJECT` and pass it with
   its ID to `consume_tv_review_decision` **in the same Python process that
   prepared the review**. The helper consumes each ID once and checks the cut,
   proxy, and QC sheet digests before returning the approved cut path. Unknown,
   replayed, or stale approvals never authorize export. If approval returns a
   path, run `video_release_checkpoint` on that exact cut, then `video_export`
   only if the checkpoint passes. Keep the cut unchanged through export.
   Rejection returns no path: propose another range without exporting. A playback
   acknowledgement, timeout, or unrecognized reply is not an approval.

```python
from kinocut.tv_preview import consume_tv_review_decision, prepare_tv_review_payload, tv_review_messages

review = prepare_tv_review_payload("cut.mp4", caption="Interview cut — review 03")
# After publishing review["proxy_path"] and review["qc_sheet_path"]:
messages = tv_review_messages(review, proxy_url=hosted_video_url, qc_sheet_url=hosted_sheet_url)
# Each message has action="ui.show_media" and args with url, kind, caption.
# After receiving a recognized decision from the paired TV:
approved_cut = consume_tv_review_decision(response_review_id, response_decision)
```
