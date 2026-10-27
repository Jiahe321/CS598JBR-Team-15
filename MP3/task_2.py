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
            # Crafted prompt: include the docstring (the specification), prescribe explicit
            # reasoning steps, and give one buggy and one correct worked example.
            full_code = entry["prompt"] + entry["buggy_solution"]
            prompt = """You are an AI programming assistant. You are an AI programming assistant utilizing the DeepSeek Coder model, developed by DeepSeek Company, and you only answer questions related to computer science. For politically sensitive questions, security and privacy issues, and other non-computer science questions, you will refuse to answer.
### Instruction:

Below is a Python function with a docstring that specifies its intended behavior. Decide whether the implementation is Buggy (it violates the docstring for at least one input) or Correct (it matches the docstring for every input).

Be a strict code reviewer. Implementations in this task often contain one small hidden bug: a wrong comparison or arithmetic operator, a wrong variable, a wrong constant or index, a missing step (such as a missing abs, sort, strip or return), or an extra condition. Code that looks reasonable can still be buggy.

Follow these steps exactly:
Step 1 - Requirements: list every behavior the docstring requires as R1, R2, ... (what is returned, ordering, rounding, handling of special or edge inputs).
Step 2 - Check each requirement: for each Ri, quote the exact line of code that implements it, then write OK only if that line does exactly what Ri says. Write VIOLATED if the line is missing, uses the wrong operator, variable or constant, or does something extra.
Step 3 - Example: run the first docstring example through the code one statement at a time. Write "Expected:" with the output copied from the docstring and "Actual:" with the value the code really produces. Do not copy the expected value into Actual.
Step 4 - Decision: answer Buggy if any requirement is VIOLATED, if Expected differs from Actual, or if you could not verify some requirement. Answer Correct only if every requirement is OK and Expected equals Actual.
Write the final prediction within <start> and <end> tags, for example <start>Buggy<end>, and stop writing after that tag.

Example 1:
def count_even(numbers: List[int]) -> int:
    \"\"\" Return how many numbers in the list are even.
    >>> count_even([1, 2, 4])
    2
    \"\"\"
    count = 0
    for n in numbers:
        if n % 2 == 1:
            count += 1
    return count
Step 1 - Requirements: R1: count the even numbers. R2: return the count as an integer.
Step 2 - Check: R1: `if n % 2 == 1:` selects odd numbers, so VIOLATED. R2: `return count` returns an integer, OK.
Step 3 - Example: for [1, 2, 4], only 1 satisfies n % 2 == 1, so count is 1. Expected: 2. Actual: 1.
Step 4 - Decision: R1 is VIOLATED and Expected differs from Actual.
<start>Buggy<end>

Example 2:
def sum_abs(numbers: List[int]) -> int:
    \"\"\" Return the sum of the absolute values of the numbers.
    >>> sum_abs([-1, 2, -3])
    6
    \"\"\"
    total = 0
    for n in numbers:
        total += n
    return total
Step 1 - Requirements: R1: add up the absolute value of every number. R2: return the total.
Step 2 - Check: R1: `total += n` adds n itself and never takes the absolute value, so VIOLATED. R2: `return total` is OK.
Step 3 - Example: for [-1, 2, -3], total is -1 + 2 - 3 = -2. Expected: 6. Actual: -2.
Step 4 - Decision: R1 is VIOLATED and Expected differs from Actual.
<start>Buggy<end>

Now analyze this function:
{full_code}
### Response:"""

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
