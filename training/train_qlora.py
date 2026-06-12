'''QLoRA fine-tune of the GM model (ROADMAP 3.2) - free-tier cloud script.

This does NOT run on the development machine (6 GB VRAM is too small and
Unsloth needs Linux); it is written for a free Kaggle GPU notebook:

  1. Generate the dataset locally first:
       python -m training.generate_dataset --n 300
  2. kaggle.com -> Create -> Notebook; in settings pick Accelerator: GPU T4.
  3. Upload training/data/dataset.jsonl as a Dataset (private) and attach it
     to the notebook; set DATASET_PATH below to its mounted path.
  4. In the first cell:  %pip install unsloth
     In the second cell: %run train_qlora.py   (upload this file too)
  5. After training (roughly 1-2 hours for 300 examples x 3 epochs on a T4)
     download oneshot-gm.Q4_K_M.gguf from the output pane.
  6. Locally, next to the downloaded file:
       ollama create oneshot-gm -f training/Modelfile
     The game's startup menu then offers the fine-tuned model (model.py).

Base model: unsloth's 4-bit quantisation of Mistral-7B-Instruct-v0.3 (Apache
2.0) - the same weights `ollama pull mistral:instruct` serves, so the LoRA
trains on exactly the model the game runs. Hyperparameters follow the
roadmap (r=16, alpha=32, 4-bit, seq 2048, lr 2e-4).

The dataset's "prompt" field is already the full production prompt string
(rules + sheet + STATUS + rolls + summary + history + action, flattened by
model._build_prompt_from_memory); here it is only wrapped in Mistral's
[INST] template, which is what Ollama's template wraps it in at inference.
Loss is masked to the response tokens (train_on_responses_only), so the
model learns to write GM replies, not to reproduce prompts.
'''

BASE_MODEL = 'unsloth/mistral-7b-instruct-v0.3-bnb-4bit'
DATASET_PATH = 'dataset.jsonl'       # adjust to /kaggle/input/<dataset>/dataset.jsonl
OUTPUT_GGUF_DIR = 'oneshot-gm'       # produces oneshot-gm/*.Q4_K_M.gguf
MAX_SEQ_LENGTH = 2048
LORA_R = 16
LORA_ALPHA = 32
LEARNING_RATE = 2e-4
EPOCHS = 3


def main():
    # Imported inside main so the repo's test suite can import the module
    # tree without the training stack installed.
    import json

    from datasets import Dataset
    from transformers import TrainingArguments
    from trl import SFTTrainer
    from unsloth import FastLanguageModel
    from unsloth.chat_templates import train_on_responses_only

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=BASE_MODEL,
        max_seq_length=MAX_SEQ_LENGTH,
        load_in_4bit=True,
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r=LORA_R,
        lora_alpha=LORA_ALPHA,
        lora_dropout=0,
        target_modules=['q_proj', 'k_proj', 'v_proj', 'o_proj',
                        'gate_proj', 'up_proj', 'down_proj'],
        bias='none',
        use_gradient_checkpointing='unsloth',
        random_state=3407,
    )

    with open(DATASET_PATH, encoding='utf-8') as f:
        records = [json.loads(line) for line in f]
    print(f'{len(records)} training examples from {DATASET_PATH}')

    # Mistral instruct template; the tokenizer adds the leading BOS itself.
    def to_text(record):
        return {'text': f"[INST] {record['prompt']} [/INST] {record['response']}"
                        f"{tokenizer.eos_token}"}

    dataset = Dataset.from_list([to_text(r) for r in records])

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        dataset_text_field='text',
        max_seq_length=MAX_SEQ_LENGTH,
        args=TrainingArguments(
            per_device_train_batch_size=2,
            gradient_accumulation_steps=4,
            num_train_epochs=EPOCHS,
            learning_rate=LEARNING_RATE,
            lr_scheduler_type='linear',
            warmup_steps=10,
            logging_steps=5,
            optim='adamw_8bit',
            seed=3407,
            output_dir='outputs',
            report_to='none',
        ),
    )
    # Mask loss to everything after [/INST]: the model is graded only on the
    # GM reply, never on reproducing the prompt.
    trainer = train_on_responses_only(
        trainer, instruction_part='[INST]', response_part='[/INST]')

    stats = trainer.train()
    print(f"Training done: {stats.metrics.get('train_loss', '?')} final loss. "
          'Sanity-check that loss decreased before exporting.')

    # Merge the adapter and export a Q4_K_M GGUF for Ollama in one step.
    model.save_pretrained_gguf(OUTPUT_GGUF_DIR, tokenizer,
                               quantization_method='q4_k_m')
    print(f'GGUF written under {OUTPUT_GGUF_DIR}/ - download it and run '
          '"ollama create oneshot-gm -f training/Modelfile" locally.')


if __name__ == '__main__':
    main()
