import os
from google import genai
from google.genai import types

def analyze_frame():
    # Make sure we have the api key
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY not found in environment.")
        return
    
    client = genai.Client(api_key=api_key)
    
    frame_path = "/Users/simongonzalezdecruz/workspaces/mcp-video/frame_test.jpg"
    
    # Upload the file
    print("Uploading file to Gemini...")
    file = client.files.upload(file=frame_path)
    
    # Generate content
    print("Analyzing image...")
    response = client.models.generate_content(
        model='gemini-2.5-pro',
        contents=[
            file,
            "Look at this video frame. Where exactly are the English subtitles located on the screen? Be precise about their position (top, middle, bottom) and how much space they take up. Also describe where the Korean subtitles are."
        ]
    )
    print("Gemini Analysis:")
    print(response.text)

if __name__ == "__main__":
    analyze_frame()
