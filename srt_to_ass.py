import sys
import re

def srt_time_to_ass(time_str):
    # SRT: 00:00:03,200 -> ASS: 0:00:03.20
    h, m, s_ms = time_str.split(':')
    s, ms = s_ms.split(',')
    return f"{int(h)}:{m}:{s}.{ms[:2]}"

def convert_srt_to_ass(srt_path, ass_path, style_name, font_name, font_size, spacing, margin_v, alignment):
    with open(srt_path, 'r', encoding='utf-8') as f:
        srt_content = f.read()

    ass_header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: {style_name},{font_name},{font_size},&H00FFFFFF,&H00000000,&H00000000,&H80000000,-1,0,0,0,100,100,{spacing},0,1,2,1,{alignment},20,20,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    blocks = srt_content.strip().split('\n\n')
    events = []
    
    for block in blocks:
        lines = block.split('\n')
        if len(lines) >= 3:
            times = lines[1].split(' --> ')
            start = srt_time_to_ass(times[0])
            end = srt_time_to_ass(times[1])
            text = "\\N".join(lines[2:])
            events.append(f"Dialogue: 0,{start},{end},{style_name},,0,0,0,,{text}")

    with open(ass_path, 'w', encoding='utf-8') as f:
        f.write(ass_header + "\n".join(events) + "\n")

if __name__ == "__main__":
    convert_srt_to_ass(
        "/Users/simongonzalezdecruz/.gemini/antigravity/scratch/subtitles_en.srt",
        "/Users/simongonzalezdecruz/.gemini/antigravity/scratch/subtitles_en_top.ass",
        style_name="EnglishTop", font_name="JetBrains Mono", font_size=36, spacing=0, margin_v=60, alignment=8
    )
    convert_srt_to_ass(
        "/Users/simongonzalezdecruz/.gemini/antigravity/scratch/subtitles_ko.srt",
        "/Users/simongonzalezdecruz/.gemini/antigravity/scratch/subtitles_ko_bottom.ass",
        style_name="KoreanBottom", font_name="NanumGothic", font_size=50, spacing=2, margin_v=60, alignment=2
    )
