"""User-language aliases and one-line examples for the discovery catalog.

The discovery catalog is indexed for retrieval by operation name, verb,
family and description (``kinocut.tool_discovery`` and the router eval's
BM25 baseline both rank over those fields). The descriptions come from the
tool docstrings, which say what the code does — "render a composition",
"generate speech audio" — and not what a person asks for — "add motion
graphics", "record a voiceover". A request phrased in ordinary words then
cannot surface the operation that answers it.

This table closes that gap with one line of everyday words per operation,
appended to the description the catalog indexes. The lines are generic: each
describes a *kind* of job in the words people use for that kind of job, so
every consumer of the catalog benefits — a person reading ``list_operations``,
an agent searching with ``search_tools``, and a model ranking candidates. They
are not written for any particular request.

How the lines are written:

* The wording is taken from the vocabulary the product already publishes for
  users: the ``kino`` CLI help, the ``video_direct`` phrasing in
  ``kinocut.direct`` and the intent verbs in ``kinocut.intent.verbs``.
* Each line is attached by the operation's own name and verb, so it follows
  the operation it describes and cannot be applied to a neighbour.
* Where several operations do the same kind of job they share one line; the
  line never names one operation at another's expense.
* A line only carries words the operation's own description does not already
  carry, so it adds vocabulary instead of repeating it.

Nothing here changes what an operation does, its parameters or its schema.
"""

from __future__ import annotations

# One line per operation, keyed by operation name. Kept short on purpose: the
# catalog summary surfaces truncate a description's first line, and retrieval
# rewards vocabulary that is specific to the operation rather than prose.
OPERATION_ALIASES: dict[str, str] = {
    # --- projects and assets -------------------------------------------------
    "video_project_create": (
        "Start a new video project or production for a release announcement, "
        "a social video or any piece you want to build a cut from."
    ),
    "video_init_project": "Set up a fresh local project folder to start editing in.",
    "video_ingest": "Bring raw footage or source media into a project so you can work from it.",
    "video_extract_frame": "Grab one still frame or a thumbnail image out of a video.",
    "video_thumbnail": "Make a thumbnail or poster image for a video.",
    "video_storyboard": "Lay out the shots of a video as a storyboard.",
    "video_export_frames": "Export the frames of a video as a sequence of still images.",
    # --- repurposing long video into platform cuts ---------------------------
    "video_repurpose": (
        "Turn one long video into the short platform versions: an Instagram Reel, "
        "a TikTok, a YouTube Short and the other social cuts."
    ),
    "video_repurpose_plan": (
        "Plan how a long video becomes short platform versions such as an Instagram Reel, a TikTok or a YouTube Short."
    ),
    "video_shorts": "Cut a long video down into a short vertical clip for social platforms.",
    "video_resize": "Reframe or resize a video for vertical, square or widescreen platforms.",
    "video_convert": "Convert a video to another format, such as a web-friendly MP4.",
    # --- speech, voice and narration -----------------------------------------
    "hyperframes_tts": ("Record a voiceover or narration from a script, using a chosen voice or a voice clone."),
    "video_add_audio": "Add, replace or lay in an audio track, voice recording or music on a video.",
    "video_dub_plan": "Plan a dubbed version of a video in another language.",
    "sound_voice_batch": "Produce a batch of spoken voice lines from a script.",
    "video_ai_transcribe": "Transcribe the speech in a video into text.",
    "hyperframes_transcribe": "Transcribe speech from audio or video into text.",
    "video_generate_subtitles": "Generate subtitles or captions from the speech in a video.",
    "video_subtitles": "Burn subtitles or captions onto a video.",
    "video_subtitles_styled": "Burn styled subtitles or captions onto a video.",
    "video_translate_captions": "Translate subtitles or captions into another language.",
    "video_auto_chapters": "Split a video into chapters from its speech.",
    # --- music, beds and sound -----------------------------------------------
    "audio_synthesize": ("Generate a tone, noise or other waveform locally as a WAV file."),
    "video_add_generated_audio": (
        "Generate procedural sound (a drone, tones or sound presets) and lay it under a video. Not speech or narration."
    ),
    "video_audio_bed": (
        "Lay background music or a soundtrack bed under narration or dialogue, and line the cuts up with the beat."
    ),
    "video_duck_audio": "Lower the background music automatically while someone is speaking.",
    "video_mix_audio": "Mix several audio tracks, such as dialogue and music, into one.",
    "audio_compose": "Layer and mix several audio tracks together with their own volumes.",
    "video_normalize_audio": "Even out the loudness of a video's audio.",
    "audio_effects": "Apply effects to an audio track, such as reverb, echo or a volume change.",
    "sound_plan_validate": "Check that a soundtrack plan is valid before rendering it.",
    "sound_mix_render": "Render the final mix of a soundtrack.",
    "sound_master_render": "Master a finished soundtrack for delivery.",
    "video_extract_audio": ("Pull the audio, music or soundtrack out of a video so you can reuse it."),
    "video_ai_stem_separation": "Separate a mixed audio track into its vocal and instrumental stems.",
    "video_audio_waveform": "Draw the waveform of a video's audio, or find its silent stretches.",
    "video_audio_spatial": "Place a video's audio in a spatial or surround mix.",
    # --- fades, transitions and motion graphics ------------------------------
    "video_fade": "Fade the picture in from black at the start and out to black at the end.",
    "video_speed": "Speed up or slow down part of a video.",
    "video_reverse": "Play a video backwards.",
    "hyperframes_render": ("Render motion graphics, titles and visuals from a Hyperframes composition onto a video."),
    "hyperframes_add_block": "Add a motion-graphics block, title or visual to a composition.",
    "video_text_animated": "Add animated titles or motion-graphics text to a video.",
    "video_mograph_count": "Add an animated number counter as motion graphics.",
    "video_mograph_progress": "Add an animated progress bar or loading graphic.",
    "video_add_text": "Add a title or text overlay to a video.",
    "video_add_texts": "Add several text overlays to a video in one pass.",
    "hyperframes_remove_background": "Remove or replace the background behind a subject.",
    "video_chroma_key": "Key out a green screen or coloured background.",
    "video_luma_key": "Key out a background by its brightness.",
    # --- editing the cut -----------------------------------------------------
    "video_edit": "Re-edit a video from its raw footage or a timeline into a new cut.",
    "video_trim": "Trim or cut a clip down to the part you want to keep.",
    "video_merge": "Join several clips into one continuous video.",
    "video_crop": "Crop a video to a region or a new aspect.",
    "video_rotate": "Rotate a video, for instance to turn phone footage upright.",
    "video_stabilize": "Stabilize shaky footage.",
    "video_overlay": "Overlay one video on top of another.",
    "video_composite_layers": "Composite several layers into one video.",
    "video_watermark": "Add a watermark or logo to a video.",
    "video_timeline_edit_plan": (
        "Plan edits to a timeline in plain language, such as removing filler words or pauses."
    ),
    "video_edit_session": "Work through a video's edits conversationally, one change at a time.",
    "video_ai_remove_silence": "Cut the long silences and dead air out of speech.",
    "video_find_moments": "Find particular moments in a video, such as where someone says something.",
    "video_semantic_query": "Search a video for the moments that match a description.",
    "video_propose_broll": "Suggest b-roll to cover parts of a video.",
    "video_punch_zoom_plan": "Plan punch-in zooms on the cut points.",
    # --- analysis, review and improvement ------------------------------------
    "video_analyze": ("Critically analyze a video and report what to improve across its content, pacing and quality."),
    "video_quality_check": "Check a video for quality problems.",
    "video_design_quality_check": "Check a video for design and visual-quality problems.",
    "video_compare_quality": "Compare the quality of two versions of a video.",
    "video_fix_design_issues": "Fix detected design problems in a video.",
    "video_qc_narrative": "Review a video's pacing and retention, including its opening.",
    "video_qc_vision": "Review a video's frames visually for problems.",
    "video_metric_qc": "Check a video against objective quality metrics such as loudness and duration.",
    "video_review_package": "Assemble a review package so a person can judge a video.",
    "video_review_card": "Build a review card summarizing a video for a person to judge.",
    "video_verdict": "Give a pass-or-fail verdict on a video.",
    "video_doctor": "Check whether the system is ready to run the next video job.",
    "video_preflight": "Run a technical preflight check on a video before publishing.",
    "video_publish_gate": "Decide whether a video is safe to publish.",
    "video_publish_validate": "Validate that a video meets a platform's publishing requirements.",
    # --- captions, colour and picture ----------------------------------------
    "video_ai_color_grade": "Color grade a video automatically.",
    "video_ai_upscale": "Upscale a video to a higher resolution.",
    "video_ai_scene_detect": "Detect the scene changes in a video.",
    "video_detect_scenes": "Detect the scene changes in a video.",
    "video_filter": "Apply a visual look or filter to a video.",
    "video_cleanup": "Delete intermediate video files after a workflow; this removes files, it does not denoise or enhance the picture.",
    # --- planning ------------------------------------------------------------
    "video_intent": "Turn a plain-language description of an edit into a plan.",
    "video_direct": "Turn spoken direction into a reviewable edit plan.",
    "video_direct_apply": "Apply a reviewed edit plan.",
    "video_workflow_plan": "Plan a multi-step video workflow without rendering it.",
    "video_workflow_render": "Run a planned video workflow and render the result.",
    "video_cutfile_validate": "Validate an edit decision list before rendering it.",
    "video_cutfile_render": "Render a video from an edit decision list.",
    "video_rescue_plan": "Plan how to rescue a video that has problems.",
    "video_rescue_render": "Render the approved repairs for a rescued video.",
    "video_restoration_plan": "Plan restorative work on damaged footage.",
    "video_hook_candidates": "Propose thumbnail and title options for a video.",
    "video_brand_kit": "Save or load the brand colours, fonts and style for a project.",
    "video_audiogram_plan": "Plan an audiogram or podcast-style waveform video.",
    "video_generative_plan": "Plan AI-generated visuals or footage for a video.",
    "video_visual_transform_plan": "Plan reframing or stabilization, such as keeping a face in frame.",
    "video_composition_plan": "Plan how source clips are composed into a video.",
    "video_creative_autopilot_plan": "Plan a video automatically from a goal, or say why it cannot.",
}


def operation_alias(name: str) -> str:
    """Return the user-language line for an operation, or "" when it has none."""

    return OPERATION_ALIASES.get(name, "")
