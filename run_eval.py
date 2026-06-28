import asyncio
import sys
import uuid
from backend.app.evaluator import run_evaluation_sequence

async def cli_log_callback(msg_type: str, message: str):
    if msg_type == "log":
        print(message)
    elif msg_type == "progress":
        print(f"[Progress: {message}%]")
    elif msg_type == "result":
        print(f"\nFinal Result: {message}")

async def main():
    print("Mnemo Evaluation Harness CLI")
    print("=============================")
    eval_user_id = uuid.uuid4()
    print(f"Running evaluation with User ID: {eval_user_id}")
    
    await run_evaluation_sequence(eval_user_id, cli_log_callback)

if __name__ == "__main__":
    # Ensure backend path is in sys.path
    import os
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    
    asyncio.run(main())
