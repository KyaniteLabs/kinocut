# Agent Prompt

Use this workflow when the user wants a local platform package from one source video.

```text
Take this source video, create platform-ready variants, generate thumbnails and storyboards, write a manifest, and produce a Video Receipt. Do not mark it publishable until a human reviews the variants.
```

Required behavior:

- Inspect the source before editing.
- Use `Client.repurpose` for package generation.
- Preserve the source media.
- Produce a receipt that points to the manifest and review artifacts.
- Keep human review pending.
