import jsonlines
import sys
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
import re

#####################################################
# Please finish all TODOs in this file for MP3/task_2;
#####################################################

def save_file(content, file_path):
    with open(file_path, 'w') as file:
        file.write(content)


def parse_prediction(response):
    predictions = re.findall(
        r"<start>\s*(buggy|correct)\s*<end>", response, re.IGNORECASE
    )
    if predictions:
        return predictions[-1].casefold(), "tags"

    # Like task_1, accept a prediction whose closing tag was omitted.
    match = re.search(
        r"<start>\s*(buggy|correct)\s*[.!]?\s*$", response, re.IGNORECASE
    )
    if match:
        return match.group(1).casefold(), "partial_tag"

    # Ignore code examples and repairs when looking for a prose conclusion.
    prose = re.sub(r"```.*?(?:```|$)", "", response, flags=re.DOTALL)
    conclusions = re.findall(
        r"\b(?:the\s+)?(?:final\s+)?(?:prediction|answer|verdict|conclusion)"
        r"\s*(?:is|should\s+be|:)\s*[\"'`*]*(buggy|correct)\b",
        prose, re.IGNORECASE
    )
    if conclusions:
        return conclusions[-1].casefold(), "text_conclusion"

    statements = re.findall(
        r"\b(?:the|this)\s+(?:(?:above|provided|given|original|current)\s+)?"
        r"(?:code|function|implementation|program)\s+is\s+"
        r"(not\s+)?(buggy|correct)\b", prose, re.IGNORECASE
    )
    labels = set()
    for negation, label in statements:
        label = label.casefold()
        if negation:
            label = "correct" if label == "buggy" else "buggy"
        labels.add(label)
    if len(labels) == 1:
        return labels.pop(), "text_statement"
    return "", "ambiguous" if labels else "missing"


def prompt_model(dataset, model_name = "deepseek-ai/deepseek-coder-6.7b-instruct", vanilla = True):
    print(f"Working with {model_name} prompt type {vanilla}...")
    
    # TODO: download the model
    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    # TODO: load the model with quantization
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        trust_remote_code=True,
        device_map='auto',
        torch_dtype=torch.bfloat16,
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type='nf4'
        ),
    )
    
    results = []
    for entry in dataset:
        # TODO: create prompt for the model
        # Tip : Use can use any data from the dataset to create 
        #       the prompt including prompt, canonical_solution, test, etc.
        full_code = entry["declaration"] + "\n" + entry["buggy_solution"]
        if vanilla:
            prompt = """You are an AI programming assistant. You are an AI programming assistant utilizing the DeepSeek Coder model, developed by DeepSeek Company, and you only answer questions related to computer science. For politically sensitive questions, security and privacy issues, and other non-computer science questions, you will refuse to answer.
### Instruction:

{full_code}
Is the above code buggy or correct? Please explain your step by step reasoning. The prediction should be enclosed within <start> and <end> tags. For example: <start>Buggy<end>
### Response:"""
        else:
            prompt = ""

        prompt = prompt.replace("{full_code}", full_code)
        
        # TODO: prompt the model and get the response
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=1024,
                do_sample=False,
                pad_token_id=tokenizer.eos_token_id
            )
        generated_tokens = outputs[0][inputs["input_ids"].shape[1]:]
        response = tokenizer.decode(generated_tokens, skip_special_tokens=True)

        # TODO: process the response and save it to results
        model_result, prediction_source = parse_prediction(response)
        # Every input uses buggy_solution, so its ground-truth label is Buggy.
        # Only responses without a recoverable, unambiguous label are invalid.
        verdict = (model_result == "buggy")

        print(f"Task_ID {entry['task_id']}: prediction={model_result or 'unknown'}, "
              f"prediction_source={prediction_source}, generated_tokens={len(generated_tokens)}, "
              f"hit_token_limit={len(generated_tokens) >= 1024}")
        print(f"Task_ID {entry['task_id']}:\nprompt:\n{prompt}\nresponse:\n{response}\nis_expected:\n{verdict}")
        results.append({
            "task_id": entry["task_id"],
            "prompt": prompt,
            "response": response,
            "is_correct": verdict
        })
        
    return results

def read_jsonl(file_path):
    dataset = []
    with jsonlines.open(file_path) as reader:
        for line in reader: 
            dataset.append(line)
    return dataset

def write_jsonl(results, file_path):
    with jsonlines.open(file_path, "w") as f:
        for item in results:
            f.write_all([item])

if __name__ == "__main__":
    """
    This Python script is to run prompt LLMs for bug detection.
    Usage:
    `python3 task_2.py <input_dataset> <model> <output_file> <if_vanilla>`|& tee prompt.log

    Inputs:
    - <input_dataset>: A `.jsonl` file, which should be your team's dataset containing 20 HumanEval problems.
    - <model>: Specify the model to use. Options are "deepseek-ai/deepseek-coder-6.7b-base" or "deepseek-ai/deepseek-coder-6.7b-instruct".
    - <output_file>: A `.jsonl` file where the results will be saved.
    - <if_vanilla>: Set to 'True' or 'False' to enable vanilla prompt
    
    Outputs:
    - You can check <output_file> for detailed information.
    """
    args = sys.argv[1:]
    input_dataset = args[0]
    model = args[1]
    output_file = args[2]
    if_vanilla = args[3] # True or False
    
    if not input_dataset.endswith(".jsonl"):
        raise ValueError(f"{input_dataset} should be a `.jsonl` file!")
    
    if not output_file.endswith(".jsonl"):
        raise ValueError(f"{output_file} should be a `.jsonl` file!")
    
    vanilla = True if if_vanilla == "True" else False
    
    dataset = read_jsonl(input_dataset)
    results = prompt_model(dataset, model, vanilla)
    write_jsonl(results, output_file)
