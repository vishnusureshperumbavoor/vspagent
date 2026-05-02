"""VSP Agent - CLI Interface"""

import sys
import io
import time
import threading
from .agent import VSPAgent

# Fix Windows console encoding
if sys.platform == 'win32':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except:
        pass


class Spinner:
    """Animated spinner for thinking indicator"""
    def __init__(self):
        self.spinning = False
        self.thread = None
        self.frames = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
        
    def start(self):
        self.spinning = True
        self.thread = threading.Thread(target=self._animate)
        self.thread.start()
        
    def _animate(self):
        idx = 0
        while self.spinning:
            print(f'\r{self.frames[idx]} Thinking...', end='', flush=True)
            idx = (idx + 1) % len(self.frames)
            time.sleep(0.1)
            
    def stop(self):
        self.spinning = False
        if self.thread:
            self.thread.join()
        print('\r' + ' ' * 20 + '\r', end='', flush=True)


def main():
    """Main CLI entry point"""
    print("=" * 62)
    print("          🤖  VSP Agent - Interactive Chat Mode")
    print("              Powered by Qwen2.5-0.5B AI")
    print("=" * 62)
    print()
    
    agent = VSPAgent()
    
    try:
        agent.init_ai()
    except Exception as e:
        print(f"❌ Error: {e}")
        print("\n💡 Try: pip install transformers torch")
        return
    
    print("\n✅ VSP Agent is ready to chat!\n")
    print("Type 'exit' or 'quit' to end the conversation.\n")
    
    conversation_history = []
    
    while True:
        try:
            user_input = input("💬 You: ").strip()
            
            if not user_input:
                continue
            
            if user_input.lower() in ['exit', 'quit']:
                print("\n👋 Thanks for chatting with VSP Agent! Goodbye! 🚀\n")
                break
            
            # Start spinner and timer
            spinner = Spinner()
            
            # Show searching indicator if applicable
            msg_lower = user_input.lower()
            if "event" in msg_lower and ("bangalore" in msg_lower or "blr" in msg_lower):
                print(f"🔍 Searching Meetup.com for events in Bangalore...")
                
            spinner.start()
            start_time = time.time()
            
            # Get AI response
            response = agent.chat(user_input, conversation_history)
            
            # Stop spinner and calculate time
            elapsed_time = time.time() - start_time
            spinner.stop()
            
            # Show response with timing
            print(f"🤖 VSP Agent: {response}")
            print(f"   ⏱️  Response time: {elapsed_time:.2f}s\n")
            
            # Update history
            conversation_history.append({"role": "user", "content": user_input})
            conversation_history.append({"role": "assistant", "content": response})
            
        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!\n")
            break
        except Exception as e:
            print(f"\n❌ Error: {e}\n")


if __name__ == "__main__":
    main()

