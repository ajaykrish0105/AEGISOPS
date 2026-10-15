import os
import joblib


ROOT = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

MODEL_PATH = os.path.join(
    ROOT,
    "ai",
    "aegisops_model.joblib"
)


ACTIONS = {
    "APPLICATION_CRASH": "RESTART_SERVICE",
    "MEMORY_EXHAUSTION": "CONTROLLED_RESTART",
    "BAD_DEPLOYMENT": "ROLLBACK_DEPLOYMENT",
    "CPU_OVERLOAD": "INVESTIGATE_OR_SCALE"
}


def analyze_incident(evidence):

    package = joblib.load(MODEL_PATH)

    model = package["model"]
    feature_names = package["features"]

    error = str(
        evidence.get("health_error", "")
    ).lower()

    features = {
        "health_down": 1,
        "timeout": int(
            "timeout" in error or
            "timed out" in error
        ),
        "connection_refused": int(
            "refused" in error
        ),
        "memory_high": int(
            evidence.get("memory_high", False)
        ),
        "cpu_high": int(
            evidence.get("cpu_high", False)
        ),
        "recent_deployment": int(
            evidence.get("recent_deployment", False)
        ),
        "error_500": int(
            evidence.get("error_500", False)
        ),
        "process_crashed": int(
            evidence.get("process_crashed", False)
        )
    }

    vector = [
        features[name]
        for name in feature_names
    ]

    probabilities = model.predict_proba(
        [vector]
    )[0]

    index = probabilities.argmax()

    incident = str(
        model.classes_[index]
    )

    confidence = float(
        probabilities[index]
    )

    action = ACTIONS.get(
        incident,
        "HUMAN_REVIEW"
    )

    return {
        "incident": incident,
        "confidence": confidence,
        "action": action
    }