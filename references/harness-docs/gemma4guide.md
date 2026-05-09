# Gemma 4 E4B IT LLM Harness Guide (Q4_K_M + llama-cpp-python)

This guide provides a specialized roadmap for building a high-performance, lightweight LLM harness using the **Gemma 4 E4B IT** (Instruction Tuned) model. Released in April 2026, this model represents the "sweet spot" for edge-AI reasoning and tool-calling.

---

## I. Research Summary: Gemma 4 "Effective" Architecture

Gemma 4 E4B is built on the **Effective Parameter (EP)** architecture. While it has 5.1B total parameters, it dynamically activates only **4B parameters** during inference, significantly reducing VRAM and battery consumption on local devices.

### 1. Key Technical Specifications
*   **Effective Size:** 4B active parameters (5.1B total).
*   **Quantization:** `Q4_K_M` (4-bit Medium) is the recommended balance for maintaining reasoning capabilities while fitting in ~6GB VRAM.
*   **Context Window:** **128,000 tokens** (Native).
*   **Native Reasoning:** Built-in "thinking" mode for complex logic and planning before tool execution.
*   **Multimodal:** Native support for text, image, and high-fidelity audio (WAV/MP3).

### 2. The "Q4_K_M" Advantage (2026 Edition)
*   **File Size:** ~5.34 GB.
*   **Memory Footprint:** ~5.5 GB (base) to 9 GB (with long context).
*   **Performance:** Optimized for Apple Silicon (M3/M4) and NVIDIA RTX 40/50 series GPUs via `llama-cpp-python`.

---

## II. Implementation Guide

### Phase 1: Environment Setup
1. **Install Dependencies:**
   ```bash
   # Ensure you have the latest version for Gemma 4 support
   pip install llama-cpp-python --upgrade
   ```
2. **Model Download:** Ensure you are using the GGUF b8778+ format which includes the corrected Gemma 4 chat templates.

### Phase 2: Building the "Reasoning" Harness
Gemma 4 is most effective when allowed to "think" before generating structured JSON. This prevents hallucinations in tool-calling.

**The Advanced Logic Loop:**
```python
import json
import re
from llama_cpp import Llama

class Gemma4Harness:
    def __init__(self, model_path):
        # Load the GGUF model with 2026 optimized settings
        self.llm = Llama(
            model_path=model_path,
            chat_format="gemma", # Native Gemma 4 template support
            n_ctx=32768,         # 32k is a great starting point for local analysis
            n_gpu_layers=-1,     # Offload all layers to GPU
            verbose=False
        )
        self.tools = {
            "analyze_data": self.analyze_data_tool,
            "read_file": self.read_file_tool
        }

    def analyze_data_tool(self, filename, query):
        return f"Analysis of {filename} complete: [Result for {query}]"

    def read_file_tool(self, filename):
        return f"Content of {filename}: [ID, Name, Date, Sales]"

    def run(self, user_input):
        # Trigger 'Thinking Mode' via the system prompt
        messages = [
            {"role": "system", "content": "<|think|>You are a data agent. Reason step-by-step then provide a tool call if needed in valid JSON format: {\"tool_name\": \"...\", \"args\": {...}}"},
            {"role": "user", "content": user_input}
        ]
        
        # Initial call (allowing higher temperature for the 'thinking' phase)
        response = self.llm.create_chat_completion(
            messages=messages,
            temperature=0.8, 
            top_p=0.95
        )
        content = response['choices'][0]['message']['content']

        # 1. Handle/Extract Thinking Block
        # Gemma 4 usually wraps reasoning in <|think|> ... </|think|>
        thinking_match = re.search(r'<\|think\|>(.*?)</\|think\|>', content, re.DOTALL)
        if thinking_match:
            print(f"[*] Model Reasoning: {thinking_match.group(1).strip()[:100]}...")

        # 2. Extract Tool Call (JSON)
        # The JSON often follows the thinking block
        json_match = re.search(r'(\{.*"tool_name":\s*"(\w+)".*\})', content, re.DOTALL)
        
        if json_match:
            try:
                tool_data = json.loads(json_match.group(1))
                tool_name = tool_data.get("tool_name")
                args = tool_data.get("args", {})
                
                if tool_name in self.tools:
                    print(f"[*] Executing {tool_name}...")
                    result = self.tools[tool_name](**args)
                    
                    # 3. Final Answer Phase (Strict Grounding)
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content": f"Tool result: {result}. Provide your final answer."})
                    
                    final_response = self.llm.create_chat_completion(
                        messages=messages,
                        temperature=0.1 # Low temperature for factual output
                    )
                    return final_response['choices'][0]['message']['content']
            except Exception as e:
                return f"Error parsing tool call: {e}. Raw content: {content}"

        return content

if __name__ == "__main__":
    MODEL_PATH = "gemma-4-e4b-it-q4_k_m.gguf"
    harness = Gemma4Harness(MODEL_PATH)
    print(harness.run("Compare sales in 'q1.csv' and 'q2.csv'"))
```

---

## III. Optimization & Troubleshooting

### 1. Temperature Control (Thinking vs. Output)
*   **Thinking Phase:** Use **0.8 - 1.0**. This allows the model to explore logical paths more effectively.
*   **JSON/Final Answer:** Use **0.0 - 0.2**. This ensures structural integrity and factual accuracy.

### 2. Troubleshooting "Overthinking" Loops
*   **Issue:** The model stays in `<|think|>` mode indefinitely or repeats logic.
*   **Fix:** Ensure your `llama-cpp-python` is using the `b8778` build or later. If it persists, add a "Stop Sequence" for `</|think|>` or limit `max_tokens` to force a transition to the tool-call phase.

### 3. Chat Template Errors
*   **Issue:** "Outdated chat template" logs.
*   **Fix:** Gemma 4 introduced new control tokens. If the auto-template fails, manually pass the Jinja template in the `Llama` constructor or update your GGUF metadata using `gguf-py`.

### 4. Hardware Scaling
| Device | Recommendation | Performance |
| :--- | :--- | :--- |
| **MacBook (M2/M3/M4 16GB)** | Use `n_gpu_layers=-1` | ~45-60 tokens/sec |
| **NVIDIA RTX 4070 (12GB)** | Use `n_gpu_layers=-1` | ~80+ tokens/sec |
| **Raspberry Pi 5 (8GB)** | Use `Q4_K_S` (Small) | ~3-5 tokens/sec |

---

## IV. Do's and Don'ts

*   **DO** use the `<|think|>` token in your system prompt to unlock reasoning.
*   **DO** use dynamic temperature (high for thought, low for action).
*   **DON'T** ignore the 128k context—use it for RAG by feeding entire small CSVs directly into the prompt.
*   **DON'T** use older GGUF versions (pre-April 2026) as they lack the multimodal and reasoning tokenizers.
