# Training Data & Fine-Tuning Compliance (UK)

This note records the decisions that keep the Phase 3 fine-tuning pipeline
compliant with UK copyright and data law for a publicly accessible project,
while leaving future commercialisation open. It is a good-faith engineering
record, not legal advice.

## Summary of the position

Every sentence of training data is generated locally by the project's own
base model (`mistral:instruct`, i.e. Mistral-7B-Instruct, Apache 2.0). No
third-party dataset, scraped text, published adventure module, or other
copyrighted work is copied into the dataset. Because no third-party work is
reproduced, no copyright permission or exception is needed in the first
place.

## Decisions and rationale

1. **Synthetic-only dataset, self-distilled from the base model.**
   The generator (`generate_dataset.py`) has Mistral-7B-Instruct write the
   story summary, the opening scene, the player action and the GM narration
   for every example. Mistral AI distributes these weights under Apache 2.0,
   which places no restriction on the use of the model's outputs, and the
   outputs are produced on local hardware under no additional terms of
   service. Training Mistral on its own filtered outputs (self-distillation)
   introduces no third-party rights into the chain.

   The only non-model text in a record is mechanical scaffolding the
   project's own code computes from the spec parameters: the check
   announcement ("Roll a Strength check... you roll a 14.") and the STATE
   bookkeeping line ("STATE: HP -3; XP +25"), built deterministically in
   `outcomes.py`. These are fixed-format game mechanics, not creative prose —
   the same category as the structural parameters in `specs.py` (point 2) —
   and fall below the originality threshold for copyright in any event. No
   assistant-generated text is involved.

2. **No assistant-authored prose in the dataset.**
   The pipeline code was written with Claude Code, but no Claude-generated
   text enters the dataset — Anthropic's terms restrict using Claude outputs
   to train competing AI models, and keeping that text out of the dataset
   avoids the question entirely. What the project's own code contributes is
   structural parameters only (`specs.py`: single-word locations, generic
   verb phrases, item nouns), which fall below the originality threshold for
   copyright protection in any event.

3. **No Wizards of the Coast content.**
   The roadmap's SRD 5.1 option (CC BY 4.0) was considered and deliberately
   dropped: the game uses its own simplified rules (1–10 stats, 5-tier D20
   consequences), so SRD text adds little, and excluding it means the
   dataset needs no attribution chain at all. Even feature names in
   `specs.py` are generic phrases rather than SRD terms.

4. **No personal data.**
   The dataset contains only generated fantasy fiction about invented
   characters; UK GDPR is not engaged.

5. **Ownership of the dataset and the adapter.**
   Under section 9(3) CDPA 1988 the UK treats the author of a
   computer-generated work as the person who made the arrangements for its
   creation — here, the project owner running the pipeline. (This provision
   is under review by the UK IPO, so treat it as a helpful default rather
   than a guarantee.) Nothing upstream restricts commercial use of the
   dataset or of a model fine-tuned on it.

6. **Distribution.**
   The fine-tuned weights are **not published**; the public repository
   carries only the pipeline code and this documentation, so anyone can
   reproduce the dataset and model themselves. If the weights are ever
   distributed, Apache 2.0 requires shipping the `NOTICE` file in this
   directory (crediting Mistral AI) alongside them; the dataset itself
   would need no further attribution.

## If the dataset composition ever changes

Re-check this file before adding any external source. The bar that keeps
commercialisation open: an express licence permitting commercial use and
derivative works (Apache 2.0, MIT, CC BY), verified on the actual dataset
card — never an assumption, and never reliance on section 29A.
