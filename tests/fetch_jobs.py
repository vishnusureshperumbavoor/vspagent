import sys
import io
import os
from dotenv import load_dotenv

# Ensure the root directory is in the path so we can find vspagent
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from vspagent.tools import JobSearchTool

def main():
    # Load environment variables
    load_dotenv()

    # Fix encoding for Windows console
    if sys.platform == 'win32':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    query = "Python Developer"
    print("=" * 60)
    print(f"💼  VSP AGENT - JOB SEARCH TEST: {query}")
    print("=" * 60)
    
    print(f"\n🔍 Fetching job listings for '{query}' in Bangalore...")
    
    try:
        jobs = JobSearchTool.search_jobs(query)
        
        if not jobs:
            print(f"\n❌ No jobs found for '{query}'. Check your API keys and connection.")
            return

        print(f"\n✅ Found {len(jobs)} jobs:\n")
        
        for i, job in enumerate(jobs, 1):
            print(f"{i}. {job['title']}")
            print(f"   🏢 Company: {job['company']}")
            print(f"   💰 Salary: {job['salary']}")
            if job['description']:
                print(f"   📝 Info: {job['description'][:100]}...")
            print(f"   🔗 Link: {job['url']}")
            print("-" * 60)

    except Exception as e:
        print(f"\n❌ Error during execution: {e}")

if __name__ == "__main__":
    main()
