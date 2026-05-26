from transformers import AutoTokenizer, AutoModelForCausalLM
import torch

# Load Model
MODEL_NAME = 'mistralai/Mistral-7B-Instruct-v0.3'

tokenizer = AutoTokenizer.from_pretrained(
    MODEL_NAME,
    trust_remote_code=True
)

model = AutoModelForCausalLM.from_pretrained(
    MODEL_NAME,
    dtype=torch.float16,
    device_map='auto',
    trust_remote_code=True
)

model.eval()

# Model call function
def generate_response(memory):

    prompt = tokenizer.apply_chat_template(
        memory,
        tokenize=False,
        add_generation_prompt=True
    )

    inputs = tokenizer(
        prompt,
        return_tensors='pt'
    ).to(model.device)

    prompt_tokens = inputs.input_ids.shape[1]

    with torch.no_grad():

        output = model.generate(
            **inputs,
            max_new_tokens=250,
            temperature=0.8,
            do_sample=True,
            pad_token_id=tokenizer.eos_token_id
        )

    generated = output[0][prompt_tokens:]

    response = tokenizer.decode(
        generated,
        skip_special_tokens=True
    )

    return response.strip(), prompt_tokens