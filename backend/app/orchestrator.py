WORKFLOW_STEPS = [
    {
        "id": "repository_analyzer",
        "name": "Repository analysis",
        "status": "analyzing",
        "description": "Analyze source files retrieved from the connected GitHub repository.",
    },
    {
        "id": "planner",
        "name": "Planning",
        "status": "planning",
        "description": "Produce a repository-grounded implementation plan and validation checklist with Groq.",
    },
    {
        "id": "coder",
        "name": "Coding",
        "status": "coding",
        "description": "Generate a unified patch for the requested change with Groq.",
    },
    {
        "id": "validator",
        "name": "Validation",
        "status": "testing",
        "description": "Apply the patch and run the selected command in a resource-limited Docker container.",
    },
    {
        "id": "reviewer",
        "name": "Review",
        "status": "reviewing",
        "description": "Review the patch and validation output with Groq; human approval is still required.",
    },
]


def workflow_steps_for_task(task) -> list[dict[str, str | bool]]:
    current_agent = task.current_agent or WORKFLOW_STEPS[0]["id"]
    current_index = next((index for index, step in enumerate(WORKFLOW_STEPS) if step["id"] == current_agent), 0)

    steps: list[dict[str, str | bool]] = []
    for index, step in enumerate(WORKFLOW_STEPS):
        if task.status in {"completed", "approved"}:
            status = "completed"
        elif index < current_index:
            status = "completed"
        elif index == current_index:
            status = "active"
        else:
            status = "pending"

        if task.status in {"failed", "cancelled"} and index >= current_index:
            status = "blocked"

        steps.append(
            {
                "id": step["id"],
                "name": step["name"],
                "description": step["description"],
                "status": status,
                "current": index == current_index,
            }
        )
    return steps


def next_workflow_step(task):
    current_agent = task.current_agent or WORKFLOW_STEPS[0]["id"]
    current_index = next((index for index, step in enumerate(WORKFLOW_STEPS) if step["id"] == current_agent), 0)
    if task.status in {"completed", "failed", "cancelled"}:
        return None
    if current_index >= len(WORKFLOW_STEPS) - 1:
        return None
    return WORKFLOW_STEPS[current_index + 1]
