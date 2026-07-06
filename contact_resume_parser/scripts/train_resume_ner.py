#!/usr/bin/env python3
"""
Phase 1 — Fine-tune a HuggingFace NER model for resume parsing.

Prerequisites:
  pip install label-studio transformers datasets torch huggingface_hub
  label-studio start   # annotate resumes, export JSON

Usage:
  huggingface-cli login
  python train_resume_ner.py --train resume_train.json --test resume_test.json --hub yourname/resume-ner-odoo

Then in Odoo: Settings > Resume Parser > set HuggingFace model to yourname/resume-ner-odoo
"""

import argparse

LABELS = [
    "O", "B-NAME", "I-NAME", "B-EMAIL", "B-PHONE",
    "B-SKILLS", "I-SKILLS", "B-EXPERIENCE", "I-EXPERIENCE",
    "B-EDUCATION", "I-EDUCATION",
]


def main():
    parser = argparse.ArgumentParser(description="Train resume NER model for Odoo")
    parser.add_argument("--train", required=True, help="Training JSON from Label Studio")
    parser.add_argument("--test", required=True, help="Test JSON from Label Studio")
    parser.add_argument("--base-model", default="dslim/bert-base-NER")
    parser.add_argument("--hub", default="", help="HuggingFace hub model id, e.g. yourname/resume-ner-odoo")
    parser.add_argument("--epochs", type=int, default=5)
    args = parser.parse_args()

    from datasets import load_dataset
    from transformers import (
        AutoModelForTokenClassification,
        AutoTokenizer,
        Trainer,
        TrainingArguments,
    )

    label2id = {label: index for index, label in enumerate(LABELS)}
    id2label = {index: label for index, label in enumerate(LABELS)}

    tokenizer = AutoTokenizer.from_pretrained(args.base_model)
    model = AutoModelForTokenClassification.from_pretrained(
        args.base_model,
        num_labels=len(LABELS),
        id2label=id2label,
        label2id=label2id,
        ignore_mismatched_sizes=True,
    )

    dataset = load_dataset(
        "json",
        data_files={"train": args.train, "test": args.test},
    )

    training_args = TrainingArguments(
        output_dir="./resume-ner-model",
        num_train_epochs=args.epochs,
        per_device_train_batch_size=8,
        learning_rate=2e-5,
        weight_decay=0.01,
        eval_strategy="epoch",
        save_strategy="epoch",
        push_to_hub=bool(args.hub),
        hub_model_id=args.hub or None,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=dataset["train"],
        eval_dataset=dataset["test"],
    )
    trainer.train()
    if args.hub:
        trainer.push_to_hub()
        print("Model pushed to HuggingFace Hub:", args.hub)
    else:
        trainer.save_model("./resume-ner-model")
        print("Model saved to ./resume-ner-model")


if __name__ == "__main__":
    main()
