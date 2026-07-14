# Hall of receipts

Curated, shareable receipt stories. Prefer anonymized paths and synthetic media.

## Entry template

```markdown
### Title
- **Date:**
- **Intent:**
- **Tools (count / names):**
- **Guardrails:**
- **Quality:**
- **Human review remaining:**
- **Artifact:** link to sample JSON or proof note
- **Lesson:**
```

## Seed entries

### Confidence baseline plumbing

- **Date:** regenerate anytime  
- **Intent:** Prove Kinocut produces a checked vertical clip from synthetic media  
- **How:** `python scripts/golden_path.py`  
- **Artifact:** `demo/golden-pack/sample_video_receipt.json`  
- **Lesson:** Receipts matter even when media is synthetic; human_review stays pending  

### Workflow engine dry-run → render

- **Intent:** Multi-step job with hashes and resume cursor  
- **How:** `examples/workflows/captioned-vertical-short/`  
- **Lesson:** Plan before render; inspect receipt after  

### Rescue package (when used)

- **Intent:** Content-preserving repair with immutable source  
- **Docs:** [RESCUE.md](RESCUE.md)  
- **Lesson:** Approval gates are the product  

## Adding an entry

1. Redact home directories and usernames  
2. Prefer relative paths in JSON  
3. Link proofs under `docs/proofs/` when formal  
4. Never commit large private media  

## Related

- [VIDEO_RECEIPT.md](VIDEO_RECEIPT.md)  
- [demo/golden-pack](../demo/golden-pack/README.md)  
