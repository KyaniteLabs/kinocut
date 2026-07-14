# S15 adversarial smoke (non-release)

Commands executed after S12 merge:

- pytest tests/test_kinocut_sound_mix.py tests/test_kinocut_sound_qa.py tests/test_kinocut_sound_public.py
- Consent fail-closed already covered in existing authorization/clone suites
- Privacy: public adapter JSON serialization asserts no home-directory or password leakage

Result: smoke green; release STOP holds.
