<!--
PUSHING CREATION-compatible starter style pack.
Inspired by github.com/PUSHINGSQUARES/pushing-creation and kept compatible
with the STYLE_/NEG_ block convention used by PUSHING FRAMES.
-->
---
title: Cinematography Rules - Starter Library
author: mcp-video
pack_version: '0.1'
template_id: cinematography
---

## STYLE_PHOTOREAL_BASE
photorealistic textures, real-world physics, natural skin pores, fabric weave visible, micro-imperfections, scratches, dust, fingerprints, shot on professional cinema equipment by a working DP, high dynamic range, natural depth of field falloff, no AI-clean.

## STYLE_KODAK_VISION
kodak vision3 50d daylight stock with kodak 2383 print emulation, gentle highlight rolloff, subtle shadow crush, warm neutral midtones, organic colour science, finished print look.

## STYLE_ANAMORPHIC
anamorphic 2x squeeze, horizontal blue streak lens flares, elliptical bokeh, edge breathing toward frame corners, complex chromatic aberration in highlights and dust motes, subtle barrel breathing on focus pulls.

## STYLE_GOLDEN_HOUR
late afternoon golden hour, low angled key from frame right casting long shadows, warm rim along subject edge, cooler fill from open sky, no overhead noon sun, directional and falling off.

## STYLE_OVERCAST_DIFFUSED
overcast sky, soft directional light from above-left, low contrast but still shaped, wet pavement holding reflections, no hard shadows, no studio softbox uniformity.

## STYLE_LOW_LIGHT_PRACTICALS
night-time, motivated by named practical sources, neon signage, tungsten window spill, sodium streetlamp, heavy halation around bright bulbs, deep shadows held with detail not crushed, no flat dim ambient.

## STYLE_SHALLOW_DOF
extremely shallow depth of field at T1.5-T2.0 on cine prime, focus locked tight on subject's eyes or hands, foreground and background falling off into creamy out-of-focus, organic falloff not gaussian blur.

## STYLE_MACRO_TACTILE
extreme macro close-up, dust motes catching directional light, fingerprint smears on glass, fabric weave at thread level, micro chromatic aberration on metal edges, breath fog on cold surfaces.

## STYLE_GRAIN_HALATION
subtle 35mm film grain visible in shadows and skin midtones, halation bleeding around clipped highlights, micro chromatic aberration on hard edges, soft bloom on bright sources, analogue interference not noise.

## STYLE_HANDHELD_OPERATOR
handheld with experienced operator, organic micro-breathing, subtle weight shifts on each step, slight rack focus between subjects, parallax that feels human, not gimbal-smooth, not shaky-cam.

## STYLE_COMPOSITION_OFFCENTRE
subject placed on rule-of-thirds intersection or in negative-space asymmetry, leading lines drawing eye through frame, shoulders or foreground elements breaking the edge, never centred-front-on hero portrait.

## STYLE_REAL_SKIN
visible skin pores, individual hair strands at hairline, slight facial asymmetry, subtle ruddiness in cheeks and ears, fine lines around eyes if appropriate to age, micro-imperfections, nobody is airbrushed.

## NEG_AI_PLASTIC_SKIN
plastic skin, smooth airbrushed skin, doll-like, mannequin, waxy, porcelain, instagram filter, beauty filter, smoothed pores, symmetrical face, perfect teeth, perfect makeup, photoshop liquify, plumped lips, identical eyes.

## NEG_AI_COMPOSITION
centred front-lit hero shot, symmetrical lighting, balanced studio softbox setup, corporate headshot framing, dead-centre subject, magazine-cover staging, every-feature-evenly-lit, no shadow side, generic stock photo.

## NEG_AI_LIGHTING
flat noon lighting, evenly-lit ambient, glow without source direction, fake lens flare overlay, every-light-balanced, studio softbox uniformity, ringlight beauty look, ambient-occlusion-fake, golden filter applied evenly.

## NEG_HUMAN_ANATOMY
deformed hands, extra fingers, missing fingers, fused fingers, distorted fingers, bad anatomy, bad proportions, extra limbs, missing limbs, floating limbs, disconnected limbs, mutated faces, mutation, disfigured, bad eyes, crossed eyes, bad teeth, clothing glitches, impossible pose.

## NEG_OBJECT_GEOMETRY
deformed geometry, distorted proportions, extra parts, missing parts, bad perspective, melted edges, ugly, blurry, low quality, watermark, text, writing, signature, logo glitches, broken physics, impossible reflection.

## NEG_INFLUENCER_AESTHETIC
travel-influencer aesthetic, everything-dreamy, all-golden-filter, soft-glowy-everywhere, main character framing, instagram preset look, lifestyle stock photo, polished commercial sheen.

# Notes

Treat the model like a director of photography. Lead shot prompts with "Shot on [camera]" or "Shot on [camera] mounted on [rig]". State T-stop, shutter speed, fps, lighting state, and direction. Use only the STYLE_ and NEG_ blocks a shot actually needs.
