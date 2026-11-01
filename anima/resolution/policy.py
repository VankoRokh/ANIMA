"""Only task-local ACTION_PRIORITY; no implicit policy precedence."""

from .contracts import PolicyEvaluation


def evaluate_policies(policies, candidates):
    results = []
    seen = set()
    for policy in policies:
        priority = policy.priority
        valid = (
            isinstance(policy.policy_id, str) and bool(policy.policy_id.strip())
            and policy.policy_id not in seen
            and policy.type == "ACTION_PRIORITY"
            and isinstance(priority, tuple) and bool(priority)
            and all(isinstance(item, str) and item.strip() for item in priority)
        )
        if valid:
            valid = len(set(priority)) == len(priority) and set(candidates).issubset(priority)
        winner = next((item for item in priority if item in candidates), None) if valid else None
        results.append(PolicyEvaluation(
            policy_id=policy.policy_id,
            winner=winner,
            valid=bool(valid),
            reason="action_priority" if valid else "malformed_or_incomplete_policy",
        ))
        if isinstance(policy.policy_id, str):
            seen.add(policy.policy_id)
    return tuple(results)
