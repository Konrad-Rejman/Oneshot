'''
QLoRA fine-tune of the GM model (ROADMAP 3.2) - free-tier cloud script.

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
     download gm-istral.Q4_K_M.gguf from the output pane.
  6. Locally, next to the downloaded file:
       ollama create gm-istral-v01 -f training/Modelfile
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
DATASET_PATH = '/kaggle/input/datasets/konradrejman/mistral-gm-json/dataset.jsonl'
OUTPUT_GGUF_DIR = 'gm-istral' # final Q4_K_M GGUF lands here (download it)
ADAPTER_DIR = 'gm-istral-lora'       # LoRA adapter saved here before the export
GGUF_BUILD_DIR = '/tmp/gm-istral-build'  # scratch for the f16 intermediate, off
                                     # the capped /kaggle/working volume (/tmp is
                                     # on the larger root overlay; /kaggle/temp
                                     # does not exist on all Kaggle images)
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
    from trl import SFTConfig, SFTTrainer
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

    # TRL on transformers 5.x takes the SFT knobs via SFTConfig (not the
    # SFTTrainer constructor) and the tokenizer as processing_class. The
    # sequence-length cap is named max_seq_length on some versions and
    # max_length on others; set whichever the installed SFTConfig exposes so a
    # too-small default can never truncate a response.
    sft_args = SFTConfig(
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
        dataset_text_field='text',
    )
    for length_attr in ('max_length', 'max_seq_length'):
        if hasattr(sft_args, length_attr):
            setattr(sft_args, length_attr, MAX_SEQ_LENGTH)

    trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        train_dataset=dataset,
        args=sft_args,
    )
    # Mask loss to everything after [/INST]: the model is graded only on the
    # GM reply, never on reproducing the prompt.
    trainer = train_on_responses_only(
        trainer, instruction_part='[INST]', response_part='[/INST]')

    stats = trainer.train()
    print(f"Training done: {stats.metrics.get('train_loss', '?')} final loss. "
          'Sanity-check that loss decreased before exporting.')

    import os
    import shutil

    # Save the LoRA adapter first - it is tiny (~100-200 MB) and is the
    # trained result. If the disk-heavy GGUF export below fails (e.g. a capped
    # output volume), this survives so the conversion can be redone without
    # retraining: reload BASE_MODEL, model.load_adapter(ADAPTER_DIR), then
    # save_pretrained_gguf.
    model.save_pretrained(ADAPTER_DIR)
    tokenizer.save_pretrained(ADAPTER_DIR)
    print(f'LoRA adapter saved under {ADAPTER_DIR}/')

    # Reclaim space before the GGUF export. Merging the adapter writes a full
    # f16 copy of the 7B (~14.5 GB) and the converter writes another, so the
    # training checkpoints have to go or a capped volume (Kaggle's /kaggle/
    # working is ~19.5 GB) runs out mid-write.
    shutil.rmtree('outputs', ignore_errors=True)

    # The GGUF export needs ~28 GB of transient space at once: the merged f16
    # safetensors model AND the f16 GGUF intermediate. The converter writes
    # the latter with a path relative to the *current working directory*, so
    # pointing only the output dir at scratch is not enough - the whole export
    # must run with cwd inside the roomy scratch volume (Unsloth's own error
    # advises "save to /tmp"). chdir there, build with a relative dir name so
    # both transients land in scratch, then copy only the final Q4_K_M
    # (~4.4 GB) back to OUTPUT_GGUF_DIR on the capped output volume.
    output_dir = os.path.abspath(OUTPUT_GGUF_DIR)
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(GGUF_BUILD_DIR, exist_ok=True)
    prev_cwd = os.getcwd()
    os.chdir(GGUF_BUILD_DIR)
    try:
        model.save_pretrained_gguf('gguf_out', tokenizer,
                                   quantization_method='q4_k_m')
        # Unsloth writes to "<dir>_gguf/" and names the file after the base
        # model, so search the whole scratch tree (cwd) rather than a guessed
        # path, and copy out (before the finally clears scratch) under the
        # name the Modelfile's FROM line expects.
        copied = False
        for root, _dirs, files in os.walk('.'):
            for name in files:
                if name.lower().endswith('.gguf') and 'q4_k_m' in name.lower():
                    dst = os.path.join(output_dir, 'gm-istral.Q4_K_M.gguf')
                    shutil.copy(os.path.join(root, name), dst)
                    print(f'Q4_K_M GGUF copied to {dst}')
                    copied = True
        if not copied:
            raise RuntimeError('No Q4_K_M .gguf found under the build dir - '
                               'nothing was copied out.')
    finally:
        os.chdir(prev_cwd)
        shutil.rmtree(GGUF_BUILD_DIR, ignore_errors=True)
    print(f'Download gm-istral.Q4_K_M.gguf from {OUTPUT_GGUF_DIR}/ and run '
          '"ollama create gm-istral-v01 -f training/Modelfile" locally.')


if __name__ == '__main__':
    main()
