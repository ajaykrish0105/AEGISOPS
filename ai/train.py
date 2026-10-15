import csv
import os
import joblib

from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split


DATASET = "data/incidents.csv"
MODEL_FILE = "ai/aegisops_model.joblib"

FEATURES = [
    "health_down",
    "timeout",
    "connection_refused",
    "memory_high",
    "cpu_high",
    "recent_deployment",
    "error_500",
    "process_crashed"
]


def load_dataset():

    X = []
    y = []

    with open(DATASET, "r", encoding="utf-8") as file:

        reader = csv.DictReader(file)

        for row in reader:

            features = [
                int(row[name])
                for name in FEATURES
            ]

            X.append(features)
            y.append(row["incident_type"])

    return X, y


def train():

    print()
    print("=" * 60)
    print("              AEGISOPS MODEL TRAINER")
    print("=" * 60)

    X, y = load_dataset()

    print(f"Training examples : {len(X)}")
    print(f"Features          : {len(FEATURES)}")
    print(f"Incident classes  : {len(set(y))}")

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=0.25,
        random_state=42,
        stratify=y
    )

    model = RandomForestClassifier(
        n_estimators=150,
        random_state=42
    )

    print()
    print("[AEGIS-AI] Training local incident model...")

    model.fit(X_train, y_train)

    predictions = model.predict(X_test)

    accuracy = accuracy_score(
        y_test,
        predictions
    )

    package = {
        "model": model,
        "features": FEATURES
    }

    os.makedirs("ai", exist_ok=True)

    joblib.dump(
        package,
        MODEL_FILE
    )

    print("[AEGIS-AI] Training complete.")
    print()
    print(f"Test Accuracy     : {accuracy * 100:.2f}%")
    print(f"Model Saved       : {MODEL_FILE}")

    print()
    print("Known incident classes:")

    for incident in sorted(set(y)):
        print(f"  -> {incident}")

    print()
    print("=" * 60)


if __name__ == "__main__":
    train()