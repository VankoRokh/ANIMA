class ScenarioRunner:
    def __init__(self, runtime):
        self.runtime = runtime

    def run(self, steps):
        if not isinstance(steps, list):
            raise ValueError(
                "Scenario must be a list of steps"
            )

        if not steps:
            raise ValueError(
                 "Scenario must contain at least one step"
            )

        results = []

        for index, step in enumerate(steps):
            try:
                result = self._run_step(step)
            except ValueError as error:
                raise ValueError(
                    f"Scenario step {index}: {error}"
                ) from error

            results.append(result)

        return results

    def _run_step(self, step):
        if not isinstance(step, dict):
            raise ValueError(
                "Scenario step must be an object"
            )

        if "action" not in step:
            raise ValueError(
                "Scenario step must contain 'action'"
            )

        action = step["action"]

        if not isinstance(action, str):
            raise ValueError(
                "Scenario action must be a string"
            )

        if action == "wake":
            events = self.runtime.wake()

        elif action == "user_input":
            if "text" not in step:
                raise ValueError(
                    "Scenario action 'user_input' "
                 "must contain 'text'"
                )

            if not isinstance(step["text"], str):
                 raise ValueError(
                    "Scenario action 'user_input' "
                    "'text' must be a string"
                )

            events = self.runtime.user_input(
                step["text"]
            )

        elif action == "sleep":
            events = self.runtime.sleep()

        else:
            raise ValueError(
                f"Unknown scenario action: {action!r}"
            )

        return {
            "action": action,
            "events": [
                event.event_type
                for event in events
            ],
        }