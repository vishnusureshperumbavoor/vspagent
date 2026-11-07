"""
Persona Model Fine-Tuning, Quantization & Publishing Engine
===========================================================
End-to-end trainer designed to fine-tune personal AI models natively without system prompts,
fuse adapters, quantize to GGUF, and publish directly to Hugging Face Hub.
"""

import os
import sys
import json
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any

ZERO_SYSTEM_CHAT_TEMPLATE = (
    "{% for message in messages %}"
    "{{'<|im_start|>' + message['role'] + '\n' + message['content'] + '<|im_end|>' + '\n'}}"
    "{% endfor %}"
    "{% if add_generation_prompt %}"
    "{{'<|im_start|>assistant\n'}}"
    "{% endif %}"
)


def build_llama_cpp(repo_dir: str = "/tmp/llama.cpp") -> str:
    """Clones and compiles llama.cpp for GGUF conversion and quantization."""
    print(f"🛠️ Setting up llama.cpp at {repo_dir}...")
    if not os.path.exists(repo_dir):
        subprocess.run(["git", "clone", "--depth", "1", "https://github.com/ggerganov/llama.cpp.git", repo_dir], check=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "gguf"], check=True)
    if os.path.exists(f"{repo_dir}/requirements.txt"):
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", f"{repo_dir}/requirements.txt"], check=True)

    build_dir = os.path.join(repo_dir, "build")
    os.makedirs(build_dir, exist_ok=True)
    subprocess.run(["cmake", "-B", build_dir, repo_dir], check=True)
    subprocess.run(["cmake", "--build", build_dir, "--config", "Release", "-j4", "--target", "llama-quantize"], check=True)
    return repo_dir


def sanitize_tokenizer_config(model_dir: str):
    """
    Fixes Transformers v5 issue where extra_special_tokens is saved as a list,
    which causes AttributeError: 'list' object has no attribute 'keys' in llama.cpp converter.
    """
    cfg_path = os.path.join(model_dir, "tokenizer_config.json")
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data.get("extra_special_tokens"), list):
                data["extra_special_tokens"] = {}
                with open(cfg_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                print("✨ Sanitized tokenizer_config.json extra_special_tokens for GGUF converter.")
        except Exception as e:
            print(f"Warning: Failed to sanitize tokenizer_config.json: {e}")


def train_persona(
    dataset_path: str,
    base_model: str = "Qwen/Qwen2.5-0.5B-Instruct",
    output_dir: str = "./vsp_model_output",
    epochs: int = 3,
    batch_size: int = 4,
    grad_accum: int = 2,
    lr: float = 2e-4,
    max_seq_len: int = 1024,
    repo_id: Optional[str] = None,
    hf_token: Optional[str] = None,
    quant_type: str = "q4_k_m",
) -> Dict[str, Any]:
    """
    Executes end-to-end training, fusion, GGUF quantization, and upload.
    """
    import torch
    from datasets import load_dataset
    from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments, DataCollatorForSeq2Seq
    from peft import LoraConfig, get_peft_model
    from huggingface_hub import HfApi, login

    token = hf_token or os.environ.get("HF_TOKEN", "")
    if repo_id and not token:
        raise ValueError("HF_TOKEN is required to push to Hugging Face Hub. Pass hf_token or set HF_TOKEN env var.")

    if token:
        login(token=token)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"\n🚀 Starting Persona Fine-Tuning on: {device} ({torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'})")

    # 1. Tokenizer
    tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)
    tokenizer.chat_template = ZERO_SYSTEM_CHAT_TEMPLATE
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # 2. Tokenize with Assistant-Only Response Loss Masking
    raw_dataset = load_dataset("json", data_files=dataset_path, split="train")

    def preprocess_conversation(example):
        input_ids = []
        labels = []
        for msg in example["messages"]:
            header = f"<|im_start|>{msg['role']}\n"
            body = f"{msg['content']}<|im_end|>\n"
            h_ids = tokenizer.encode(header, add_special_tokens=False)
            b_ids = tokenizer.encode(body, add_special_tokens=False)

            input_ids.extend(h_ids + b_ids)
            if msg["role"] == "assistant":
                labels.extend([-100] * len(h_ids))
                labels.extend(b_ids)
            else:
                labels.extend([-100] * (len(h_ids) + len(b_ids)))

        input_ids = input_ids[:max_seq_len]
        labels = labels[:max_seq_len]
        return {
            "input_ids": input_ids,
            "labels": labels,
            "attention_mask": [1] * len(input_ids),
        }

    tokenized_dataset = raw_dataset.map(preprocess_conversation, remove_columns=raw_dataset.column_names)

    # 3. Model & LoRA
    if torch.cuda.is_available():
        dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    else:
        dtype = torch.float32
    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        dtype=dtype,
        device_map="auto",
        trust_remote_code=True,
    )

    peft_config = LoraConfig(
        r=16,
        lora_alpha=32,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, peft_config)

    # 4. Trainer Setup
    collator = DataCollatorForSeq2Seq(tokenizer=tokenizer, model=model, padding=True, pad_to_multiple_of=8)
    training_args = TrainingArguments(
        output_dir=output_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=grad_accum,
        learning_rate=lr,
        warmup_steps=10,
        lr_scheduler_type="cosine",
        fp16=(dtype == torch.float16),
        bf16=(dtype == torch.bfloat16),
        logging_steps=10,
        save_strategy="no",
        report_to="none",
    )

    trainer = Trainer(
        model=model,
        train_dataset=tokenized_dataset,
        data_collator=collator,
        args=training_args,
    )

    print("\n⚡ Beginning Supervised Fine-Tuning...")
    trainer.train()

    # 5. Model Merge
    print("🧬 Merging LoRA adapter into base weights...")
    merged_model = model.merge_and_unload()
    merged_dir = os.path.join(output_dir, "merged")
    os.makedirs(merged_dir, exist_ok=True)
    merged_model.save_pretrained(merged_dir, safe_serialization=True)
    tokenizer.save_pretrained(merged_dir)
    sanitize_tokenizer_config(merged_dir)

    # 6. GGUF Quantization
    llama_dir = build_llama_cpp()
    f16_gguf = os.path.join(merged_dir, f"model-f16.gguf")
    q_gguf = os.path.join(merged_dir, f"model-{quant_type}.gguf")

    print(f"🔄 Converting to F16 GGUF...")
    subprocess.run([
        sys.executable,
        f"{llama_dir}/convert_hf_to_gguf.py",
        merged_dir,
        "--outfile", f16_gguf,
        "--outtype", "f16",
    ], check=True)

    print(f"📉 Quantizing to {quant_type.upper()} GGUF...")
    quant_bin = f"{llama_dir}/build/bin/llama-quantize"
    if not os.path.exists(quant_bin):
        for root, dirs, files in os.walk(os.path.join(llama_dir, "build")):
            if "llama-quantize" in files and os.access(os.path.join(root, "llama-quantize"), os.X_OK):
                quant_bin = os.path.join(root, "llama-quantize")
                break
    subprocess.run([quant_bin, f16_gguf, q_gguf, quant_type], check=True)
    if os.path.exists(f16_gguf):
        os.remove(f16_gguf)

    # 7. Push to Hugging Face Hub
    if repo_id and token:
        print(f"🚀 Uploading merged model and {quant_type.upper()} GGUF to Hugging Face Hub: {repo_id}...")
        api = HfApi(token=token)
        api.create_repo(repo_id=repo_id, exist_ok=True)
        api.upload_folder(
            folder_path=merged_dir,
            repo_id=repo_id,
            commit_message=f"feat: upload fine-tuned persona model with {quant_type.upper()} GGUF",
        )
        print(f"🎉 Successfully published to: https://huggingface.co/{repo_id}")

    return {
        "status": "success",
        "merged_dir": merged_dir,
        "gguf_path": q_gguf,
        "repo_id": repo_id,
    }
