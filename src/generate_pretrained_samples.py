import argparse
import datetime
import json
import os
import pytz
import subprocess
import torch
import uuid

from dotenv import find_dotenv, load_dotenv
from huggingface_hub import login
from tqdm import tqdm
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
)

load_dotenv(find_dotenv())

utc_time = datetime.datetime.now(datetime.timezone.utc)
time_string = utc_time.astimezone(pytz.timezone("US/Central"))
time_string = time_string.strftime("%m_%d_%y_%H_%M_%S")
uuid_identifier = uuid.uuid4()
identifier = "{}_{}".format(time_string, uuid_identifier)

hf_token = os.environ.get("HUGGINGFACE_TOKEN")
login(token=hf_token)


def main():
    print("\n--------------------\nStarting model evaluation!\n--------------------\n")

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fine_tune_model",
        type=str,
        default="meta-llama/Llama-3.2-1B-Instruct",
        help="HuggingFace path of the base model to be used",
    )
    parser.add_argument(
        "--test_data",
        type=str,
        default="prepared_data/test.jsonl",
        help="Test data to evaluate the fine-tuned model",
    )
    parser.add_argument(
        "--out_file",
        type=str,
        default="src/pretrained_samples.jsonl",
        help="Output file of generated samples",
    )
    args = parser.parse_args()
    print("Arguments: {}".format(vars(args)))
    print("--------------------")

    if torch.cuda.get_device_capability()[0] >= 8:
        subprocess.run(["pip3", "install", "-qqq", "flash-attn"], check=True)
        torch_dtype = torch.bfloat16
        attn_implementation = "flash_attention_2"
    else:
        torch_dtype = torch.float16
        attn_implementation = "eager"

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch_dtype,
        bnb_4bit_use_double_quant=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        args.fine_tune_model,
        quantization_config=bnb_config,
        device_map="auto",
        attn_implementation=attn_implementation,
    )
    tokenizer = AutoTokenizer.from_pretrained(
        args.fine_tune_model, trust_remote_code=True
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    with open(args.test_data) as llama_test:
        with open(args.out_file, "w") as samples:
            for l in tqdm(llama_test.readlines()):
                messages = json.loads(l[0:-1])["messages"]
                prompt = tokenizer.apply_chat_template(
                    messages[0:2], tokenize=False, add_generation_prompt=True
                )
                inputs = tokenizer(
                    prompt, return_tensors="pt", padding=True, truncation=True
                ).to("cuda")
                outputs = model.generate(
                    **inputs, max_new_tokens=150, num_return_sequences=1
                )
                preds = tokenizer.decode(outputs[0], skip_special_tokens=True)
                samples.write(
                    json.dumps(
                        {
                            "text": messages[1]["content"],
                            "sample": preds,
                            "gold": messages[2]["content"],
                        }
                    )
                    + "\n"
                )
    print("\n--------------------\nModel Evaluation completed!\n--------------------\n")


if __name__ == "__main__":
    main()
