# Review a Kinocut cut on a Hermes Gadget TV

Pair the TV in Hermes and confirm that `gadget_devices` reports `ui.show_media`.
No TV app change, listener, discovery, or upload is performed by Kinocut.

1. Prepare the review with `kinocut.tv_preview.prepare_tv_review_payload`.
   Give it the cut path and, optionally, an existing QC sheet from the review
   workflow. Otherwise it writes a JPEG contact sheet with six samples. It
   reuses video at or below 1080 pixels high (or copies it to a requested
   output path), and publishes an H.264/AAC MP4 proxy for taller video.
2. Publish **only those exact artifacts** through an authorized media host the
   TV can reach. Bind their HTTP(S) URLs with `tv_review_messages`. The helper
   does not infer URLs from filesystem paths; do not send the drafts with null
   URLs or substitute the original high-resolution cut.
3. Send the resulting `ui.show_media` requests with `gadget_action` to the
   paired TV, one at a time. Let the reviewer see both the QC image and video
   before asking for a decision. If the TV declares choice support, pass
   `decision_card` (`title` and `options`) to `gadget_ask`. On a TV that instead
   returns `APPROVE` / `REJECT` chat replies, require a reply from the paired TV
   that matches the active video review caption; map only those replies to the
   two options. Use a unique caption for each review. If the TV cannot open the
   URLs or return a decision, use the Hermes Desktop review card instead.
4. **Approve & export:** run `video_release_checkpoint` on the reviewed cut,
   then `video_export` only if the checkpoint passes. **Try another range:**
   ask for or propose a different range without exporting. A playback
   acknowledgement, timeout, or unrecognized reply is not an approval.

```python
from kinocut.tv_preview import prepare_tv_review_payload, tv_review_messages

review = prepare_tv_review_payload("cut.mp4", caption="Interview cut — review 03")
# After publishing review["proxy_path"] and review["qc_sheet_path"]:
messages = tv_review_messages(review, proxy_url=hosted_video_url, qc_sheet_url=hosted_sheet_url)
# Each message has action="ui.show_media" and args with url, kind, caption.
```
