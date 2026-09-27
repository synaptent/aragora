"""
Local Fine-Tuning with PEFT/LoRA.

Provides local fine-tuning capabilities using Parameter-Efficient Fine-Tuning
(PEFT) with Low-Rank Adaptation (LoRA) for domain-specific model adaptation.

Usage:
    from aragora.ml.local_finetuning import (
        LocalFineTuner,
        FineTuneConfig,
        TrainingData,
    )

    # Prepare training data
    data = TrainingData.from_debates(debate_outcomes)

    # Configure fine-tuning
    config = FineTuneConfig(
        base_model="microsoft/phi-2",
        lora_r=8,
        lora_alpha=32,
        epochs=3,
    )

    # Fine-tune
    tuner = LocalFineTuner(config)
    result = await tuner.train(data)

    # Use fine-tuned model
    response = tuner.generate("Improve the consensus detection algorithm")

Requirements:
    pip install peft transformers accelerate bitsandbytes
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
from collections.abc import Sequence
import asyncio

logger = logging.getLogger(__name__)


class FineTuneTask(str, Enum):
    """Types of fine-tuning tasks."""

    COMPLETION = "completion"  # Standard text completion
    INSTRUCTION = "instruction"  # Instruction following
    PREFERENCE = "preference"  # DPO/RLHF preference learning
    CLASSIFICATION = "classification"  # Text classification


@dataclass
class TrainingExample:
    """Single training example."""

    instruction: str  # Task instruction/prompt
    input_text: str = ""  # Optional input context
    output: str = ""  # Expected output
    rejected: str = ""  # For preference learning: rejected output
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "instruction": self.instruction,
            "input": self.input_text,
            "output": self.output,
            "rejected": self.rejected if self.rejected else None,
            "metadata": self.metadata,
        }

    @classmethod
    def from_debate(
        cls,
        task: str,
        winning_response: str,
        losing_response: str | None = None,
        context: str = "",
    ) -> TrainingExample:
        """Create training example from debate outcome.

        Args:
            task: The debate task/question
            winning_response: The consensus/winning response
            losing_response: Optional rejected response for preference learning
            context: Optional additional context

        Returns:
            TrainingExample instance
        """
        return cls(
            instruction=task,
            input_text=context,
            output=winning_response,
            rejected=losing_response or "",
            metadata={"source": "debate"},
        )


@dataclass
class TrainingData:
    """Collection of training examples."""

    examples: list[TrainingExample] = field(default_factory=list)
    task_type: FineTuneTask = FineTuneTask.INSTRUCTION

    def __len__(self) -> int:
        return len(self.examples)

    def add(self, example: TrainingExample) -> None:
        self.examples.append(example)

    def to_jsonl(self, path: str | Path) -> None:
        """Export to JSONL format."""
        path = Path(path)
        with open(path, "w") as f:
            for ex in self.examples:
                f.write(json.dumps(ex.to_dict()) + "\n")

    @classmethod
    def from_jsonl(cls, path: str | Path) -> TrainingData:
        """Load from JSONL format."""
        path = Path(path)
        examples = []
        with open(path) as f:
            for line in f:
                data = json.loads(line)
                examples.append(
                    TrainingExample(
                        instruction=data.get("instruction", ""),
                        input_text=data.get("input", ""),
                        output=data.get("output", ""),
                        rejected=data.get("rejected", ""),
                        metadata=data.get("metadata", {}),
                    )
                )
        return cls(examples=examples)

    @classmethod
    def from_debates(
        cls,
        debate_outcomes: Sequence[dict[str, Any]],
    ) -> TrainingData:
        """Create training data from debate outcomes.

        Args:
            debate_outcomes: List of debate outcome dicts with:
                - task: The debate task
                - consensus: The consensus response
                - rejected: Optional rejected responses
                - context: Optional context

        Returns:
            TrainingData instance
        """
        data = cls(task_type=FineTuneTask.PREFERENCE)
        for outcome in debate_outcomes:
            task = outcome.get("task", "")
            consensus = outcome.get("consensus", "")
            rejected_list = outcome.get("rejected", [])
            context = outcome.get("context", "")

            if not task or not consensus:
                continue

            # Create example with best rejected response for preference learning
            rejected = rejected_list[0] if rejected_list else ""

            data.add(
                TrainingExample.from_debate(
                    task=task,
                    winning_response=consensus,
                    losing_response=rejected,
                    context=context,
                )
            )

        return data


@dataclass
class FineTuneConfig:
    """Configuration for fine-tuning."""

    # Model settings
    base_model: str = "microsoft/phi-2"  # Small local model
    output_dir: str = "./fine_tuned_model"

    # LoRA settings
    lora_r: int = 8  # LoRA rank
    lora_alpha: int = 32  # LoRA scaling factor
    lora_dropout: float = 0.05
    target_modules: list[str] = field(default_factory=lambda: ["q_proj", "v_proj"])

    # Training settings
    epochs: int = 3
    batch_size: int = 4
    learning_rate: float = 2e-4
    warmup_steps: int = 100
    max_seq_length: int = 512
    gradient_accumulation_steps: int = 4

    # Memory optimization
    use_4bit: bool = True  # 4-bit quantization
    use_gradient_checkpointing: bool = True

    # Logging
    logging_steps: int = 10
    save_steps: int = 100


@dataclass
class FineTuneResult:
    """Result of fine-tuning."""

    success: bool
    model_path: str
    metrics: dict[str, float] = field(default_factory=dict)
    training_time_seconds: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "model_path": self.model_path,
            "metrics": self.metrics,
            "training_time_seconds": round(self.training_time_seconds, 2),
            "error": self.error,
        }


class LocalFineTuner:
    """Local fine-tuning with PEFT/LoRA.

    Enables domain-specific adaptation of small local models
    using debate outcomes and other training data.

    Features:
    - Memory-efficient 4-bit quantization
    - LoRA for parameter-efficient training
    - Support for various training objectives
    - Checkpoint saving and resuming
    """

    def __init__(self, config: FineTuneConfig | None = None):
        """Initialize the fine-tuner.

        Args:
            config: Fine-tuning configuration
        """
        self.config = config or FineTuneConfig()
        self._model: Any | None = None
        self._tokenizer: Any | None = None
        self._peft_model: Any | None = None
        self._is_loaded = False

    def _check_dependencies(self) -> bool:
        """Check if required dependencies are available."""
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401
            import peft  # noqa: F401

            return True
        except ImportError as e:
            logger.error(
                "Missing dependency: %s. Install with: pip install peft transformers accelerate bitsandbytes",
                e,
            )
            return False

    def _load_base_model(self) -> None:
        """Load the base model with quantization."""
        if self._is_loaded:
            return

        if not self._check_dependencies():
            raise ImportError("Required dependencies not installed")

        import torch
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            BitsAndBytesConfig,
        )

        logger.info("Loading base model: %s", self.config.base_model)

        # Configure quantization
        if self.config.use_4bit:
            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_use_double_quant=True,
            )
        else:
            bnb_config = None

        # Load tokenizer
        self._tokenizer = AutoTokenizer.from_pretrained(  # nosec B615
            self.config.base_model,
            trust_remote_code=True,
        )
        if getattr(self._tokenizer, "pad_token", None) is None:
            setattr(self._tokenizer, "pad_token", getattr(self._tokenizer, "eos_token", None))

        # Load model
        self._model = AutoModelForCausalLM.from_pretrained(  # nosec B615
            self.config.base_model,
            quantization_config=bnb_config,
            device_map="auto",
            trust_remote_code=True,
        )

        if self.config.use_gradient_checkpointing:
            if hasattr(self._model, "gradient_checkpointing_enable"):
                self._model.gradient_checkpointing_enable()

        self._is_loaded = True
        logger.info("Model loaded: %s", self.config.base_model)

    def _prepare_peft_model(self) -> None:
        """Prepare model for PEFT training."""
        if self._peft_model is not None:
            return

        from peft import (
            LoraConfig,
            get_peft_model,
            prepare_model_for_kbit_training,
        )

        # Prepare for k-bit training
        self._model = prepare_model_for_kbit_training(self._model)

        # Configure LoRA
        lora_config = LoraConfig(
            r=self.config.lora_r,
            lora_alpha=self.config.lora_alpha,
            lora_dropout=self.config.lora_dropout,
            target_modules=self.config.target_modules,
            bias="none",
            task_type="CAUSAL_LM",
        )

        # Apply LoRA
        self._peft_model = get_peft_model(self._model, lora_config)

        trainable, total = self._peft_model.get_nb_trainable_parameters()
        logger.info(
            f"Trainable parameters: {trainable:,} / {total:,} ({100 * trainable / total:.2f}%)"
        )

    def _format_training_example(self, example: TrainingExample) -> str:
        """Format training example for the model."""
        if example.input_text:
            return (
                f"### Instruction:\n{example.instruction}\n\n"
                f"### Input:\n{example.input_text}\n\n"
                f"### Response:\n{example.output}"
            )
        else:
            return f"### Instruction:\n{example.instruction}\n\n### Response:\n{example.output}"

    def _prepare_dataset(self, data: TrainingData):
        """Prepare dataset for training."""
        from datasets import Dataset

        formatted = [{"text": self._format_training_example(ex)} for ex in data.examples]

        return Dataset.from_list(formatted)

    def train(self, data: TrainingData) -> FineTuneResult:
        """Train the model on provided data.

        Args:
            data: Training data

        Returns:
            Fine-tuning result with metrics
        """
        import time

        start_time = time.time()

        try:
            # Load model
            self._load_base_model()
            self._prepare_peft_model()

            tokenizer = self._tokenizer
            peft_model = self._peft_model
            if tokenizer is None or peft_model is None:
                raise RuntimeError(
                    "Model initialization did not produce a tokenizer and PEFT model"
                )

            # Prepare dataset
            dataset = self._prepare_dataset(data)

            from transformers import (
                TrainingArguments,
                Trainer,
                DataCollatorForLanguageModeling,
            )

            # Tokenize dataset
            def tokenize_function(examples):
                return tokenizer(
                    examples["text"],
                    truncation=True,
                    max_length=self.config.max_seq_length,
                    padding="max_length",
                )

            tokenized_dataset = dataset.map(
                tokenize_function,
                batched=True,
                remove_columns=dataset.column_names,
            )

            # Configure training
            training_args = TrainingArguments(
                output_dir=self.config.output_dir,
                num_train_epochs=self.config.epochs,
                per_device_train_batch_size=self.config.batch_size,
                gradient_accumulation_steps=self.config.gradient_accumulation_steps,
                learning_rate=self.config.learning_rate,
                warmup_steps=self.config.warmup_steps,
                logging_steps=self.config.logging_steps,
                save_steps=self.config.save_steps,
                fp16=True,
                report_to=[],  # Disable wandb etc
            )

            # Data collator
            data_collator = DataCollatorForLanguageModeling(
                tokenizer=tokenizer,
                mlm=False,
            )

            # Create trainer
            trainer = Trainer(
                model=peft_model,
                args=training_args,
                train_dataset=tokenized_dataset,
                data_collator=data_collator,
            )

            # Train
            logger.info("Starting training...")
            train_result = trainer.train()

            # Save model
            peft_model.save_pretrained(self.config.output_dir)
            tokenizer.save_pretrained(self.config.output_dir)

            training_time = time.time() - start_time

            return FineTuneResult(
                success=True,
                model_path=self.config.output_dir,
                metrics={
                    "train_loss": train_result.training_loss,
                    "epochs": self.config.epochs,
                    "examples": len(data),
                },
                training_time_seconds=training_time,
            )

        except Exception as e:  # noqa: BLE001 - torch/transformers raise library-specific exceptions
            logger.error("Training failed: %s", e)
            return FineTuneResult(
                success=False,
                model_path="",
                error=str(e),
                training_time_seconds=time.time() - start_time,
            )

    async def train_async(self, data: TrainingData) -> FineTuneResult:
        """Async wrapper for training."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.train, data)

    def load_trained_model(self, model_path: str) -> None:
        """Load a previously trained model.

        Args:
            model_path: Path to saved PEFT model
        """
        if not self._check_dependencies():
            raise ImportError("Required dependencies not installed")

        from peft import PeftModel
        import torch
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            BitsAndBytesConfig,
        )

        # Load base model
        if self.config.use_4bit:
            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.float16,
            )
        else:
            bnb_config = None

        self._model = AutoModelForCausalLM.from_pretrained(  # nosec B615
            self.config.base_model,
            quantization_config=bnb_config,
            device_map="auto",
            trust_remote_code=True,
        )

        # Load PEFT adapter
        self._peft_model = PeftModel.from_pretrained(  # nosec B615
            self._model,
            model_path,
        )

        # Load tokenizer
        self._tokenizer = AutoTokenizer.from_pretrained(  # nosec B615
            model_path,
            trust_remote_code=True,
        )

        self._is_loaded = True
        logger.info("Loaded fine-tuned model from %s", model_path)

    def generate(
        self,
        prompt: str,
        max_new_tokens: int = 256,
        temperature: float = 0.7,
        top_p: float = 0.9,
    ) -> str:
        """Generate text using the fine-tuned model.

        Args:
            prompt: Input prompt
            max_new_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            top_p: Nucleus sampling threshold

        Returns:
            Generated text
        """
        if not self._is_loaded:
            raise RuntimeError("Model not loaded. Call train() or load_trained_model() first.")

        model = self._peft_model if self._peft_model else self._model
        tokenizer = self._tokenizer
        if model is None or tokenizer is None:
            raise RuntimeError("Loaded model is missing its model or tokenizer")

        # Format prompt
        formatted_prompt = f"### Instruction:\n{prompt}\n\n### Response:\n"

        inputs = tokenizer(
            formatted_prompt,
            return_tensors="pt",
            truncation=True,
            max_length=self.config.max_seq_length,
        )
        device = getattr(model, "device", None)
        if device is not None:
            inputs = inputs.to(device)

        with __import__("torch").no_grad():
            pad_token_id = getattr(tokenizer, "pad_token_id", None)
            outputs = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=top_p,
                do_sample=True,
                pad_token_id=pad_token_id,
            )

        generated = tokenizer.decode(
            outputs[0][inputs["input_ids"].shape[1] :],
            skip_special_tokens=True,
        )

        return generated.strip()

    async def generate_async(
        self,
        prompt: str,
        max_new_tokens: int = 256,
        temperature: float = 0.7,
        top_p: float = 0.9,
    ) -> str:
        """Async wrapper for generation."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: self.generate(prompt, max_new_tokens, temperature, top_p)
        )


@dataclass
class DPOConfig(FineTuneConfig):
    """Configuration for Direct Preference Optimization training."""

    beta: float = 0.1  # DPO beta parameter
    reference_free: bool = False


class DPOFineTuner(LocalFineTuner):
    """Fine-tuner using Direct Preference Optimization.

    DPO learns from preference pairs (chosen vs rejected responses)
    without requiring a separate reward model.

    Best used when training data includes rejected alternatives.
    """

    def __init__(self, config: DPOConfig | None = None):
        super().__init__(config or DPOConfig())

    def train(self, data: TrainingData) -> FineTuneResult:
        """Train using DPO on preference data.

        Args:
            data: Training data with chosen/rejected pairs

        Returns:
            Fine-tuning result
        """
        # Filter to examples with rejected responses
        preference_data = TrainingData(
            examples=[ex for ex in data.examples if ex.rejected],
            task_type=FineTuneTask.PREFERENCE,
        )

        if not preference_data.examples:
            logger.warning("No preference pairs found, falling back to SFT")
            return super().train(data)

        import time

        start_time = time.time()

        try:
            self._load_base_model()
            self._prepare_peft_model()

            tokenizer = self._tokenizer
            peft_model = self._peft_model
            if tokenizer is None or peft_model is None:
                raise RuntimeError(
                    "Model initialization did not produce a tokenizer and PEFT model"
                )

            from trl import DPOTrainer
            from transformers import TrainingArguments

            # Prepare dataset
            from datasets import Dataset

            formatted = []
            for ex in preference_data.examples:
                formatted.append(
                    {
                        "prompt": ex.instruction + (f"\n{ex.input_text}" if ex.input_text else ""),
                        "chosen": ex.output,
                        "rejected": ex.rejected,
                    }
                )

            dataset = Dataset.from_list(formatted)

            # Configure DPO training
            training_args = TrainingArguments(
                output_dir=self.config.output_dir,
                num_train_epochs=self.config.epochs,
                per_device_train_batch_size=self.config.batch_size,
                gradient_accumulation_steps=self.config.gradient_accumulation_steps,
                learning_rate=self.config.learning_rate,
                warmup_steps=self.config.warmup_steps,
                logging_steps=self.config.logging_steps,
                save_steps=self.config.save_steps,
                fp16=True,
                report_to=[],
            )

            # Create DPO trainer
            dpo_config = getattr(self.config, "beta", 0.1)
            trainer = DPOTrainer(
                model=peft_model,
                args=training_args,
                train_dataset=dataset,
                tokenizer=tokenizer,
                beta=dpo_config,
            )

            # Train
            logger.info("Starting DPO training...")
            train_result = trainer.train()

            # Save
            peft_model.save_pretrained(self.config.output_dir)
            tokenizer.save_pretrained(self.config.output_dir)

            training_time = time.time() - start_time

            return FineTuneResult(
                success=True,
                model_path=self.config.output_dir,
                metrics={
                    "train_loss": train_result.training_loss,
                    "epochs": self.config.epochs,
                    "preference_pairs": len(preference_data),
                },
                training_time_seconds=training_time,
            )

        except ImportError:
            logger.warning("TRL not installed, falling back to SFT")
            return super().train(data)
        except Exception as e:  # noqa: BLE001 - torch/transformers raise library-specific exceptions
            logger.error("DPO training failed: %s", e)
            return FineTuneResult(
                success=False,
                model_path="",
                error=str(e),
                training_time_seconds=time.time() - start_time,
            )


# Factory function
def create_fine_tuner(
    method: str = "lora",
    config: FineTuneConfig | None = None,
) -> LocalFineTuner:
    """Create a fine-tuner instance.

    Args:
        method: Fine-tuning method ("lora" or "dpo")
        config: Optional configuration

    Returns:
        Fine-tuner instance
    """
    if method == "dpo":
        dpo_config = config if isinstance(config, DPOConfig) else DPOConfig()
        return DPOFineTuner(dpo_config)
    return LocalFineTuner(config or FineTuneConfig())
