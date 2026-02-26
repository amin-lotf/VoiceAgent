import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline
from langchain_huggingface import HuggingFacePipeline, ChatHuggingFace

model_path = "./models/gemma-3-4b-it"


tokenizer = AutoTokenizer.from_pretrained(model_path)

# Gemma typically doesn't have a pad token; set it to eos to avoid warnings / issues.
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

model = AutoModelForCausalLM.from_pretrained(
    model_path,
    device_map="auto",
    dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
)

gen_pipe = pipeline(
    task="text-generation",
    model=model,
    tokenizer=tokenizer,
    return_full_text=False,
)

llm = HuggingFacePipeline(pipeline=gen_pipe)

chat_model = ChatHuggingFace(
    llm=llm,
    # generation kwargs applied per call; you can also pass at invoke-time
    model_kwargs={
        "max_new_tokens": 256,        # keep short for patches
        "do_sample": False,           # IMPORTANT
        "repetition_penalty": 1.03,
        "eos_token_id": tokenizer.eos_token_id,
        "pad_token_id": tokenizer.pad_token_id,
    },
)