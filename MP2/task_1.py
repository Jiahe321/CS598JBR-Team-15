import jsonlines
import sys
import torch
import re
import random
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig

#####################################################
# Please finish all TODOs in this file for MP2;
#####################################################

def save_file(content, file_path):
    with open(file_path, 'w') as file:
        file.write(content)

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
        test_code = entry.get("test", "")

        matches = re.findall(r"assert\s+candidate\((.*?)\)\s*==\s*(.*?)(?=\n|$)", test_code)

        if matches:
            input_str, expected_raw = random.choice(matches)
            input_str = input_str.strip()
            expected_raw = expected_raw.strip()
            
            err_match = re.search(r'^(.*?)(?:,\s*["\'].*?["\'])\s*$', expected_raw)
            if err_match:
                expected_str = err_match.group(1).strip()
            else:
                expected_str = expected_raw
        else:
            input_str = ""
            expected_str = ""

        def_match = re.search(r'(def\s+\w+\s*\(.*?\)\s*(?:->\s*[^:]+)?:)', entry["prompt"], re.DOTALL)
        if def_match:
            func_signature = def_match.group(1)
        else:
            func_signature = entry["prompt"].strip().split('\n')[0]

        full_code = func_signature + "\n" + entry["canonical_solution"]

        if vanilla:
          prompt = """You are an AI programming assistant. You are an AI programming assistant, utilizing the DeepSeek Coder model, developed by DeepSeek Company, and you only answer questions related to computer science. For politically sensitive questions, security and privacy issues, and other non-computer science questions, you will refuse to answer.

### Instruction:
If the string is {selected_candidate}, what will the following code return?
The return value prediction must be enclosed between [Output] and [/Output] tags. For example: [Output]prediction[/Output]

{full_code}

### Response:"""
        prompt = prompt.format(selected_candidate=repr(input_str), full_code=full_code)

        # TODO: prompt the model and get the response
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)

        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_length=800,
                do_sample=False,
                temperature=0,
                pad_token_id=tokenizer.eos_token_id
            )

        response = tokenizer.decode(
            outputs[0][inputs["input_ids"].shape[1]:],
            skip_special_tokens=True
        )

        # TODO: process the response and save it to results
        m = re.search(r"\[Output\]\s*(.*?)\s*\[/Output\]", response, re.DOTALL)
        if not m:
          m = re.search(r"\[Output\]\s*(.+?)(?:\n|$)", response)
        model_result = m.group(1).strip() if m else ""

        verdict = False

        # For debug
        print(model_result, expected_str)

        if model_result == expected_str:
          verdict = True

        print(f"Task_ID {entry['task_id']}:\nprompt:\n{prompt}\nresponse:\n{response}\nis_correct:\n{verdict}")
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
    This Python script is to run prompt LLMs for code synthesis.
    Usage:
    `python3 Task_1.py <input_dataset> <model> <output_file> <if_vanilla>`|& tee prompt.log

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
