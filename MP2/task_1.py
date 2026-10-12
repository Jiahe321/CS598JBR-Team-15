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
        import ast, math
        test_code = entry.get("test", "")

        # Ground truth = run the canonical solution on inputs taken from the test code.
        # The prompt prefix (imports / helper functions) is executed together with the solution.
        env = {}
        exec(entry["prompt"] + entry["canonical_solution"], env)
        solution = env[entry["entry_point"]]
        exec(test_code, env)

        # Collect every `candidate(...)` call in the test (works for ==, abs(...) < eps, assert not, ...)
        candidates = []
        for node in ast.walk(ast.parse(test_code)):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "candidate" and node.args and not node.keywords):
                try:
                    arg_srcs = [ast.get_source_segment(test_code, a) for a in node.args]
                    arg_vals = [eval(s, env) for s in arg_srcs]      # fails (skipped) if args use loop vars etc.
                    expected_val = solution(*arg_vals)
                    ast.literal_eval(repr(expected_val))             # keep only literal-comparable outputs
                    arg_str = ", ".join(arg_srcs)
                    if len(arg_str) <= 200 and len(repr(expected_val)) <= 200:
                        candidates.append((arg_str, expected_val))
                except Exception:
                    continue

        if candidates:
            # Fix Seed
            rng = random.Random(f"{42}-{entry['task_id']}")
            selected_candidate, expected_val = rng.choice(candidates)
            expected_str = repr(expected_val)
        else:
            selected_candidate = ""
            expected_val = None
            expected_str = ""

        # Signature of the entry-point function (docstring dropped, so examples do not leak the answer);
        # everything before it in the prompt (imports / helper functions) is kept.
        def_match = re.search(r'(def\s+' + re.escape(entry["entry_point"]) + r'\s*\(.*?\)\s*(?:->\s*[^:]+)?:)', entry["prompt"], re.DOTALL)
        if def_match:
            func_signature = entry["prompt"][:def_match.start()] + def_match.group(1)
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
        else:
          prompt = """You are an AI programming assistant, utilizing the DeepSeek Coder model, developed by DeepSeek Company, and you only answer questions related to computer science. For politically sensitive questions, security and privacy issues, and other non-computer science questions, you will refuse to answer.
### Instruction:
Predict what the code returns for the given input by tracing it step by step, exactly like a Python interpreter would.
1. Write down the input values, then trace the execution line by line (loops iteration by iteration). After every change, write the new value of each affected variable. Do all arithmetic explicitly.
2. Only after the trace, give the final result as a Python literal: strings in quotes, lists in brackets, True/False/None, floats as Python prints them (e.g. 2.0).
3. The final answer must be enclosed ONCE between [Output] and [/Output] tags, e.g. [Output]prediction[/Output], and nothing may be written after [/Output].

### Example
## Code
def f(nums, k):
    out = []
    for n in nums:
        if n % k == 0:
            out.append(n / k)
    return out

## Question
If the input is [4, 7, 8], 2, what will the code return?

## Response:
nums = [4, 7, 8], k = 2, out = [].
n = 4: 4 % 2 = 0, so append 4 / 2 = 2.0, out = [2.0].
n = 7: 7 % 2 = 1, not appended, out = [2.0].
n = 8: 8 % 2 = 0, so append 8 / 2 = 4.0, out = [2.0, 4.0].
The function returns out = [2.0, 4.0].
[Output][2.0, 4.0][/Output]

### Now solve this one
## Code
{full_code}

## Question
If the input is {selected_candidate}, what will the code return?

### Response:
"""
        prompt = prompt.format(selected_candidate=selected_candidate, full_code=full_code)

        # TODO: prompt the model and get the response
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)

        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=512,
                do_sample=False,
                pad_token_id=tokenizer.eos_token_id
            )

        response = tokenizer.decode(
            outputs[0][inputs["input_ids"].shape[1]:],
            skip_special_tokens=True
        )

        # TODO: process the response and save it to results
        outs = re.findall(r"\[Output\]\s*(.*?)\s*\[/Output\]", response, re.DOTALL)
        if outs:
          # vanilla: first answer; step-by-step prompt: the final answer comes last
          model_result = (outs[0] if vanilla else outs[-1]).strip().strip("`").strip()
        else:
          m = re.search(r"\[Output\]\s*(.+?)(?:\n|$)", response)
          model_result = m.group(1).strip().strip("`").strip() if m else ""

        verdict = False

        # For debug
        print(model_result, expected_str)

        # Compare values, not strings: 'a' vs "a", 1.0 vs 1.00, spacing in lists, ...
        try:
          model_val = ast.literal_eval(model_result)
          if isinstance(expected_val, float) and isinstance(model_val, (int, float)) and not isinstance(model_val, bool):
            verdict = math.isclose(model_val, expected_val, rel_tol=1e-3, abs_tol=1e-3)
          else:
            verdict = (model_val == expected_val and type(model_val) == type(expected_val))
        except Exception:
          verdict = (model_result == expected_str)

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
