import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline, GenerationConfig
from langchain_huggingface import HuggingFacePipeline, ChatHuggingFace

model_path = "./models/gemma-3-4b-it"

tokenizer = AutoTokenizer.from_pretrained(model_path)
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

model = AutoModelForCausalLM.from_pretrained(
    model_path,
    device_map="auto",
    dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
)

# hard reset both configs
if hasattr(model.config, "max_length"):
    model.config.max_length = None
if hasattr(model.generation_config, "max_length"):
    model.generation_config.max_length = None
if hasattr(model.generation_config, "max_new_tokens"):
    model.generation_config.max_new_tokens = None

# 1. Clean pipeline - NO generation parameters here
gen_pipe = pipeline(
    task="text-generation",
    model=model,
    tokenizer=tokenizer,
    return_full_text=False,
    # Do NOT add max_new_tokens, do_sample, generation_config, etc.
)

# 2. All generation settings go here
llm = HuggingFacePipeline(
    pipeline=gen_pipe,
    pipeline_kwargs={
        "max_new_tokens": 256,          # ← change this as needed (80 is quite short)
        "max_length": None,             # helps silence the old max_length warning
        "do_sample": False,
        "repetition_penalty": 1.03,
        "eos_token_id": tokenizer.eos_token_id,
        "pad_token_id": tokenizer.pad_token_id,
    },
)

agent_model = ChatHuggingFace(llm=llm)