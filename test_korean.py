import subprocess

test_srt = "test.srt"
with open(test_srt, "w") as f:
    f.write("1\n00:00:00,000 --> 00:00:01,000\n안녕하세요 Test\n")

cmd = [
    "ffmpeg", "-y",
    "-f", "lavfi", "-i", "color=c=black:s=1280x720:d=1",
    "-vf", f"subtitles='{test_srt}':force_style='FontName=AppleGothic,FontSize=40,PrimaryColour=&H00F0FF,Alignment=8'",
    "test_korean_font.mp4"
]
subprocess.run(cmd, check=True)
print("Success")
