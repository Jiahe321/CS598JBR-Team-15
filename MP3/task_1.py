import jsonlines
import sys
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
import re
import tempfile
import os
import subprocess

#####################################################
# Please finish all TODOs in this file for MP3/task_1;
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

    import glob
 
    def _num(task_id):
        return str(task_id).split("/")[-1]
 
    needed = {_num(e["task_id"]) for e in dataset}
    java_map = {}
    script_dir = os.path.dirname(os.path.abspath(__file__))
    search_dirs = [os.getcwd(), script_dir, os.path.dirname(script_dir)]
    for dd in search_dirs:
        for path in sorted(glob.glob(os.path.join(dd, "selected_humanevalx_java_*.jsonl"))):
            with jsonlines.open(path) as reader:
                recs = {_num(r["task_id"]): r for r in reader}
            if needed <= set(recs):
                java_map = recs
                break
        if java_map:
            break

    results = []
    for entry in dataset:
        # TODO: create prompt for the model
        # Tip : Use can use any data from the dataset to create 
        #       the prompt including prompt, canonical_solution, test, etc.
        # Java declaration / test for this problem (HumanEval/N <-> Java/N)
        java_rec = java_map[_num(entry["task_id"])]
        test_code = java_rec["test"]
        java_decl = java_rec["declaration"]
 
        # Signature of the (last) Python function in the prompt (docstring dropped, so examples
        # do not leak the answer); everything before it (imports / helper functions) is kept.
        fn_name = re.escape(entry["entry_point"]) if entry.get("entry_point") else r"\w+"
        def_matches = list(re.finditer(
            r'def\s+' + fn_name + r'\s*\(.*?\)\s*(?:->\s*[^:]+)?:',
            entry["prompt"], re.DOTALL
        ))
        if def_matches:
            dm = def_matches[-1]
            func_signature = entry["prompt"][:dm.start()] + dm.group(0)
        else:
            func_signature = entry["prompt"].strip().split('\n')[0]
        full_code = func_signature + "\n" + entry["canonical_solution"]

        if vanilla:
            prompt = """You are an AI programming assistant utilizing the DeepSeek Coder model, developed by DeepSeek Company, and you only answer questions related to computer science. For politically sensitive questions, security and privacy issues, and other non-computer science questions, you will refuse to answer.
  
### Instruction:
 
Can you translate the following Python code into Java?
 
The new Java code must be enclosed between [Java Start] and [Java End]
{full_code}
### Response:"""
        else:
            # Crafted prompt: exact Java signatures from the HumanEval-X declaration, strict output
            # format (no main/test code), type-mapping hints, and one worked example.
            java_sigs = "\n".join(
                m.strip() for m in re.findall(r'^[ \t]*public[^\n{;]*\([^)]*\)[^\n{;]*\{', java_decl, re.M)
            )
            prompt = """You are an AI programming assistant utilizing the DeepSeek Coder model, developed by DeepSeek Company, and you only answer questions related to computer science. For politically sensitive questions, security and privacy issues, and other non-computer science questions, you will refuse to answer.

### Instruction:

Translate the following Python code into Java.

Requirements:
1. Put ALL translated methods inside a single class named `Solution`. Use `import java.util.*;` at the top if you need it.
2. Use exactly these method signatures (same names, parameter types and return types), because a test harness will call them on a `Solution` object:
{java_sigs}
3. Translate every Python function, including helper functions.
4. Do NOT write a `main` method, test code, `System.out.println` calls or example usage.
5. Preserve the exact behavior of the Python code. Python `//` is integer division, Python lists map to `List<...>` (use `ArrayList`), Python tuples/mixed lists map to `List<Object>`, and Python `str` slicing maps to `substring`.
6. Enclose the complete Java code between [Java Start] and [Java End]. Write nothing else after [Java End].

Example.
Python code:
def add_pairs(numbers: List[int], k: int) -> List[int]:
    result = []
    for n in numbers:
        result.append(n // k + 1)
    return result
Java signature:
public List<Integer> addPairs(List<Integer> numbers, int k) {
Answer:
[Java Start]
import java.util.*;

class Solution {
    public List<Integer> addPairs(List<Integer> numbers, int k) {
        List<Integer> result = new ArrayList<>();
        for (int n : numbers) {
            result.add(n / k + 1);
        }
        return result;
    }
}
[Java End]

Now translate this Python code:
{full_code}
### Response:"""
            prompt = prompt.replace("{java_sigs}", java_sigs)
 
        # str.replace instead of str.format, so curly braces inside the code can't break the template
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
        response = tokenizer.decode(
            outputs[0][inputs["input_ids"].shape[1]:],
            skip_special_tokens=True
        )
 
        # TODO: process the response and save it to results
        m = re.search(r"\[Java Start\]\s*(.*?)\s*\[Java End\]", response, re.DOTALL)
        if m:
            model_result = m.group(1)
        else:
            # no closing tag (e.g. truncated output): take everything after [Java Start]
            m = re.search(r"\[Java Start\]\s*(.*)", response, re.DOTALL)
            model_result = m.group(1) if m else ""
        # strip possible ```java code fences
        model_result = re.sub(r"^```(?:java)?\s*|\s*```$", "", model_result.strip()).strip()
        if "class Solution" in model_result:
            model_result = model_result.replace("public class Solution", "class Solution")
        else:
            # model used another class name (e.g. `public class Main`): rename it to Solution
            model_result = re.sub(r"(?:public\s+)?class\s+\w+", "class Solution", model_result, count=1)
 
        verdict = False

        # For debug
        # print(model_result)
        if model_result:
            # everything before "class Solution" in the Java declaration is the import section
            header = java_decl.split("class Solution")[0] if java_decl else "import java.util.*;\nimport java.lang.*;\n"
            if "class Solution" in model_result:
                src = header + model_result
            else:
                src = header + "class Solution {\n" + model_result + "\n}\n"
            src += "\n" + test_code  # Java test (contains `public class Main`)
 
            with tempfile.TemporaryDirectory() as d:
                with open(os.path.join(d, "Main.java"), "w") as f:
                    f.write(src)
                try:
                    c = subprocess.run(["javac", "Main.java"], cwd=d,
                                       capture_output=True, text=True, timeout=60)
                    if c.returncode == 0:
                        r = subprocess.run(["java", "Main"], cwd=d,
                                           capture_output=True, text=True, timeout=30)
                        verdict = (r.returncode == 0)
                except subprocess.TimeoutExpired:
                    verdict = False
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
    This Python script is to run prompt LLMs for code translation.
    Usage:
    `python3 task_1.py <input_dataset> <model> <output_file> <if_vanilla>`|& tee prompt.log

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
