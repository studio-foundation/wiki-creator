#!/usr/bin/env python3
"""LoRA fine-tuning script for wiki-page-item generation.

Fine-tunes Llama-3.2-3B-Instruct via Unsloth QLoRA 4-bit on Alpaca-format
JSONL and exports a GGUF file.

Usage:
    python scripts/lora_train.py \
        --dataset-dir processing_output/lora/throneofglass/ \
        --output-dir models/wiki-page-item-lora/

    # Skip training, only merge+export from existing adapter:
    python scripts/lora_train.py \
        --dataset-dir processing_output/lora/throneofglass/ \
        --output-dir models/wiki-page-item-lora/ \
        --skip-train

Dependencies (NOT in project setup.py — GPU-only):
    pip install unsloth matplotlib
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Graceful import checks for heavy GPU-only dependencies
# ---------------------------------------------------------------------------

def _check_dependency(module_name: str, install_hint: str) -> None:
    try:
        __import__(module_name)
    except ImportError:
        print(
            f"ERROR: '{module_name}' is not installed.\n"
            f"Install it with: {install_hint}\n"
            f"This is a GPU-only dependency and is not part of the project's setup.py.",
            file=sys.stderr,
        )
        sys.exit(1)


_check_dependency("unsloth", "pip install unsloth")
_check_dependency("matplotlib", "pip install matplotlib")

# These imports are deferred past the check so the error message is clean.
from unsloth import FastLanguageModel  # noqa: E402
from datasets import Dataset  # noqa: E402
from transformers import TrainingArguments  # noqa: E402
from trl import SFTTrainer  # noqa: E402
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MODEL_NAME = "unsloth/Llama-3.2-3B-Instruct"
MAX_SEQ_LENGTH = 4096
LORA_RANK = 16
LORA_ALPHA = 32
TARGET_MODULES = ["q_proj", "v_proj"]

CHATML_TEMPLATE = (
    "<|im_start|>user\n{instruction}<|im_end|>\n"
    "<|im_start|>assistant\n{output}<|im_end|>"
)

# ---------------------------------------------------------------------------
# Dataset helpers
# ---------------------------------------------------------------------------

def load_jsonl(path: Path) -> list[dict]:
    """Load an Alpaca-format JSONL file."""
    if not path.exists():
        print(f"ERROR: dataset file not found: {path}", file=sys.stderr)
        sys.exit(1)
    rows = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                print(f"WARNING: skipping malformed line {i} in {path}: {exc}", file=sys.stderr)
    return rows


def format_chatml(example: dict) -> dict:
    """Format an Alpaca example to ChatML text."""
    return {
        "text": CHATML_TEMPLATE.format(
            instruction=example["instruction"],
            output=example["output"],
        )
    }


def load_dataset(dataset_dir: Path) -> tuple[Dataset, Dataset]:
    """Load train.jsonl and eval.jsonl, return HF Datasets."""
    train_rows = load_jsonl(dataset_dir / "train.jsonl")
    eval_rows = load_jsonl(dataset_dir / "eval.jsonl")

    if not train_rows:
        print("ERROR: train.jsonl is empty.", file=sys.stderr)
        sys.exit(1)

    train_ds = Dataset.from_list([format_chatml(r) for r in train_rows])
    eval_ds = Dataset.from_list([format_chatml(r) for r in eval_rows]) if eval_rows else None

    print(f"Loaded {len(train_rows)} training examples, {len(eval_rows)} eval examples.")
    return train_ds, eval_ds


# ---------------------------------------------------------------------------
# Phase 2 — Training
# ---------------------------------------------------------------------------

def train(
    train_ds: Dataset,
    eval_ds: Dataset | None,
    output_dir: Path,
    epochs: int,
) -> tuple[dict, list[float], list[float]]:
    """Run QLoRA fine-tuning. Returns (hyperparams, train_losses, eval_losses)."""

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=MODEL_NAME,
        max_seq_length=MAX_SEQ_LENGTH,
        load_in_4bit=True,
    )

    model = FastLanguageModel.get_peft_model(
        model,
        r=LORA_RANK,
        lora_alpha=LORA_ALPHA,
        target_modules=TARGET_MODULES,
        lora_dropout=0,
        bias="none",
        use_gradient_checkpointing="unsloth",
    )

    adapter_dir = output_dir / "adapter"
    adapter_dir.mkdir(parents=True, exist_ok=True)

    training_args = TrainingArguments(
        output_dir=str(adapter_dir),
        num_train_epochs=epochs,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=4,
        learning_rate=2e-4,
        fp16=True,
        logging_steps=1,
        eval_strategy="epoch" if eval_ds else "no",
        save_strategy="epoch",
        save_total_limit=1,
        report_to="none",
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=train_ds,
        eval_dataset=eval_ds,
        dataset_text_field="text",
        max_seq_length=MAX_SEQ_LENGTH,
        args=training_args,
    )

    print("\n--- Starting training ---")
    start = time.time()
    result = trainer.train()
    elapsed = time.time() - start
    print(f"--- Training complete in {elapsed:.1f}s ---\n")

    # Extract losses from log history
    train_losses = [
        entry["loss"] for entry in trainer.state.log_history if "loss" in entry
    ]
    eval_losses = [
        entry["eval_loss"] for entry in trainer.state.log_history if "eval_loss" in entry
    ]

    # Print summary
    final_train_loss = train_losses[-1] if train_losses else None
    final_eval_loss = eval_losses[-1] if eval_losses else None
    print(f"Final train loss: {final_train_loss}")
    print(f"Final eval loss:  {final_eval_loss}")

    # Save adapter
    model.save_pretrained(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))
    print(f"Adapter saved to {adapter_dir}")

    hyperparams = {
        "model": MODEL_NAME,
        "max_seq_length": MAX_SEQ_LENGTH,
        "lora_rank": LORA_RANK,
        "lora_alpha": LORA_ALPHA,
        "target_modules": TARGET_MODULES,
        "epochs": epochs,
        "batch_size": 1,
        "gradient_accumulation_steps": 4,
        "learning_rate": 2e-4,
        "train_samples": len(train_ds),
        "eval_samples": len(eval_ds) if eval_ds else 0,
        "training_time_s": round(elapsed, 1),
        "final_train_loss": final_train_loss,
        "final_eval_loss": final_eval_loss,
    }

    return hyperparams, train_losses, eval_losses


# ---------------------------------------------------------------------------
# Loss curve
# ---------------------------------------------------------------------------

def save_loss_curve(
    train_losses: list[float],
    eval_losses: list[float],
    output_dir: Path,
) -> None:
    """Save a loss curve PNG to output_dir."""
    fig, ax = plt.subplots(figsize=(8, 5))
    if train_losses:
        ax.plot(train_losses, label="train loss", alpha=0.7)
    if eval_losses:
        # Eval losses are per-epoch; space them evenly across steps
        n_steps = len(train_losses)
        n_evals = len(eval_losses)
        if n_steps > 0 and n_evals > 0:
            step_interval = n_steps / n_evals
            eval_x = [int((i + 1) * step_interval) - 1 for i in range(n_evals)]
            ax.plot(eval_x, eval_losses, "o-", label="eval loss")
    ax.set_xlabel("Step")
    ax.set_ylabel("Loss")
    ax.set_title("LoRA Training Loss")
    ax.legend()
    ax.grid(True, alpha=0.3)

    path = output_dir / "loss_curve.png"
    fig.savefig(str(path), dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"Loss curve saved to {path}")


# ---------------------------------------------------------------------------
# Phase 3 — Merge
# ---------------------------------------------------------------------------

def merge_adapter(output_dir: Path) -> tuple:
    """Load adapter and merge into base model (float16)."""
    adapter_dir = output_dir / "adapter"
    merged_dir = output_dir / "merged"
    merged_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n--- Merging adapter from {adapter_dir} ---")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=str(adapter_dir),
        max_seq_length=MAX_SEQ_LENGTH,
        load_in_4bit=True,
    )

    model.save_pretrained_merged(
        str(merged_dir),
        tokenizer,
        save_method="merged_16bit",
    )
    print(f"Merged model saved to {merged_dir}")
    return model, tokenizer


# ---------------------------------------------------------------------------
# Phase 4 — Export GGUF
# ---------------------------------------------------------------------------

def export_gguf(model, tokenizer, output_dir: Path) -> None:
    """Export Q4_K_M GGUF."""
    gguf_dir = output_dir / "gguf"
    gguf_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n--- Exporting GGUF to {gguf_dir} ---")
    model.save_pretrained_gguf(
        str(gguf_dir),
        tokenizer,
        quantization_method="q4_k_m",
    )
    print(f"GGUF exported to {gguf_dir}")

    # Find the .gguf file to print the ollama command
    gguf_files = list(gguf_dir.glob("*.gguf"))
    if gguf_files:
        gguf_path = gguf_files[0]
        print(f"\nTo load in Ollama:")
        print(f"  ollama create wiki-page-item -f {gguf_path}")


# ---------------------------------------------------------------------------
# Train log
# ---------------------------------------------------------------------------

def save_train_log(hyperparams: dict, output_dir: Path) -> None:
    """Save train_log.json with hyperparams + final losses."""
    path = output_dir / "train_log.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(hyperparams, f, indent=2, ensure_ascii=False)
    print(f"Train log saved to {path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fine-tune Llama-3.2-3B-Instruct via QLoRA for wiki-page-item generation."
    )
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        required=True,
        help="Directory containing train.jsonl and eval.jsonl",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory for adapter, merged model, GGUF, and logs",
    )
    parser.add_argument(
        "--skip-train",
        action="store_true",
        default=False,
        help="Skip training; load adapter from {output-dir}/adapter/ and do merge+export only",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=3,
        help="Number of training epochs (default: 3)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    # Phase 1 — Load dataset
    print("=== Phase 1: Loading dataset ===")
    train_ds, eval_ds = load_dataset(args.dataset_dir)

    if args.skip_train:
        # Skip training, verify adapter exists
        adapter_dir = output_dir / "adapter"
        if not (adapter_dir / "adapter_config.json").exists():
            print(
                f"ERROR: --skip-train specified but no adapter found at {adapter_dir}",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"\n=== Skipping training, loading adapter from {adapter_dir} ===")
        hyperparams = {
            "model": MODEL_NAME,
            "skip_train": True,
            "adapter_dir": str(adapter_dir),
        }
        train_losses, eval_losses = [], []
    else:
        # Phase 2 — Train
        print("\n=== Phase 2: Training ===")
        hyperparams, train_losses, eval_losses = train(
            train_ds, eval_ds, output_dir, args.epochs
        )

        # Save loss curve
        if train_losses or eval_losses:
            save_loss_curve(train_losses, eval_losses, output_dir)

    # Phase 3 — Merge
    print("\n=== Phase 3: Merging adapter ===")
    model, tokenizer = merge_adapter(output_dir)

    # Phase 4 — Export GGUF
    print("\n=== Phase 4: Exporting GGUF ===")
    export_gguf(model, tokenizer, output_dir)

    # Save train log
    save_train_log(hyperparams, output_dir)

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
