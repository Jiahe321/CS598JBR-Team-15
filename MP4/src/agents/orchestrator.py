import json
import re
from pathlib import Path

VALID = {"writer", "tester", "reader", "stop"}


def default_policy(report, analysed_sig):
    if not report["build_ok"]:
        return {"next_agent": "writer", "task": "Fix the compile errors."}
    if not report["core_ok"]:
        if report["sig"] != analysed_sig:
            return {"next_agent": "tester", "task": "Analyse the failing CRUST tests and classify each failure."}
        return {"next_agent": "writer", "task": "Fix the failing tests using the failure analysis."}
    if not report["extra_ok"]:
        return {"next_agent": "tester", "task": "Some extra tests fail: decide if they are bad tests or translation bugs."}
    return {"next_agent": "writer", "task": "Reduce unsafe usage and Clippy findings without breaking tests."}


class Orchestrator:
    def __init__(self, ctx, prompt_file):
        self.ctx = ctx
        self.system = Path(prompt_file).read_text()

    def decide(self, it, phase, report, rendered, analysed_sig):
        ctx = self.ctx
        fallback = default_policy(report, analysed_sig)
        recent = ctx.state.decisions[-5:]
        user = (f"Iteration {it}, phase {phase}. Tokens used: {ctx.llm.total_tokens}.\n"
                f"Recent decisions: {json.dumps(recent)}\n\nHarness feedback:\n{rendered}\n\n"
                f"Default recommendation: {json.dumps(fallback)}")
        decision = fallback
        try:
            text = ctx.llm.chat([{"role": "system", "content": self.system}, {"role": "user", "content": user}],
                                max_tokens=700, temperature=0.0)
            m = re.search(r"\{.*\}", text, re.S)
            d = json.loads(m.group(0)) if m else {}
            ok = d.get("next_agent") in VALID and isinstance(d.get("task", ""), str)
            if ok and d["next_agent"] == "stop" and not (report["core_ok"] and report["extra_ok"]):
                ok = False
            if ok:
                decision = {"next_agent": d["next_agent"], "task": d.get("task", "") or fallback["task"]}
            ctx.logger.log("orchestrator", raw=text, accepted=ok)
        except Exception as e:
            ctx.logger.log("orchestrator", error=str(e), accepted=False)
        ctx.state.decisions.append({"it": it, **decision})
        return decision
