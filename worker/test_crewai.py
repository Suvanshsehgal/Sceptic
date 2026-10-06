from crewai_wrapper import analyze_with_crewai
from dotenv import load_dotenv
import os

def test_crewai():
    # Only run if LLM API key is available
    if not os.getenv("OPENAI_API_KEY") and not os.getenv("GROQ_API_KEY"):
        print("Skipping CrewAI test, no API key found.")
        return

    code = """
import os
os.path.join("a", "b")
os.non_existent_function()
"""
    print("Running CrewAI Fact-Checker Agent on code:")
    print(code)
    print("-" * 50)
    
    result = analyze_with_crewai(code)
    
    print("-" * 50)
    print("CrewAI Result:")
    print(result)

if __name__ == "__main__":
    load_dotenv(dotenv_path="../.env")
    test_crewai()
