"""A minimal evaluated agent for testing the evaluation machinery before the real agents exist."""

from apps.ai.gateway import AgentSpec
from apps.evals.evaluation import EvaluatedAgent, classification_score

TOY = EvaluatedAgent(
    spec=AgentSpec(
        name="toy_level",
        prompt_version="v1",
        instructions="أعط مستوى بلوم.",
        schema={
            "type": "object",
            "properties": {"level_id": {"type": "integer"}},
            "required": ["level_id"],
            "additionalProperties": False,
        },
    ),
    input_fields=("objective",),
    labels=("1", "2", "3", "4", "5", "6"),
    payload=lambda item: {"objective": item["objective"]},
    label_of=lambda output: str(output["level_id"]),
    score=classification_score,
)

CSV = """item_key,objective,expert,label
o1,أن يذكر المتدرب خطوات العزل,khalid,1
o1,أن يذكر المتدرب خطوات العزل,sara,1
o1,أن يذكر المتدرب خطوات العزل,mazen,1
o2,أن يطبق المتدرب الإجراء,khalid,3
o2,أن يطبق المتدرب الإجراء,sara,3
o2,أن يطبق المتدرب الإجراء,mazen,2
o3,أن يقيّم المتدرب الخطة,khalid,5
o3,أن يقيّم المتدرب الخطة,sara,4
o3,أن يقيّم المتدرب الخطة,mazen,6
o4,أن يصمم المتدرب نموذجًا,khalid,6
o4,أن يصمم المتدرب نموذجًا,sara,5
o4,أن يصمم المتدرب نموذجًا,adjudicator,6
"""
